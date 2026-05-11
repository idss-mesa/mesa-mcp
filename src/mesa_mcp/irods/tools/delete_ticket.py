"""``ds_delete_ticket`` — revoke an existing iRODS ticket."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import tickets as ticket_helpers
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class DeleteTicketInput(BaseModel):
    """Input schema for ``ds_delete_ticket``."""

    ticket: str = Field(
        ...,
        min_length=1,
        description="The ticket string to delete.",
    )


@register_tool(
    "ds_delete_ticket",
    (
        "Revoke an existing iRODS ticket. Issuer or admin only — the server "
        "enforces this. Anonymous callers are rejected at the tool layer."
    ),
    input_model=DeleteTicketInput,
)
async def handle_delete_ticket(
    args: DeleteTicketInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to delete tickets",
            details={"tool": "ds_delete_ticket"},
        )
    sess = session or default_pool().get(auth)
    return ticket_helpers.revoke_ticket(sess, args.ticket)
