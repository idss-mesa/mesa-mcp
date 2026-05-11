"""Shared fixtures for the transport-layer tests.

The OIDC tests need a working JWT signing setup. Rather than mocking JWT
verification itself (which would test the mock, not the code), we mint a
fresh RSA keypair per test session, expose it as a JWKS, and let the real
PyJWT decode path run against tokens we sign ourselves.

The fake httpx client routes ``discovery_url`` GETs to a static document
that points ``jwks_uri`` at a separate URL the same client serves the
JWKS from. This mirrors the real discovery/JWKS split without needing a
local Keycloak.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

DISCOVERY_URL = "https://kc.example.test/realms/CyVerse/.well-known/openid-configuration"
JWKS_URL = "https://kc.example.test/realms/CyVerse/protocol/openid-connect/certs"
ISSUER = "https://kc.example.test/realms/CyVerse"
TEST_KID = "test-key-1"


@dataclass
class FakeKeycloak:
    """Holds a freshly-generated RSA key + the URLs that expose its JWKS."""

    private_key: rsa.RSAPrivateKey
    private_pem: bytes
    jwk: dict[str, Any]
    discovery_doc: dict[str, Any]
    discovery_url: str = DISCOVERY_URL
    jwks_url: str = JWKS_URL
    issuer: str = ISSUER
    kid: str = TEST_KID
    # Track every request the handler saw — tests assert on cache hits.
    request_log: list[str] = field(default_factory=list)


def _build_keypair() -> tuple[rsa.RSAPrivateKey, bytes, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # PyJWT exposes ``RSAAlgorithm.to_jwk`` which returns a JWK string; we
    # parse it so we can inject ``kid`` and ``use``/``alg`` fields the way
    # Keycloak does.
    jwk_str = RSAAlgorithm.to_jwk(private_key.public_key())
    jwk = json.loads(jwk_str)
    jwk["kid"] = TEST_KID
    jwk["use"] = "sig"
    jwk["alg"] = "RS256"
    return private_key, private_pem, jwk


@pytest.fixture
def fake_keycloak() -> FakeKeycloak:
    """A self-contained Keycloak stand-in: keypair + discovery doc + JWK."""
    private_key, private_pem, jwk = _build_keypair()
    discovery_doc = {
        "issuer": ISSUER,
        "jwks_uri": JWKS_URL,
        "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
        "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
        "userinfo_endpoint": f"{ISSUER}/protocol/openid-connect/userinfo",
    }
    return FakeKeycloak(
        private_key=private_key,
        private_pem=private_pem,
        jwk=jwk,
        discovery_doc=discovery_doc,
    )


@pytest.fixture
def fake_http_client(fake_keycloak: FakeKeycloak) -> httpx.AsyncClient:
    """Return an :class:`httpx.AsyncClient` whose transport hits an in-memory
    handler that knows how to serve the discovery doc and JWKS.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fake_keycloak.request_log.append(url)
        if url == fake_keycloak.discovery_url:
            return httpx.Response(200, json=fake_keycloak.discovery_doc)
        if url == fake_keycloak.jwks_url:
            return httpx.Response(200, json={"keys": [fake_keycloak.jwk]})
        return httpx.Response(404, json={"error": "not found"})

    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)
