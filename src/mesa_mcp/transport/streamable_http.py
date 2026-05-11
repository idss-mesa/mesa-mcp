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
from typing import TYPE_CHECKING

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
    SSE or single JSON depending on the request shape. ``stateless=False``
    means client sessions persist across requests (the ``Mcp-Session-Id``
    header). Stateless mode is appropriate for a Lambda-style serverless
    deployment but not for our long-running uvicorn process.
    """
    from mcp.server import Server as McpServer

    mcp_server = server._build_mcp_server(McpServer)
    return StreamableHTTPSessionManager(
        app=mcp_server,
        json_response=False,
        stateless=False,
    )
