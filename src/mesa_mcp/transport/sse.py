"""Starlette application that exposes mesa-mcp over HTTP/SSE.

Three routes are mounted:

* ``GET /sse`` — Server-Sent Events upgrade. Holds the long-lived stream
  the MCP client reads server messages from.
* ``POST /messages/`` — companion endpoint the MCP client POSTs JSON-RPC
  requests to. The session id is carried in the query string.
* ``GET /healthz`` — unauthenticated liveness probe.

Authentication
--------------
Every route except ``/healthz`` requires a CyVerse Keycloak bearer JWT.
:class:`OIDCAuthenticator` validates the signature, ``exp``, ``iss``, and
(optionally) ``aud``. On success the resulting :class:`AuthValue` is
bound to the :mod:`mesa_mcp.context` contextvars for the duration of the
request so tool handlers see the caller without threading a parameter.

Local-development escape hatch
------------------------------
When ``ServerConfig.oidc_discovery_url`` is empty, the middleware logs a
warning and lets *every* request through with a fake anonymous-ish
:class:`AuthValue`. **DO NOT enable this in production.** Production
deployments must set a discovery URL; the empty-URL branch exists only
so a developer can curl ``/healthz`` against a fresh checkout without
having to wire up Keycloak first.

Uvicorn / anyio quirk
---------------------
Both uvicorn and the MCP SDK use anyio; uvicorn's ``Server.serve()``
coroutine is anyio-compatible so we can ``await`` it from our existing
asyncio loop. We do *not* call ``uvicorn.run(...)`` (which would create
its own loop) — instead we drive ``Server.serve()`` directly from the
mesa-mcp coroutine.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx
from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.types import ASGIApp, Receive, Scope, Send

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.context import current_auth_value, current_config

from .healthz import healthz
from .oidc import OIDCAuthenticator, OIDCError
from .wellknown import (
    PROTECTED_RESOURCE_METADATA_PATH,
    metadata_url,
    oauth_protected_resource_metadata,
)

if TYPE_CHECKING:
    from mesa_mcp.config import Config
    from mesa_mcp.server import MesaServer

logger = logging.getLogger(__name__)


# Path prefixes the OIDC middleware MUST NOT challenge. Everything else
# requires a valid bearer token. The OAuth protected-resource metadata
# URL is public by RFC 9728 — clients fetch it *before* they have a token.
_PUBLIC_PREFIXES: tuple[str, ...] = (
    "/healthz",
    PROTECTED_RESOURCE_METADATA_PATH,
)


def _is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _PUBLIC_PREFIXES)


def _www_authenticate(scope: Scope, exc: OIDCError, config: Config) -> str:
    """Build the ``WWW-Authenticate`` header value for a 401 from the OIDC
    middleware.

    Follows RFC 6750 §3 (challenge syntax) and RFC 9728 §5 (the
    ``resource_metadata`` parameter pointing at our protected-resource
    metadata document, so a compliant MCP client can discover where to
    fetch an access token).
    """
    parts = ['Bearer realm="mesa-mcp"']
    detail = (exc.detail or "").lower()
    # "missing" Authorization is *no credentials*, not *bad credentials*,
    # so we omit the ``error`` parameter per RFC 6750 §3.1 — but we still
    # advertise where to find the resource metadata.
    if "missing" not in detail:
        parts.append('error="invalid_token"')
        # ``error_description`` is quoted-string; escape embedded quotes.
        safe = (exc.detail or "").replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'error_description="{safe}"')
    parts.append(f'resource_metadata="{metadata_url(scope, config=config)}"')
    return ", ".join(parts)


class OIDCMiddleware:
    """Authenticate every non-public request via a bearer JWT.

    On success, binds the caller's :class:`AuthValue` and the running
    :class:`Config` to the contextvars in :mod:`mesa_mcp.context`. The
    bindings are scoped to this middleware's dispatch frame, which is
    the same async-task ancestor as the SSE handler — so when the MCP
    SDK calls back into our tool dispatcher inside ``connect_sse``, the
    contextvar lookup resolves to the value we set here.

    Implemented as a raw ASGI middleware (not :class:`BaseHTTPMiddleware`)
    because the SSE route returns a streaming response, and
    ``BaseHTTPMiddleware`` buffers the response body before passing it
    through — which deadlocks long-lived SSE streams.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        authenticator: OIDCAuthenticator | None,
        config: Config,
    ) -> None:
        self._app = app
        self._authenticator = authenticator
        self._config = config

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Non-HTTP scopes (lifespan, websocket) pass through untouched.
            await self._app(scope, receive, send)
            return

        path = scope.get("path", "")
        # Bind the config even for public routes so a future /healthz that
        # reports config-derived facts can read it.
        config_token = current_config.set(self._config)
        auth_token = None
        try:
            if _is_public(path):
                await self._app(scope, receive, send)
                return

            if self._authenticator is None:
                # Local-dev / no-OIDC mode. Fake an anonymous AuthValue so
                # tool handlers that require one don't crash, but log a
                # loud warning per request.
                logger.warning(
                    "OIDC disabled: serving request without bearer-token "
                    "verification. Do not run this configuration in production."
                )
                fake = AuthValue(
                    username="anonymous",
                    zone=self._config.irods.zone,
                    password=None,
                    auth_scheme="anonymous",
                )
                auth_token = current_auth_value.set(fake)
                await self._app(scope, receive, send)
                return

            headers = Headers(scope=scope)
            try:
                auth_value = await self._authenticator.authenticate(
                    headers.get("authorization"),
                    zone=self._config.irods.zone,
                )
            except OIDCError as exc:
                response_headers: dict[str, str] = {}
                if exc.status_code == 401:
                    response_headers["WWW-Authenticate"] = _www_authenticate(
                        scope, exc, self._config
                    )
                response = JSONResponse(
                    {"error": "unauthorized", "detail": exc.detail},
                    status_code=exc.status_code,
                    headers=response_headers,
                )
                await response(scope, receive, send)
                return

            auth_token = current_auth_value.set(auth_value)
            await self._app(scope, receive, send)
        finally:
            if auth_token is not None:
                current_auth_value.reset(auth_token)
            current_config.reset(config_token)


