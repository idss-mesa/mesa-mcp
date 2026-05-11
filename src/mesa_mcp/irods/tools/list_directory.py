"""``ds_list_directory`` — paginated directory listing.

Python port of ``irods-mcp-server/irods/list_directory.go``. Returns the
files and subdirectories under a collection along with their resource and
WebDAV URIs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.context import (
    require_current_auth_value,
    require_current_client_pool,
    require_current_config,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._helpers import entry_info, entry_uris, resolve_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool


class ListDirectoryInput(BaseModel):
    """Input schema matching the Go reference."""

    path: str = Field(description="The path to the directory (collection) to list.")
    offset: int = Field(
        default=0,
        description="Number of entries to skip (for pagination). Default: 0.",
    )
    limit: int = Field(
        default=100,
        description="Maximum number of entries to return (for pagination). Default: 100, max: 500.",
    )


def _list_entries(coll: Any, auth_value: Any, webdav_base: str) -> list[dict[str, Any]]:
    """Combine subcollections and data objects into one ordered list of entries."""
    entries: list[dict[str, Any]] = []

    for sub in getattr(coll, "subcollections", []) or []:
        sub_path = getattr(sub, "path", None)
        info = entry_info(sub, "collection")
        uris = entry_uris(sub_path or "", auth_value, webdav_base)
        entries.append({"entry_info": info, **uris})

    for obj in getattr(coll, "data_objects", []) or []:
        obj_path = getattr(obj, "path", None)
        info = entry_info(obj, "data_object")
        uris = entry_uris(obj_path or "", auth_value, webdav_base)
        entries.append({"entry_info": info, **uris})

    return entries


@register_tool(
    "ds_list_directory",
    "Get a list of files (data-objects) and directories (collections) in a "
    "specified path.\n\t\tThe specified path must be an iRODS path. The "
    "output is in JSON format.\n\t\tThe output contains entries in the "
    "given directory (collection) path. Use offset and limit parameters to "
    "paginate through large directories.",
    input_model=ListDirectoryInput,
)
async def handle_list_directory(args: ListDirectoryInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    config = require_current_config()
    session = pool.get(auth_value)

    kind, model = resolve_target(session, normalized)
    if kind != "collection":
        raise ToolError(
            code="invalid_argument",
            message=f"path {normalized!r} is not a directory (collection)",
            details={"path": normalized},
        )

    # Pagination defaults / clamping mirror the Go reference exactly.
    offset = args.offset if args.offset >= 0 else 0
    limit = args.limit
    if limit <= 0:
        limit = 100
    elif limit > 500:
        limit = 500

    all_entries = _list_entries(model, auth_value, config.irods.webdav_url)
    total = len(all_entries)
    if offset > total:
        offset = total
    end = min(offset + limit, total)
    page = all_entries[offset:end]

    directory_info = entry_info(model, "collection")
    directory_uris = entry_uris(normalized, auth_value, config.irods.webdav_url)
    return {
        "directory_info": directory_info,
        "directory_resource_uri": directory_uris["resource_uri"],
        "directory_webdav_uri": directory_uris["webdav_uri"],
        "directory_entries": page,
        "total": total,
        "offset": offset,
        "limit": limit,
    }
