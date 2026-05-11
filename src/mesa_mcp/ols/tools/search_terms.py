"""``mesa_ols_search_terms`` — cross-ontology or scoped term search."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient
from mesa_mcp.server import register_tool


class SearchTermsInput(BaseModel):
    """Input schema for ``mesa_ols_search_terms``."""

    query: str = Field(..., min_length=1, description="Free-text search string.")
    ontology_id: str | None = Field(
        None,
        description="Optional ontology to restrict the search (e.g. 'envo').",
    )
    descendants_of: str | None = Field(
        None,
        description=(
            "Optional parent term IRI. When set together with ``ontology_id``, "
            "only descendants of this term are returned (uses the v1-compat "
            "``allChildrenOf`` search)."
        ),
    )
    size: int = Field(15, ge=1, le=100, description="Max results.")


@register_tool(
    "mesa_ols_search_terms",
    "Search OLS terms across all ontologies or scoped to one. Optionally "
    "restrict to descendants of a parent IRI (hierarchy walk).",
    input_model=SearchTermsInput,
)
async def handle_search_terms(
    args: SearchTermsInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Return matched terms as a list under ``results``."""
    ols = client or get_default_client()
    try:
        if args.descendants_of and args.ontology_id:
            results = ols.search_term_descendants(
                query=args.query,
                ontology_id=args.ontology_id,
                parent_iri=args.descendants_of,
                size=args.size,
            )
        else:
            results = ols.search_terms(
                query=args.query,
                ontology_id=args.ontology_id,
                size=args.size,
            )
    except OLSAPIError as exc:  # pragma: no cover - exercised via mocks
        return {
            "results": [],
            "error": str(exc),
            "status_code": exc.status_code,
        }
    return {"results": results, "count": len(results)}
