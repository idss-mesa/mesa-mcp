"""``mesa_ducklake_time_travel`` — the AVU set on an iRODS path at a past instant.

Read-only counterpart to the mirror that ``ds_add_avu``,
``ds_delete_avu`` and ``mesa_avu_apply_term`` write through
:func:`mesa_mcp.ducklake.client.record_avu_change`. Given a path inside
a MESA-enabled project and an ``as_of`` timestamp, the tool returns the
AVUs that were in effect on that path at that instant
(``DuckLakeClient.get_avus_as_of``).

mesa-ducklake reconstructs the set from change rows whose ``ts`` is
**at or before** ``as_of`` (``ts <= as_of``), so a change stamped at
exactly ``as_of`` is included. It has no filter arguments, so the
optional ``attribute`` and ``unit`` exact-match filters are applied
here, in Python, after the read.

``as_of`` is a timestamp only. mesa-ducklake's ``parse_as_of`` and
``get_avus_as_of`` have no snapshot-id form, so a bare integer is
rejected with ``invalid_argument`` rather than guessed at.

Requires:

* mesa-ducklake installed (else ``ducklake_disabled``).
* ``Config.ducklake.catalog_dsn`` set (else ``ducklake_disabled``).
* ``irods_path`` inside a collection carrying ``mesa.enabled=true``
  (else ``not_mesa_project``) that is also registered in the catalog
  (else ``time_travel_project_not_registered``).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import _find_project_root, get_default_client
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_ducklake_time_travel"

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


class TimeTravelInput(BaseModel):
    """Input schema for ``mesa_ducklake_time_travel``."""

    irods_path: str = Field(
        ...,
        description=(
            "Absolute iRODS path of the data object or collection whose AVUs "
            "to read. Must sit inside a MESA-enabled project."
        ),
    )
    as_of: str = Field(
        ...,
        description=(
            "ISO-8601 timestamp (``2026-09-01T12:00:00Z``). Returns the AVUs in "
            "effect at that instant; a change stamped at exactly this time is "
            "included. A timestamp with no zone is read as UTC. Snapshot ids "
            "are not supported."
        ),
    )
    attribute: str | None = Field(
        default=None,
        description="Only return AVUs whose attribute equals this string exactly.",
    )
    unit: str | None = Field(
        default=None,
        description=(
            "Only return AVUs whose unit equals this string exactly. "
            "Pass an empty string to match AVUs with no unit."
        ),
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        description=(
            f"Maximum number of AVUs to return. Default {DEFAULT_LIMIT}; values "
            f"above {MAX_LIMIT} are capped at {MAX_LIMIT}."
        ),
    )


@register_tool(
    TOOL_NAME,
    "Return the AVUs that were in effect on an iRODS path inside a "
    "MESA-enabled project at a past timestamp, read from the project's "
    "DuckLake. Changes stamped at exactly as_of are included. Optional "
    "exact-match filters on attribute and unit. Read-only.",
    input_model=TimeTravelInput,
)
async def handle_mesa_ducklake_time_travel(
    args: TimeTravelInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    client = get_default_client()
    if client is None:
        raise ToolError(
            code="ducklake_disabled",
            message=(
                f"{TOOL_NAME} requires DuckLake. Set "
                "MESA_MCP_DUCKLAKE__CATALOG_DSN (or `ducklake.catalog_dsn` "
                "in config.yaml) and ensure the mesa-ducklake package is "
                "installed."
            ),
        )

    # Validate as_of before touching iRODS so a bad timestamp fails fast.
    as_of = _parse_as_of(args.as_of)
    limit = _clamp_limit(args.limit)

    norm = assert_allowed(args.irods_path, auth_value)
    session = default_pool().get(auth_value)

    project = _resolve_project(client, session, auth_value, norm)

    rows = _read_rows(client, project, norm, session, as_of=as_of)

    if args.attribute is not None:
        rows = [r for r in rows if r.attribute == args.attribute]
    if args.unit is not None:
        rows = [r for r in rows if r.unit == args.unit]
    # The library's query has no ORDER BY. Sort so `limit` keeps the
    # same AVUs on every call.
    rows.sort(key=lambda r: (r.attribute, r.value, r.unit))
    rows = rows[:limit]

    return {
        "project_id": str(project.project_id),
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "count": len(rows),
        "rows": [r.model_dump(mode="json") for r in rows],
    }


# ---------------------------------------------------------------------------
# Helpers — each one isolates a failure stage so the ToolError code says
# *which* step blew up.
# ---------------------------------------------------------------------------


def _parse_as_of(value: str) -> datetime:
    """Turn the ``as_of`` input into a TZ-aware UTC datetime.

    Uses ``mesa_ducklake.time_travel.parse_as_of`` when the package is
    importable, so the tool and ``get_avus_as_of`` read the string the
    same way. mesa-ducklake is an optional dependency, so the fallback
    applies the same rules: a trailing ``Z`` is accepted and a naive
    timestamp is read as UTC.

    An all-digit string is refused with its own message: it is almost
    certainly a snapshot id, which the library cannot resolve, and
    ``fromisoformat`` would otherwise read ``20260901`` as a date.
    """
    if value.strip().isdigit():
        raise ToolError(
            code="invalid_argument",
            message=(
                f"as_of must be an ISO-8601 timestamp, got {value!r}. Snapshot "
                "ids are not supported: mesa-ducklake can only time-travel by "
                "timestamp."
            ),
            details={"as_of": value},
        )
    try:
        return _library_parse_as_of()(value)
    except ValueError as exc:
        raise ToolError(
            code="invalid_argument",
            message=f"as_of must be an ISO-8601 timestamp, got {value!r}.",
            details={"as_of": value},
        ) from exc


def _library_parse_as_of() -> Callable[[str], datetime]:
    """Return mesa-ducklake's ``parse_as_of``, or a local copy of its rules."""
    try:
        from mesa_ducklake.time_travel import parse_as_of
    except ImportError:
        return _fallback_parse_as_of
    return parse_as_of


