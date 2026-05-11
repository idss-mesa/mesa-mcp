"""``ds_directory_tree`` — recursive directory walk with bounded depth.

Python port of ``irods-mcp-server/irods/directory_tree.go``.
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

# Match ``irods/common/default_values.go``.
DEFAULT_TREE_SCAN_MAX_DEPTH = 3
MAX_TREE_SCAN_DEPTH = 10


class DirectoryTreeInput(BaseModel):
    path: str = Field(description="The path to the directory (collection) to list.")
    depth: int = Field(
        default=DEFAULT_TREE_SCAN_MAX_DEPTH,
        description=(
            f"The depth of the directory tree to list. Default value is "
            f"{DEFAULT_TREE_SCAN_MAX_DEPTH}. Depth must be greater than or "
            f"equal to 1. Depth must not be too large, otherwise the "
            f"output may be too large. Maximum value is {MAX_TREE_SCAN_DEPTH}."
        ),
    )


def _walk(
    model: Any,
    auth_value: Any,
    webdav_base: str,
    cur_depth: int,
    max_depth: int,
) -> list[dict[str, Any]]:
    """Recursively serialize a collection's children, bounded by ``max_depth``."""
    entries: list[dict[str, Any]] = []

    for sub in getattr(model, "subcollections", []) or []:
        sub_path = getattr(sub, "path", None) or ""
        sub_entry: dict[str, Any] = {
            "entry_info": entry_info(sub, "collection"),
            **entry_uris(sub_path, auth_value, webdav_base),
        }
        if cur_depth + 1 <= max_depth:
            sub_entry["directory_entries"] = _walk(
                sub,
                auth_value,
                webdav_base,
                cur_depth + 1,
                max_depth,
            )
        entries.append(sub_entry)

    for obj in getattr(model, "data_objects", []) or []:
        obj_path = getattr(obj, "path", None) or ""
        entries.append(
            {
                "entry_info": entry_info(obj, "data_object"),
                **entry_uris(obj_path, auth_value, webdav_base),
            }
        )

    return entries


@register_tool(
    "ds_directory_tree",
    "Get a recursive tree view of files (data-objects) and directories "
    "(collections).\n\t\tThe specified path must be an iRODS path. The "
    "output is in JSON format.\n\t\tThe output contains all entries in the "
    "given directory (collection) path.",
    input_model=DirectoryTreeInput,
)
async def handle_directory_tree(args: DirectoryTreeInput) -> dict[str, Any]:
    auth_value = require_current_auth_value()
    normalized = assert_allowed(args.path, auth_value)

    pool = require_current_client_pool()
    config = require_current_config()
    session = pool.get(auth_value)

    depth = args.depth
    if depth <= 0:
        depth = DEFAULT_TREE_SCAN_MAX_DEPTH
    elif depth > MAX_TREE_SCAN_DEPTH:
        depth = MAX_TREE_SCAN_DEPTH

    kind, model = resolve_target(session, normalized)
    if kind != "collection":
        raise ToolError(
            code="invalid_argument",
            message=f"path {normalized!r} is not a directory (collection)",
            details={"path": normalized},
        )

    webdav_base = config.irods.webdav_url
    children = _walk(model, auth_value, webdav_base, 1, depth)

    directory_uris = entry_uris(normalized, auth_value, webdav_base)
    return {
        "directory_info": entry_info(model, "collection"),
        "directory_resource_uri": directory_uris["resource_uri"],
        "directory_webdav_uri": directory_uris["webdav_uri"],
        "directory_entries": children,
    }
