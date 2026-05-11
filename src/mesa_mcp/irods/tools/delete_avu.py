"""``ds_delete_avu`` — delete an AVU from a file, directory, resource, or user.

Ported from ``irods-mcp-server/irods/delete_avu.go``. Input shape is
byte-for-byte; on a successful path-target delete the change is mirrored
into DuckLake.

Note on the ``id`` field
------------------------
The Go reference accepts an ``id`` argument to address a specific AVU row.
python-irodsclient's high-level ``MetadataManager.remove`` API addresses
AVUs by ``(name, value, units)`` rather than by row id, so the ``id``
field is accepted in the schema (for wire compatibility) but ignored at
runtime — the call still goes through the triple. This matches the
behaviour you get from ``imeta rm`` on the iRODS command line.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_change
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import delete_avu_from_irods, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool

TOOL_NAME = "ds_delete_avu"


class DeleteAvuInput(BaseModel):
    """Input schema for ``ds_delete_avu``. Mirrors the Go ``DeleteAVUInputArgs``."""

    target_type: Literal["path", "resource", "user"] = Field(
        ...,
        description=(
            "The type of the target to delete AVU. It can be 'path', 'resource', "
            "or 'user'."
        ),
    )
    target: str = Field(
        ...,
        description=(
            "The target to delete AVU. Path for 'path' target_type, resource name "
            "for 'resource' target_type, and user name for 'user' target_type."
        ),
    )
    id: int = Field(
        default=0,
        description="The ID of the AVU to delete.",
    )
    attribute: str = Field(
        default="",
        description=(
            "The attribute of the AVU to delete. This field can be ignored if "
            "ID is provided."
        ),
    )
    value: str = Field(
        default="",
        description="The value of the AVU to delete. Default is an empty string.",
    )
    unit: str = Field(
        default="",
        description="The unit of the AVU to delete. Default is an empty string.",
    )


@register_tool(
    TOOL_NAME,
    "Delete an AVU (attribute-value-unit) from a file, directory, resource, or user.",
    input_model=DeleteAvuInput,
)
async def handle_ds_delete_avu(
    args: DeleteAvuInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Delete an AVU; mirror successful path-target deletes into DuckLake."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message=f"{TOOL_NAME} requires an authenticated caller.",
        )

    if args.target_type == "path":
        norm = assert_allowed(args.target, auth_value)
        session = default_pool().get(auth_value)
        path_target = resolve_path_target(session, norm)
        avu = delete_avu_from_irods(
            session,
            norm,
            path_target,
            {"attribute": args.attribute, "value": args.value, "unit": args.unit},
        )

        result: dict[str, Any] = {
            "target_type": "path",
            "target": norm,
            "id": args.id,
            "attribute": avu["attribute"],
            "value": avu["value"],
            "unit": avu["unit"],
            "path_target_type": path_target,
        }
        try:
            await record_avu_change(
                auth_value=auth_value,
                irods_path=norm,
                target_type=path_target,
                attribute=avu["attribute"],
                value=avu["value"],
                unit=avu["unit"],
                op="delete",
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

    if args.target_type == "resource":
        session = default_pool().get(auth_value)
        _delete_resource_avu(session, args.target, args.attribute, args.value, args.unit)
        return {
            "target_type": "resource",
            "target": args.target,
            "id": args.id,
            "attribute": args.attribute,
            "value": args.value,
            "unit": args.unit,
        }

    if args.target_type == "user":
        session = default_pool().get(auth_value)
        _delete_user_avu(session, args.target, args.attribute, args.value, args.unit)
        return {
            "target_type": "user",
            "target": args.target,
            "id": args.id,
            "attribute": args.attribute,
            "value": args.value,
            "unit": args.unit,
        }

    raise ToolError(  # pragma: no cover - pydantic Literal blocks this
        code="invalid_argument",
        message=f"Unsupported target_type: {args.target_type!r}.",
        details={"target_type": args.target_type},
    )


def _delete_resource_avu(
    session: Any,
    resource_name: str,
    attribute: str,
    value: str,
    unit: str,
) -> None:
    from irods.meta import iRODSMeta  # type: ignore[import-not-found]
    from irods.models import Resource  # type: ignore[import-not-found]

    try:
        session.metadata.remove(Resource, resource_name, iRODSMeta(attribute, value, unit))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to delete AVU from resource {resource_name!r}: {exc}",
            details={"resource": resource_name, "attribute": attribute},
        ) from exc


def _delete_user_avu(
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
        session.metadata.remove(User, user, iRODSMeta(attribute, value, unit))
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="irods_error",
            message=f"Failed to delete AVU from user {user_name!r}: {exc}",
            details={"user": user_name, "attribute": attribute},
        ) from exc
