"""``ds_list_directory_details`` — paginated listing with ACL + replica info.

Python port of ``irods-mcp-server/irods/list_directory_details.go``. Same
output shape as ``ds_list_directory`` but each entry's ACL list is also
included, and ``webdav_uri`` is computed with the access list so anonymous
URLs are minted for anonymously-readable objects.
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
from mesa_mcp.irods._helpers import (
    access_records,
    entry_info,
    entry_uris,
    resolve_target,
)
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.server import register_tool


class ListDirectoryDetailsInput(BaseModel):
    path: str = Field(description="The path to the directory (collection) to list.")
    offset: int = Field(
        default=0,
        description="Number of entries to skip (for pagination). Default: 0.",
    )
    limit: int = Field(
        default=100,
        description="Maximum number of entries to return (for pagination). Default: 100, max: 500.",
    )


def _acls_for(session: Any, model: Any, kind: str) -> list[Any]:
    """Best-effort ACL fetch.

    ``python-irodsclient`` exposes ``session.acls.get(model)``. If the test
    double doesn't implement ``session.acls``, we silently fall back to an
    empty list so the rest of the handler can keep flowing — the result
    structure carries an ``accesses`` array of zero length, exactly as the
    Go reference does on partial failure.
    """
    acls = getattr(session, "acls", None)
    if acls is None:
        return []
    getter = getattr(acls, "get", None)
    if getter is None:
        return []
    try:
        return list(getter(model))
    except Exception:  # noqa: BLE001
        return []


@register_tool(
    "ds_list_directory_details",
    "Get a list of files (data-objects) and directories (collections) in a "
    "specified path with full detailed info.\n\t\tThe specified path must "
    "be an iRODS path. The output is in JSON format.\n\t\tThe output "
    "contains entries in the given directory (collection) path, and users "
    "or groups who can access the files (data-ojects). Files (data-objects) "
    "will also have replica information. Use offset and limit parameters to "
    "paginate through large directories.",
    input_model=ListDirectoryDetailsInput,
)
async def handle_list_directory_details(
    args: ListDirectoryDetailsInput,
) -> dict[str, Any]:
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

    offset = args.offset if args.offset >= 0 else 0
    limit = args.limit
    if limit <= 0:
        limit = 100
    elif limit > 500:
        limit = 500

    webdav_base = config.irods.webdav_url

    entries: list[dict[str, Any]] = []
    for sub in getattr(model, "subcollections", []) or []:
        sub_path = getattr(sub, "path", None) or ""
        sub_accesses = _acls_for(session, sub, "collection")
        uris = entry_uris(sub_path, auth_value, webdav_base, accesses=sub_accesses)
        entries.append(
            {
                "entry_info": entry_info(sub, "collection"),
                "accesses": access_records(sub_accesses),
                **uris,
            }
        )

    for obj in getattr(model, "data_objects", []) or []:
        obj_path = getattr(obj, "path", None) or ""
        obj_accesses = _acls_for(session, obj, "data_object")
        uris = entry_uris(obj_path, auth_value, webdav_base, accesses=obj_accesses)
        entries.append(
            {
                "entry_info": entry_info(obj, "data_object"),
                "accesses": access_records(obj_accesses),
                **uris,
            }
        )

    total = len(entries)
    if offset > total:
        offset = total
    end = min(offset + limit, total)
    page = entries[offset:end]

    directory_uris = entry_uris(normalized, auth_value, webdav_base)
    return {
        "directory_info": entry_info(model, "collection"),
        "directory_resource_uri": directory_uris["resource_uri"],
        "directory_webdav_uri": directory_uris["webdav_uri"],
        "directory_entries": page,
        "total": total,
        "offset": offset,
        "limit": limit,
    }
