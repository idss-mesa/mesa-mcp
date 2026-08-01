"""Starlette application that exposes mesa-mcp over HTTP/SSE + Streamable HTTP.

Routes mounted:

* ``GET /sse`` — old-spec SSE upgrade. Holds the long-lived stream
  ``mcp-remote``-style clients (Claude Desktop, Claude Code, Cline,
  Continue via bridge) read server messages from.
* ``POST /messages/?session_id=…`` — companion endpoint for the old-spec
  SSE transport's client-initiated frames.
* ``POST /mcp`` (and ``GET``/``DELETE`` for stream and session-close) —
  Streamable HTTP transport (MCP spec 2025-03-26+). This is what
  Claude.ai's custom-connector UI speaks.
* ``GET /healthz`` — unauthenticated liveness probe.
* ``GET /.well-known/oauth-protected-resource`` — RFC 9728 metadata.

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

import contextlib
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
from mesa_mcp.context import (
    current_auth_value,
    current_client_pool,
    current_config,
)
from mesa_mcp.irods.client_pool import default_pool

from .healthz import healthz
from .oidc import OIDCAuthenticator, OIDCError
from .streamable_http import (
    STREAMABLE_HTTP_PATH,
    build_streamable_http_session_manager,
)
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


class _McpSlashNormalizer:
    """ASGI middleware: rewrite ``/mcp`` → ``/mcp/`` so the Streamable
    HTTP Mount serves both forms with no 307 redirect.

    Starlette's :class:`Mount` matches ``/mcp/`` (and ``/mcp/anything``)
    but not the bare ``/mcp``. With the default ``redirect_slashes=True``
    it would issue a 307 to add the trailing slash — but some MCP
    clients (Claude.ai's custom-connector UI included) don't follow POST
    redirects reliably, so the connector handshake silently fails.

    This middleware sits *outside* the OIDC gate so the rewrite happens
    before routing or auth. Only the exact path ``/mcp`` is rewritten;
    everything else (including ``/mcp/``, ``/mcp/foo``, ``/messages``,
    ``/sse``) passes through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("path") == STREAMABLE_HTTP_PATH:
            scope = dict(scope)
            scope["path"] = STREAMABLE_HTTP_PATH + "/"
            # ``raw_path`` is bytes; keep it in sync so middlewares that
            # prefer it (e.g. uvicorn's access log) report the rewritten
            # URL. Original-path inspection isn't a use case here.
            scope["raw_path"] = scope["path"].encode("ascii")
        await self._app(scope, receive, send)


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
        # Bind the iRODS client pool for the duration of the request.
        #
        # Required by the MCP 2026-07-28 stateless core: with no session to
        # carry server-scoped state, every request must arrive at the tool
        # handlers fully provisioned. Previously only the stdio path bound
        # this contextvar, so every tool using ``require_current_client_pool``
        # (ds_list_directory, ds_make_directory, ds_copy_file, …) failed with
        # ``internal_error`` over HTTP while the ``default_pool()`` tools
        # worked — an inconsistency this binding removes.
        #
        # The pool itself is process-wide and keyed per caller
        # (``AuthValue.cache_key``), so sharing it across requests and
        # instances is correct: it is a connection cache, not session state.
        pool_token = current_client_pool.set(default_pool())
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
            current_client_pool.reset(pool_token)
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
    """Assemble the Starlette app: SSE + Streamable HTTP + healthz + OIDC.

    Two MCP transports coexist on the same app, both behind the same
    OIDC gate:

    * Old SSE (``/sse`` + ``/messages/``) — driven by the MCP SDK's
      :class:`SseServerTransport`. Kept for ``mcp-remote`` bridges from
      stdio-only clients (Claude Desktop, Claude Code, Cline, Continue).
    * Streamable HTTP (``/mcp``) — driven by the SDK's
      :class:`StreamableHTTPSessionManager`. The transport Claude.ai's
      custom-connector UI speaks.

    The session manager is stateful (it tracks ``Mcp-Session-Id``-keyed
    sessions in memory), so it runs inside a Starlette ``lifespan`` task.
    """
    # Lazy import: the mcp SDK isn't needed for ``import mesa_mcp.transport``.
    from mcp.server.sse import SseServerTransport

    sse_transport = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        # DEPRECATED transport (MCP 2026-07-28).
        #
        # The two-endpoint SSE transport (`GET /sse` + `POST /messages/`) is
        # a pre-stateless-core design: it depends on a long-lived,
        # session-affine stream, which is exactly what the 2026-07-28 spec
        # removes. `/mcp` (stateless Streamable HTTP) is the go-forward
        # transport. This route is retained only so existing `mcp-remote`
        # bridges keep working through the deprecation window; it pins a
        # client to one instance and therefore does not scale horizontally.
        logger.warning(
            "legacy SSE transport in use (GET /sse); deprecated under MCP "
            "2026-07-28 — migrate the client to the stateless Streamable "
            "HTTP endpoint at %s",
            STREAMABLE_HTTP_PATH,
        )
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
    streamable_manager = build_streamable_http_session_manager(server)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        # ``StreamableHTTPSessionManager.run`` spawns a task group that
        # owns session lifecycles and cleanup. Must be inside an active
        # context for ``handle_request`` to function.
        async with streamable_manager.run():
            yield

    routes = [
        Route("/healthz", endpoint=healthz, methods=["GET"]),
        Route(
            PROTECTED_RESOURCE_METADATA_PATH,
            endpoint=oauth_protected_resource_metadata,
            methods=["GET"],
        ),
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse_transport.handle_post_message),
        # ``Mount("/mcp", ...)`` only matches paths *with* a trailing
        # slash (``/mcp/``, ``/mcp/foo``). For ``/mcp`` exactly,
        # Starlette would 307-redirect to ``/mcp/`` — some MCP clients
        # (Claude.ai's connector) don't follow POST redirects reliably.
        # The :class:`_McpSlashNormalizer` middleware below rewrites
        # ``/mcp`` to ``/mcp/`` before routing so this Mount serves
        # both forms with no redirect.
        Mount(STREAMABLE_HTTP_PATH, app=streamable_manager.handle_request),
    ]

    middleware = [
        # Outermost: normalize the bare ``/mcp`` path to ``/mcp/`` so
        # the Streamable HTTP Mount serves both forms without redirect.
        # Must run before OIDC so the auth gate sees the normalized
        # path (the gate doesn't currently care, but future
        # path-based policies might).
        Middleware(_McpSlashNormalizer),
        Middleware(
            OIDCMiddleware,
            authenticator=authenticator,
            config=config,
        ),
    ]

    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)

    # Stash collaborators on the app so tests and shutdown hooks can
    # reach them. The authenticator owns an ``httpx.AsyncClient`` that
    # benefits from explicit ``aclose``; the session manager owns the
    # in-memory session map.
    app.state.oidc_authenticator = authenticator
    app.state.streamable_http_session_manager = streamable_manager
    return app
