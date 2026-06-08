"""``mesa_avu_apply_datacite`` — validate a DataCite record and bulk-write it as AVUs.

Validates against the DataCite 4.x model, serializes via datacite_to_avus, writes
every AVU to the iRODS path, then mirrors them into DuckLake as ONE snapshot.
Mirrors irods/tools/add_avus.py + ols/tools/avu_apply_term.py.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.datacite.schema import DataCiteMetadata
from mesa_mcp.datacite.transform import datacite_to_avus
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_changes
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import add_avu_to_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "mesa_avu_apply_datacite"


class ApplyDataCiteInput(BaseModel):
    target: str = Field(..., description="iRODS path of the data-object or collection.")
    record: dict[str, Any] = Field(..., description="A DataCite 4.x record (validated).")
    naming: str = Field("both", description="canonical | cyverse_template | both")


@register_tool(
    TOOL_NAME,
    "Validate a DataCite 4.x record and write it to an iRODS path as AVUs (canonical "
    "and/or CyVerse-template naming), mirrored to DuckLake as one snapshot.",
    input_model=ApplyDataCiteInput,
)
async def handle_apply_datacite(
    args: ApplyDataCiteInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Validate a DataCite record; bulk-write its AVUs; mirror as one DuckLake snapshot."""
    if auth_value is None:
        raise ToolError(code="unauthenticated", message=f"{TOOL_NAME} requires authentication.")

    try:
        record = DataCiteMetadata.model_validate(args.record)
    except ValidationError as exc:
        raise ToolError(
            code="datacite_invalid",
            message="record failed DataCite validation",
            details={"errors": exc.errors(include_url=False)},
        ) from exc

    avus = datacite_to_avus(record, naming=args.naming)

    norm = assert_allowed(args.target, auth_value)
    session = default_pool().get(auth_value)
    path_target = resolve_path_target(session, norm)

    written: list[dict[str, str]] = []
    batch_changes: list[tuple[str, str, str, Literal["add", "delete"]]] = []
    errors: list[dict[str, str]] = []

    for avu in avus:
        try:
            w = add_avu_to_irods(
                session,
                norm,
                path_target,
                {"attribute": avu["attribute"], "value": avu["value"], "unit": ""},
            )
            written.append(w)
            batch_changes.append((w["attribute"], w["value"], w["unit"], "add"))
        except ToolError as exc:
            errors.append({"attribute": avu["attribute"], "error": str(exc)})

    result: dict[str, Any] = {
        "target": norm,
        "path_target_type": path_target,
        "written": len(written),
        "errors": errors,
    }

    if batch_changes:
        try:
            await record_avu_changes(
                auth_value=auth_value,
                irods_path=norm,
                target_type=path_target,
                changes=batch_changes,
                tool_name=TOOL_NAME,
                session=session,
            )
        except DuckLakeMirrorError as exc:
            result["partial_failure"] = {
                "code": "ducklake_mirror_failed",
                "message": str(exc),
            }

    return result
