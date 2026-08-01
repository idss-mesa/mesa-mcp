"""Conformance tests for the MCP **2026-07-28** specification.

These lock in the stateless-core migration so the properties cannot
silently regress:

* no ``initialize`` handshake and no ``Mcp-Session-Id`` (stateless core)
* ``server/discover`` answers capability discovery
* every tool schema declares the JSON Schema 2020-12 dialect
* ``tools/list`` carries the cacheable ``ttlMs`` / ``cacheScope`` hint
* the universal ``_meta`` object is populated
* header routing binds the HTTP envelope to the JSON-RPC body
  (mismatched ``Mcp-Name`` is rejected — desync / protocol-confusion
  defense)

The HTTP tests drive the real Starlette app through an ASGI transport,
including its lifespan, so they exercise the actual SDK request path
rather than a mock.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import jsonschema
import pytest

from mesa_mcp.config import Config
from mesa_mcp.server import (
    JSON_SCHEMA_DIALECT,
    TOOLS_LIST_TTL_MS,
    MesaServer,
)
from mesa_mcp.transport.sse import build_sse_app

# The 2026-07-28 request envelope. Under the stateless core a client's
# capabilities ride *every* request via ``params._meta`` instead of being
# negotiated once by an ``initialize`` handshake.
REQUEST_ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


# ---------------------------------------------------------------------------
# Tool-surface conformance (no transport needed)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def tool_defs():
    return MesaServer(config=Config())._tool_definitions()


def test_every_input_schema_declares_2020_12_dialect(tool_defs):
    offenders = [
        t.name for t in tool_defs if t.input_schema.get("$schema") != JSON_SCHEMA_DIALECT
    ]
    assert offenders == [], f"tools missing the 2020-12 dialect: {offenders}"


def test_every_input_schema_is_a_valid_2020_12_schema(tool_defs):
    """Declaring the dialect is not enough — the schema must be legal in it."""
    for t in tool_defs:
        jsonschema.Draft202012Validator.check_schema(t.input_schema)


def test_declared_output_schemas_are_valid_2020_12(tool_defs):
    published = [t for t in tool_defs if t.output_schema]
    assert published, "expected at least one tool to publish an outputSchema"
    for t in published:
        assert t.output_schema.get("$schema") == JSON_SCHEMA_DIALECT
        jsonschema.Draft202012Validator.check_schema(t.output_schema)


def test_universal_meta_is_populated(tool_defs):
    """Spec 2026-07-28 gives every object a ``_meta``; we tag the surface."""
    missing = [t.name for t in tool_defs if not t.meta]
    assert missing == [], f"tools missing _meta: {missing}"
    assert all("io.mesa/surface" in t.meta for t in tool_defs)


def test_meta_serializes_under_its_wire_alias(tool_defs):
    """``meta`` must go out as ``_meta`` (and ``input_schema`` as ``inputSchema``)."""
    wire = tool_defs[0].model_dump(by_alias=True, exclude_none=True)
    assert "_meta" in wire
    assert "inputSchema" in wire


@pytest.mark.asyncio
async def test_declared_output_schema_matches_the_live_payload():
    """A published outputSchema must describe what the handler actually returns."""
    server = MesaServer(config=Config())
    spec = next(t for t in server._tool_definitions() if t.name == "ds_ping")
    payload = await server.call("ds_ping", {"message": "hi"})
    jsonschema.Draft202012Validator(spec.output_schema).validate(payload)


# ---------------------------------------------------------------------------
# Stateless HTTP conformance (drives the real ASGI app)
# ---------------------------------------------------------------------------


class _AppHarness:
    """Run the Starlette app with its lifespan active.

    The Streamable HTTP session manager starts its task group in the
    lifespan, so a bare ASGITransport request would fail with
    "Task group is not initialized".
    """

    def __init__(self, app):
        self._app = app
        self._recv: asyncio.Queue = asyncio.Queue()
        self._send: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self) -> httpx.AsyncClient:
        await self._recv.put({"type": "lifespan.startup"})
        self._task = asyncio.create_task(
            self._app({"type": "lifespan"}, self._recv.get, self._send.put)
        )
        message = await self._send.get()
        assert message["type"] == "lifespan.startup.complete", message
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self._app), base_url="http://testserver"
        )
        return self._client

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()
        await self._recv.put({"type": "lifespan.shutdown"})
        await self._send.get()
        if self._task is not None:
            self._task.cancel()


def _headers(method: str, name: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def _parse(response: httpx.Response) -> dict:
    """Read a JSON-RPC payload from either a JSON body or an SSE frame."""
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:].strip())
    return response.json()


@pytest.fixture
def app():
    config = Config()  # no oidc_discovery_url -> local no-OIDC mode
    return build_sse_app(MesaServer(config=config), config)


def test_session_manager_is_configured_stateless():
    """The transport must be built in stateless mode.

    This is asserted directly on the session manager rather than inferred
    from a request. In the 2026-07-28 *modern era* the SDK ignores sessions
    for both settings, so a modern-era round-trip cannot distinguish them —
    a behavioural-only test would pass even with ``stateless=False`` (this
    was verified by mutation). The legacy-era test below covers the
    observable difference.
    """
    from mesa_mcp.transport.streamable_http import (
        build_streamable_http_session_manager,
    )

    manager = build_streamable_http_session_manager(MesaServer(config=Config()))
    assert manager.stateless is True


@pytest.mark.asyncio
async def test_legacy_era_request_establishes_no_session(app):
    """A legacy-era client must not be issued an ``Mcp-Session-Id``.

    Without the ``MCP-Protocol-Version`` header the SDK serves the legacy
    era, which is where ``stateless=`` actually changes behaviour: a
    stateful server mints and returns a session id, a stateless one does
    not.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    async with _AppHarness(app) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers=headers,
        )
    assert response.status_code == 200
    assert "mcp-session-id" not in {k.lower() for k in response.headers}


