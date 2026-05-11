"""Unauthenticated liveness endpoint.

The OIDC middleware mounted by :mod:`mesa_mcp.transport.sse` skips this
route, so a load balancer can poll ``/healthz`` without holding a bearer
token. The response is intentionally minimal — just ``status: ok`` plus
the running mesa-mcp version, mirroring the pattern in
``formation-mcp/internal/server/health.go``.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from mesa_mcp import __version__


async def healthz(request: Request) -> JSONResponse:
    """Return a static ``{"status": "ok", "version": ...}`` payload."""
    del request  # unused — endpoint has no inputs
    return JSONResponse({"status": "ok", "version": __version__})
