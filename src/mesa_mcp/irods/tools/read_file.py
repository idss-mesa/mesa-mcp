"""``ds_read_file`` — read a slice of a data object.

Python port of ``irods-mcp-server/irods/read_file.go``. The Go reference
returns MCP content blocks (text/image/embedded resource); since the
mesa-mcp tool registry expects ``dict`` returns, we serialize the same
information into a structured payload: caller gets the bytes (as text or
base64), the detected MIME type, and the size markers the Go reference
uses to decide encoding.
"""

from __future__ import annotations

import base64
import mimetypes
from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
    require_current_config,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import resolve_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.webdav import make_resource_uri, make_webdav_url
from mesa_mcp.server import register_tool

MIN_READ_LENGTH = 64 * 1024  # 64KB — matches Go ``MinReadLength``.
MAX_INLINE_SIZE = 1 * 1024 * 1024  # 1MB — matches Go ``MaxInlineSize``.
MAX_BASE64_SIZE = 1 * 1024 * 1024  # 1MB — matches Go ``MaxBase64Size``.


class ReadFileInput(BaseModel):
    path: str = Field(description="The path to the file (data-object) to read.")
    offset: int = Field(
        default=0,
        description="The offset to start reading the file from. Default is 0.",
    )
    length: int = Field(
        default=MIN_READ_LENGTH,
        description=(
            f"The maximum length of the file to read. Default value is "
            f"{MAX_INLINE_SIZE}. Length must be greater than or equal to "
            f"{MIN_READ_LENGTH}. Length must not be too large, otherwise "
            f"the output may be too large. Maximum value is {MAX_INLINE_SIZE}."
        ),
    )


def _is_text_mime(mime_type: str) -> bool:
    """Same predicate the Go reference uses to decide text-vs-binary."""
    if mime_type.startswith("text/"):
        return True
    if mime_type in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/javascript",
        "application/x-javascript",
        "application/x-yaml",
    }:
        return True
    return "+xml" in mime_type or "+json" in mime_type or "+yaml" in mime_type


@register_tool(
    "ds_read_file",
    "Read the partial content of a file (data-object) with the specified "
    "path and offset.\n\t\tThe specified path must be an iRODS path.\n\t\tIf "
    "the file is too large to be displayed inline, use the WebDAV URI to "
    "access it.",
    input_model=ReadFileInput,
)
async def handle_read_file(args: ReadFileInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    config = require_current_config()
    session = pool.get(auth_value)

    length = args.length
    if length < MIN_READ_LENGTH:
        length = MIN_READ_LENGTH
    elif length > MAX_INLINE_SIZE:
        length = MAX_INLINE_SIZE

    kind, model = resolve_target(session, normalized)
    resource_uri = make_resource_uri(normalized)
    webdav_uri = make_webdav_url(config.irods.webdav_url, normalized, auth_value)

    if kind != "data_object":
        # Match Go: return a reference instead of erroring.
        return {
            "path": normalized,
            "is_directory": True,
            "resource_uri": resource_uri,
            "message": (
                f"This is a directory (collection). Use the resource URI "
                f"to browse its contents: {resource_uri!r}"
            ),
        }

    size = getattr(model, "size", 0) or 0
    offset = args.offset
    if offset < 0:
        offset = 0
    elif offset >= size:
        offset = size

    # Read the slice.
    try:
        with session.data_objects.open(normalized, "r") as fp:
            fp.seek(offset)
            content_bytes: bytes = fp.read(length)
    except Exception as exc:  # noqa: BLE001
        raise ToolError(
            code="internal_error",
            message=f"failed to read file (data-object) {normalized!r}",
            details={"path": normalized, "cause": str(exc)},
        ) from exc

    mime_type, _ = mimetypes.guess_type(normalized)
    if not mime_type:
        # Same fallback as Go's ``http.DetectContentType`` when offset==0.
        mime_type = "application/octet-stream"

    payload: dict[str, Any] = {
        "path": normalized,
        "offset": offset,
        "length": len(content_bytes),
        "size": size,
        "mime_type": mime_type,
        "resource_uri": resource_uri,
        "webdav_uri": webdav_uri,
    }

    if _is_text_mime(mime_type):
        try:
            payload["text"] = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            payload["text"] = content_bytes.decode("utf-8", errors="replace")
        return payload

    # Binary / image — base64 if under the inline size cap.
    if size <= MAX_BASE64_SIZE:
        payload["base64"] = base64.b64encode(content_bytes).decode("ascii")
    else:
        payload["message"] = (
            f"Binary file ({mime_type!r}, {size} bytes) is too large to "
            f"encode to base64 format. Access it via WebDAV URI: {webdav_uri!r}"
        )
    return payload
