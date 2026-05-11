"""Tests for the Streamable HTTP transport mounted at ``/mcp``.

We do not drive the full MCP handshake here — that is the SDK's job and
already exercised in the upstream test suite. Our concern is the
boundary mesa-mcp owns:

* The OIDC middleware gates ``/mcp`` exactly like it gates ``/sse``.
* 401 responses carry the same ``WWW-Authenticate`` shape, including
  ``resource_metadata`` pointing at our protected-resource metadata.
* A valid bearer token gets past the gate and reaches the SDK's
  :class:`StreamableHTTPSessionManager.handle_request`, which then
  responds with whatever the protocol says is right for the inbound
  payload.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.server import MesaServer
from mesa_mcp.transport.oidc import OIDCError
from mesa_mcp.transport.sse import build_sse_app
from mesa_mcp.transport.streamable_http import STREAMABLE_HTTP_PATH
from mesa_mcp.transport.wellknown import PROTECTED_RESOURCE_METADATA_PATH


class _FakeAuthenticator:
    """Duplicated from test_sse_auth.py to keep this file self-contained."""

    def __init__(self, *, accept_token: str, av: AuthValue) -> None:
        self._accept_token = accept_token
        self._av = av

    async def authenticate(
        self,
        authorization_header: str | None,
        *,
        zone: str = "",
    ) -> AuthValue:
        if not authorization_header:
            raise OIDCError("missing Authorization header", status_code=401)
        parts = authorization_header.strip().split(None, 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            raise OIDCError("malformed Authorization", status_code=401)
        if parts[1] != self._accept_token:
            raise OIDCError("token rejected", status_code=401)
        return self._av

    async def aclose(self) -> None:
        return None


@pytest.fixture
def sse_app_streamable(config_fixture, monkeypatch) -> Any:
    """Build the full SSE app (which now includes ``/mcp``) with a fake
    OIDC authenticator and ``public_base_url`` set so the WWW-Authenticate
    challenge is deterministic.
    """
    config = config_fixture.model_copy(deep=True)
    config.server.oidc_discovery_url = (
        "https://kc.example.test/realms/CyVerse/.well-known/openid-configuration"
    )
    config.server.public_base_url = "https://mesa-mcp.example.test"

    fake = _FakeAuthenticator(
        accept_token="good-token",
        av=AuthValue(username="tswetnam", zone="iplant", password=None),
    )

    import mesa_mcp.transport.sse as sse_module

    monkeypatch.setattr(sse_module, "_build_authenticator", lambda cfg: fake)

    server = MesaServer(config=config)
    return build_sse_app(server, config)


# ---------------------------------------------------------------------------
# Auth gate parity with /sse
# ---------------------------------------------------------------------------


def test_mcp_post_requires_bearer_token(sse_app_streamable) -> None:
    """Without any Authorization header, ``POST /mcp`` must 401."""
    with TestClient(sse_app_streamable) as client:
        resp = client.post(
            STREAMABLE_HTTP_PATH,
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
        )
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_mcp_post_401_includes_www_authenticate(sse_app_streamable) -> None:
    """The 401 from ``/mcp`` carries the same RFC 9728 pointer as ``/sse``."""
    with TestClient(sse_app_streamable) as client:
        resp = client.post(
            STREAMABLE_HTTP_PATH,
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
        )
    challenge = resp.headers.get("WWW-Authenticate", "")
    assert challenge.startswith("Bearer ")
    assert (
        f'resource_metadata="https://mesa-mcp.example.test'
        f'{PROTECTED_RESOURCE_METADATA_PATH}"'
        in challenge
    )


def test_mcp_post_rejects_bad_bearer(sse_app_streamable) -> None:
    """A bad token → 401 with ``error="invalid_token"``."""
    with TestClient(sse_app_streamable) as client:
        resp = client.post(
            STREAMABLE_HTTP_PATH,
            headers={"Authorization": "Bearer wrong"},
            json={"jsonrpc": "2.0", "method": "ping", "id": 1},
        )
    assert resp.status_code == 401
    challenge = resp.headers.get("WWW-Authenticate", "")
    assert 'error="invalid_token"' in challenge


# ---------------------------------------------------------------------------
# Past-the-gate behavior
# ---------------------------------------------------------------------------


def test_mcp_valid_token_reaches_sdk_handler(sse_app_streamable) -> None:
    """A valid bearer + a minimal MCP ``initialize`` request must pass the
    OIDC gate.

    We do not assert the SDK's response shape (that is the SDK's
    responsibility). We *do* assert the response is not a 401 from our
    middleware, proving the gate let the request through to the
    Streamable HTTP session manager. Anything non-401 with a body that
    is not our ``error=unauthorized`` JSON proves the handoff.
    """
    initialize_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "mesa-mcp-tests", "version": "0.0.0"},
        },
    }
    with TestClient(sse_app_streamable) as client:
        resp = client.post(
            STREAMABLE_HTTP_PATH,
            headers={
                "Authorization": "Bearer good-token",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
            json=initialize_payload,
        )

    assert resp.status_code != 401, (
        f"OIDC middleware unexpectedly rejected a valid token; body={resp.text!r}"
    )
    # The SDK either returns an immediate JSON response (200 with the
    # initialize result + ``Mcp-Session-Id`` header) or an SSE stream.
    # Both confirm the handoff. The thing we are explicitly ruling out
    # is the ``{"error": "unauthorized", ...}`` body our middleware
    # would produce on 401.
    try:
        body = resp.json()
    except ValueError:
        # SSE/text response — definitely not our 401 JSON.
        return
    assert body.get("error") != "unauthorized", (
        f"Expected to clear the auth gate but got our unauthorized body: {body!r}"
    )
