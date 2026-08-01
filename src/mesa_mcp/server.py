"""MCP server bootstrap for mesa-mcp.

This module wires together the configuration, the tool registry, and the
chosen MCP transport. Today it ships a single no-op tool (``ds_ping``) so we
can prove the wire end-to-end; future PRs will register the full ``ds_*``
iRODS surface, the ``mesa_ols_*`` ontology surface, and the
``mesa_ducklake_*`` history surface — see ``CLAUDE.md`` for the plan.

Design notes:

* Tools register themselves with :func:`register_tool` at import time. The
  server constructor then iterates the registry and binds each one into the
  MCP SDK's tool table.
* The registry is intentionally MCP-SDK-agnostic. Handlers are plain async
  callables that accept a Pydantic-validated input model and return a JSON-
  serializable dict. The :class:`MesaServer` adapter does the SDK-specific
  translation. This keeps unit tests trivial: call the registered handler
  directly, no MCP harness required.
* When the ``mcp`` SDK isn't installed, importing this module still works.
  Only :meth:`MesaServer.serve` actually needs ``mcp``.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from . import __version__
from .config import Config
from .errors import ToolError

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]

# --- MCP 2026-07-28 spec constants -----------------------------------------

#: JSON Schema dialect the spec pins tool schemas to.
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: ``tools/list`` cache TTL. The tool surface is fixed at deploy time, so a
#: 5-minute public TTL is safe. Under the stateless core there is no session
#: to amortize discovery over, so cacheable list results matter more than
#: they did pre-2026-07-28.
TOOLS_LIST_TTL_MS = 300_000


def _tool_surface(name: str) -> str:
    """Classify a tool into its mesa-mcp surface family, for ``_meta``.

    mesa-mcp exposes ~50 tools spanning four subsystems; tagging each with
    its family lets a client group or filter them without name-prefix
    guesswork.
    """
    if name.startswith(("mesa_ols_", "mesa_avu_apply_term", "mesa_avu_from_term")):
        return "ontology"
    if name.startswith("mesa_ducklake_"):
        return "history"
    if name.startswith(("mesa_datacite_", "mesa_avu_apply_datacite")):
        return "datacite"
    if name.startswith("mesa_policy_"):
        return "policy"
    if name.startswith("ds_"):
        return "irods"
    return "core"


@dataclass(frozen=True)
class ToolSpec:
    """Static description of a tool, ready for MCP registration."""

    name: str
    description: str
    handler: ToolHandler
    input_model: type[BaseModel] | None = None
    # Free-form extras (kept for forward-compat with later wiring needs).
    meta: dict[str, Any] = field(default_factory=dict)


_REGISTRY: dict[str, ToolSpec] = {}


def register_tool(
    name: str,
    description: str,
    *,
    input_model: type[BaseModel] | None = None,
) -> Callable[[ToolHandler], ToolHandler]:
    """Decorator that adds a tool to the global mesa-mcp tool registry.

    Example
    -------
    >>> @register_tool("ds_example", "Demo tool.", input_model=ExampleIn)
    ... async def handle_example(args: ExampleIn) -> dict:
    ...     return {"ok": True}
    """

    def decorator(handler: ToolHandler) -> ToolHandler:
        if name in _REGISTRY:
            raise ValueError(f"Tool {name!r} already registered")
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            handler=handler,
            input_model=input_model,
        )
        return handler

    return decorator


def get_registered_tools() -> list[ToolSpec]:
    """Return all tools currently in the registry."""
    return list(_REGISTRY.values())


def get_tool(name: str) -> ToolSpec:
    """Look up a tool by name, raising ``KeyError`` if missing."""
    return _REGISTRY[name]


def clear_registry() -> None:
    """Test helper: wipe the registry. Avoid in production code paths."""
    _REGISTRY.clear()


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------


class DsPingInput(BaseModel):
    """Input schema for the ``ds_ping`` smoke-test tool."""

    message: str | None = None


@register_tool(
    "ds_ping",
    "Liveness check. Echoes back the supplied message (or 'ok') and the "
    "running mesa-mcp version. No iRODS access required.",
    input_model=DsPingInput,
)
async def handle_ds_ping(args: DsPingInput) -> dict[str, Any]:
    """Return a structured pong payload."""
    return {
        "pong": args.message if args.message else "ok",
        "version": __version__,
    }


# Side-effect imports: each package walks its own directory with pkgutil and
# imports every .py file, firing every @register_tool decorator.
import mesa_mcp.datacite.tools  # noqa: E402,F401  (auto-registers DataCite tools)

from . import ols as _ols_tools  # noqa: E402,F401  (registration side effect)
from .ducklake import tools as _ducklake_tools  # noqa: E402,F401  (registration side effect)
from .irods import tools as _irods_tools  # noqa: E402,F401  (registration side effect)

# ---------------------------------------------------------------------------
# Server adapter
# ---------------------------------------------------------------------------


def _handler_accepts_kwarg(handler: ToolHandler, name: str) -> bool:
    """Return True when ``handler``'s signature accepts a keyword named ``name``.

    Used by :func:`_invoke_handler` to opt handlers into receiving ``auth_value``
    from :mod:`mesa_mcp.context` without forcing the existing OLS handlers
    (which don't need it) to grow new parameters.
    """
    try:
        sig = inspect.signature(handler)
    except (TypeError, ValueError):  # pragma: no cover - builtins / C functions
        return False
    for param in sig.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == name and param.kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            return True
    return False


async def _invoke_handler(spec: ToolSpec, raw_args: dict[str, Any] | None) -> dict[str, Any]:
    """Validate ``raw_args`` against the spec's input model and dispatch.

    Centralized so the MCP adapter and the unit tests share one code path.
    Raises :class:`ToolError` for validation failures.

    Handlers that declare an ``auth_value`` keyword (e.g. ``ds_*`` iRODS
    tools) receive the current request's :class:`AuthValue` pulled from the
    :mod:`mesa_mcp.context` contextvar. Handlers without that keyword (the
    existing OLS tools) keep their pre-existing signature and never see it.
    """
    from mesa_mcp.context import get_current_auth_value

    raw_args = raw_args or {}

    extra_kwargs: dict[str, Any] = {}
    if _handler_accepts_kwarg(spec.handler, "auth_value"):
        extra_kwargs["auth_value"] = get_current_auth_value()

    if spec.input_model is None:
        if raw_args:
            result = spec.handler(**raw_args, **extra_kwargs)
        else:
            result = spec.handler(**extra_kwargs) if extra_kwargs else spec.handler()
    else:
        try:
            parsed = spec.input_model.model_validate(raw_args)
        except Exception as exc:  # pydantic ValidationError, ultimately
            raise ToolError(
                code="invalid_argument",
                message=f"Invalid arguments for tool {spec.name!r}: {exc}",
                details={"tool": spec.name},
            ) from exc
        result = spec.handler(parsed, **extra_kwargs) if extra_kwargs else spec.handler(parsed)

    if inspect.isawaitable(result):
        result = await result
    if not isinstance(result, dict):
        raise ToolError(
            code="internal_error",
            message=f"Tool {spec.name!r} returned a non-dict result.",
            details={"tool": spec.name, "result_type": type(result).__name__},
        )
    return result


@dataclass
class MesaServer:
    """Adapter that exposes the mesa-mcp tool registry over the MCP SDK.

    Constructed eagerly; ``serve()`` actually opens the transport. Tests can
    inspect ``self.tools`` without touching the network or stdio.
    """

    config: Config
    tools: list[ToolSpec] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tools:
            self.tools = get_registered_tools()

    async def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """In-process tool invocation, used by tests and embedders."""
        try:
            spec = _REGISTRY[name]
        except KeyError as exc:
            raise ToolError(
                code="unknown_tool",
                message=f"No tool registered with name {name!r}.",
                details={"name": name},
            ) from exc
        return await _invoke_handler(spec, args)

    async def serve(self, transport: str) -> None:
        """Run the MCP server on the given transport. Imports ``mcp`` lazily."""
        if transport == "stdio":
            await self._serve_stdio()
        elif transport == "sse":
            await self._serve_sse()
        else:  # pragma: no cover - argparse should prevent this
            raise ValueError(f"Unsupported transport: {transport!r}")

    async def _serve_stdio(self) -> None:
        """Bind the MCP server to stdio (the primary supported transport).

        stdio has one user for the lifetime of the process, so we resolve
        credentials once at startup and bind the auth/config/pool
        contextvars before entering the MCP loop. Handler invocations
        spawned inside the loop inherit those values — that is how the
        ``ds_*`` tools see an :class:`AuthValue` without a per-request
        middleware.
        """
        # Lazy imports so the rest of the module — including tests — remains
        # usable when the MCP SDK isn't installed.
        from mcp.server import Server  # type: ignore[import-not-found]
        from mcp.server.stdio import stdio_server  # type: ignore[import-not-found]

        from mesa_mcp.auth.extract import resolve_credentials
        from mesa_mcp.context import (
            current_auth_value,
            current_client_pool,
            current_config,
        )
        from mesa_mcp.irods.client_pool import default_pool

        auth_value = resolve_credentials(self.config)
        pool = default_pool()

        current_auth_value.set(auth_value)
        current_client_pool.set(pool)
        current_config.set(self.config)

        mcp_server = self._build_mcp_server(Server)
        try:
            async with stdio_server() as (read_stream, write_stream):
                # SDK 2.x ``run()`` drives a *dual-era* loop: the client's
                # first request selects either the legacy handshake era or
                # the 2026-07-28 per-request-envelope era. The options object
                # is therefore no longer an ``initialize`` handshake — it is
                # the capability/extension declaration the SDK serves to
                # ``server/discover``. It stays, so a stdio client on either
                # era works.
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                )
        finally:
            pool.close()

    async def _serve_sse(self) -> None:
        """Run the HTTP/SSE transport with OIDC bearer-token auth.

        See :mod:`mesa_mcp.transport.sse` for the routing + middleware
        details. Binds to ``config.server.bind_address:bind_port`` via
        uvicorn. uvicorn is anyio-compatible so we drive its
        :class:`uvicorn.Server` from the existing asyncio loop rather
        than calling :func:`uvicorn.run`, which would spawn a fresh
        loop and conflict with our test harnesses.
        """
        import uvicorn  # type: ignore[import-not-found]

        from mesa_mcp.transport.sse import build_sse_app

        app = build_sse_app(self, self.config)
        uv_config = uvicorn.Config(
            app,
            host=self.config.server.bind_address,
            port=self.config.server.bind_port,
            log_level=self.config.server.log_level,
            lifespan="on",
        )
        uv_server = uvicorn.Server(uv_config)
        try:
            await uv_server.serve()
        finally:
            authenticator = getattr(app.state, "oidc_authenticator", None)
            if authenticator is not None:
                await authenticator.aclose()

    def _build_mcp_server(self, server_cls: Any) -> Any:
        """Construct an ``mcp.server.Server`` populated with our tool registry.

        Targets the **MCP 2026-07-28** spec via the ``mcp`` Python SDK 2.x.

        The 1.x decorator API (``@server.list_tools()`` /
        ``@server.call_tool()``) was removed in SDK 2.0.0; registration now
        happens through **constructor callbacks** that take a
        ``ServerRequestContext`` plus typed params and return typed results.
        The mesa-mcp tool registry itself is unchanged — this adapter is the
        only SDK-coupled seam.

        Spec features wired here:

        * **Cacheable list results** — ``cache_hints`` makes the SDK stamp
          ``ttlMs``/``cacheScope`` onto ``tools/list``. Our tool surface is
          static for the lifetime of a deployment, so a minutes-scale public
          TTL is safe and saves every client a full re-list per request (which
          matters much more now that there is no session to amortize it over).
        * **JSON Schema 2020-12** — tool ``inputSchema`` carries an explicit
          ``$schema`` dialect declaration.
        * **Universal ``_meta``** — tool definitions advertise their mesa-mcp
          surface family so clients can group ~50 tools sensibly.

        ``server/discover`` is handled by the SDK itself; there is no
        ``initialize`` handshake to configure.
        """
        from mcp import types as mcp_types  # type: ignore[import-not-found]
        from mcp.server.caching import CacheHint  # type: ignore[import-not-found]

        async def _on_list_tools(_ctx: Any, _params: Any = None) -> Any:
            return mcp_types.ListToolsResult(tools=self._tool_definitions())

        async def _on_call_tool(_ctx: Any, params: Any) -> Any:
            import json

            is_error = False
            try:
                payload = await self.call(params.name, params.arguments)
            except ToolError as exc:
                payload = {"error": exc.to_payload()}
                is_error = True
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text=json.dumps(payload))],
                structuredContent=payload,
                isError=is_error,
            )

        return server_cls(
            "mesa-mcp",
            version=__version__,
            cache_hints={
                "tools/list": CacheHint(ttl_ms=TOOLS_LIST_TTL_MS, scope="public"),
            },
            on_list_tools=_on_list_tools,
            on_call_tool=_on_call_tool,
        )

    def _tool_definitions(self) -> list[Any]:
        """Render the registry as MCP ``Tool`` objects (spec 2026-07-28).

        Split out from :meth:`_build_mcp_server` so the conformance tests can
        assert schema dialect and ``_meta`` without standing up a transport.
        """
        from mcp import types as mcp_types  # type: ignore[import-not-found]

        out: list[Any] = []
        for spec in self.tools:
            if spec.input_model is not None:
                input_schema = spec.input_model.model_json_schema()
            else:
                input_schema = {"type": "object", "properties": {}}
            # Pydantic v2 emits 2020-12 but omits the dialect declaration;
            # the spec expects tool schemas to identify their dialect.
            input_schema.setdefault("$schema", JSON_SCHEMA_DIALECT)
            out.append(
                mcp_types.Tool(
                    name=spec.name,
                    description=spec.description,
                    inputSchema=input_schema,
                    _meta={"io.mesa/surface": _tool_surface(spec.name)},
                )
            )
        return out


# ---------------------------------------------------------------------------
# Public entrypoint used by __main__
# ---------------------------------------------------------------------------


def run(config: Config, transport: str | None = None) -> None:
    """Synchronous entry point that starts the MCP server.

    The CLI calls this; tests usually instantiate :class:`MesaServer` directly
    and exercise :meth:`MesaServer.call`.
    """
    import asyncio

    server = MesaServer(config=config)
    effective_transport = transport or config.server.transport
    asyncio.run(server.serve(effective_transport))
