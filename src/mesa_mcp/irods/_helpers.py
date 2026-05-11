"""Shared utilities for the ``ds_*`` tool handlers.

The underscore prefix is load-bearing: the auto-discovery in
``mesa_mcp/irods/tools/__init__.py`` skips modules whose name starts with
``_``, so a non-tool helper that happens to live next to the tool
modules does not get pulled in as a tool itself. This module sits one
level up (``mesa_mcp/irods/_helpers.py``) so that even if the discovery
rules ever loosen, helpers stay out of the tool registry.

What lives here:

* :func:`resolve_target` — given a session and a path, work out whether
  the object is a collection or a data object and return the
  ``python-irodsclient`` model alongside a small ``kind`` string. Mirrors
  the Go reference's ``fs.Stat`` + ``IsDir`` idiom which several handlers
  rely on.
* :func:`entry_info` — produce the JSON shape the Go reference emits
  under ``entry_info`` / ``directory_info``: a small dict with ``path``,
  ``name``, ``type`` (``"directory"`` / ``"file"``), ``size``, and
  timestamps. The Go ``Entry`` struct is ad-hoc — we mirror the keys the
  handlers serialize, not every field on the iRODS object.
* :func:`split_user_zone` — parse ``"user#zone"`` for ``ds_modify_access``.
* :func:`access_records` — best-effort serialization of an iRODSAccess
  list (each Go handler emits an ``accesses`` slice on its way out).
* :func:`avu_records` — best-effort serialization of an iRODSMeta list.

These functions are intentionally defensive: they tolerate
``python-irodsclient`` model objects (real or :class:`MagicMock`) and
fall back to attribute access via ``getattr`` so that unit tests do not
have to mock every internal attribute the model class might expose.
"""

from __future__ import annotations

from typing import Any

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.webdav import (
    make_resource_uri,
    make_webdav_url,
    make_webdav_url_with_accesses,
)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def resolve_target(session: Any, path: str) -> tuple[str, Any]:
    """Return ``("collection", coll)`` or ``("data_object", obj)`` for ``path``.

    Raises :class:`ToolError` with code ``"not_found"`` if neither lookup
    succeeds.

    The python-irodsclient API splits collections and data-objects into
    two namespaces; the Go reference uses one ``fs.Stat`` call that
    returns an ``Entry`` either way. Most handlers do follow-up work
    based on the kind, so we return both pieces of info from a single
    helper to keep the call sites narrow.
    """
    last_exc: Exception | None = None
    try:
        coll = session.collections.get(path)
        return "collection", coll
    except Exception as exc:  # noqa: BLE001 - PRC raises a variety of types
        last_exc = exc

    try:
        obj = session.data_objects.get(path)
        return "data_object", obj
    except Exception as exc:  # noqa: BLE001
        last_exc = exc

    raise ToolError(
        code="not_found",
        message=f"Path {path!r} is not a collection or data object.",
        details={"path": path, "cause": str(last_exc) if last_exc else None},
    )


def target_exists(session: Any, path: str) -> bool:
    """Return True iff ``path`` exists as either a collection or a data object."""
    try:
        resolve_target(session, path)
    except ToolError:
        return False
    return True


# ---------------------------------------------------------------------------
# Entry / access / AVU serialization
# ---------------------------------------------------------------------------


def _iso(value: Any) -> str | None:
    """Best-effort ISO-8601 timestamp for whatever PRC hands us."""
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:  # pragma: no cover - defensive
            return None
    return str(value)


def entry_info(model: Any, kind: str) -> dict[str, Any]:
    """Serialize a PRC collection / data-object model into a small dict.

    Keys mirror the fields the Go reference emits — ``path``, ``name``,
    ``type``, ``size``, ``create_time``, ``modify_time``. ``size`` is only
    meaningful for data objects.
    """
    path = getattr(model, "path", None)
    name = getattr(model, "name", None)
    if not name and path:
        name = path.rstrip("/").rsplit("/", 1)[-1]

    info: dict[str, Any] = {
        "path": path,
        "name": name,
        "type": "directory" if kind == "collection" else "file",
        "create_time": _iso(getattr(model, "create_time", None)),
        "modify_time": _iso(getattr(model, "modify_time", None)),
    }

    if kind == "data_object":
        info["size"] = getattr(model, "size", None)
        info["checksum"] = getattr(model, "checksum", None)
        replicas = getattr(model, "replicas", None)
        if replicas is not None:
            info["replicas"] = [_replica_dict(r) for r in replicas]
    return info


