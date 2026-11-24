"""``mesa_ducklake_history`` — read the AVU change log for an iRODS path.

Read-only counterpart to the mirror that ``ds_add_avu``,
``ds_delete_avu`` and ``mesa_avu_apply_term`` write through
:func:`mesa_mcp.ducklake.client.record_avu_change`. Given a path inside
a MESA-enabled project, the tool returns either:

* the change log for that path (``DuckLakeClient.get_history``), newest
  first, when ``as_of`` is not supplied; or
* the AVU set that was in effect at ``as_of``
  (``DuckLakeClient.get_avus_as_of``) when it is.

Both calls return ``AvuChange`` rows. mesa-ducklake has no filter
arguments, so the optional ``attribute`` and ``unit`` exact-match
filters are applied here, in Python, after the read.

Requires:

* mesa-ducklake installed (else ``ducklake_disabled``).
* ``Config.ducklake.catalog_dsn`` set (else ``ducklake_disabled``).
* ``irods_path`` inside a collection carrying ``mesa.enabled=true``
  (else ``not_mesa_project``) that is also registered in the catalog
  (else ``history_project_not_registered``).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import _find_project_root, get_default_client
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_ducklake_history"

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000


class HistoryInput(BaseModel):
    """Input schema for ``mesa_ducklake_history``."""

    irods_path: str = Field(
        ...,
        description=(
            "Absolute iRODS path of the data object or collection whose AVU "
            "history to read. Must sit inside a MESA-enabled project."
        ),
    )
    attribute: str | None = Field(
        default=None,
        description="Only return rows whose AVU attribute equals this string exactly.",
    )
    unit: str | None = Field(
        default=None,
        description=(
            "Only return rows whose AVU unit equals this string exactly. "
            "Pass an empty string to match rows with no unit."
        ),
    )
    as_of: str | None = Field(
        default=None,
        description=(
            "ISO-8601 timestamp (``2026-09-01T12:00:00Z``). When set, return "
            "the AVUs in effect at that instant instead of the change log. "
            "A timestamp with no zone is read as UTC."
        ),
    )
    limit: int = Field(
        default=DEFAULT_LIMIT,
        description=(
            f"Maximum number of rows to return. Default {DEFAULT_LIMIT}; values "
            f"above {MAX_LIMIT} are capped at {MAX_LIMIT}."
        ),
    )


@register_tool(
    TOOL_NAME,
    "Read the DuckLake AVU history for an iRODS path inside a MESA-enabled "
    "project. Without as_of, returns the change log (newest first). With "
    "as_of, returns the AVUs that were in effect at that timestamp. "
    "Optional exact-match filters on attribute and unit. Read-only.",
    input_model=HistoryInput,
)
async def handle_mesa_ducklake_history(
    args: HistoryInput,
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
    rows = rows[:limit]

    return {
        "project_id": str(project.project_id),
        "count": len(rows),
        "rows": [r.model_dump(mode="json") for r in rows],
    }


# ---------------------------------------------------------------------------
# Helpers — each one isolates a failure stage so the ToolError code says
# *which* step blew up.
# ---------------------------------------------------------------------------


def _parse_as_of(value: str | None) -> datetime | None:
    """Turn the ``as_of`` input into a TZ-aware UTC datetime, or ``None``.

    Same rules as ``mesa_ducklake.time_travel.parse_as_of``: a trailing
    ``Z`` is accepted and a naive timestamp is read as UTC. Parsing here
    rather than in the library turns a malformed string into a structured
    ``invalid_argument`` instead of a bare ``ValueError``.
    """
    if value is None:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ToolError(
            code="invalid_argument",
            message=f"as_of must be an ISO-8601 timestamp, got {value!r}.",
            details={"as_of": value},
        ) from exc
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
            code="history_failed_catalog_lookup",
            message=f"DuckLake catalog lookup failed for {project_root!r}: {exc}",
            details={"irods_path": irods_path, "project_root": project_root},
        ) from exc

    if project is None:
        raise ToolError(
            code="history_project_not_registered",
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
    as_of: datetime | None,
) -> list[Any]:
    """Fetch ``AvuChange`` rows from mesa-ducklake for one path.

    ``get_history`` takes a ``limit``; ``get_avus_as_of`` does not (an
    effective AVU set is bounded by what is on the object). Because the
    attribute/unit filters run *after* this read, ``get_history`` is
    always asked for ``MAX_LIMIT`` rows and the caller trims to ``limit``
    afterwards, so a filter cannot hide matches that sit beyond the first
    ``limit`` unfiltered rows. The scan is still bounded by ``MAX_LIMIT``.
    """
    try:
        if as_of is not None:
            return list(
                client.get_avus_as_of(project.project_id, irods_path, as_of, session=session)
            )
        return list(
            client.get_history(project.project_id, irods_path, limit=MAX_LIMIT, session=session)
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="history_failed_read",
            message=f"DuckLake read failed for {irods_path!r}: {exc}",
            details={"irods_path": irods_path, "project_id": str(project.project_id)},
        ) from exc
