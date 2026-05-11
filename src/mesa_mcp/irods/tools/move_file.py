"""``ds_move_file`` — rename / move a data object or collection.

Python port of ``irods-mcp-server/irods/move_file.go``.
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
    entry_info,
    reject_anonymous_write,
    resolve_target,
)
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool


class MoveFileInput(BaseModel):
    old_path: str = Field(
        description="The old path to the file (data-object) or directory (collection).",
    )
    new_path: str = Field(
        description=(
            "The new, complete path to move the file (data-object) or "
            "directory (collection) to, including its new name. The path "
            "must not already exist."
        ),
    )


@register_tool(
    "ds_move_file",
    "Move a file (data-object) or directory (collection) to a new location.",
    input_model=MoveFileInput,
)
async def handle_move_file(args: MoveFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_move_file")
    old_normalized = assert_allowed(args.old_path, auth_value)
    new_normalized = assert_allowed(args.new_path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    kind, model = resolve_target(session, old_normalized)
    old_entry_info = entry_info(model, kind)

    try:
        if kind == "collection":
            session.collections.move(old_normalized, new_normalized)
        else:
            session.data_objects.move(old_normalized, new_normalized)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=(
                f"failed to move file (data-object) or directory "
                f"(collection) from {old_normalized!r} to {new_normalized!r}"
            ),
            details={
                "old_path": old_normalized,
                "new_path": new_normalized,
                "cause": str(exc),
            },
        ) from exc

    new_kind, new_model = resolve_target(session, new_normalized)
    return {
        "old_path": old_normalized,
        "old_entry_info": old_entry_info,
        "new_path": new_normalized,
        "new_entry_info": entry_info(new_model, new_kind),
    }
