"""``ds_add_avu`` — add an AVU to a file, directory, resource, or user.

Ported from ``irods-mcp-server/irods/add_avu.go``. Input shape and tool
description are byte-for-byte; on success the tool also calls
:func:`mesa_mcp.ducklake.client.record_avu_change` so the change is
mirrored into the project's DuckLake when the path lives inside a
MESA-enabled project.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_change
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import add_avu_to_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "ds_add_avu"


class AddAvuInput(BaseModel):
    """Input schema for ``ds_add_avu``. Mirrors the Go ``AddAVUInputArgs``."""

    target_type: Literal["path", "resource", "user"] = Field(
        ...,
        description=(
            "The type of the target to add AVU. It can be 'path', 'resource', "
            "or 'user'."
        ),
    )
    target: str = Field(
        ...,
        description=(
            "The target to add AVU. Path for 'path' target_type, resource name "
            "for 'resource' target_type, and user name for 'user' target_type."
        ),
    )
    attribute: str = Field(..., description="The attribute of the AVU to add.")
    value: str = Field(..., description="The value of the AVU to add.")
    unit: str = Field(
        default="",
        description="The unit of the AVU to add. Default is an empty string.",
    )


@register_tool(
    TOOL_NAME,
    "Add a new AVU (attribute-value-unit) to a file (data-object), directory "
    "(collection), resource, or user.",
    input_model=AddAvuInput,
)
async def handle_ds_add_avu(
    args: AddAvuInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Add an AVU; mirror successful path-target writes into DuckLake."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    if args.target_type == "path":
        norm = assert_allowed(args.target, auth_value)
        session = default_pool().get(auth_value)
        path_target = resolve_path_target(session, norm)
        avu = add_avu_to_irods(
            session,
            norm,
            path_target,
            {"attribute": args.attribute, "value": args.value, "unit": args.unit},
        )

        # iRODS write succeeded. Mirror to DuckLake (if MESA-enabled).
        result: dict[str, Any] = {
            "target_type": "path",
            "target": norm,
            "attribute": args.attribute,
            "path_target_type": path_target,
            "avu": avu,
        }
        try:
            await record_avu_change(
                auth_value=auth_value,
                irods_path=norm,
                target_type=path_target,
                attribute=avu["attribute"],
                value=avu["value"],
                unit=avu["unit"],
                op="add",
                tool_name=TOOL_NAME,
                session=session,
            )
        except DuckLakeMirrorError as exc:
            # Partial-failure: iRODS state is intact; DuckLake mirror failed.
            result["partial_failure"] = {
                "code": "ducklake_mirror_failed",
                "message": str(exc),
                "project_id": str(exc.project_id) if exc.project_id else None,
            }
        return result

    if args.target_type == "resource":
        session = default_pool().get(auth_value)
        _add_resource_avu(session, args.target, args.attribute, args.value, args.unit)
        return {
            "target_type": "resource",
            "target": args.target,
            "attribute": args.attribute,
        }

    if args.target_type == "user":
        session = default_pool().get(auth_value)
        _add_user_avu(session, args.target, args.attribute, args.value, args.unit)
        return {
            "target_type": "user",
            "target": args.target,
            "attribute": args.attribute,
        }

    raise ToolError(  # pragma: no cover - pydantic Literal blocks this
        code="invalid_argument",
        message=f"Unsupported target_type: {args.target_type!r}.",
        details={"target_type": args.target_type},
    )


def _add_resource_avu(
    session: Any,
    resource_name: str,
    attribute: str,
    value: str,
    unit: str,
) -> None:
    from irods.meta import iRODSMeta  # type: ignore[import-not-found]
    from irods.models import Resource  # type: ignore[import-not-found]

    try:
        session.metadata.add(Resource, resource_name, iRODSMeta(attribute, value, unit))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to add AVU to resource {resource_name!r}: {exc}",
            details={"resource": resource_name, "attribute": attribute},
        ) from exc


def _add_user_avu(
    session: Any,
    user_name: str,
    attribute: str,
    value: str,
    unit: str,
) -> None:
    from irods.meta import iRODSMeta  # type: ignore[import-not-found]
    from irods.models import User  # type: ignore[import-not-found]

    user = user_name.split("#", 1)[0] if "#" in user_name else user_name
    try:
        session.metadata.add(User, user, iRODSMeta(attribute, value, unit))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to add AVU to user {user_name!r}: {exc}",
            details={"user": user_name, "attribute": attribute},
        ) from exc
