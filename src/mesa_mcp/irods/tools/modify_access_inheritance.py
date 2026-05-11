"""``ds_modify_access_inheritance`` — toggle a collection's ACL inheritance.

Python port of ``irods-mcp-server/irods/modify_access_inheritance.go``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import reject_anonymous_write, target_exists
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool


class ModifyAccessInheritanceInput(BaseModel):
    path: str = Field(
        description="The path to the directory (collection) to modify access.",
    )
    inherit: bool = Field(
        description=(
            "If set, access to the directory (collection) will be inherited "
            "by all child entries."
        ),
    )
    recurse: bool = Field(
        default=False,
        description=(
            "If set, apply the inheritance flag to all entries within the "
            "given directory (collection) recursively."
        ),
    )


@register_tool(
    "ds_modify_access_inheritance",
    "Modify data access inheritance flag of a file or directory.",
    input_model=ModifyAccessInheritanceInput,
)
async def handle_modify_access_inheritance(
    args: ModifyAccessInheritanceInput,
) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_modify_access_inheritance")
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    if not target_exists(session, normalized):
        raise ToolError(
            code="not_found",
            message=f"path {normalized!r} does not exist",
            details={"path": normalized},
        )

    try:
        from irods.access import iRODSAccess

        access_name = "inherit" if args.inherit else "noinherit"
        acl = iRODSAccess(access_name, normalized)
        session.acls.set(acl, recursive=args.recurse)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=f"failed to change access inheritance for {normalized!r}",
            details={"path": normalized, "cause": str(exc)},
        ) from exc

    return {
        "path": normalized,
        "inherit": args.inherit,
    }
