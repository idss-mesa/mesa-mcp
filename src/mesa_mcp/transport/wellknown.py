"""OAuth 2.0 / OpenID Connect well-known metadata endpoints.

Implements RFC 9728 — *OAuth 2.0 Protected Resource Metadata* — so that
MCP clients (Claude.ai's custom connectors, the ``mcp-remote`` bridge,
…) can discover the CyVerse Keycloak authorization server starting only
from the mesa-mcp base URL.

A compliant client that receives a ``401`` from ``/sse`` with a
``WWW-Authenticate: Bearer resource_metadata="<url>"`` header will fetch
that URL to learn:

* ``resource`` — canonical resource identifier (matches what tokens
  should be audience-bound to).
* ``authorization_servers`` — list of AS issuer URLs to drive the OAuth
  dance against. We surface the CyVerse Keycloak realm.
* ``bearer_methods_supported`` — always ``["header"]`` for MCP.
* ``scopes_supported`` — empty today; Keycloak's ``openid`` is enough.

The endpoint is unauthenticated by design — clients hit it *before* they
have a token.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Scope

from mesa_mcp.context import current_config

if TYPE_CHECKING:
    from mesa_mcp.config import Config

logger = logging.getLogger(__name__)

# Path of the metadata endpoint we publish (RFC 9728 §3).
PROTECTED_RESOURCE_METADATA_PATH = "/.well-known/oauth-protected-resource"

# Suffix to strip from an OIDC discovery URL to recover the issuer URL —
# i.e. the canonical AS identifier the client uses for AS metadata.
_DISCOVERY_SUFFIX = "/.well-known/openid-configuration"


def issuer_from_discovery_url(discovery_url: str) -> str:
    """Recover the issuer URL from an OIDC discovery URL.

    ``https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration``
    becomes
    ``https://kc.cyverse.org/auth/realms/CyVerse``.
    """
    if discovery_url.endswith(_DISCOVERY_SUFFIX):
        return discovery_url[: -len(_DISCOVERY_SUFFIX)]
    return discovery_url


def resource_url(scope: Scope, *, config: Config | None) -> str:
    """Return the canonical resource URL for this mesa-mcp deployment.

    Prefers ``ServerConfig.public_base_url`` when set; otherwise rebuilds
    from the inbound request's host + scheme. nginx supplies
    ``X-Forwarded-Proto`` so the scheme stays correct behind TLS
    termination.
    """
    if config is not None and config.server.public_base_url:
        return config.server.public_base_url.rstrip("/")

    headers = Headers(scope=scope)
    forwarded_proto = headers.get("x-forwarded-proto", "")
    scheme = (
        forwarded_proto.split(",", 1)[0].strip()
        if forwarded_proto
        else scope.get("scheme") or "https"
    )
    host = headers.get("host") or ""
    return f"{scheme}://{host}"


def metadata_url(scope: Scope, *, config: Config | None) -> str:
    """Return the absolute URL of the protected-resource metadata document."""
    return f"{resource_url(scope, config=config)}{PROTECTED_RESOURCE_METADATA_PATH}"


async def oauth_protected_resource_metadata(request: Request) -> JSONResponse:
    """Serve the RFC 9728 protected-resource metadata document."""
    config = current_config.get()
    authorization_servers: list[str] = []
    if config is not None and config.server.oidc_discovery_url:
        authorization_servers.append(
            issuer_from_discovery_url(config.server.oidc_discovery_url)
        )

    body: dict[str, object] = {
        "resource": resource_url(request.scope, config=config),
        "authorization_servers": authorization_servers,
        "bearer_methods_supported": ["header"],
        "scopes_supported": [],
    }
    # The document changes only on redeploy; let upstream caches hold it
    # for an hour. ``public`` is fine — the endpoint is unauthenticated.
    return JSONResponse(body, headers={"Cache-Control": "public, max-age=3600"})
