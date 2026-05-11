"""``ds_write_file`` — write base64-encoded bytes at an offset.

Python port of ``irods-mcp-server/irods/write_file.go``. Reads base64
payload, decodes, opens the data object for append/write, seeks, writes.

Anonymous callers are rejected up front per the project access rules.
"""

from __future__ import annotations

import base64
from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import reject_anonymous_write, resolve_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool

MAX_INLINE_SIZE = 1 * 1024 * 1024  # 1MB — matches ``read_file.py``.


class WriteFileInput(BaseModel):
    path: str = Field(description="The path to the file (data-object) to write to.")
    offset: int = Field(
        default=0,
        description="The offset to start writing the file from. Default is 0.",
    )
    content: str = Field(
        description=(
            f"The Base64-encoded content to write to the file (data-object). "
            f"Maximum size is {MAX_INLINE_SIZE} bytes."
        ),
    )


@register_tool(
    "ds_write_file",
    "Write the partial content to a file (data-object) with the specified "
    "path and offset.\n\t\tThe specified path must be an iRODS path.\n\t\tIf "
    "the file is too large to be displayed inline, use the WebDAV URI to "
    "access it.",
    input_model=WriteFileInput,
)
async def handle_write_file(args: WriteFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    reject_anonymous_write(auth_value, "ds_write_file")
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    session = pool.get(auth_value)

    try:
        raw_bytes = base64.b64decode(args.content, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="invalid_argument",
            message=(
                f"failed to decode base64 content for file (data-object) "
                f"{normalized!r}"
            ),
            details={"path": normalized},
        ) from exc

    # If the path resolves to a collection, that's an error matching Go.
    file_size = 0
    try:
        kind, model = resolve_target(session, normalized)
        if kind == "collection":
            raise ToolError(
                code="invalid_argument",
                message=f"path {normalized!r} is a directory (collection)",
                details={"path": normalized},
            )
        file_size = getattr(model, "size", 0) or 0
    except ToolError as exc:
        if exc.code == "not_found":
            # New file; offset clamped to 0.
            file_size = 0
        else:
            raise

    offset = args.offset
    if offset < 0:
        offset = 0
    elif offset >= file_size:
        offset = file_size

    # ``r+`` keeps the file's existing contents intact and supports seek;
    # ``w`` would truncate. For brand-new files we use ``w`` and ignore the
    # offset.
    open_mode = "w" if file_size == 0 else "r+"
    try:
        with session.data_objects.open(normalized, open_mode) as fp:
            if open_mode == "r+" and offset > 0:
                fp.seek(offset)
            fp.write(raw_bytes)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=f"failed to write file (data-object) {normalized!r}",
            details={"path": normalized, "cause": str(exc)},
        ) from exc

    return {
        "path": normalized,
        "offset": offset,
        "bytes_written": len(raw_bytes),
    }
