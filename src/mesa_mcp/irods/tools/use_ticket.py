"""``ds_use_ticket`` — bind a ticket id to the current MCP call.

This tool does **not** mutate the user's primary session. Instead it
records the ticket id on the ``current_ticket`` :class:`contextvars.ContextVar`
so any subsequent AVU writes (or other writes) made in the same MCP
call carry the ticket id through into DuckLake's ``via_ticket`` column
(see ``mesa-ducklake/CLAUDE.md``).

The tool also opens a ticket-mediated session as a sanity check —
``python-irodsclient``'s ``session.tickets`` / ``supply`` mechanism
attaches a ticket to subsequent operations on that session, and we
exercise it once to confirm the ticket is valid. We do not return the
ticket-mediated session: tool handlers go back through ``default_pool``
for their main session, and only the contextvar carries provenance.
"""

from __future__ import annotations

from typing import Any

from irods.ticket import Ticket
from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import current_ticket, require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class UseTicketInput(BaseModel):
    """Input schema for ``ds_use_ticket``."""

    ticket: str = Field(
        ...,
        min_length=1,
        description="The ticket string to use for subsequent operations.",
    )


@register_tool(
    "ds_use_ticket",
    (
        "Bind an iRODS ticket to the current MCP call. Subsequent AVU writes "
        "made in the same call record the ticket id in DuckLake's via_ticket "
        "column. Does not modify the caller's primary session."
    ),
    input_model=UseTicketInput,
)
async def handle_use_ticket(
    args: UseTicketInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to use tickets",
            details={"tool": "ds_use_ticket"},
        )

    # Open a ticket-mediated session as a validity probe. ``Ticket.supply``
    # binds the ticket to the session it was constructed against, so we
    # don't use the caller's primary session here — we hand the ticket to
    # a fresh session that the pool would otherwise serve. Anything that
    # fails surfaces as a ToolError to the caller.
    sess = session or default_pool().get(auth)
    try:
        Ticket(sess, ticket=args.ticket).supply()
    except Exception as exc:  # noqa: BLE001 - PRC error hierarchy varies
        raise ToolError(
            code="irods_error",
            message=f"Failed to bind ticket {args.ticket!r}: {exc}",
            details={"ticket": args.ticket},
        ) from exc

    current_ticket.set(args.ticket)
    return {
        "ticket": args.ticket,
        "bound": True,
        "note": (
            "Ticket is now bound to the current MCP call context. "
            "AVU writes in this call will record via_ticket in DuckLake."
        ),
    }