def _fallback_parse_as_of(value: str) -> datetime:
    """Same rules as ``mesa_ducklake.time_travel.parse_as_of`` for strings."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clamp_limit(limit: int) -> int:
    """Keep ``limit`` within ``1..MAX_LIMIT`` (same clamping style as ``ds_read_file``)."""
    if limit < 1:
        return 1
    if limit > MAX_LIMIT:
        return MAX_LIMIT
    return limit


def _resolve_project(client: Any, session: Any, auth_value: AuthValue, irods_path: str) -> Any:
    """Map ``irods_path`` to its catalog ``Project`` or raise a structured error."""
    project_root = _find_project_root(session, auth_value.zone, irods_path)
    if project_root is None:
        raise ToolError(
            code="not_mesa_project",
            message=(
                f"{irods_path!r} is not inside a MESA-enabled project (no "
                "ancestor collection carries mesa.enabled=true). Run "
                "mesa_ducklake_init_project on the project root first."
            ),
            details={"irods_path": irods_path},
        )

    try:
        project = client.find_project_by_path(project_root)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="time_travel_failed_catalog_lookup",
            message=f"DuckLake catalog lookup failed for {project_root!r}: {exc}",
            details={"irods_path": irods_path, "project_root": project_root},
        ) from exc

    if project is None:
        raise ToolError(
            code="time_travel_project_not_registered",
            message=(
                f"{project_root!r} carries mesa.enabled=true but has no row in "
                "the DuckLake catalog. Run mesa_ducklake_init_project on it to "
                "repair the drift."
            ),
            details={"irods_path": irods_path, "project_root": project_root},
        )
    return project


def _read_rows(
    client: Any,
    project: Any,
    irods_path: str,
    session: Any,
    *,
    as_of: datetime,
) -> list[Any]:
    """Fetch the effective ``AvuChange`` rows for one path from mesa-ducklake.

    ``get_avus_as_of`` takes no limit: the effective set is bounded by
    what was on the object, so the caller filters and trims afterwards.
    """
    try:
        return list(client.get_avus_as_of(project.project_id, irods_path, as_of, session=session))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="time_travel_failed_read",
            message=f"DuckLake read failed for {irods_path!r}: {exc}",
            details={"irods_path": irods_path, "project_id": str(project.project_id)},
        ) from exc
