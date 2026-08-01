"""Authorization-hardening tests (MCP 2026-07-28).

Covers the two controls the spec's auth-hardening work pushes onto the
resource server:

* **Strict audience binding** — a token must be bound to *this* resource
  (RFC 8707 resource indicator / RFC 9728 ``resource``), so a token minted
  for another CyVerse service cannot be replayed against mesa-mcp.
* **Issuer identification** — the discovery document must actually belong
  to the issuer it claims (RFC 8414 §3.3), and its ``jwks_uri`` must be
  same-origin with that issuer, so a substituted document cannot redirect
  signing-key retrieval to an attacker-controlled host (mix-up defense).

These use the real PyJWT decode path against a locally-signed key — see
``conftest.py``.
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest

from mesa_mcp.transport.oidc import OIDCAuthenticator, OIDCError

from .conftest import FakeKeycloak

RESOURCE = "https://mesa-mcp.example.test"


def _token(kc: FakeKeycloak, **claims: Any) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": kc.issuer,
        "sub": "00000000-0000-0000-0000-000000000001",
        "preferred_username": "tswetnam",
        "iat": now,
        "exp": now + 300,
    }
    payload.update(claims)
    return jwt.encode(
        payload,
        kc.private_key,
        algorithm="RS256",
        headers={"kid": kc.kid, "alg": "RS256"},
    )


# ---------------------------------------------------------------------------
# Strict audience binding
# ---------------------------------------------------------------------------


def test_requires_an_audience_at_construction(fake_keycloak):
    """A server that cannot bind tokens to itself must not accept them."""
    with pytest.raises(ValueError, match="requires an audience"):
        OIDCAuthenticator(discovery_url=fake_keycloak.discovery_url)


def test_opting_out_of_audience_is_allowed_explicitly(fake_keycloak):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,
    )
    assert auth.require_audience is False


async def test_token_without_aud_is_rejected(fake_keycloak, fake_http_client):
    """The core replay defense.

    PyJWT's audience check passes vacuously when the claim is absent, so
    the ``aud`` claim is explicitly *required*. Without this, a token
    issued for any other service in the realm authenticates here.
    """
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        http_client=fake_http_client,
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {_token(fake_keycloak)}")
    assert exc_info.value.status_code == 401


async def test_token_for_another_service_is_rejected(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        http_client=fake_http_client,
    )
    other = _token(fake_keycloak, aud="https://some-other-cyverse-service.test")
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {other}")
    assert "audience" in exc_info.value.detail.lower()


async def test_correctly_bound_token_is_accepted(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        http_client=fake_http_client,
    )
    value = await auth.authenticate(
        f"Bearer {_token(fake_keycloak, aud=RESOURCE)}", zone="iplant"
    )
    assert value.username == "tswetnam"
    assert value.zone == "iplant"


# ---------------------------------------------------------------------------
# Issuer identification / mix-up defense
# ---------------------------------------------------------------------------


async def test_discovery_claiming_a_foreign_issuer_is_rejected(
    fake_keycloak, fake_http_client
):
    """RFC 8414 §3.3: the issuer must match where the metadata came from.

    The foreign ``jwks_uri`` is moved to the *same* foreign origin as the
    claimed issuer, so the same-origin check below cannot fire. This
    isolates the derived-issuer check — verified by mutation: disabling
    only that check makes this test fail.
    """
    evil = "https://evil.example.test/realms/CyVerse"
    fake_keycloak.discovery_doc["issuer"] = evil
    fake_keycloak.discovery_doc["jwks_uri"] = f"{evil}/protocol/openid-connect/certs"
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        http_client=fake_http_client,
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {_token(fake_keycloak, aud=RESOURCE)}")
    assert exc_info.value.status_code == 503
    assert "does not match its discovery url" in exc_info.value.detail.lower()


async def test_jwks_uri_on_a_foreign_origin_is_rejected(
    fake_keycloak, fake_http_client
):
    """A tampered document must not redirect signing-key retrieval."""
    fake_keycloak.discovery_doc["jwks_uri"] = "https://evil.example.test/certs"
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        http_client=fake_http_client,
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {_token(fake_keycloak, aud=RESOURCE)}")
    assert exc_info.value.status_code == 503
    assert "same-origin" in exc_info.value.detail.lower()


async def test_expected_issuer_pin_is_enforced(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        expected_issuer="https://kc.cyverse.org/auth/realms/CyVerse",
        http_client=fake_http_client,
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {_token(fake_keycloak, aud=RESOURCE)}")
    assert exc_info.value.status_code == 503


async def test_matching_expected_issuer_passes(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience=RESOURCE,
        expected_issuer=fake_keycloak.issuer,
        http_client=fake_http_client,
    )
    value = await auth.authenticate(f"Bearer {_token(fake_keycloak, aud=RESOURCE)}")
    assert value.username == "tswetnam"


# ---------------------------------------------------------------------------
# Wiring: the enforced audience is the one we advertise
# ---------------------------------------------------------------------------


def test_audience_defaults_to_the_published_resource_identifier():
    """The audience enforced must be the ``resource`` clients were told to request."""
    from mesa_mcp.config import Config, ServerConfig
    from mesa_mcp.transport.sse import _build_authenticator

    config = Config(
        server=ServerConfig(
            oidc_discovery_url=(
                "https://kc.example.test/realms/CyVerse/.well-known/openid-configuration"
            ),
            public_base_url="https://mesa-mcp.example.test/",
        )
    )
    auth = _build_authenticator(config)
    assert auth is not None
    # Trailing slash normalized so it matches the published ``resource``.
    assert auth.audience == "https://mesa-mcp.example.test"
    assert auth.expected_issuer == "https://kc.example.test/realms/CyVerse"
