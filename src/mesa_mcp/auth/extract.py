"""Transport-specific :class:`AuthValue` extractors.

Three extractors live here:

* :func:`extract_from_env` — used by the stdio transport. The values come from
  the already-loaded :class:`mesa_mcp.config.Config`, which itself respects
  the ``MESA_MCP_*`` environment variables.
* :func:`extract_from_headers` — HTTP/SSE transport JWT-claim trusted-decode
  helper. See :mod:`mesa_mcp.transport.oidc` for the verified path.
* :func:`resolve_credentials` — the chain stdio uses at server start:
  explicit env vars > ``~/.irods/irods_environment.json`` + ``.irodsA`` >
  anonymous fallback. This is what lets a VICE pod (or a local install
  where the user has already run ``iinit``) work without any
  ``MESA_MCP_*`` env vars.

Both extractor helpers return a frozen :class:`AuthValue`; callers should
never mutate the returned object.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from .models import ANONYMOUS_USER, AuthValue

if TYPE_CHECKING:
    from mesa_mcp.config import Config

logger = logging.getLogger(__name__)


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


def resolve_credentials(
    config: Config,
    *,
    env: Mapping[str, str] | None = None,
    irods_env_file: Path | None = None,
    irods_password_file: Path | None = None,
) -> AuthValue:
    """Pick the best available credentials for a stdio mesa-mcp process.

    Resolution order (highest wins):

    1. **Explicit ``MESA_MCP_*`` env vars or values already on the
       loaded ``Config``.** If the operator supplied a username here we
       honour it directly — they know what they want.
    2. **``~/.irods/irods_environment.json`` + ``~/.irods/.irodsA``.**
       Path overrides from ``IRODS_ENVIRONMENT_FILE`` /
       ``IRODS_AUTHENTICATION_FILE`` are respected. This is the path
       that makes Mode B (local install) and Mode C (CyVerse VICE app)
       work without any ``MESA_MCP_*`` boilerplate after ``iinit``.
    3. **Anonymous** — read-only access to the iRODS zone's public
       shared collections. Last-resort fallback.

    Parameters
    ----------
    config:
        Loaded :class:`Config`. Used for the default zone and as the
        fallback source for any field the env file is silent about.
    env:
        Optional environment mapping. Defaults to :data:`os.environ`.
        Useful in tests.
    irods_env_file, irods_password_file:
        Optional explicit paths to the iRODS config files. Useful in
        tests, or when the operator keeps iRODS config outside the
        default ``~/.irods/`` location.

    Returns
    -------
    A frozen :class:`AuthValue` ready to hand to the iRODS client pool.
    """
    from .irods_env import extract_from_irods_env_file, load_irods_environment

    source = env if env is not None else os.environ

    # Layer 1: explicit operator-supplied creds win.
    env_value = extract_from_env(config, env=source)
    operator_set_user = bool(
        _first_nonempty(source.get("MESA_MCP_IRODS_USER"))
        or (config.irods.user and config.irods.user != ANONYMOUS_USER)
    )
    operator_set_password = bool(
        _first_nonempty(source.get("MESA_MCP_IRODS_PASSWORD"))
        or config.irods.password
    )
    if operator_set_user and (operator_set_password or env_value.is_anonymous()):
        logger.debug(
            "resolve_credentials: using MESA_MCP_* / config-supplied credentials "
            "(user=%s, scheme=%s)",
            env_value.username,
            env_value.auth_scheme,
        )
        return env_value

    # Layer 2: ~/.irods/ files — only attempt if the env file actually exists,
    # so a missing file doesn't raise on hosts without iinit set up.
    try:
        env_data = load_irods_environment(irods_env_file)
    except FileNotFoundError:
        env_data = None

    if env_data is not None:
        try:
            file_value = extract_from_irods_env_file(
                env_file=irods_env_file,
                password_file=irods_password_file,
                zone_override=config.irods.zone or None,
            )
        except (FileNotFoundError, ValueError) as exc:
            logger.warning(
                "resolve_credentials: ignoring unreadable iRODS env file: %s",
                exc,
            )
        else:
            logger.debug(
                "resolve_credentials: using iRODS env file (user=%s, zone=%s, "
                "scheme=%s)",
                file_value.username,
                file_value.zone,
                file_value.auth_scheme,
            )
            return file_value

    # Layer 3: anonymous fallback. Useful for tools that only browse the
    # public shared zone (e.g. mesa_ols_* read paths that never touch
    # iRODS at all).
    logger.info(
        "resolve_credentials: no MESA_MCP_* env vars, no iRODS env file — "
        "falling back to anonymous access."
    )
    return env_value


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
