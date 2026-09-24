"""``ds_use_ticket`` — attach a ticket to the caller's pooled iRODS session.

``Ticket.supply`` sets the ticket on the session it was constructed
against, and python-irodsclient applies it to every connection that
session hands out afterwards. We supply it to the caller's own pooled
session: the pool keeps one session per caller identity
(:meth:`AuthValue.cache_key`), so the ticket applies to that identity's
later calls and never to anyone else's.

The ticket id is also recorded on that same session
(:func:`mesa_mcp.context.bind_session_ticket`) so later AVU writes by the
same identity carry it into DuckLake's ``via_ticket`` column (see
``mesa-ducklake/CLAUDE.md``). A contextvar alone cannot do this — each MCP
call runs in its own context, so a ``set`` here is gone by the next call.
"""

from __future__ import annotations

from typing import Any

from irods.ticket import Ticket
from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import (
    bind_session_ticket,
    current_ticket,
    require_current_auth_value,
)
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import ticket_errors
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
        "Supply an iRODS ticket to the caller's iRODS session. Subsequent "
        "operations by the same caller run with the ticket applied, and their "
        "AVU writes record the ticket id in DuckLake's via_ticket column. "
        "Other callers' sessions are unaffected."
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

    # ``Ticket.supply`` attaches the ticket to *this* session — the caller's
    # own pooled session, keyed by identity, so it cannot reach another
    # caller. PRC applies it lazily when the session next opens a
    # connection, so a bad ticket surfaces on the next operation rather
    # than here; errors raised now still map to a ToolError.
    sess = session or default_pool().get(auth)
    try:
        Ticket(sess, ticket=args.ticket).supply()
    except Exception as exc:  # noqa: BLE001 - PRC error hierarchy varies
        # A restricted ticket surfaces as an unmapped KeyError(<code>) in
        # python-irodsclient; translate it into something the caller can
        # act on rather than reporting the bare number.
        mapped = ticket_errors.as_tool_error(exc, context="Failed to bind ticket")
        if mapped is not None:
            raise mapped from exc
        raise ToolError(
            code="irods_error",
            message=f"Failed to bind ticket: {exc}",
            details={},
        ) from exc

    # The session binding is what persists to later calls; the contextvar
    # only covers anything else run in this same call.
    bind_session_ticket(sess, args.ticket)
    current_ticket.set(args.ticket)
    return {
        "ticket": args.ticket,
        "bound": True,
        "note": (
            "Ticket is now supplied to your iRODS session. Your subsequent "
            "operations use it, and your AVU writes record via_ticket in DuckLake."
        ),
    }
