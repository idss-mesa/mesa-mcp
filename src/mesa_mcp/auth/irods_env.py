"""Native loader for the standard iRODS client config files.

iRODS clients (``iinit``, iCommands, python-irodsclient, etc.) ship their
credentials in two files under ``~/.irods/``:

* ``irods_environment.json`` — a JSON object with ``irods_user_name``,
  ``irods_zone_name``, ``irods_host``, ``irods_port``,
  ``irods_authentication_scheme``, and friends. Written by ``iinit``.
* ``.irodsA`` — the user's password, scrambled with iRODS's standard
  obfuscation. Also written by ``iinit``.

When mesa-mcp runs **locally** (Mode B) or **inside a CyVerse VICE pod**
(Mode C — JupyterLab, RStudio, Cloud Shell), those files already exist
because the user has authenticated to iRODS via ``iinit`` or the pod's
bootstrap script. This module lets mesa-mcp pick the credentials up
directly, so the operator doesn't have to copy fields into ``MESA_MCP_*``
environment variables.

The standard iRODS overrides apply: ``IRODS_ENVIRONMENT_FILE`` and
``IRODS_AUTHENTICATION_FILE`` env vars, if set, win over the default
``~/.irods/<name>`` location. This matches python-irodsclient and the
iCommands.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import ANONYMOUS_USER, AuthValue

DEFAULT_ENV_FILENAME = "irods_environment.json"
DEFAULT_PASSWORD_FILENAME = ".irodsA"

# Env-var names recognised by the iCommands and python-irodsclient.
ENV_FILE_OVERRIDE = "IRODS_ENVIRONMENT_FILE"
PASSWORD_FILE_OVERRIDE = "IRODS_AUTHENTICATION_FILE"


def _resolve_path(filename: str, override: Path | None, env_name: str) -> Path:
    """Pick the file path with the standard iRODS precedence chain.

    Precedence (highest first):

    1. The ``override`` argument, when not ``None`` (used by tests).
    2. The ``IRODS_ENVIRONMENT_FILE`` / ``IRODS_AUTHENTICATION_FILE``
       environment variables, matching the iCommands.
    3. ``~/.irods/<filename>``.
    """
    if override is not None:
        return override
    env_value = os.environ.get(env_name)
    if env_value:
        return Path(env_value).expanduser()
    return Path.home() / ".irods" / filename


def default_env_file() -> Path:
    """Return the default path to ``irods_environment.json``."""
    return _resolve_path(DEFAULT_ENV_FILENAME, None, ENV_FILE_OVERRIDE)


def default_password_file() -> Path:
    """Return the default path to ``.irodsA``."""
    return _resolve_path(DEFAULT_PASSWORD_FILENAME, None, PASSWORD_FILE_OVERRIDE)


def load_irods_environment(env_file: Path | None = None) -> dict[str, Any]:
    """Read and parse the iRODS environment JSON file.

    Returns the parsed mapping. Raises :class:`FileNotFoundError` if the
    file does not exist, and :class:`ValueError` if it does not contain a
    JSON object at the top level (e.g. corrupted, or someone wrote a list).
    """
    path = _resolve_path(DEFAULT_ENV_FILENAME, env_file, ENV_FILE_OVERRIDE)
    if not path.is_file():
        raise FileNotFoundError(f"iRODS environment file not found: {path}")
    with path.open("r", encoding="utf-8") as fp:
        data = json.load(fp)
    if not isinstance(data, dict):
        raise ValueError(
            f"iRODS environment file must contain a JSON object at the top level: {path}"
        )
    return data


def load_irods_password(password_file: Path | None = None) -> str | None:
    """Read and descramble the iRODS authentication file.

    Returns the plaintext password, or ``None`` if the file is missing —
    a common case for anonymous-only setups, or for callers that intend
    to supply the password via another channel.

    Uses :func:`irods.password_obfuscation.decode`, which understands
    both legacy (UID-keyed) and modern obfuscation. python-irodsclient
    must be installed.
    """
    path = _resolve_path(
        DEFAULT_PASSWORD_FILENAME, password_file, PASSWORD_FILE_OVERRIDE
    )
    if not path.is_file():
        return None
    try:
        from irods.password_obfuscation import decode
    except ImportError as exc:  # pragma: no cover - python-irodsclient is a runtime dep
        raise RuntimeError(
            "python-irodsclient is required to decode .irodsA; install it "
            "or fall back to MESA_MCP_IRODS_PASSWORD."
        ) from exc

    with path.open("r", encoding="utf-8") as fp:
        scrambled = fp.read().strip()
    if not scrambled:
        return None
    return decode(scrambled)


def extract_from_irods_env_file(
    env_file: Path | None = None,
    password_file: Path | None = None,
    *,
    zone_override: str | None = None,
    require_password: bool = False,
) -> AuthValue:
    """Build an :class:`AuthValue` from the standard iRODS client config.

    Reads:

    * ``~/.irods/irods_environment.json`` (or ``$IRODS_ENVIRONMENT_FILE``)
      for username, zone, and auth scheme.
    * ``~/.irods/.irodsA`` (or ``$IRODS_AUTHENTICATION_FILE``) for the
      scrambled password. Optional unless ``require_password=True``;
      anonymous-mode setups have no password file.

    Parameters
    ----------
    env_file:
        Override the environment file path. Useful in tests.
    password_file:
        Override the password file path. Useful in tests.
    zone_override:
        Force a specific zone name. Defaults to the value from the env
        file, falling back to ``"iplant"`` when the env file is silent.
    require_password:
        When ``True``, raise :class:`FileNotFoundError` if the password
        file is missing for a non-anonymous user. Defaults to ``False``
        so callers can chain this with env-var fallback.

    Raises
    ------
    FileNotFoundError
        The environment file is missing, or ``require_password`` is set
        and the password file is missing for a non-anonymous user.
    ValueError
        The environment file is not a JSON object.
    """
    env_data = load_irods_environment(env_file)

    username = (env_data.get("irods_user_name") or "").strip() or ANONYMOUS_USER
    zone = (
        zone_override
        or (env_data.get("irods_zone_name") or "").strip()
        or "iplant"
    )
    raw_scheme = (env_data.get("irods_authentication_scheme") or "").strip().lower()

    scheme: str
    if username == ANONYMOUS_USER:
        scheme = "anonymous"
    elif raw_scheme == "pam":
        scheme = "pam"
    elif raw_scheme in {"native", "", "password"}:
        scheme = "native"
    else:
        # Unknown scheme — fall back to native and let the server complain
        # if it really is invalid. Don't reject at the extractor.
        scheme = "native"

    password: str | None
    if scheme == "anonymous":
        password = None
    else:
        password = load_irods_password(password_file)
        if password is None and require_password:
            path = _resolve_path(
                DEFAULT_PASSWORD_FILENAME, password_file, PASSWORD_FILE_OVERRIDE
            )
            raise FileNotFoundError(
                f"iRODS password file not found: {path}. Run `iinit` to create it, "
                "or set MESA_MCP_IRODS_PASSWORD."
            )

    proxy_user = (env_data.get("irods_proxy_user") or "").strip() or None

    return AuthValue(
        username=username,
        zone=zone,
        password=password,
        auth_scheme=scheme,  # type: ignore[arg-type]
        proxy_user=proxy_user,
    )
