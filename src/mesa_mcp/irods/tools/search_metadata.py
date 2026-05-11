"""``ds_search_metadata`` — flexible metadata search across iCAT.

The Go reference doesn't ship a standalone ``search_metadata.go``; the
mesa-mcp ``CLAUDE.md`` lists ``ds_search_metadata`` alongside
``ds_search_files_by_avu`` as the more permissive sibling. This tool
accepts any combination of ``attribute``, ``value``, and ``unit`` (each
matched exactly) plus an optional ``target`` filter (``data_object``,
``collection``, ``both``). Results are filtered to the caller's
accessible paths.

Use ``ds_search_files_by_avu`` for the byte-for-byte Go-compatible
shape; use this tool when you want to narrow by unit, restrict to
collections only, or look up rows by attribute alone.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.access import is_within, normalize
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class SearchMetadataInput(BaseModel):
    """Input schema for ``ds_search_metadata``."""

    attribute: str | None = Field(
        None,
        description="Match only AVUs with this attribute name.",
    )
    value: str | None = Field(
        None,
        description="Match only AVUs with this value.",
    )
    unit: str | None = Field(
        None,
        description="Match only AVUs with this unit (often an ontology CURIE).",
    )
    target: Literal["data_object", "collection", "both"] = Field(
        "both",
        description="Restrict results to data objects, collections, or both.",
    )

    @model_validator(mode="after")
    def _at_least_one_predicate(self) -> SearchMetadataInput:
        if not (self.attribute or self.value or self.unit):
            raise ValueError(
                "ds_search_metadata requires at least one of 'attribute', "
                "'value', or 'unit'."
            )
        return self


@register_tool(
    "ds_search_metadata",
    "Search iRODS by AVU attribute/value/unit. More permissive than "
    "ds_search_files_by_avu: any combination of attribute, value, and unit "
    "can be supplied and you can restrict the result type to data objects, "
    "collections, or both.",
    input_model=SearchMetadataInput,
)
async def handle_ds_search_metadata(
    args: SearchMetadataInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Return matching entries filtered to the caller's accessible paths."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message="ds_search_metadata requires an authenticated caller.",
        )

    session = default_pool().get(auth_value)
    accessible_roots = [normalize(p) for p in auth_value.accessible_paths()]

    entries: list[dict[str, Any]] = []
    if args.target in ("data_object", "both"):
        entries.extend(_search_data_objects(session, args.attribute, args.value, args.unit))
    if args.target in ("collection", "both"):
        entries.extend(_search_collections(session, args.attribute, args.value, args.unit))

    filtered: list[dict[str, Any]] = []
    for entry in entries:
        path = entry.get("path", "")
        if any(is_within(path, root) for root in accessible_roots):
            filtered.append(entry)

    return {
        "search_attribute": args.attribute,
        "search_value": args.value,
        "search_unit": args.unit,
        "target": args.target,
        "matching_entries": filtered,
    }


def _search_data_objects(
    session: Any,
    attribute: str | None,
    value: str | None,
    unit: str | None,
) -> list[dict[str, Any]]:
    from irods.column import Criterion  # type: ignore[import-not-found]
    from irods.models import (  # type: ignore[import-not-found]
        Collection,
        DataObject,
        DataObjectMeta,
    )

    try:
        q = session.query(Collection.name, DataObject.name)
        if attribute:
            q = q.filter(Criterion("=", DataObjectMeta.name, attribute))
        if value:
            q = q.filter(Criterion("=", DataObjectMeta.value, value))
        if unit:
            q = q.filter(Criterion("=", DataObjectMeta.units, unit))
        rows = q.all()
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to search data objects by metadata: {exc}",
            details={"attribute": attribute, "value": value, "unit": unit},
        ) from exc

    out: list[dict[str, Any]] = []
    for row in rows or []:
        coll = _row_value(row, Collection.name)
        name = _row_value(row, DataObject.name)
        if not coll or not name:
            continue
        out.append(
            {
                "path": f"{coll.rstrip('/')}/{name}",
                "entry_type": "data_object",
                "name": name,
            }
        )
    return out


def _search_collections(
    session: Any,
    attribute: str | None,
    value: str | None,
    unit: str | None,
) -> list[dict[str, Any]]:
    from irods.column import Criterion  # type: ignore[import-not-found]
    from irods.models import (  # type: ignore[import-not-found]
        Collection,
        CollectionMeta,
    )

    try:
        q = session.query(Collection.name)
        if attribute:
            q = q.filter(Criterion("=", CollectionMeta.name, attribute))
        if value:
            q = q.filter(Criterion("=", CollectionMeta.value, value))
        if unit:
            q = q.filter(Criterion("=", CollectionMeta.units, unit))
        rows = q.all()
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to search collections by metadata: {exc}",
            details={"attribute": attribute, "value": value, "unit": unit},
        ) from exc

    out: list[dict[str, Any]] = []
    for row in rows or []:
        path = _row_value(row, Collection.name)
        if not path:
            continue
        out.append({"path": path, "entry_type": "collection", "name": path})
    return out


def _row_value(row: Any, column: Any) -> Any:
    try:
        return row[column]
    except Exception:  # noqa: BLE001
        key = getattr(column, "icat_key", None) or getattr(column, "name", None)
        if isinstance(row, dict) and key in row:
            return row[key]
        return None