@pytest.mark.asyncio
async def test_tools_list_needs_no_session_or_handshake(app):
    """The stateless core: one self-contained POST, no prior initialize."""
    async with _AppHarness(app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": REQUEST_ENVELOPE},
            },
            headers=_headers("tools/list"),
        )
    assert response.status_code == 200
    # No session is established, so no session header may come back.
    assert "mcp-session-id" not in {k.lower() for k in response.headers}
    result = _parse(response)["result"]
    assert len(result["tools"]) > 0


@pytest.mark.asyncio
async def test_tools_list_advertises_a_cache_hint(app):
    async with _AppHarness(app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": REQUEST_ENVELOPE},
            },
            headers=_headers("tools/list"),
        )
    result = _parse(response)["result"]
    assert result["ttlMs"] == TOOLS_LIST_TTL_MS
    assert result["cacheScope"] == "public"


@pytest.mark.asyncio
async def test_server_discover_replaces_the_handshake(app):
    async with _AppHarness(app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "server/discover",
                "params": {"_meta": REQUEST_ENVELOPE},
            },
            headers=_headers("server/discover"),
        )
    assert response.status_code == 200
    result = _parse(response)["result"]
    assert "capabilities" in result
    assert "supportedVersions" in result


@pytest.mark.asyncio
async def test_independent_requests_share_no_session_state(app):
    """Any instance can answer any request — the load-balancer property."""
    async with _AppHarness(app) as client:
        pongs = []
        for i in range(3):
            response = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 100 + i,
                    "method": "tools/call",
                    "params": {
                        "name": "ds_ping",
                        "arguments": {"message": f"req{i}"},
                        "_meta": REQUEST_ENVELOPE,
                    },
                },
                headers=_headers("tools/call", "ds_ping"),
            )
            assert response.status_code == 200
            pongs.append(_parse(response)["result"]["structuredContent"]["pong"])
    assert pongs == ["req0", "req1", "req2"]


# ---------------------------------------------------------------------------
# Stateless-era transport hardening
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forged_host_header_is_rejected_when_allowlisted():
    """DNS-rebinding protection.

    Matters more under the stateless core: with no session handshake to
    anchor a connection, every POST is independently trusted, so a rebound
    DNS name aimed at a locally-bound mesa-mcp would otherwise reach the
    tool surface directly.
    """
    from mesa_mcp.config import ServerConfig

    config = Config(
        server=ServerConfig(public_base_url="https://mesa-mcp.example.test")
    )
    rebind_app = build_sse_app(MesaServer(config=config), config)
    async with _AppHarness(rebind_app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": REQUEST_ENVELOPE},
            },
            headers={**_headers("tools/list"), "Host": "attacker.example"},
        )
    assert response.status_code == 421


@pytest.mark.asyncio
async def test_allowlisted_host_is_accepted():
    from mesa_mcp.config import ServerConfig

    config = Config(
        server=ServerConfig(public_base_url="https://mesa-mcp.example.test")
    )
    ok_app = build_sse_app(MesaServer(config=config), config)
    async with _AppHarness(ok_app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {"_meta": REQUEST_ENVELOPE},
            },
            headers={**_headers("tools/list"), "Host": "mesa-mcp.example.test"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_mismatched_mcp_name_header_is_rejected(app):
    """Header routing is an integrity check, not just dispatch.

    A desync / protocol-confusion attempt — HTTP envelope naming one tool
    while the JSON-RPC body names another — must be refused by the
    transport before any handler runs.
    """
    async with _AppHarness(app) as client:
        response = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "ds_ping",
                    "arguments": {"message": "x"},
                    "_meta": REQUEST_ENVELOPE,
                },
            },
            # Header claims a destructive tool the body does not name.
            headers=_headers("tools/call", "ds_delete_file"),
        )
    assert response.status_code == 400
    assert "does not match" in _parse(response)["error"]["message"]
