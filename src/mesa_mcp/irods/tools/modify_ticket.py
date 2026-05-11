"""``ds_modify_ticket`` — adjust restrictions on an existing ticket.

Cannot change the ticket's mode (``read``/``write``) — that is fixed at
issuance by iRODS itself. Callers who supply ``mode`` get an
``invalid_argument`` error.
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


class ModifyTicketInput(BaseModel):
    """Input schema for ``ds_modify_ticket``.

    ``mode`` is intentionally absent; iRODS does not allow re-assigning a
    ticket's permission. Including it in the spec would be misleading.
    """

    ticket: str = Field(
        ...,
        min_length=1,
        description="The ticket string to modify.",
    )
    uses: int | None = Field(
        default=None,
        ge=0,
        description="New uses-allowed cap.",
    )
    expiry: str | None = Field(
        default=None,
        description="New ISO-8601 expiry timestamp.",
    )
    write_byte_limit: int | None = Field(
        default=None,
        ge=0,
        description="New write-byte limit (write tickets only).",
    )
    host_restriction: str | None = Field(
        default=None,
        description="Add an allowed-host restriction.",
    )
    user_restriction: str | None = Field(
        default=None,
        description="Add an allowed-user restriction.",
    )


@register_tool(
    "ds_modify_ticket",
    (
        "Modify restrictions on an existing iRODS ticket. Cannot change "
        "the ticket's mode — that is set at issuance time. Returns the "
        "applied restrictions. Anonymous users are not allowed to modify tickets."
    ),
    input_model=ModifyTicketInput,
)
async def handle_modify_ticket(
    args: ModifyTicketInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to modify tickets",
            details={"tool": "ds_modify_ticket"},
        )
    sess = session or default_pool().get(auth)
    return ticket_helpers.modify_ticket(
        sess,
        args.ticket,
        uses=args.uses,
        expiry=args.expiry,
        write_byte_limit=args.write_byte_limit,
        host_restriction=args.host_restriction,
        user_restriction=args.user_restriction,
    )
