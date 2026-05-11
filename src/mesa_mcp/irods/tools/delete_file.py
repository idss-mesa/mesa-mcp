"""``ds_delete_file`` — remove a data object or collection.

Python port of ``irods-mcp-server/irods/delete_file.go``. Collections are
removed recursively (``recurse=True``, ``force=True``) to match the Go
reference's ``RemoveDir(path, true, true)``.
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


class DeleteFileInput(BaseModel):
    path: str = Field(
        description="The path to the file (data-object) or directory (collection) to delete.",
    )


@register_tool(
    "ds_delete_file",
    "Delete a file (data-object) or directory (collection).",
    input_model=DeleteFileInput,
)
async def handle_delete_file(args: DeleteFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_delete_file")
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    kind, model = resolve_target(session, normalized)
    snapshot = entry_info(model, kind)

    try:
        if kind == "collection":
            session.collections.remove(normalized, recurse=True, force=True)
        else:
            session.data_objects.unlink(normalized, force=True)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=(
                f"failed to delete file (data-object) or directory "
                f"(collection) {normalized!r}"
            ),
            details={"path": normalized, "cause": str(exc)},
        ) from exc

    return {
        "path": normalized,
        "entry_info": snapshot,
    }
