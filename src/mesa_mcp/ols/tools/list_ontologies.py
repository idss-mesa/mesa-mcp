"""``mesa_ols_list_ontologies`` — paginated catalog of OLS ontologies."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient
from mesa_mcp.server import register_tool


class ListOntologiesInput(BaseModel):
    """Input schema for ``mesa_ols_list_ontologies``."""

    page: int = Field(0, ge=0, description="Zero-indexed page number.")
    size: int = Field(25, ge=1, le=200, description="Results per page (1–200).")


@register_tool(
    "mesa_ols_list_ontologies",
    "List ontologies available in the EMBL-EBI Ontology Lookup Service (OLS4), "
    "paginated. Returns 266+ ontologies (ENVO, GO, CHEBI, etc.).",
    input_model=ListOntologiesInput,
)
async def handle_list_ontologies(
    args: ListOntologiesInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Return the OLS ontology catalog page."""
    ols = client or get_default_client()
    try:
        return ols.list_ontologies(page=args.page, size=args.size)
    except OLSAPIError as exc:  # pragma: no cover - surfaced via tests on transport
        return {"error": str(exc), "status_code": exc.status_code}
