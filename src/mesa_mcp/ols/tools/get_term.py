"""``mesa_ols_get_term`` — full term record lookup by IRI."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.errors import ToolError
from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient
from mesa_mcp.server import register_tool


class GetTermInput(BaseModel):
    """Input schema for ``mesa_ols_get_term``."""

    ontology_id: str = Field(
        ..., min_length=1, description="Ontology identifier (e.g. 'envo')."
    )
    iri: str = Field(
        ...,
        min_length=1,
        description="Full term IRI, e.g. 'http://purl.obolibrary.org/obo/ENVO_00000428'.",
    )


@register_tool(
    "mesa_ols_get_term",
    "Get the full record (label, CURIE, synonyms, definition, parents/children) "
    "for a single OLS term by IRI.",
    input_model=GetTermInput,
)
async def handle_get_term(
    args: GetTermInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Return the term record, or raise ``ToolError(not_found)`` if absent."""
    ols = client or get_default_client()
    try:
        term = ols.get_term(args.ontology_id, args.iri)
    except OLSAPIError as exc:
        raise ToolError(
            code="upstream_error",
            message=str(exc),
            details={"status_code": exc.status_code},
        ) from exc

    if term is None:
        raise ToolError(
            code="not_found",
            message=f"Term {args.iri!r} not found in ontology {args.ontology_id!r}.",
            details={"ontology_id": args.ontology_id, "iri": args.iri},
        )
    return term
