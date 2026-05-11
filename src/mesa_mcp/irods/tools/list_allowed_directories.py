"""``ds_list_allowed_directories`` — enumerate the caller's accessible paths.

Python port of ``irods-mcp-server/irods/list_allowed_directories.go``.

The Go reference walks every registered tool and asks each one for the
paths it considers accessible (``GetAccessiblePaths``), then collates them
per-path along with the list of tools that work there. We don't have the
per-tool ``GetAccessiblePaths`` indirection in Python — the auth-aware
accessibility surface lives on :class:`AuthValue` itself — so the output
is computed from :meth:`AuthValue.accessible_paths` and the static
registry of ``ds_*`` tools currently loaded.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mesa_mcp.context import require_current_auth_value
from mesa_mcp.irods.webdav import make_resource_uri
from mesa_mcp.server import get_registered_tools, register_tool

# Tools that operate on a specific path (i.e. consume a caller's accessible
# paths) — used to populate ``apis_allowed`` per directory. ``ds_ping`` and
# ``ds_list_allowed_directories`` themselves don't take a path, so they're
# excluded.
_TOOLS_WITHOUT_PATH: frozenset[str] = frozenset(
    {
        "ds_ping",
        "ds_list_allowed_directories",
    }
)


class ListAllowedDirectoriesInput(BaseModel):
    """No inputs — matches the Go reference's empty schema."""


@register_tool(
    "ds_list_allowed_directories",
    "Get a list of directories (collections) that this server is allowed to "
    "access.\n\t\tThe output also contains API names that can be requested "
    "to each directory (collection).",
    input_model=ListAllowedDirectoriesInput,
)
async def handle_list_allowed_directories(
    _args: ListAllowedDirectoriesInput,
) -> dict[str, Any]:
    auth_value = require_current_auth_value()

    apis_for_path: list[str] = sorted(
        spec.name
        for spec in get_registered_tools()
        if spec.name.startswith("ds_") and spec.name not in _TOOLS_WITHOUT_PATH
    )

    directories: list[dict[str, Any]] = []
    for path in auth_value.accessible_paths():
        directories.append(
            {
                "path": path,
                "resource_uri": make_resource_uri(path),
                "apis_allowed": list(apis_for_path),
                "allowed": True,
            }
        )

    return {"directories": directories}
