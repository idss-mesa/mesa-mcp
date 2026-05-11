"""``ds_get_file_info`` — detailed metadata about a file or directory.

Python port of ``irods-mcp-server/irods/get_file_info.go``.
"""

from __future__ import annotations

import mimetypes
from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
    require_current_config,
)
from mesa_mcp.irods._helpers import (
    access_records,
    avu_records,
    entry_info,
    entry_uris,
    resolve_target,
)
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool


class GetFileInfoInput(BaseModel):
    path: str = Field(
        description="The path to the file (data-object) or directory (collection).",
    )


def _mime_type_from_extension(path: str) -> str:
    """Best-effort MIME type from extension. Falls back to octet-stream."""
    if not path:
        return "application/octet-stream"
    guess, _ = mimetypes.guess_type(path)
    return guess or "application/octet-stream"


@register_tool(
    "ds_get_file_info",
    "Retrieve detailed metadata about a file or directory.",
    input_model=GetFileInfoInput,
)
async def handle_get_file_info(args: GetFileInfoInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    config = require_current_config()
    session = pool.get(auth_value)

    kind, model = resolve_target(session, normalized)

    # ACLs
    accesses: list[Any] = []
    acls = getattr(session, "acls", None)
    if acls is not None and hasattr(acls, "get"):
        try:
            accesses = list(acls.get(model))
        except Exception:  # noqa: BLE001
            accesses = []

    # Inheritance — only meaningful for collections.
    access_inheritance: dict[str, Any] | None = None
    if kind == "collection":
        inherit = getattr(model, "inheritance", None)
        if inherit is not None:
            access_inheritance = {"path": normalized, "inherit": bool(inherit)}

    # AVUs (filter system attributes for anonymous users, like Go does).
    avus: list[Any] = []
    meta = getattr(model, "metadata", None)
    if meta is not None and hasattr(meta, "items"):
        try:
            avus = list(meta.items())
        except Exception:  # noqa: BLE001
            avus = []

    serialized_avus = avu_records(avus, hide_system=auth_value.is_anonymous())

    if kind == "collection":
        mime_type = "Directory"
    else:
        mime_type = _mime_type_from_extension(normalized)

    uris = entry_uris(normalized, auth_value, config.irods.webdav_url, accesses=accesses)
    return {
        "mime_type": mime_type,
        "entry_info": entry_info(model, kind),
        "resource_uri": uris["resource_uri"],
        "webdav_uri": uris["webdav_uri"],
        "accesses": access_records(accesses),
        "access_inheritance": access_inheritance,
        "avus": serialized_avus,
    }