def _replica_dict(replica: Any) -> dict[str, Any]:
    """Compact replica record. ``python-irodsclient`` exposes many fields."""
    return {
        "number": getattr(replica, "number", None),
        "resource_name": getattr(replica, "resource_name", None),
        "status": getattr(replica, "status", None),
        "checksum": getattr(replica, "checksum", None),
        "size": getattr(replica, "size", None),
        "create_time": _iso(getattr(replica, "create_time", None)),
        "modify_time": _iso(getattr(replica, "modify_time", None)),
    }


def access_records(accesses: Any) -> list[dict[str, Any]]:
    """Serialize an iterable of iRODSAccess records.

    Defensive: missing iterables or PRC failures return an empty list.
    """
    if not accesses:
        return []
    out: list[dict[str, Any]] = []
    for acc in accesses:
        out.append(
            {
                "user_name": getattr(acc, "user_name", None),
                "user_zone": getattr(acc, "user_zone", None),
                "access_name": getattr(acc, "access_name", None),
                "path": getattr(acc, "path", None),
            }
        )
    return out


def avu_records(metas: Any, *, hide_system: bool = False) -> list[dict[str, Any]]:
    """Serialize an iterable of iRODSMeta records into ``(a, v, u)`` triples."""
    if not metas:
        return []
    out: list[dict[str, Any]] = []
    for meta in metas:
        name = getattr(meta, "name", None)
        if hide_system and _is_system_attribute(name):
            continue
        out.append(
            {
                "id": getattr(meta, "id", None),
                "attribute": name,
                "value": getattr(meta, "value", None),
                "unit": getattr(meta, "units", None) or None,
            }
        )
    return out


# These prefixes mirror ``irods/common/unit.go`` from the Go reference,
# which keeps the irods system-managed attribute list. We use the same
# discriminator so the anonymous user sees the same filtered AVU view.
_SYSTEM_ATTRIBUTE_PREFIXES: tuple[str, ...] = (
    "ipc_",
    "ipc::",
    "irods::",
)


def _is_system_attribute(name: str | None) -> bool:
    if not name:
        return False
    return name.startswith(_SYSTEM_ATTRIBUTE_PREFIXES)


# ---------------------------------------------------------------------------
# URL minting wrappers
# ---------------------------------------------------------------------------


def entry_uris(
    path: str,
    auth_value: AuthValue,
    webdav_base: str,
    *,
    accesses: list[Any] | None = None,
) -> dict[str, str]:
    """Return ``{"resource_uri": …, "webdav_uri": …}`` for ``path``."""
    return {
        "resource_uri": make_resource_uri(path),
        "webdav_uri": make_webdav_url_with_accesses(
            webdav_base,
            path,
            auth_value,
            accesses,
        )
        if accesses is not None
        else make_webdav_url(webdav_base, path, auth_value),
    }


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def split_user_zone(spec: str, default_zone: str) -> tuple[str, str]:
    """Split ``"user#zone"`` (or just ``"user"``) into ``(user, zone)``.

    Mirrors the Go reference's ``strings.Split(userOrGroup, "#")`` idiom in
    ``modify_access.go``: if no ``#`` is present, fall back to the caller's
    zone.
    """
    if "#" in spec:
        user, _, zone = spec.partition("#")
        return user, zone or default_zone
    return spec, default_zone


def reject_anonymous_write(auth_value: AuthValue, tool_name: str) -> None:
    """Raise ``forbidden`` if the caller is anonymous.

    Anonymous read access is intentional; writes are categorically rejected
    at the tool layer so we don't even try to push a mutation to iRODS.
    """
    if auth_value.is_anonymous():
        raise ToolError(
            code="forbidden",
            message=(
                f"{tool_name}: anonymous callers may not perform writes."
            ),
            details={"tool": tool_name, "user": auth_value.username},
        )
