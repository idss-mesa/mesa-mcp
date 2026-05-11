"""HTTP/SSE transport for mesa-mcp.

This package contains:

* :mod:`mesa_mcp.transport.oidc` — CyVerse Keycloak bearer-token verification.
* :mod:`mesa_mcp.transport.sse`  — Starlette app that mounts the MCP SDK's
  SSE transport behind the OIDC middleware.
* :mod:`mesa_mcp.transport.healthz` — unauthenticated liveness endpoint.

Everything in this package is opt-in: the stdio transport in
:mod:`mesa_mcp.server` doesn't import any of it, so installing mesa-mcp
without the HTTP dependencies (Starlette/uvicorn) still works for stdio.
"""

from __future__ import annotations

__all__: list[str] = []
