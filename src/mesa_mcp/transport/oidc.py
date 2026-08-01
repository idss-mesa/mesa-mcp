"""CyVerse Keycloak / OpenID Connect bearer-token verification.

The HTTP/SSE transport calls :meth:`OIDCAuthenticator.authenticate` once per
incoming request. The authenticator:

1. Pulls the OIDC discovery document from ``discovery_url`` (cached one day).
2. Pulls the JWKS from the discovery document's ``jwks_uri`` (cached 15
   minutes — Keycloak rotates keys, so we don't want a long-lived cache).
3. Verifies the JWT signature, ``exp``, ``iss``, and ``aud`` claims.
4. Returns a frozen :class:`AuthValue` with ``auth_scheme="native"`` and
   identity pulled from ``preferred_username`` (fallback ``sub``). The zone
   comes from the running :class:`Config` because Keycloak tokens don't
   carry an iRODS zone claim.

The CyVerse Keycloak realm URL is
``https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration``.

Notes on quirks observed against the live Keycloak:

* The discovery doc's ``issuer`` field is what tokens claim as ``iss`` — we
  pin token validation to that exact string, not to the discovery URL.
* Keycloak's access tokens carry ``aud`` set to the *client* that requested
  them, which may not be the resource server's own client ID. The audience
  argument therefore defaults to ``None`` (skip aud check) — set it via
  ``ServerConfig.oidc_audience`` when you want a strict bind.
* The JWKS endpoint is rate-limited; we honour ``Cache-Control: max-age`` if
  Keycloak sends it, but we never extend our cache past 15 minutes regardless
  of what the server suggests.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK
from jwt.exceptions import (
    DecodeError,
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidSignatureError,
    InvalidTokenError,
    MissingRequiredClaimError,
)

from mesa_mcp.auth.models import AuthValue

logger = logging.getLogger(__name__)

# Default TTLs. Discovery documents change rarely (issuer URL, endpoints,
# supported algorithms); JWKS rotates much more frequently in Keycloak.
DEFAULT_DISCOVERY_TTL = 24 * 60 * 60  # 1 day
DEFAULT_JWKS_TTL = 15 * 60  # 15 minutes
DEFAULT_HTTP_TIMEOUT = 10.0

# Signing algorithms we accept. Keycloak defaults to RS256; we allow the
# common RSA/ECDSA flavors any sane realm might pick. HS* (shared-secret)
# is intentionally excluded — bearer JWTs in OIDC are always asymmetric.
ACCEPTED_ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512")


class OIDCError(Exception):
    """Raised when bearer-token authentication fails.

    Attributes
    ----------
    status_code:
        HTTP status hint the transport layer should return. Usually 401
        (missing/invalid token) or 503 (OIDC infrastructure unreachable).
    detail:
        Short, safe-to-surface description of the failure. Never includes
        the token itself, signing keys, or stack frames.
    """

    def __init__(
        self,
        detail: str,
        *,
        status_code: int = 401,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"OIDCError(status={self.status_code}, detail={self.detail!r})"


@dataclass
class _CachedDoc:
    """In-memory TTL cache for the discovery doc + JWKS pair."""

    data: dict[str, Any]
    expires_at: float

    def alive(self, now: float) -> bool:
        return now < self.expires_at


@dataclass
class OIDCAuthenticator:
    """Validates inbound bearer JWTs against a CyVerse Keycloak realm.

    Parameters
    ----------
    discovery_url:
        Full URL to the realm's ``.well-known/openid-configuration``.
    client_id:
        OAuth client ID of the resource server. Currently only used to
        annotate logs; audience validation uses :attr:`audience`.
    audience:
        Expected ``aud`` claim — the canonical resource identifier of this
        deployment (RFC 8707 resource indicator / RFC 9728 ``resource``).
    require_audience:
        When ``True`` (default, MCP 2026-07-28 hardening) a missing or
        mismatched ``aud`` is rejected, and constructing the authenticator
        without an ``audience`` is a configuration error. When ``False``,
        audience validation is skipped and every request logs a warning.
    expected_issuer:
        Issuer this deployment trusts. When set, the issuer advertised by
        the discovery document must match it exactly — see
        :meth:`_get_discovery`.
    http_client:
        Pre-built :class:`httpx.AsyncClient`. When omitted, the
        authenticator creates and owns one. Tests inject a stub.
    discovery_ttl, jwks_ttl:
        Cache lifetimes for the discovery document and JWKS (seconds).
    """

    discovery_url: str
    client_id: str | None = None
    audience: str | None = None
    require_audience: bool = True
    expected_issuer: str | None = None
    http_client: httpx.AsyncClient | None = None
    discovery_ttl: float = DEFAULT_DISCOVERY_TTL
    jwks_ttl: float = DEFAULT_JWKS_TTL
    http_timeout: float = DEFAULT_HTTP_TIMEOUT

    _discovery_cache: _CachedDoc | None = field(default=None, init=False, repr=False)
    _jwks_cache: _CachedDoc | None = field(default=None, init=False, repr=False)
    _owns_client: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.http_client is None:
            self.http_client = httpx.AsyncClient(timeout=self.http_timeout)
            self._owns_client = True
        # Fail fast at construction rather than per request: a server that
        # cannot bind tokens to itself must not begin accepting them.
        if self.require_audience and not self.audience:
            raise ValueError(
                "OIDCAuthenticator requires an audience when "
                "require_audience is True. Set server.oidc_audience (or "
                "server.public_base_url, which supplies the canonical "
                "resource identifier), or set "
                "server.oidc_require_audience=false to accept any "
                "validly-signed token from the realm — which allows a "
                "token issued for another service to be replayed here."
            )
        if not self.require_audience:
            logger.warning(
                "audience validation is DISABLED — any validly-signed token "
                "from this realm is accepted, including tokens minted for "
                "other services. Set server.oidc_audience to close this."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def authenticate(
        self,
        authorization_header: str | None,
        *,
        zone: str = "",
    ) -> AuthValue:
        """Verify ``Authorization`` and return the caller's :class:`AuthValue`.

        Parameters
        ----------
        authorization_header:
            Raw value of the ``Authorization`` HTTP header. Must be
            ``Bearer <jwt>``. ``None`` or any other shape raises
            :class:`OIDCError` with status 401.
        zone:
            iRODS zone to embed in the returned :class:`AuthValue`. Keycloak
            tokens don't carry an iRODS zone claim, so the caller (transport
            layer) pulls it from :class:`mesa_mcp.config.Config`.
        """
        token = _extract_bearer(authorization_header)
        discovery = await self._get_discovery()
        jwks = await self._get_jwks(discovery)

        signing_key = _select_signing_key(token, jwks)

        verify_aud = self.require_audience or self.audience is not None
        required_claims = ["exp", "iss"]
        if verify_aud:
            # Force a *present* aud claim: PyJWT's audience check passes
            # vacuously on a token that simply omits the claim, so
            # requiring it is what actually binds the token to us.
            required_claims.append("aud")

        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=list(ACCEPTED_ALGORITHMS),
                audience=self.audience,
                issuer=discovery["issuer"],
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iss": True,
                    "verify_aud": verify_aud,
                    "require": required_claims,
                },
            )
        except ExpiredSignatureError as exc:
            raise OIDCError("token expired", status_code=401) from exc
        except InvalidAudienceError as exc:
            raise OIDCError("invalid token audience", status_code=401) from exc
        except InvalidIssuerError as exc:
            raise OIDCError("invalid token issuer", status_code=401) from exc
        except InvalidSignatureError as exc:
            raise OIDCError("invalid token signature", status_code=401) from exc
        except MissingRequiredClaimError as exc:
            raise OIDCError(
                f"token missing required claim: {exc.claim}",
                status_code=401,
            ) from exc
        except (DecodeError, InvalidTokenError) as exc:
            raise OIDCError(f"invalid token: {exc}", status_code=401) from exc

        username = claims.get("preferred_username") or claims.get("sub")
        if not username:
            raise OIDCError(
                "token has neither preferred_username nor sub",
                status_code=401,
            )
        # CyVerse usernames sometimes arrive with a realm suffix
        # (``alice@CyVerse``); strip to match the iRODS username form.
        if "@" in username:
            username = username.split("@", 1)[0]

        return AuthValue(
            username=username,
            zone=zone,
            password=None,
            auth_scheme="native",
        )

    async def aclose(self) -> None:
        """Close the owned HTTP client, if we created one."""
        if self._owns_client and self.http_client is not None:
            await self.http_client.aclose()

    # ------------------------------------------------------------------
    # Internal: discovery + JWKS fetch
    # ------------------------------------------------------------------

    async def _get_discovery(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._discovery_cache is not None and self._discovery_cache.alive(now):
            return self._discovery_cache.data

        assert self.http_client is not None  # set in __post_init__
        try:
            resp = await self.http_client.get(self.discovery_url)
            resp.raise_for_status()
            doc = resp.json()
        except httpx.HTTPError as exc:
            raise OIDCError(
                "OIDC discovery fetch failed",
                status_code=503,
            ) from exc
        except ValueError as exc:  # JSON decode
            raise OIDCError(
                "OIDC discovery response was not JSON",
                status_code=503,
            ) from exc

        if not isinstance(doc, dict):
            raise OIDCError(
                "OIDC discovery document was not a JSON object",
                status_code=503,
            )
        if "issuer" not in doc or "jwks_uri" not in doc:
            raise OIDCError(
                "OIDC discovery document missing issuer/jwks_uri",
                status_code=503,
            )

        # --- Issuer identification (mix-up defense) --------------------
        #
        # Everything downstream trusts this document: the ``iss`` we pin
        # token validation to, and the ``jwks_uri`` we fetch signing keys
        # from. If a substituted or misconfigured document can name any
        # issuer it likes, an attacker-controlled authorization server
        # could have its keys accepted as authoritative for mesa-mcp.
        #
        # Two checks close that:
        #
        # 1. RFC 8414 §3.3 — the issuer MUST match the URL the metadata
        #    was retrieved from. This is the standard binding between a
        #    discovery document and the identity it claims.
        # 2. An explicit ``expected_issuer`` pin, when configured.
        issuer = doc["issuer"]
        if not isinstance(issuer, str) or not issuer:
            raise OIDCError(
                "OIDC discovery document has a non-string issuer",
                status_code=503,
            )

        derived = _issuer_from_discovery_url(self.discovery_url)
        if derived is not None and issuer.rstrip("/") != derived.rstrip("/"):
            logger.error(
                "OIDC issuer mismatch: discovery URL implies %r but the "
                "document claims %r — refusing to trust it",
                derived,
                issuer,
            )
            raise OIDCError(
                "OIDC discovery issuer does not match its discovery URL",
                status_code=503,
            )

        if (
            self.expected_issuer is not None
            and issuer.rstrip("/") != self.expected_issuer.rstrip("/")
        ):
            logger.error(
                "OIDC issuer %r does not match the configured expected "
                "issuer %r — refusing to trust it",
                issuer,
                self.expected_issuer,
            )
            raise OIDCError(
                "OIDC discovery issuer does not match the configured issuer",
                status_code=503,
            )

        # The JWKS URI must live under the same origin as the issuer, so a
        # tampered document cannot point key retrieval at a foreign host.
        if not _same_origin(doc["jwks_uri"], issuer):
            logger.error(
                "OIDC jwks_uri %r is not same-origin with issuer %r — "
                "refusing to fetch signing keys",
                doc["jwks_uri"],
                issuer,
            )
            raise OIDCError(
                "OIDC jwks_uri is not same-origin with the issuer",
                status_code=503,
            )

        self._discovery_cache = _CachedDoc(
            data=doc,
            expires_at=now + self.discovery_ttl,
        )
        # The JWKS cache is keyed off the discovery doc, so invalidate it
        # whenever we refresh the discovery doc to avoid serving a JWKS
        # belonging to a stale ``jwks_uri``.
        self._jwks_cache = None
        return doc

    async def _get_jwks(self, discovery: dict[str, Any]) -> list[dict[str, Any]]:
        now = time.monotonic()
        if self._jwks_cache is not None and self._jwks_cache.alive(now):
            return self._jwks_cache.data["keys"]  # type: ignore[no-any-return]

        jwks_uri = discovery["jwks_uri"]
        assert self.http_client is not None
        try:
            resp = await self.http_client.get(jwks_uri)
            resp.raise_for_status()
            payload = resp.json()
        except httpx.HTTPError as exc:
            raise OIDCError("JWKS fetch failed", status_code=503) from exc
        except ValueError as exc:
            raise OIDCError("JWKS response was not JSON", status_code=503) from exc

        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise OIDCError("JWKS response missing 'keys' list", status_code=503)

        self._jwks_cache = _CachedDoc(
            data=payload,
            expires_at=now + self.jwks_ttl,
        )
        return payload["keys"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


#: Well-known suffixes a discovery URL may carry. RFC 8414 places the
#: metadata at ``/.well-known/oauth-authorization-server``; OIDC Discovery
#: uses ``/.well-known/openid-configuration``. Keycloak also serves the
#: OIDC form under a realm path.
_DISCOVERY_SUFFIXES = (
    "/.well-known/openid-configuration",
    "/.well-known/oauth-authorization-server",
)


def _issuer_from_discovery_url(discovery_url: str) -> str | None:
    """Derive the issuer a discovery URL implies (RFC 8414 §3.3).

    Returns ``None`` when the URL uses a non-standard layout we cannot
    reason about — the caller then skips the derived-issuer check rather
    than rejecting a legitimate but unusual deployment.
    """
    for suffix in _DISCOVERY_SUFFIXES:
        if discovery_url.endswith(suffix):
            return discovery_url[: -len(suffix)]
    return None


def _same_origin(url: str, other: str) -> bool:
    """True when both URLs share scheme, host, and port."""
    from urllib.parse import urlparse

    a, b = urlparse(url), urlparse(other)
    if not a.scheme or not a.netloc:
        return False
    return (a.scheme, a.hostname, a.port) == (b.scheme, b.hostname, b.port)


def _extract_bearer(authorization_header: str | None) -> str:
    """Return the bare token from ``Authorization: Bearer <token>``.

    Raises :class:`OIDCError` for missing/malformed headers.
    """
    if not authorization_header:
        raise OIDCError("missing Authorization header", status_code=401)
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise OIDCError(
            "Authorization header must be 'Bearer <token>'",
            status_code=401,
        )
    return parts[1].strip()


def _select_signing_key(token: str, jwks: list[dict[str, Any]]) -> Any:
    """Pick the JWK matching the JWT's ``kid`` and return a verification key.

    Returns whatever shape ``jwt.decode`` accepts as ``key`` (a public key
    object from :mod:`cryptography`).
    """
    try:
        unverified = jwt.get_unverified_header(token)
    except (DecodeError, InvalidTokenError) as exc:
        raise OIDCError(f"invalid JWT header: {exc}", status_code=401) from exc

    kid = unverified.get("kid")
    matching: dict[str, Any] | None = None
    if kid is None:
        # No ``kid`` — only acceptable if the JWKS has exactly one key.
        if len(jwks) == 1:
            matching = jwks[0]
        else:
            raise OIDCError(
                "JWT header missing 'kid' and JWKS has multiple keys",
                status_code=401,
            )
    else:
        for jwk_data in jwks:
            if jwk_data.get("kid") == kid:
                matching = jwk_data
                break

    if matching is None:
        raise OIDCError("no matching JWK for token's kid", status_code=401)

    try:
        return PyJWK.from_dict(matching).key
    except (KeyError, ValueError, InvalidTokenError) as exc:
        raise OIDCError(f"could not parse matching JWK: {exc}", status_code=401) from exc
