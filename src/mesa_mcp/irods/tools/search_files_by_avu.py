"""``ds_search_files_by_avu`` — search by AVU attribute + value.

Ported from ``irods-mcp-server/irods/search_files_by_avu.go``. Returns data
objects (and, in the Go reference, collections too) whose AVUs match the
given attribute + value, filtered down to entries inside the caller's
accessible paths.

We query data objects and collections separately because python-irodsclient's
``session.query`` is a SQL-builder over iCAT — one builder per object kind.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import is_within, normalize
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class SearchFilesByAvuInput(BaseModel):
    """Input schema. Mirrors the Go ``SearchFilesByAVUInputArgs``."""

    attribute: str = Field(..., description="The attribute to search for.")
    value: str = Field(..., description="The value of the attribute to search for.")


@register_tool(
    "ds_search_files_by_avu",
    "Search for files (data-objects) and directories (collections) matching "
    "iRODS AVU (attribute-value-units) using specified attribute and value. "
    "The matching entries are returned in JSON format.",
    input_model=SearchFilesByAvuInput,
)
async def handle_ds_search_files_by_avu(
    args: SearchFilesByAvuInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Return matching entries filtered to the caller's accessible paths."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message="ds_search_files_by_avu requires an authenticated caller.",
        )

    session = default_pool().get(auth_value)

    accessible_roots = [normalize(p) for p in auth_value.accessible_paths()]

    entries: list[dict[str, Any]] = []
    entries.extend(_search_data_objects(session, args.attribute, args.value))
    entries.extend(_search_collections(session, args.attribute, args.value))

    # Filter to the caller's accessible paths (mirror Go's IsAccessAllowed).
    filtered: list[dict[str, Any]] = []
    for entry in entries:
        path = entry.get("path", "")
        if any(is_within(path, root) for root in accessible_roots):
            filtered.append(entry)

    return {
        "search_attribute": args.attribute,
        "search_value": args.value,
        "matching_entries": filtered,
    }


def _search_data_objects(
    session: Any,
    attribute: str,
    value: str,
) -> list[dict[str, Any]]:
    from irods.column import Criterion  # type: ignore[import-not-found]
    from irods.models import (  # type: ignore[import-not-found]
        Collection,
        DataObject,
        DataObjectMeta,
    )

    try:
        rows = (
            session.query(Collection.name, DataObject.name)
            .filter(Criterion("=", DataObjectMeta.name, attribute))
            .filter(Criterion("=", DataObjectMeta.value, value))
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to search data objects by AVU: {exc}",
            details={"attribute": attribute, "value": value},
        ) from exc

    out: list[dict[str, Any]] = []
    for row in rows or []:
        # ``row`` is a ``ResultSet`` row; values are addressed by column model.
        coll = _row_value(row, Collection.name)
        name = _row_value(row, DataObject.name)
        if not coll or not name:
            continue
        path = f"{coll.rstrip('/')}/{name}"
        out.append({"path": path, "entry_type": "data_object", "name": name})
    return out


def _search_collections(
    session: Any,
    attribute: str,
    value: str,
) -> list[dict[str, Any]]:
    from irods.column import Criterion  # type: ignore[import-not-found]
    from irods.models import (  # type: ignore[import-not-found]
        Collection,
        CollectionMeta,
    )

    try:
        rows = (
            session.query(Collection.name)
            .filter(Criterion("=", CollectionMeta.name, attribute))
            .filter(Criterion("=", CollectionMeta.value, value))
            .all()
        )
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to search collections by AVU: {exc}",
            details={"attribute": attribute, "value": value},
        ) from exc

    out: list[dict[str, Any]] = []
    for row in rows or []:
        path = _row_value(row, Collection.name)
        if not path:
            continue
        out.append({"path": path, "entry_type": "collection", "name": path})
    return out


def _row_value(row: Any, column: Any) -> Any:
    """Defensive accessor for python-irodsclient query rows."""
    try:
        return row[column]
    except Exception:  # noqa: BLE001 - row might be a plain dict in tests
        # Tests sometimes hand back plain dicts keyed by the column's icat_key.
        key = getattr(column, "icat_key", None) or getattr(column, "name", None)
        if isinstance(row, dict) and key in row:
            return row[key]
        return None
