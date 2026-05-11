"""``mesa_avu_from_term`` — pure ontology-term → AVU transformation.

This tool only *computes* the AVU triple. It does not touch iRODS and does not
record anything in DuckLake — the composite write-side tool
``mesa_avu_apply_term`` (deferred until iRODS auth lands) will do that.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.errors import ToolError
from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient, _label_to_snake
from mesa_mcp.ols.transform import ontology_annotations_to_avus
from mesa_mcp.server import register_tool


class AvuFromTermInput(BaseModel):
    """Input schema for ``mesa_avu_from_term``."""

    ontology_id: str = Field(
        ..., min_length=1, description="Ontology identifier (e.g. 'envo')."
    )
    value: str = Field(
        ...,
        min_length=1,
        description="User-supplied AVU value. Often the term label, but free-form.",
    )
    iri: str | None = Field(
        None,
        description=(
            "Full IRI of the term to use. Either ``iri`` or ``curie`` must be "
            "supplied, alongside ``label`` if you want to skip the OLS lookup."
        ),
    )
    curie: str | None = Field(
        None,
        description="Term CURIE (e.g. 'ENVO:00000428') — used directly as the AVU unit.",
    )
    label: str | None = Field(
        None,
        description=(
            "Term label. If omitted, mesa-mcp fetches it from OLS using "
            "``ontology_id`` + ``iri``."
        ),
    )


@register_tool(
    "mesa_avu_from_term",
    "Pure transformation: turn an OLS term + user value into the canonical AVU "
    "triple (attribute='<ontology>.<snake_case_label>', value=<value>, "
    "unit=<CURIE>) without writing to iRODS.",
    input_model=AvuFromTermInput,
)
async def handle_avu_from_term(
    args: AvuFromTermInput,
    *,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Compute the AVU dict for ``ontology_id`` + chosen term + value."""
    if not args.iri and not args.curie:
        raise ToolError(
            code="invalid_argument",
            message="Either 'iri' or 'curie' must be supplied.",
            details={},
        )

    label = args.label
    curie = args.curie or ""
    iri = args.iri or ""

    # If we don't have a label yet, look the term up.
    if label is None and args.iri:
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
        label = term.get("label", "")
        curie = curie or term.get("curie", "")
        iri = iri or term.get("iri", "")

    if not label:
        raise ToolError(
            code="invalid_argument",
            message="Could not determine a term label. Supply 'label' explicitly or 'iri'.",
            details={},
        )

    # Use the snake-case helper baked into the OLS client (same impl the portal uses).
    snake_key = _label_to_snake(label)
    if not snake_key:
        raise ToolError(
            code="invalid_argument",
            message=f"Label {label!r} could not be converted to a snake_case key.",
            details={"label": label},
        )

    avus = ontology_annotations_to_avus(
        args.ontology_id,
        [{"key": snake_key, "value": args.value, "curie": curie}],
    )
    if not avus:
        # Shouldn't happen given the checks above, but be defensive.
        raise ToolError(
            code="invalid_argument",
            message="Could not build an AVU from the supplied term + value.",
            details={"ontology_id": args.ontology_id, "value": args.value},
        )

    return {
        "avu": avus[0],
        "term": {
            "ontologyId": args.ontology_id.lower(),
            "label": label,
            "curie": curie,
            "iri": iri,
        },
    }
