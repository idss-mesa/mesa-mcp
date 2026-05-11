"""Configuration model and loader for mesa-mcp.

Precedence (highest wins): explicit CLI flag > environment variable > YAML
file > built-in default.

Environment variables use the ``MESA_MCP_`` prefix and a double-underscore
delimiter to descend into nested sections — e.g. ``MESA_MCP_IRODS__HOST``
maps to ``config.irods.host``.

This module deliberately does **not** validate connectivity. It validates
shape only; whether the iRODS host actually answers is the connection pool's
problem.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

Transport = Literal["stdio", "sse"]
LogLevel = Literal["debug", "info", "warning", "error", "critical"]

ENV_PREFIX = "MESA_MCP_"
ENV_DELIM = "__"


class IRODSConfig(BaseModel):
    """Connection settings for the CyVerse Data Store (iRODS)."""

    host: str = "data.cyverse.org"
    port: int = 1247
    zone: str = "iplant"
    user: str = "anonymous"
    password: str | None = None
    # Used by ds_* path-safety checks (see access.py).
    shared_dir_name: str = "shared"
    webdav_url: str = "https://data.cyverse.org/dav/"
    proxy_auth: bool = False


class OLSConfig(BaseModel):
    """EMBL-EBI Ontology Lookup Service settings."""

    base_url: str = "https://www.ebi.ac.uk/ols4/api"
    # Cache TTLs in seconds. Tuned for the OLS code ported from esiil-portal.
    ontology_cache_ttl: int = 3600
    term_cache_ttl: int = 600
    search_cache_ttl: int = 60
    request_timeout: float = 30.0


class DuckLakeConfig(BaseModel):
    """Postgres catalog / DuckDB compute settings for mesa-ducklake."""

    # Postgres DSN for the DuckLake catalog. Empty disables DuckLake mirroring;
    # AVU writes still succeed but are not recorded.
    catalog_dsn: str | None = None
    # iRODS sub-collection (per project) that holds the Parquet data files.
    data_collection: str = ".mesa/ducklake"


class ServerConfig(BaseModel):
    """Generic server settings (transport, OIDC, logging)."""

    transport: Transport = "stdio"
    bind_address: str = "127.0.0.1"
    bind_port: int = 8080

    # Optional CyVerse Keycloak OIDC settings — only required when serving
    # the HTTP/SSE transport.
    oidc_discovery_url: str | None = None
    oauth2_client_id: str | None = None
    oauth2_client_secret: str | None = None
    # Expected ``aud`` claim for inbound JWTs. When set, the OIDC middleware
    # rejects tokens whose audience does not match. When left ``None`` the
    # middleware skips audience validation (useful when the access token is
    # issued for a different client than the resource server's own ID).
    oidc_audience: str | None = None

    log_level: LogLevel = "info"


class Config(BaseModel):
    """Root configuration object passed around the mesa-mcp process."""

    irods: IRODSConfig = Field(default_factory=IRODSConfig)
    ols: OLSConfig = Field(default_factory=OLSConfig)
    ducklake: DuckLakeConfig = Field(default_factory=DuckLakeConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _coerce_scalar(raw: str) -> Any:
    """Best-effort string -> typed scalar coercion for env-var values."""
    lowered = raw.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", ""}:
        return None
    # Try int, then float, then leave as-is.
    try:
        if raw.isdigit() or (raw.startswith("-") and raw[1:].isdigit()):
            return int(raw)
    except (ValueError, AttributeError):
        pass
    try:
        return float(raw)
    except (ValueError, TypeError):
        return raw


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict where ``overlay`` keys (recursively) win over ``base``."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, dict)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dict. An empty file becomes ``{}``."""
    with path.open("r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")
    return data


def _load_env(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Collect ``MESA_MCP_*`` env vars into a nested dict mirroring ``Config``."""
    source = env if env is not None else os.environ
    out: dict[str, Any] = {}
    for key, raw in source.items():
        if not key.startswith(ENV_PREFIX):
            continue
        stripped = key[len(ENV_PREFIX) :]
        parts = [p.lower() for p in stripped.split(ENV_DELIM) if p]
        if not parts:
            continue
        cursor = out
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
            if not isinstance(cursor, dict):
                # Conflict — a previous env var staked out this key as a
                # scalar. Skip silently; explicit YAML/flags can fix it.
                cursor = {}
                break
        cursor[parts[-1]] = _coerce_scalar(raw)
    return out


def _flag_overrides_to_dict(flag_overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Translate flat CLI overrides into the nested config layout."""
    if not flag_overrides:
        return {}
    nested: dict[str, Any] = {"server": {}}
    if "transport" in flag_overrides:
        nested["server"]["transport"] = flag_overrides["transport"]
    if "log_level" in flag_overrides:
        nested["server"]["log_level"] = flag_overrides["log_level"]
    return nested


def load_config(
    path: Path | None = None,
    *,
    flag_overrides: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    """Load configuration with precedence flag > env > YAML > defaults.

    Parameters
    ----------
    path:
        Optional path to a YAML config file.
    flag_overrides:
        Optional flat mapping of CLI overrides (currently ``transport`` and
        ``log_level``).
    env:
        Optional override for the process environment, used by tests.
    """
    yaml_layer: dict[str, Any] = {}
    if path is not None:
        yaml_layer = _load_yaml(path)

    env_layer = _load_env(env)
    flag_layer = _flag_overrides_to_dict(flag_overrides)

    merged = _deep_merge(yaml_layer, env_layer)
    merged = _deep_merge(merged, flag_layer)

    return Config.model_validate(merged)
