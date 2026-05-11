"""``mesa_ols_generate_template`` — SCHEMAS template from top-level ontology terms."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.errors import ToolError
from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient
from mesa_mcp.server import register_tool


class GenerateTemplateInput(BaseModel):
    """Input schema for ``mesa_ols_generate_template``."""

    ontology_id: str = Field(
        ...,
        min_length=1,
        description="Ontology identifier to generate a template for (e.g. 'envo').",
    )


@register_tool(
    "mesa_ols_generate_template",
    "Generate a SCHEMAS-compatible template (prefix + top-level term fields) "
    "for an ontology. This is the function that drives the esiil-portal "
    "auto-generated AVU forms.",
    input_model=GenerateTemplateInput,
)
async def handle_generate_template(
    args: GenerateTemplateInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Return the SCHEMAS dict for the ontology."""
    ols = client or get_default_client()
    try:
        return ols.generate_template(args.ontology_id)
    except OLSAPIError as exc:
        raise ToolError(
            code="upstream_error",
            message=str(exc),
            details={"status_code": exc.status_code, "ontology_id": args.ontology_id},
        ) from exc