def _build_authenticator(config: Config) -> OIDCAuthenticator | None:
    """Construct an :class:`OIDCAuthenticator` or ``None`` for no-OIDC mode."""
    url = config.server.oidc_discovery_url
    if not url:
        logger.warning(
            "ServerConfig.oidc_discovery_url is empty — running without "
            "OIDC. This is acceptable for local development only."
        )
        return None
    return OIDCAuthenticator(
        discovery_url=url,
        client_id=config.server.oauth2_client_id,
        audience=config.server.oidc_audience,
        http_client=httpx.AsyncClient(timeout=10.0),
    )


def build_sse_app(server: MesaServer, config: Config) -> Starlette:
    """Assemble the Starlette app: SSE + healthz + OIDC middleware.

    The MCP SDK's :class:`SseServerTransport` is mounted at ``/sse`` for
    the upgrade GET and ``/messages/`` for client POSTs (matching the
    SDK's example wiring).
    """
    # Lazy import: the mcp SDK isn't needed for ``import mesa_mcp.transport``.
    from mcp.server.sse import SseServerTransport

    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        # Build a fresh MCP server per session so the tool registry binds
        # to the right context. Reusing one Server instance across SSE
        # sessions is also fine since our tools are stateless w.r.t. the
        # Server, but per-session keeps the wiring symmetric with stdio.
        from mcp.server import Server as McpServer

        mcp_server = server._build_mcp_server(McpServer)
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )
        # SseServerTransport.connect_sse signals client-disconnect via
        # context-manager exit; we still must return a Response so
        # Starlette doesn't NoneType-error on the connection cleanup.
        return Response()

    authenticator = _build_authenticator(config)

    routes = [
        Route("/healthz", endpoint=healthz, methods=["GET"]),
        Route(
            PROTECTED_RESOURCE_METADATA_PATH,
            endpoint=oauth_protected_resource_metadata,
            methods=["GET"],
        ),
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
    ]

    middleware = [
        Middleware(
            OIDCMiddleware,
            authenticator=authenticator,
            config=config,
        ),
    ]

    app = Starlette(routes=routes, middleware=middleware)

    # Stash the authenticator on the app so tests and shutdown hooks can
    # ``aclose`` the HTTP client when they're done.
    app.state.oidc_authenticator = authenticator
    return app
