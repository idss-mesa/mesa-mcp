"""``mesa_ols_get_ontology`` — single ontology detail lookup."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.errors import ToolError
from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient
from mesa_mcp.server import register_tool


class GetOntologyInput(BaseModel):
    """Input schema for ``mesa_ols_get_ontology``."""

    ontology_id: str = Field(
        ...,
        min_length=1,
        description="Ontology identifier, e.g. 'envo', 'go', 'chebi'. Case-insensitive.",
    )


@register_tool(
    "mesa_ols_get_ontology",
    "Fetch metadata for a single OLS ontology (term count, version, homepage, "
    "preferred prefix).",
    input_model=GetOntologyInput,
)
async def handle_get_ontology(
    args: GetOntologyInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Return the ontology detail record."""
    ols = client or get_default_client()
    try:
        return ols.get_ontology(args.ontology_id)
    except OLSAPIError as exc:
        if exc.status_code == 404:
            raise ToolError(
                code="not_found",
                message=f"Ontology {args.ontology_id!r} not found in OLS.",
                details={"ontology_id": args.ontology_id},
            ) from exc
        raise ToolError(
            code="upstream_error",
            message=str(exc),
            details={"status_code": exc.status_code},
        ) from exc
