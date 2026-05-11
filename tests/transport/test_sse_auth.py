"""End-to-end tests for the SSE app's OIDC middleware.

We don't drive an MCP client here — we just verify the auth gate at
``/sse`` and the OIDC failure shape.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.server import MesaServer
from mesa_mcp.transport.oidc import OIDCError
from mesa_mcp.transport.sse import build_sse_app


class _FakeAuthenticator:
    """Minimal stand-in: returns a fixed :class:`AuthValue` for "good" tokens,
    raises :class:`OIDCError` otherwise. Used to keep these tests independent
    of the full discovery/JWKS plumbing exercised in ``test_oidc.py``.
    """

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
def sse_app_with_fake_oidc(config_fixture, monkeypatch) -> Any:
    """Build the SSE app but swap in a fake authenticator that we control."""
    # We need the build function to produce *some* authenticator, so set a
    # non-empty discovery URL — then patch ``_build_authenticator`` to
    # hand back our fake.
    config = config_fixture.model_copy(deep=True)
    config.server.oidc_discovery_url = "https://kc.example.test/realms/CyVerse"
    fake = _FakeAuthenticator(
        accept_token="good-token",
        av=AuthValue(username="tswetnam", zone="iplant", password=None),
    )

    import mesa_mcp.transport.sse as sse_module

    monkeypatch.setattr(sse_module, "_build_authenticator", lambda cfg: fake)

    server = MesaServer(config=config)
    return build_sse_app(server, config)


def test_sse_requires_bearer_token(sse_app_with_fake_oidc) -> None:
    client = TestClient(sse_app_with_fake_oidc)
    resp = client.get("/sse")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error"] == "unauthorized"
    assert "detail" in body


def test_sse_rejects_bad_bearer_token(sse_app_with_fake_oidc) -> None:
    client = TestClient(sse_app_with_fake_oidc)
    resp = client.get("/sse", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_sse_accepts_valid_bearer_token_at_messages_endpoint(
    sse_app_with_fake_oidc,
) -> None:
    """A valid token must reach the SSE transport (which then returns its
    own non-401 error). We probe the companion ``/messages/`` endpoint
    rather than ``/sse`` because the SSE GET is a streaming response and
    Starlette's ``TestClient`` would hold the connection open. Without
    a session id, ``handle_post_message`` returns 400 — confirming the
    auth middleware let us through to the SDK handler.
    """
    client = TestClient(sse_app_with_fake_oidc)
    resp = client.post(
        "/messages/",
        headers={
            "Authorization": "Bearer good-token",
            "Content-Type": "application/json",
        },
        content="{}",
    )
    # The MCP SDK's POST handler validates the session_id query parameter.
    # We didn't supply one, so it returns 400 "session_id is required" —
    # not our 401, which proves the auth middleware let us through.
    assert resp.status_code == 400
    assert "session_id" in resp.text


def test_messages_endpoint_rejects_missing_token(sse_app_with_fake_oidc) -> None:
    client = TestClient(sse_app_with_fake_oidc)
    resp = client.post("/messages/", content="{}")
    assert resp.status_code == 401
    assert resp.json()["error"] == "unauthorized"


def test_oidc_middleware_directly_with_valid_token(config_fixture, monkeypatch) -> None:
    """Exercise the OIDC middleware in isolation with a known-good token.

    We don't actually drive the streaming SSE handler here — Starlette's
    sync ``TestClient`` cannot probe an SSE stream without holding the
    connection open. Instead we wrap a trivial downstream ASGI app and
    confirm the middleware:

    * Returns 200 when the authenticator accepts the token, AND
    * Has bound :class:`AuthValue` to the contextvar at the point the
      downstream app runs.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from mesa_mcp.context import get_current_auth_value
    from mesa_mcp.transport.sse import OIDCMiddleware

    async def probe(request) -> JSONResponse:
        av = get_current_auth_value()
        return JSONResponse(
            {"username": av.username if av else None}
        )

    fake = _FakeAuthenticator(
        accept_token="good-token",
        av=AuthValue(username="tswetnam", zone="iplant", password=None),
    )
    inner = Starlette(routes=[Route("/probe", endpoint=probe, methods=["GET"])])
    app = OIDCMiddleware(inner, authenticator=fake, config=config_fixture)

    client = TestClient(app)
    resp = client.get("/probe", headers={"Authorization": "Bearer good-token"})
    assert resp.status_code == 200
    assert resp.json() == {"username": "tswetnam"}

    resp_bad = client.get("/probe")
    assert resp_bad.status_code == 401


def test_healthz_does_not_require_token(sse_app_with_fake_oidc) -> None:
    client = TestClient(sse_app_with_fake_oidc)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_no_oidc_mode_lets_anything_through(config_fixture) -> None:
    """Local-dev mode (``oidc_discovery_url=""``) must accept any request,
    log a loud warning, and bind an anonymous :class:`AuthValue`.
    """
    config = config_fixture.model_copy(deep=True)
    config.server.oidc_discovery_url = ""
    server = MesaServer(config=config)
    app = build_sse_app(server, config)
    client = TestClient(app)
    resp = client.get("/healthz")
    assert resp.status_code == 200
