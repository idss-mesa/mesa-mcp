"""Per-request context shared between the transport adapter and tool handlers.

The mesa-mcp tool registry is intentionally MCP-SDK-agnostic: handlers are
plain async callables that take a Pydantic-validated input model. They have
no positional ``ctx`` argument because the registry historically only
dispatched argument validation. The iRODS ``ds_*`` tools need the caller's
:class:`AuthValue`, though, and threading that as a kwarg through every
handler would force a churning edit of every existing tool plus its tests.

Instead we expose ``current_auth_value`` as a :class:`contextvars.ContextVar`.
The transport layer (or a test) sets it before calling ``MesaServer.call``;
handlers (or the registry's dispatch helper) read it.

This is the minimal seam required to wire AVU writes into iRODS without
disturbing the existing OLS tools — those tools simply never read the
contextvar.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

from mesa_mcp.auth.models import AuthValue

if TYPE_CHECKING:
    from mesa_mcp.config import Config
    from mesa_mcp.irods.client_pool import IRODSClientPool

# The default is ``None`` so OLS tools (which don't need auth) can run from
# unit tests that never set the contextvar.
current_auth_value: ContextVar[AuthValue | None] = ContextVar(
    "mesa_mcp_current_auth_value",
    default=None,
)

# The currently-active iRODS ticket id, if the call is going through one.
# ``ds_use_ticket`` sets this for the duration of subsequent handler
# invocations in the same MCP call. AVU-write tools read it and emit it as
# the ``via_ticket`` field of the ``AvuChange`` record they hand to
# DuckLake. Defaults to ``None`` because most calls are not
# ticket-mediated.
current_ticket: ContextVar[str | None] = ContextVar(
    "mesa_mcp_current_ticket",
    default=None,
)

# The connection pool + config are server-scoped (not strictly per-request),
# but parking them on contextvars keeps tool signatures small: every
# ``ds_*`` tool that touches iRODS reads pool+config+auth from this single
# module and never has to plumb them through positional arguments.
current_client_pool: ContextVar[IRODSClientPool | None] = ContextVar(
    "mesa_mcp_current_client_pool",
    default=None,
)
current_config: ContextVar[Config | None] = ContextVar(
    "mesa_mcp_current_config",
    default=None,
)


def get_current_auth_value() -> AuthValue | None:
    """Return the caller's :class:`AuthValue`, or ``None`` outside a request."""
    return current_auth_value.get()


def require_current_auth_value() -> AuthValue:
    """Return the caller's :class:`AuthValue`, raising if none is set.

    Used by handlers that cannot operate without an authenticated caller
    (every ``ds_*`` tool that touches iRODS).
    """
    auth = current_auth_value.get()
    if auth is None:
        from mesa_mcp.errors import ToolError

        raise ToolError(
            code="unauthenticated",
            message=(
                "This tool requires an authenticated caller, but no "
                "AuthValue was bound to the request context."
            ),
        )
    return auth


def get_current_ticket() -> str | None:
    """Return the currently-active iRODS ticket id, or ``None``."""
    return current_ticket.get()


def require_current_client_pool() -> IRODSClientPool:
    """Return the bound :class:`IRODSClientPool`, raising if none is set.

    Tools that open iRODS sessions call this once at the top of the handler
    so the ``LookupError``-flavoured failure mode becomes a structured
    :class:`ToolError`.
    """
    pool = current_client_pool.get()
    if pool is None:
        from mesa_mcp.errors import ToolError

        raise ToolError(
            code="internal_error",
            message=(
                "This tool requires an iRODS client pool, but none is "
                "bound to the current request context."
            ),
        )
    return pool


def require_current_config() -> Config:
    """Return the bound :class:`Config`, raising if none is set."""
    config = current_config.get()
    if config is None:
        from mesa_mcp.errors import ToolError

        raise ToolError(
            code="internal_error",
            message=(
                "This tool requires a Config, but none is bound to the "
                "current request context."
            ),
        )
    return config
