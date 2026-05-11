"""``ds_get_metadata`` — fetch the full metadata bundle for a path.

The Go reference does not ship a standalone ``get_metadata.go`` file —
``ds_get_file_info`` includes AVUs in its bundle, and ``ds_list_avus``
returns just the AVU triples. The mesa-mcp tool list in ``CLAUDE.md``
calls out ``ds_get_metadata`` as a separate entry, so we expose it here
as a thin convenience over ``ds_list_avus``: same input shape but
narrowed to a single path argument, and the output includes the
detected ``target_type`` ("data_object" or "collection") plus the AVU
list so a caller has the full picture in one call.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.errors import ToolError
from mesa_mcp.irods._avu_helpers import list_avus_for_path, resolve_path_target
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class GetMetadataInput(BaseModel):
    """Input schema for ``ds_get_metadata``."""

    path: str = Field(
        ...,
        description=(
            "Absolute iRODS path of the data object or collection whose "
            "metadata you want."
        ),
    )


@register_tool(
    "ds_get_metadata",
    "Fetch the full AVU metadata bundle for an iRODS path (data object or "
    "collection). Returns the resolved target type alongside the AVU list.",
    input_model=GetMetadataInput,
)
async def handle_ds_get_metadata(
    args: GetMetadataInput,
    *,
    auth_value: AuthValue | None = None,
) -> dict[str, Any]:
    """Return ``{path, target_type, avus}`` for the requested iRODS path."""
    if auth_value is None:
        raise ToolError(
            code="unauthenticated",
            message="ds_get_metadata requires an authenticated caller.",
        )

    norm = assert_allowed(args.path, auth_value)
    session = default_pool().get(auth_value)
    target_type = resolve_path_target(session, norm)
    avus = list_avus_for_path(session, norm, target_type)

    return {
        "path": norm,
        "target_type": target_type,
        "avus": avus,
    }
