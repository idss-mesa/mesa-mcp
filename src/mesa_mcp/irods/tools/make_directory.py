"""``ds_make_directory`` — create a new collection.

Python port of ``irods-mcp-server/irods/make_directory.go``.
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


class MakeDirectoryInput(BaseModel):
    path: str = Field(description="The path to the new directory to create.")


@register_tool(
    "ds_make_directory",
    "Make a new directory (collection).",
    input_model=MakeDirectoryInput,
)
async def handle_make_directory(args: MakeDirectoryInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_make_directory")
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    try:
        session.collections.create(normalized)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=f"failed to make directory (collection) for {normalized!r}",
            details={"path": normalized, "cause": str(exc)},
        ) from exc

    kind, model = resolve_target(session, normalized)
    return {
        "path": normalized,
        "entry_info": entry_info(model, kind),
    }
