"""Tests for the OAuth 2.0 protected-resource metadata endpoint.

Covers:

* GET ``/.well-known/oauth-protected-resource`` returns a well-formed
  RFC 9728 document.
* The endpoint is unauthenticated (no bearer token needed).
* When the OIDC middleware rejects a request to ``/sse`` with a 401, the
  response carries ``WWW-Authenticate: Bearer ... resource_metadata=<url>``
  pointing at the metadata endpoint.
* The ``public_base_url`` config field, when set, wins over the
  request-derived host.
"""

from __future__ import annotations

from typing import Any

import pytest
from starlette.testclient import TestClient

from mesa_mcp.auth.models import AuthValue
from mesa_mcp.server import MesaServer
from mesa_mcp.transport.oidc import OIDCError
from mesa_mcp.transport.sse import build_sse_app
from mesa_mcp.transport.wellknown import (
    PROTECTED_RESOURCE_METADATA_PATH,
    issuer_from_discovery_url,
)

# ---------------------------------------------------------------------------
# Helper from test_sse_auth.py — duplicated here to keep this file standalone.
# ---------------------------------------------------------------------------


class _FakeAuthenticator:
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
def sse_app_with_metadata(config_fixture, monkeypatch) -> Any:
    """Build the SSE app with a fake OIDC authenticator and the protected-
    resource metadata config populated.
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
# Issuer helper
# ---------------------------------------------------------------------------


def test_issuer_from_discovery_url_strips_well_known_suffix() -> None:
    assert (
        issuer_from_discovery_url(
            "https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration"
        )
        == "https://kc.cyverse.org/auth/realms/CyVerse"
    )


def test_issuer_from_discovery_url_passthrough_when_no_suffix() -> None:
    assert (
        issuer_from_discovery_url("https://kc.example.test/realms/CyVerse")
        == "https://kc.example.test/realms/CyVerse"
    )


# ---------------------------------------------------------------------------
# Metadata endpoint
# ---------------------------------------------------------------------------


def test_metadata_endpoint_is_public(sse_app_with_metadata) -> None:
    """No bearer token required."""
    client = TestClient(sse_app_with_metadata)
    resp = client.get(PROTECTED_RESOURCE_METADATA_PATH)
    assert resp.status_code == 200


def test_metadata_endpoint_body_shape(sse_app_with_metadata) -> None:
    client = TestClient(sse_app_with_metadata)
    body = client.get(PROTECTED_RESOURCE_METADATA_PATH).json()
    assert body["resource"] == "https://mesa-mcp.example.test"
    assert body["authorization_servers"] == [
        "https://kc.example.test/realms/CyVerse"
    ]
    assert body["bearer_methods_supported"] == ["header"]
    assert body["scopes_supported"] == []


def test_metadata_endpoint_falls_back_to_request_host(
    config_fixture, monkeypatch
) -> None:
    """When ``public_base_url`` is empty, the resource URL is rebuilt from
    the inbound request's scheme + host headers.
    """
    config = config_fixture.model_copy(deep=True)
    config.server.oidc_discovery_url = (
        "https://kc.example.test/realms/CyVerse/.well-known/openid-configuration"
    )
    config.server.public_base_url = None

    fake = _FakeAuthenticator(
        accept_token="good-token",
        av=AuthValue(username="tswetnam", zone="iplant", password=None),
    )
    import mesa_mcp.transport.sse as sse_module

    monkeypatch.setattr(sse_module, "_build_authenticator", lambda cfg: fake)

    server = MesaServer(config=config)
    app = build_sse_app(server, config)

    client = TestClient(app, base_url="http://mesa.local")
    body = client.get(
        PROTECTED_RESOURCE_METADATA_PATH,
        headers={"X-Forwarded-Proto": "https"},
    ).json()
    assert body["resource"] == "https://mesa.local"


def test_metadata_endpoint_omits_authorization_servers_when_oidc_disabled(
    config_fixture,
) -> None:
    """No OIDC discovery URL → empty ``authorization_servers`` list.

    Local-dev mode shouldn't claim an AS it can't actually verify against.
    """
    config = config_fixture.model_copy(deep=True)
    config.server.oidc_discovery_url = ""
    config.server.public_base_url = "https://mesa-mcp.example.test"
    server = MesaServer(config=config)
    app = build_sse_app(server, config)
    client = TestClient(app)
    body = client.get(PROTECTED_RESOURCE_METADATA_PATH).json()
    assert body["authorization_servers"] == []


# ---------------------------------------------------------------------------
# WWW-Authenticate on 401
# ---------------------------------------------------------------------------


def test_401_includes_www_authenticate_with_resource_metadata(
    sse_app_with_metadata,
) -> None:
    client = TestClient(sse_app_with_metadata)
    resp = client.get("/sse")
    assert resp.status_code == 401
    challenge = resp.headers.get("WWW-Authenticate", "")
    assert challenge.startswith("Bearer ")
    assert (
        f'resource_metadata="https://mesa-mcp.example.test'
        f'{PROTECTED_RESOURCE_METADATA_PATH}"'
        in challenge
    )


def test_401_missing_token_omits_invalid_token_error(sse_app_with_metadata) -> None:
    """No credentials → no ``error=invalid_token`` per RFC 6750 §3.1.

    Still advertises ``resource_metadata`` so clients can bootstrap auth.
    """
    client = TestClient(sse_app_with_metadata)
    resp = client.get("/sse")
    challenge = resp.headers.get("WWW-Authenticate", "")
    assert 'error="invalid_token"' not in challenge
    assert "resource_metadata=" in challenge


def test_401_bad_token_includes_invalid_token_error(sse_app_with_metadata) -> None:
    """A *bad* token does carry ``error=invalid_token``."""
    client = TestClient(sse_app_with_metadata)
    resp = client.get("/sse", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401
    challenge = resp.headers.get("WWW-Authenticate", "")
    assert 'error="invalid_token"' in challenge
    assert 'error_description="' in challenge
    assert "resource_metadata=" in challenge
