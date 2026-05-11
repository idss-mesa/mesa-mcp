"""``mesa_avu_apply_term`` — composite OLS-term → iRODS-AVU → DuckLake.

Combines three steps that are otherwise separate tools:

1. Validate the iRODS path against the caller's accessible paths.
2. Resolve an OLS term (by IRI or CURIE) to ``{label, curie, iri}`` via
   the OLS singleton (no network if both label and curie are passed in).
3. Build the canonical AVU triple via ``ontology_annotations_to_avus`` and
   write it through the same helper ``ds_add_avu`` uses. The same helper
   then runs the DuckLake mirror.

The whole point of this tool is "one call, full provenance" for an agent
tagging a file with an ontology term.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_change
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import add_avu_to_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.ols import get_default_client
from mesa_mcp.ols.client import OLSAPIError, OLSClient, _label_to_snake
from mesa_mcp.ols.transform import ontology_annotations_to_avus
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_avu_apply_term"


class ApplyTermInput(BaseModel):
    """Input schema for ``mesa_avu_apply_term``."""

    path: str = Field(
        ...,
        description="Absolute iRODS path of the data object or collection to tag.",
    )
    ontology_id: str = Field(
        ...,
        min_length=1,
        description="Ontology identifier (e.g. 'envo').",
    )
    value: str = Field(
        ...,
        min_length=1,
        description="User-supplied AVU value. Often the term label, but free-form.",
    )
    iri: str | None = Field(
        None,
        description="Full IRI of the OLS term. Either ``iri`` or ``curie`` is required.",
    )
    curie: str | None = Field(
        None,
        description="CURIE of the OLS term (e.g. 'ENVO:00000428').",
    )
    label: str | None = Field(
        None,
        description=(
            "Optional term label. When omitted, the label is looked up "
            "via OLS so the AVU attribute can be ``<ontology>.<snake_case_label>``."
        ),
    )


@register_tool(
    TOOL_NAME,
    "Resolve an OLS term, build the canonical AVU triple "
    "(<ontology>.<snake_label>, <value>, <CURIE>), write it to the iRODS "
    "path, and record the change in the project's DuckLake. Composite of "
    "mesa_avu_from_term + ds_add_avu, in one call.",
    input_model=ApplyTermInput,
)
async def handle_mesa_avu_apply_term(
    args: ApplyTermInput,
    *,
    auth_value: AuthValue | None = None,
    client: OLSClient | None = None,
) -> dict[str, Any]:
    """Run the composite pipeline. Returns the AVU written + DuckLake info."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    if not args.iri and not args.curie:
        raise ToolError(
            code="invalid_argument",
            message="Either 'iri' or 'curie' must be supplied.",
            details={},
        )

    # 1. Path safety.
    norm = assert_allowed(args.path, auth_value)

    # 2. Resolve the term.
    label = args.label
    curie = args.curie or ""
    iri = args.iri or ""

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
            message=(
                "Could not determine a term label. Supply 'label' explicitly or "
                "'iri' so the OLS lookup can resolve one."
            ),
            details={},
        )

    snake_key = _label_to_snake(label)
    if not snake_key:
        raise ToolError(
            code="invalid_argument",
            message=f"Label {label!r} could not be converted to a snake_case key.",
            details={"label": label},
        )

    # 3. Build the AVU via the same transform the portal uses.
    avus = ontology_annotations_to_avus(
        args.ontology_id,
        [{"key": snake_key, "value": args.value, "curie": curie}],
    )
    if not avus:
        raise ToolError(
            code="invalid_argument",
            message="Could not build an AVU from the supplied term + value.",
            details={"ontology_id": args.ontology_id, "value": args.value},
        )
    avu = avus[0]

    # 4. Write through the shared helper (same code path as ds_add_avu).
    session = default_pool().get(auth_value)
    path_target = resolve_path_target(session, norm)
    written = add_avu_to_irods(session, norm, path_target, avu)

    # 5. Mirror to DuckLake.
    result: dict[str, Any] = {
        "path": norm,
        "target_type": path_target,
        "avu": written,
        "term": {
            "ontologyId": args.ontology_id.lower(),
            "label": label,
            "curie": curie,
            "iri": iri,
        },
    }
    try:
        await record_avu_change(
            auth_value=auth_value,
            irods_path=norm,
            target_type=path_target,
            attribute=written["attribute"],
            value=written["value"],
            unit=written["unit"],
            op="add",
            tool_name=TOOL_NAME,
            session=session,
        )
    except DuckLakeMirrorError as exc:
        result["partial_failure"] = {
            "code": "ducklake_mirror_failed",
            "message": str(exc),
            "project_id": str(exc.project_id) if exc.project_id else None,
        }
    return result
