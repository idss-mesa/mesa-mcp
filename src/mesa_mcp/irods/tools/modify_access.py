"""``ds_modify_access`` — change user/group ACL on a path.

Python port of ``irods-mcp-server/irods/modify_access.go``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import (
    reject_anonymous_write,
    split_user_zone,
    target_exists,
)
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool

# The enum mirrors ``modify_access.go`` byte-for-byte.
_ACCESS_LEVELS: tuple[str, ...] = (
    "own",
    "delete_object",
    "modify_object",
    "create_object",
    "delete_metadata",
    "modify_metadata",
    "create_metadata",
    "read_object",
    "read_metadata",
    "null",
    "read",
    "write",
)


class ModifyAccessInput(BaseModel):
    access_level: str = Field(
        description=(
            "The access level to set to the user. It can be 'own', "
            "'delete_object', 'modify_object', 'create_object', "
            "'delete_metadata', 'modify_metadata', 'create_metadata', "
            "'read_object', 'read_metadata', or 'null'. For iRODS version "
            "prior to 4.3.0, only 'own', 'write', 'read', and 'null' are "
            "allowed."
        ),
    )
    user_or_group: str = Field(
        description=(
            "The user or group to set access. You can specify a user by "
            "'username#zone' or a group by 'groupname#zone' to set zone. "
            "if zone is not specified, the client's zone will be used."
        ),
    )
    path: str = Field(
        description=(
            "The path to the file (data-object) or directory (collection) "
            "to modify access."
        ),
    )
    recurse: bool = Field(
        default=False,
        description=(
            "If set, apply the given access to all entries within the "
            "given directory (collection) recursively."
        ),
    )


@register_tool(
    "ds_modify_access",
    "Modify data access of a user or group to a file (data-object) or directory (collection).",
    input_model=ModifyAccessInput,
)
async def handle_modify_access(args: ModifyAccessInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_modify_access")

    if args.access_level not in _ACCESS_LEVELS:
        raise ToolError(
            code="invalid_argument",
            message=(
                f"invalid access_level {args.access_level!r}; expected one "
                f"of {list(_ACCESS_LEVELS)}"
            ),
            details={"access_level": args.access_level},
        )

    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    if not target_exists(session, normalized):
        raise ToolError(
            code="not_found",
            message=f"path {normalized!r} does not exist",
            details={"path": normalized},
        )

    user, zone = split_user_zone(args.user_or_group, auth_value.zone)

    try:
        from irods.access import iRODSAccess

        acl = iRODSAccess(args.access_level, normalized, user, zone)
        # The PRC ``session.acls.set`` accepts a ``recursive`` kwarg.
        session.acls.set(acl, recursive=args.recurse)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=(
                f"failed to change ACLs for {args.user_or_group!r} to "
                f"{normalized!r} with access level {args.access_level!r}"
            ),
            details={
                "path": normalized,
                "user": user,
                "zone": zone,
                "cause": str(exc),
            },
        ) from exc

    return {
        "path": normalized,
        "user_name": user,
        "user_zone": zone,
        "access_level": args.access_level,
    }
