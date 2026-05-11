"""``mesa_ols_get_term_hierarchy`` — children of an OLS term (hierarchy walk)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient
from mesa_mcp.server import register_tool


class GetTermHierarchyInput(BaseModel):
    """Input schema for ``mesa_ols_get_term_hierarchy``."""

    ontology_id: str = Field(
        ..., min_length=1, description="Ontology identifier (e.g. 'envo')."
    )
    iri: str = Field(..., min_length=1, description="Full IRI of the parent term.")
    size: int = Field(50, ge=1, le=500, description="Max children to return.")


@register_tool(
    "mesa_ols_get_term_hierarchy",
    "List the direct children of an OLS term. Use this to walk an ontology's "
    "class hierarchy one level at a time.",
    input_model=GetTermHierarchyInput,
)
async def handle_get_term_hierarchy(
    args: GetTermHierarchyInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Return the children of the given term."""
    ols = client or get_default_client()
    try:
        children = ols.get_term_children(
            ontology_id=args.ontology_id,
            iri=args.iri,
            size=args.size,
        )
    except OLSAPIError as exc:  # pragma: no cover - exercised via mocks
        return {
            "children": [],
            "count": 0,
            "error": str(exc),
            "status_code": exc.status_code,
        }
    return {
        "ontologyId": args.ontology_id.lower(),
        "parentIri": args.iri,
        "children": children,
        "count": len(children),
    }
