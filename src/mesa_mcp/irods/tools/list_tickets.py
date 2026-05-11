"""``ds_list_tickets`` — list iRODS tickets visible to the caller.

Ported from ``irods-mcp-server/irods/list_tickets.go``. Anonymous users
are forbidden, matching the Go server's behaviour. Output shape mirrors
the Go ``model.TicketWithRestrictions`` payload: each entry has
``ticket`` (the iRODS ticket row) and ``restrictions`` (allowed hosts /
users / groups).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import tickets as ticket_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class ListTicketsInput(BaseModel):
    """Input schema for ``ds_list_tickets`` (no arguments)."""


@register_tool(
    "ds_list_tickets",
    (
        "Get a list of iRODS tickets. Return information about the tickets, "
        "such as their IDs and expiration times, in JSON format. Anonymous "
        "users are not allowed to list tickets."
    ),
    input_model=ListTicketsInput,
)
async def handle_list_tickets(
    _args: ListTicketsInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Return ``{"tickets": [...]}``. ``session`` injection is for tests only."""
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to list tickets",
            details={"tool": "ds_list_tickets"},
        )
    sess = session or default_pool().get(auth)
    return {"tickets": ticket_helpers.list_tickets(sess)}
