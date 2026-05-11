"""In-process facade over the ``mesa-ducklake`` package.

mesa-ducklake is the sibling repo at https://github.com/cyverse/mesa-ducklake
that owns the AVU-history schema (Postgres catalog + Parquet data files in
each project's ``/.mesa/ducklake/`` iRODS collection, time-travel enabled).

This facade keeps the mesa-mcp <-> mesa-ducklake import surface narrow, so
the two repos can evolve independently and we can swap to an out-of-process
boundary later without churn at the call sites.

Public entry points:

* :func:`get_default_client` / :func:`set_default_client` — process-wide
  :class:`DuckLakeClient` singleton. When ``Config.ducklake.catalog_dsn``
  is empty, the singleton is ``None`` and AVU mirroring is a no-op.
* :func:`record_avu_change` — the function every AVU-write tool calls
  *after* a successful iRODS write. It walks the path's parents looking
  for a MESA-enabled project, builds an :class:`AvuChange`, and hands it
  to ``DuckLakeClient.record_changes``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Literal

import structlog

from mesa_mcp.auth.models import AuthValue

if TYPE_CHECKING:
    from irods.session import iRODSSession

# We import the upstream ``DuckLakeClient`` lazily inside :func:`get_default_client`
# so that test environments without ``mesa-ducklake`` installed (or with the
# catalog DSN left unset) never hit the import.

logger = structlog.get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_client: Any | None = None
_default_client_initialised: bool = False


def get_default_client() -> Any | None:
    """Return the process-wide ``DuckLakeClient``, or ``None`` if disabled.

    Lazily constructs the client on first call. When
    ``Config.ducklake.catalog_dsn`` is empty (or ``None``), DuckLake mirroring
    is disabled and this returns ``None`` — every call site treats that as a
    no-op.
    """
    global _default_client, _default_client_initialised
    if _default_client_initialised:
        return _default_client

    # Lazy config import to dodge circular dependencies at module load time.
    from mesa_mcp.config import load_config

    config = load_config()
    dsn = config.ducklake.catalog_dsn
    if not dsn:
        _default_client = None
        _default_client_initialised = True
        return None

    try:
        from mesa_ducklake import DuckLakeClient as _RealClient  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        logger.warning(
            "mesa_ducklake_unavailable",
            error=str(exc),
            message="mesa-ducklake package not importable; DuckLake mirroring disabled.",
        )
        _default_client = None
        _default_client_initialised = True
        return None

    # Per-call sites pass session through to ``record_changes``/read
    # methods, so the constructor session stays ``None`` here. The
    # cache configuration is plumbed through so operators can pin a
    # systemd ``CacheDirectory=`` or raise the cap from YAML.
    client_kwargs: dict[str, Any] = {
        "postgres_dsn": dsn,
        "irods_session": None,
        "cache_cap_bytes": config.ducklake.cache_cap_bytes,
    }
    if config.ducklake.cache_dir:
        client_kwargs["cache_dir"] = config.ducklake.cache_dir
    _default_client = _RealClient(**client_kwargs)
    _default_client_initialised = True
    return _default_client


def set_default_client(client: Any | None) -> None:
    """Replace (or clear) the module-level singleton. Test-only injection."""
    global _default_client, _default_client_initialised
    _default_client = client
    _default_client_initialised = True


def reset_default_client() -> None:
    """Force the next :func:`get_default_client` call to rebuild from config.

    Used by tests that exercise the lazy-init path.
    """
    global _default_client, _default_client_initialised
    _default_client = None
    _default_client_initialised = False


# ---------------------------------------------------------------------------
# Project-detection cache
# ---------------------------------------------------------------------------

# Cache of (zone, project_root) → bool ("is MESA-enabled?"). Entries expire
# after :data:`_PROJECT_TTL` seconds so we don't pin a stale answer if an
# admin flips ``mesa.enabled`` on or off underneath us.
_PROJECT_TTL = 300  # 5 minutes
_project_cache: dict[tuple[str, str], tuple[float, bool]] = {}


def _project_cache_get(zone: str, root: str) -> bool | None:
    entry = _project_cache.get((zone, root))
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at < time.monotonic():
        _project_cache.pop((zone, root), None)
        return None
    return value


def _project_cache_set(zone: str, root: str, value: bool) -> None:
    _project_cache[(zone, root)] = (time.monotonic() + _PROJECT_TTL, value)


def reset_project_cache() -> None:
    """Wipe the MESA-project detection cache. Test-only helper."""
    _project_cache.clear()


def _iter_parents(path: str) -> list[str]:
    """Yield ``path`` and each parent collection up to (but excluding) ``/``.

    ``/iplant/home/alice/proj/file`` -> ``['/iplant/home/alice/proj/file',
    '/iplant/home/alice/proj', '/iplant/home/alice', '/iplant/home', '/iplant']``.
    """
    parents: list[str] = []
    current = path
    while current and current != "/":
        parents.append(current)
        parent = current.rsplit("/", 1)[0]
        if not parent:
            break
        current = parent
    return parents


def _collection_has_mesa_enabled(session: Any, path: str) -> bool:
    """Return True if ``path`` is a collection carrying ``mesa.enabled=true``."""
    # Local imports keep the module import-clean when ``python-irodsclient``
    # is mocked out.
    from irods.exception import CollectionDoesNotExist
    from irods.models import Collection

    try:
        session.collections.get(path)
    except (CollectionDoesNotExist, Exception):  # noqa: BLE001
        return False

    try:
        metas = session.metadata.get(Collection, path)
    except Exception:  # noqa: BLE001
        return False
    for m in metas or []:
        # The ``mesa.enabled`` AVU acts as the project marker; the value is
        # canonically the literal string ``"true"`` but we accept any truthy
        # form to keep this robust against minor portal/CLI inconsistencies.
        if getattr(m, "name", "") == "mesa.enabled":
            value = (getattr(m, "value", "") or "").strip().lower()
            if value in {"true", "yes", "1"}:
                return True
    return False


def _find_project_root(session: Any, zone: str, irods_path: str) -> str | None:
    """Walk ``irods_path``'s ancestors looking for a MESA-enabled collection.

    Returns the matching project root path, or ``None`` when nothing in the
    chain carries ``mesa.enabled=true``. Each (zone, candidate) result is
    cached for ``_PROJECT_TTL`` seconds.
    """
    for candidate in _iter_parents(irods_path):
        cached = _project_cache_get(zone, candidate)
        if cached is True:
            return candidate
        if cached is False:
            continue
        enabled = _collection_has_mesa_enabled(session, candidate)
        _project_cache_set(zone, candidate, enabled)
        if enabled:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Public API: record_avu_change
# ---------------------------------------------------------------------------


class DuckLakeMirrorError(Exception):
    """Raised when an AVU write succeeded in iRODS but its DuckLake mirror failed.

    Tool handlers wrap this into a structured partial-failure response so the
    client sees the iRODS-side change reflected and can react to the mirror
    failure (e.g., by re-trying or surfacing a warning to the user).
    """

    def __init__(self, message: str, *, project_id: Any = None, cause: Exception | None = None):
        super().__init__(message)
        self.project_id = project_id
        self.__cause__ = cause


async def record_avu_change(
    *,
    auth_value: AuthValue,
    irods_path: str,
    target_type: Literal["data_object", "collection"],
    attribute: str,
    value: str,
    unit: str,
    op: Literal["add", "delete"],
    tool_name: str,
    session: iRODSSession | None = None,
) -> None:
    """Mirror an AVU change into the project's DuckLake, if any.

    Short-circuits silently when:

    * the config has no ``catalog_dsn`` (DuckLake disabled),
    * mesa-ducklake isn't importable in this environment, or
    * the path is not within any MESA-enabled project (no
      ``mesa.enabled=true`` AVU on a parent collection).

    Populates ``actor`` from ``auth_value.username``, ``source`` as
    ``f"mesa-mcp:{tool_name}"``, and ``via_ticket`` from
    ``session.attributes.get('mesa.via_ticket')`` when set.

    Raises :class:`DuckLakeMirrorError` when DuckLake is enabled and the
    project *is* MESA-enabled but the catalog write itself fails. Callers
    should translate this into a structured partial-failure response.
    """
    client = get_default_client()
    if client is None:
        # DuckLake disabled — silent no-op.
        return

    if session is None:
        # Project detection requires a live iRODS session; without one we
        # can't tell whether the path is inside a MESA project. Treat as
        # "not MESA-enabled" and return — the caller has already written
        # the AVU to iRODS so we can't undo, and the user wanted that
        # write to succeed.
        logger.debug(
            "record_avu_change.no_session",
            irods_path=irods_path,
            tool_name=tool_name,
            message="No iRODS session supplied; skipping MESA project detection.",
        )
        return

    project_root = _find_project_root(session, auth_value.zone, irods_path)
    if project_root is None:
        # Not a MESA-enabled project — silent no-op (this is the documented
        # "exception" case in the design: project not MESA-enabled => no
        # exception, just a skip).
        return

    # Look up or register the project. ``find_project_by_path`` is the
    # documented way to map a path to a project_id in mesa-ducklake.
    try:
        project = client.find_project_by_path(project_root)
        if project is None:
            project = client.register_project(
                irods_path=project_root,
                actor=auth_value.username,
                zone=auth_value.zone,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "record_avu_change.project_lookup_failed",
            irods_path=irods_path,
            project_root=project_root,
            tool_name=tool_name,
            error=str(exc),
        )
        raise DuckLakeMirrorError(
            f"DuckLake project lookup failed for {project_root!r}: {exc}",
            cause=exc,
        ) from exc

    # Ticket provenance: prefer the contextvar set by ``ds_use_ticket`` (the
    # canonical signal in mesa-mcp); fall back to the legacy session-attribute
    # form that the design notes mention so we stay compatible with the
    # rule-engine callback path that sets it that way.
    from mesa_mcp.context import get_current_ticket

    via_ticket: str | None = get_current_ticket()
    if via_ticket is None:
        attributes = getattr(session, "attributes", None)
        if attributes is not None:
            try:
                via_ticket = attributes.get("mesa.via_ticket")
            except Exception:  # noqa: BLE001
                via_ticket = None

    # Build the AvuChange. Imported here so the module is usable when
    # mesa-ducklake isn't installed (the get_default_client call above
    # would have returned None already in that case).
    from mesa_ducklake.models import AvuChange  # type: ignore[import-not-found]

    change = AvuChange(
        irods_path=irods_path,
        target_type=target_type,
        attribute=attribute,
        value=value,
        unit=unit,
        op=op,
        actor=auth_value.username,
        source=f"mesa-mcp:{tool_name}",
        via_ticket=via_ticket,
    )

    try:
        client.record_changes(
            project_id=project.project_id,
            actor=auth_value.username,
            changes=[change],
            note=f"{op} AVU via {tool_name}",
            session=session,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "record_avu_change.write_failed",
            irods_path=irods_path,
            project_id=str(project.project_id),
            tool_name=tool_name,
            op=op,
            attribute=attribute,
            error=str(exc),
        )
        raise DuckLakeMirrorError(
            f"DuckLake write failed for project {project.project_id}: {exc}",
            project_id=project.project_id,
            cause=exc,
        ) from exc


# ---------------------------------------------------------------------------
# Back-compat shim (kept for any older imports)
# ---------------------------------------------------------------------------


class DuckLakeClient:
    """Stub kept so older imports don't break.

    The real client comes from the ``mesa-ducklake`` package; mesa-mcp wraps
    it via :func:`get_default_client` and :func:`record_avu_change`. This
    placeholder stays in place so any pre-existing imports of
    ``mesa_mcp.ducklake.client.DuckLakeClient`` keep working — they get a
    no-op instance whose methods raise :class:`NotImplementedError` and a
    clear hint to migrate.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs

    def _unimplemented(self, name: str) -> Any:
        raise NotImplementedError(
            f"mesa_mcp.ducklake.client.DuckLakeClient.{name} is no longer the public "
            "entry point. Use mesa_mcp.ducklake.client.get_default_client() and "
            "record_avu_change(...) instead."
        )

    def record_changes(self, *args: Any, **kwargs: Any) -> Any:
        return self._unimplemented("record_changes")

    def init_project(self, *args: Any, **kwargs: Any) -> Any:
        return self._unimplemented("init_project")

    def history(self, *args: Any, **kwargs: Any) -> Any:
        return self._unimplemented("history")

    def time_travel(self, *args: Any, **kwargs: Any) -> Any:
        return self._unimplemented("time_travel")

    def snapshot(self, *args: Any, **kwargs: Any) -> Any:
        return self._unimplemented("snapshot")

    def diff(self, *args: Any, **kwargs: Any) -> Any:
        return self._unimplemented("diff")

    def close(self) -> None:
        return self._unimplemented("close")
