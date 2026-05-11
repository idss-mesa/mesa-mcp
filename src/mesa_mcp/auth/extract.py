"""Transport-specific :class:`AuthValue` extractors.

Two extractors live here:

* :func:`extract_from_env` — used by the stdio transport. The values come from
  the already-loaded :class:`mesa_mcp.config.Config`, which itself respects
  the ``MESA_MCP_*`` environment variables. This is the *only* path wired up
  today.
* :func:`extract_from_headers` — placeholder for the HTTP/SSE transport that
  arrives with the OIDC PR. The signature is stable so handler code can
  reference it; the body raises :class:`NotImplementedError` until then.

Both functions return a frozen :class:`AuthValue`; callers should never mutate
the returned object.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from .models import ANONYMOUS_USER, AuthValue

if TYPE_CHECKING:
    from mesa_mcp.config import Config


def _first_nonempty(*candidates: str | None) -> str | None:
    """Return the first non-empty candidate, or ``None`` if all are empty."""
    for c in candidates:
        if c:
            return c
    return None


def extract_from_env(
    config: Config,
    *,
    env: Mapping[str, str] | None = None,
) -> AuthValue:
    """Build an :class:`AuthValue` from the stdio environment + config.

    Precedence (highest wins):

    1. Explicit ``MESA_MCP_IRODS_USER`` / ``MESA_MCP_IRODS_PASSWORD`` env vars
       (the single-underscore form documented in the task spec).
    2. Values already loaded into ``config.irods.*`` (which itself picks up
       the canonical double-underscore ``MESA_MCP_IRODS__USER`` form).
    3. The literal default ``"anonymous"`` for the user.

    The ``zone`` always comes from ``config.irods.zone`` — there's no env-only
    override path for it because mesa-mcp doesn't ship a zone-discovery flow.
    """
    source = env if env is not None else os.environ

    env_user = _first_nonempty(source.get("MESA_MCP_IRODS_USER"))
    env_password = _first_nonempty(source.get("MESA_MCP_IRODS_PASSWORD"))
    env_scheme = _first_nonempty(source.get("MESA_MCP_IRODS_AUTH_SCHEME"))
    env_ticket = _first_nonempty(source.get("MESA_MCP_IRODS_TICKET"))
    env_proxy = _first_nonempty(source.get("MESA_MCP_IRODS_PROXY_USER"))

    username = env_user or config.irods.user or ANONYMOUS_USER
    password = env_password if env_password is not None else config.irods.password

    scheme: str
    if username == ANONYMOUS_USER and not password:
        scheme = "anonymous"
    elif env_scheme:
        scheme = env_scheme.lower()
    else:
        scheme = "native"

    if scheme not in {"native", "pam", "anonymous"}:
        # Unknown scheme — fall back to native and let the iRODS server
        # reject the connection if it really is invalid. We don't want the
        # extractor itself to throw here, because the stdio process is
        # already running by the time anyone reads creds.
        scheme = "native"

    return AuthValue(
        username=username,
        zone=config.irods.zone,
        password=password if scheme != "anonymous" else None,
        auth_scheme=scheme,  # type: ignore[arg-type]
        proxy_user=env_proxy,
        ticket=env_ticket,
    )


def extract_from_headers(
    headers: Mapping[str, str],
    config: Config,
) -> AuthValue:
    """Build an :class:`AuthValue` from HTTP request headers.

    This is the **trusted-decode** path: callers MUST have already verified
    the JWT signature, expiry, issuer, and audience. The
    :class:`mesa_mcp.transport.oidc.OIDCAuthenticator` is the production
    verifier; this helper exists so non-OIDC paths (e.g. an internal
    development proxy that has already authenticated upstream) can still
    materialize an :class:`AuthValue` from headers in one place.

    Supported header shapes:

    * ``Authorization: Bearer <jwt>`` — decoded *without* signature
      verification because that's the verifier's job. The ``preferred_username``
      claim (fallback ``sub``) becomes :attr:`AuthValue.username`. The zone
      comes from ``config.irods.zone``; password is ``None``;
      ``auth_scheme`` is ``"native"``.
    * Missing or non-Bearer header → :class:`ValueError`. The middleware
      will translate that into a 401.

    The shape is final: ``headers`` first (so middleware can adapt MCP-SDK
    header containers cheaply), ``config`` second (for zone defaults).
    """
    import jwt as _jwt  # local import keeps stdio-only installs PyJWT-free

    from .models import AuthValue

    auth_header: str | None = None
    for k, v in headers.items():
        if k.lower() == "authorization":
            auth_header = v
            break

    if not auth_header:
        raise ValueError("missing Authorization header")
    parts = auth_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise ValueError("Authorization header must be 'Bearer <token>'")
    token = parts[1].strip()

    try:
        claims = _jwt.decode(token, options={"verify_signature": False})
    except _jwt.InvalidTokenError as exc:
        raise ValueError(f"could not decode JWT: {exc}") from exc

    username = claims.get("preferred_username") or claims.get("sub")
    if not username:
        raise ValueError("JWT has neither preferred_username nor sub claim")
    if "@" in username:
        username = username.split("@", 1)[0]

    return AuthValue(
        username=username,
        zone=config.irods.zone,
        password=None,
        auth_scheme="native",
    )
