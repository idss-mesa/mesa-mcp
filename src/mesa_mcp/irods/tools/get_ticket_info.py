"""``ds_get_ticket_info`` — fetch a single iRODS ticket by name.

Ported from ``irods-mcp-server/irods/get_ticket_info.go``. The Go server
exposes the input field as ``name``; we mirror that exactly so MCP
clients can swap between the two servers transparently.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import tickets as ticket_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class GetTicketInfoInput(BaseModel):
    """Input schema for ``ds_get_ticket_info``."""

    name: str = Field(
        ...,
        min_length=1,
        description="The name of the iRODS ticket to get information about.",
    )


@register_tool(
    "ds_get_ticket_info",
    (
        "Get information about a specific iRODS ticket, such as its ID and "
        "expiration time, in JSON format. Anonymous users are not allowed to "
        "get ticket information."
    ),
    input_model=GetTicketInfoInput,
)
async def handle_get_ticket_info(
    args: GetTicketInfoInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to list tickets",
            details={"tool": "ds_get_ticket_info"},
        )
    sess = session or default_pool().get(auth)
    info = ticket_helpers.lookup_ticket(sess, args.name)
    if info is None:
        raise ToolError(
            code="not_found",
            message=f"Ticket {args.name!r} not found.",
            details={"ticket": args.name},
        )
    return info
