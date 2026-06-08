"""``ds_add_avus`` — bulk-add multiple AVUs to one data-object or collection.

Writes N AVUs to iRODS and then mirrors them ALL into DuckLake as a SINGLE
snapshot via :func:`mesa_mcp.ducklake.client.record_avu_changes`.  This
replaces N sequential ``ds_add_avu`` calls (each of which triggers its own
Parquet push) with one batched round-trip — ~30× fewer iRODS network hops when
tagging a typical ~30-AVU object.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_changes
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import add_avu_to_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "ds_add_avus"


class AvuItem(BaseModel):
    """A single AVU triple."""

    attribute: str
    value: str
    unit: str = ""


class AddAvusInput(BaseModel):
    """Input schema for ``ds_add_avus``."""

    target_type: Literal["path"] = "path"
    target: str = Field(..., description="iRODS path of the data-object or collection.")
    avus: list[AvuItem] = Field(
        ..., description="AVUs to add in one batched call."
    )


@register_tool(
    TOOL_NAME,
    "Add MULTIPLE AVUs to one data-object/collection in a single call and mirror "
    "them all into DuckLake as ONE snapshot (efficient bulk tagging).",
    input_model=AddAvusInput,
)
async def handle_ds_add_avus(
    args: AddAvusInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Add many AVUs to one path; mirror them all in a single DuckLake snapshot."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    norm = assert_allowed(args.target, auth_value)
    session = default_pool().get(auth_value)
    path_target = resolve_path_target(session, norm)

    written: list[dict[str, str]] = []
    batch_changes: list[tuple[str, str, str, Literal["add", "delete"]]] = []
    errors: list[dict[str, str]] = []

    for item in args.avus:
        try:
            avu = add_avu_to_irods(
                session,
                norm,
                path_target,
                {"attribute": item.attribute, "value": item.value, "unit": item.unit},
            )
        except ToolError as exc:
            errors.append({"attribute": item.attribute, "error": str(exc)})
            continue

        written.append(avu)
        batch_changes.append((avu["attribute"], avu["value"], avu["unit"], "add"))

    result: dict[str, Any] = {
        "target_type": "path",
        "target": norm,
        "path_target_type": path_target,
        "written": len(written),
        "avus": written,
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
                "project_id": str(exc.project_id) if exc.project_id else None,
            }

    return result
