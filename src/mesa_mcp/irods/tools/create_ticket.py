"""``ds_create_ticket`` — mint a fresh iRODS ticket.

This goes beyond ``irods-mcp-server``'s read-only ticket surface; see
``CLAUDE.md`` "Group 1b" for the rationale. Inputs match the schema
spec'd there exactly:

* ``path`` — data-object or collection the ticket is bound to (validated
  through :func:`mesa_mcp.irods.access.assert_allowed`).
* ``mode`` — ``read`` or ``write``.
* ``uses_allowed`` — optional cap on the number of uses.
* ``expiry`` — ISO-8601 timestamp at which the ticket auto-expires.
* ``write_byte_limit`` — for write tickets only.
* ``host_restriction`` — restrict to a specific client host.
* ``user_restriction`` — restrict to a specific iRODS user.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import require_current_auth_value
from mesa_mcp.errors import ToolError
from mesa_mcp.irods import tickets as ticket_helpers
from mesa_mcp.irods.access import assert_allowed
from mesa_mcp.irods.client_pool import default_pool
from mesa_mcp.server import register_tool


class CreateTicketInput(BaseModel):
    """Input schema for ``ds_create_ticket``."""

    path: str = Field(
        ...,
        min_length=1,
        description="The iRODS path the ticket grants access to.",
    )
    mode: Literal["read", "write"] = Field(
        ...,
        description="Ticket access mode: 'read' or 'write'.",
    )
    uses_allowed: int | None = Field(
        default=None,
        ge=0,
        description="Maximum number of times this ticket may be used.",
    )
    expiry: str | None = Field(
        default=None,
        description="ISO-8601 timestamp at which the ticket expires.",
    )
    write_byte_limit: int | None = Field(
        default=None,
        ge=0,
        description="Maximum bytes that may be written via this ticket (write tickets only).",
    )
    host_restriction: str | None = Field(
        default=None,
        description="Restrict ticket usage to clients connecting from this host.",
    )
    user_restriction: str | None = Field(
        default=None,
        description="Restrict ticket usage to this iRODS user.",
    )


@register_tool(
    "ds_create_ticket",
    (
        "Create a read or write iRODS ticket on a data object or collection. "
        "Returns the ticket string plus the restrictions that were applied. "
        "Anonymous users may not create tickets."
    ),
    input_model=CreateTicketInput,
)
async def handle_create_ticket(
    args: CreateTicketInput,
    *,
    auth_value: AuthValue | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    auth = auth_value or require_current_auth_value()
    if auth.is_anonymous():
        raise ToolError(
            code="forbidden",
            message="anonymous user is not allowed to create tickets",
            details={"tool": "ds_create_ticket"},
        )

    if args.write_byte_limit is not None and args.mode != "write":
        raise ToolError(
            code="invalid_argument",
            message="write_byte_limit may only be set on write-mode tickets.",
            details={"mode": args.mode},
        )

    norm = assert_allowed(args.path, auth)
    sess = session or default_pool().get(auth)
    try:
        record = ticket_helpers.issue_ticket(
            sess,
            norm,
            args.mode,
            uses_allowed=args.uses_allowed,
            expiry=args.expiry,
            write_byte_limit=args.write_byte_limit,
            host_restriction=args.host_restriction,
            user_restriction=args.user_restriction,
        )
    except ValueError as exc:
        raise ToolError(
            code="invalid_argument",
            message=str(exc),
            details={"path": norm, "mode": args.mode},
        ) from exc

    return record
