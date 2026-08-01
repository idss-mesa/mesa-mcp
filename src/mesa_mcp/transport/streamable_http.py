"""Streamable HTTP transport for mesa-mcp.

The MCP spec from 2025-03-26 onwards replaces the old two-endpoint SSE
transport (``GET /sse`` + ``POST /messages/?session_id=…``) with a
single-endpoint *Streamable HTTP* transport: the client POSTs JSON-RPC
messages to one URL and the server may respond either with a direct
JSON body or with an SSE stream of server-initiated frames.

This is the transport **Claude.ai's custom-connector UI speaks**. The
older SSE transport is what ``mcp-remote`` (and most Claude Desktop
bridges) still use, so mesa-mcp keeps both: ``/sse`` + ``/messages/``
for compatibility, and ``/mcp`` for Streamable HTTP. They share the
OIDC middleware, so the bearer-token rules and 401 challenge format
are identical.

This module is intentionally small: the MCP Python SDK ships
:class:`StreamableHTTPSessionManager`, which is a full ASGI handler.
We just build one around a shared :class:`mcp.server.Server` and let
:func:`mesa_mcp.transport.sse.build_sse_app` mount it.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

if TYPE_CHECKING:
    from mesa_mcp.server import MesaServer

logger = logging.getLogger(__name__)

# Path the Streamable HTTP transport is mounted at. ``/mcp`` is the
# convention reflected in most upstream examples and what Claude.ai's
# connector UI expects when it falls back from auto-discovery.
STREAMABLE_HTTP_PATH = "/mcp"


def build_streamable_http_session_manager(
    server: "MesaServer",
) -> StreamableHTTPSessionManager:
    """Build a Streamable HTTP session manager bound to ``server``'s tools.

    The SDK's session manager owns the per-client session state; we hand
    it one :class:`mcp.server.Server` (mesa-mcp's tool registry wired
    up) and reuse it across sessions. Our tools are stateless w.r.t. the
    underlying SDK Server — per-call state lives in the request-scoped
    contextvars set by :class:`OIDCMiddleware` — so the shared-Server
    pattern is safe here.

    ``json_response=False`` keeps the default behavior: the manager picks
    SSE or single JSON depending on the request shape.

    ``stateless=True`` implements the **MCP 2026-07-28 stateless core**:
    no ``initialize`` handshake and no ``Mcp-Session-Id``. Every POST is
    self-contained, so any mesa-mcp instance can answer any request and the
    hosted deployment scales horizontally behind a plain round-robin load
    balancer instead of requiring session affinity.

    This is safe for mesa-mcp because the server holds no per-client
    protocol state: the caller's identity is re-derived from the bearer
    token on every request by :class:`~mesa_mcp.transport.sse.OIDCMiddleware`,
    and the iRODS connection pool is keyed by
    :meth:`~mesa_mcp.auth.models.AuthValue.cache_key` — a per-caller cache,
    not a per-session one.
    """
    from mcp.server import Server as McpServer

    mcp_server = server._build_mcp_server(McpServer)
    return StreamableHTTPSessionManager(
        app=mcp_server,
        json_response=False,
        stateless=True,
        security_settings=_transport_security(server.config),
    )


def _transport_security(config: Any) -> Any | None:
    """Build DNS-rebinding protection settings from config.

    Validating ``Host`` and ``Origin`` matters more under the stateless
    core: with no session handshake to anchor a connection, every POST is
    independently trusted, so a rebound DNS name pointing a victim's
    browser at a locally-bound mesa-mcp would otherwise reach the tool
    surface directly.

    Returns ``None`` when no allow-list is configured — appropriate behind
    a reverse proxy that already normalizes ``Host``, and the SDK default.
    """
    from mcp.server.transport_security import (  # type: ignore[import-not-found]
        TransportSecuritySettings,
    )

    server_config = getattr(config, "server", None)
    if server_config is None:
        return None

    hosts = list(getattr(server_config, "allowed_hosts", []) or [])
    origins = list(getattr(server_config, "allowed_origins", []) or [])

    # The public base URL is by definition a legitimate Host/Origin.
    public = getattr(server_config, "public_base_url", None)
    if public:
        from urllib.parse import urlparse

        parsed = urlparse(public)
        if parsed.netloc:
            if parsed.netloc not in hosts:
                hosts.append(parsed.netloc)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in origins:
                origins.append(origin)

    if not hosts and not origins:
        return None
    return TransportSecuritySettings(
        allowed_hosts=hosts,
        allowed_origins=origins,
    )
