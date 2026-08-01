"""Unit tests for :class:`mesa_mcp.transport.oidc.OIDCAuthenticator`."""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest

from mesa_mcp.transport.oidc import OIDCAuthenticator, OIDCError

from .conftest import FakeKeycloak


def _make_token(
    kc: FakeKeycloak,
    *,
    claims: dict[str, Any] | None = None,
    headers: dict[str, Any] | None = None,
    algorithm: str = "RS256",
    key: Any = None,
) -> str:
    """Sign a JWT with the fake Keycloak's key (or a caller-supplied one)."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "iss": kc.issuer,
        "sub": "00000000-0000-0000-0000-000000000001",
        "preferred_username": "tswetnam",
        "iat": now,
        "exp": now + 300,
    }
    if claims:
        payload.update(claims)
    full_headers = {"kid": kc.kid, "alg": algorithm}
    if headers:
        full_headers.update(headers)
    signing_key = key if key is not None else kc.private_key
    return jwt.encode(payload, signing_key, algorithm=algorithm, headers=full_headers)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_authenticate_happy_path(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    token = _make_token(fake_keycloak)
    av = await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert av.username == "tswetnam"
    assert av.zone == "iplant"
    assert av.password is None
    assert av.auth_scheme == "native"


async def test_authenticate_caches_discovery_and_jwks(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    token = _make_token(fake_keycloak)
    await auth.authenticate(f"Bearer {token}", zone="iplant")
    await auth.authenticate(f"Bearer {token}", zone="iplant")
    # Exactly one discovery fetch and one JWKS fetch despite two calls.
    discovery_hits = [u for u in fake_keycloak.request_log if u == fake_keycloak.discovery_url]
    jwks_hits = [u for u in fake_keycloak.request_log if u == fake_keycloak.jwks_url]
    assert len(discovery_hits) == 1
    assert len(jwks_hits) == 1


async def test_username_falls_back_to_sub(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    token = _make_token(
        fake_keycloak,
        claims={"preferred_username": None},
    )
    # ``preferred_username`` is None means the helper drops it; we want the
    # claim absent. Re-encode with the key removed.
    token = _make_token(fake_keycloak, claims={"preferred_username": ""})
    # An empty string is falsy in our extractor, so we fall back to sub.
    av = await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert av.username == "00000000-0000-0000-0000-000000000001"


async def test_username_strips_realm_suffix(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    token = _make_token(
        fake_keycloak,
        claims={"preferred_username": "alice@CyVerse"},
    )
    av = await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert av.username == "alice"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


async def test_missing_token_raises(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(None, zone="iplant")
    assert exc_info.value.status_code == 401
    assert "missing" in exc_info.value.detail.lower()


async def test_malformed_authorization_header(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    with pytest.raises(OIDCError):
        await auth.authenticate("Basic dXNlcjpwYXNz", zone="iplant")


async def test_expired_token(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    now = int(time.time())
    token = _make_token(
        fake_keycloak,
        claims={"iat": now - 3600, "exp": now - 60},
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert "expired" in exc_info.value.detail.lower()


async def test_wrong_audience(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience="mesa-mcp",
        http_client=fake_http_client,
    )
    token = _make_token(
        fake_keycloak,
        claims={"aud": "some-other-client"},
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert "audience" in exc_info.value.detail.lower()


async def test_correct_audience_accepted(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        audience="mesa-mcp",
        http_client=fake_http_client,
    )
    token = _make_token(fake_keycloak, claims={"aud": "mesa-mcp"})
    av = await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert av.username == "tswetnam"


async def test_wrong_issuer(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    token = _make_token(
        fake_keycloak,
        claims={"iss": "https://evil.example.com"},
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert "issuer" in exc_info.value.detail.lower()


async def test_invalid_signature(fake_keycloak, fake_http_client):
    """Sign with a different key — verification must reject it."""
    from cryptography.hazmat.primitives.asymmetric import rsa

    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    # Crucially, keep the same ``kid`` so the JWKS resolves to the (real)
    # public key, but the signature comes from the rogue private key.
    token = _make_token(fake_keycloak, key=rogue_key)
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {token}", zone="iplant")
    # Either the signature path or the generic decode path can produce the
    # rejection — both are valid surfaces here.
    assert exc_info.value.status_code == 401


async def test_unknown_kid(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    token = _make_token(
        fake_keycloak,
        headers={"kid": "not-a-real-kid"},
    )
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert "kid" in exc_info.value.detail.lower() or "jwk" in exc_info.value.detail.lower()


async def test_discovery_unreachable(fake_keycloak):
    """A 5xx from the discovery endpoint surfaces as a 503 OIDCError."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=client,
    )
    token = _make_token(fake_keycloak)
    with pytest.raises(OIDCError) as exc_info:
        await auth.authenticate(f"Bearer {token}", zone="iplant")
    assert exc_info.value.status_code == 503


async def test_token_missing_username_claims(fake_keycloak, fake_http_client):
    auth = OIDCAuthenticator(
        discovery_url=fake_keycloak.discovery_url,
        require_audience=False,  # legacy fixture: not exercising aud binding
        http_client=fake_http_client,
    )
    # ``sub`` is required by JWT decoders in some configs; we don't require
    # it ourselves, so we strip both username sources to confirm we error.
    token = _make_token(
        fake_keycloak,
        claims={"preferred_username": "", "sub": ""},
    )
    with pytest.raises(OIDCError):
        await auth.authenticate(f"Bearer {token}", zone="iplant")
