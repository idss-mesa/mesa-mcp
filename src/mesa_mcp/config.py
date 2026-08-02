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

import logging
import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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

    # NOTE the ``/v2``. Every endpoint is built by appending to this value,
    # and the OLS4 v1 API does not serve them. This default was previously
    # ``.../ols4/api`` — harmless only because nothing read the field; the
    # moment it was honoured, that value broke every OLS call.
    base_url: str = "https://www.ebi.ac.uk/ols4/api/v2"
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
    #
    # NOT IMPLEMENTED. Nothing in mesa-mcp or mesa-ducklake reads this, so
    # setting it has no effect and the layout is whatever mesa-ducklake
    # chooses. Retained because the field is part of the documented config
    # surface and removing it would silently ignore an operator's YAML;
    # wire it through mesa_ducklake before treating it as live.
    data_collection: str = ".mesa/ducklake"
    # Local Parquet cache directory. mesa-ducklake materializes each
    # snapshot's Parquet here before pushing to iRODS; reads pull
    # missing files from iRODS back into this cache. When unset,
    # mesa-ducklake falls back to ``platformdirs.user_cache_dir
    # ("mesa-ducklake")`` — honors ``XDG_CACHE_HOME`` on Linux and
    # systemd ``CacheDirectory=`` semantics.
    cache_dir: str | None = None
    # Soft cap on total bytes held in ``cache_dir``. After every
    # successful AVU mirror, files are evicted oldest-first until the
    # cap is met. ``0`` disables eviction (unbounded). Default 1 GiB.
    cache_cap_bytes: int = 1 << 30


class ServerConfig(BaseModel):
    """Generic server settings (transport, OIDC, logging)."""

    transport: Transport = "stdio"
    bind_address: str = "127.0.0.1"
    bind_port: int = 8080

    # Canonical public base URL of this MCP server (no trailing slash) —
    # e.g. ``https://mesa-mcp.cis240692.projects.jetstream-cloud.org``.
    # Advertised as the ``resource`` field in the RFC 9728 protected-
    # resource metadata document at ``/.well-known/oauth-protected-
    # resource``, and used to build the ``resource_metadata`` URL in the
    # ``WWW-Authenticate`` header on 401 responses. When unset, the
    # metadata endpoint reconstructs the value from the inbound request's
    # ``Host``/``X-Forwarded-Proto`` headers — fine for local development
    # but should be set explicitly in production so the value is stable
    # against header spoofing on the loopback bind.
    public_base_url: str | None = None

    # Optional CyVerse Keycloak OIDC settings — only required when serving
    # the HTTP/SSE transport.
    oidc_discovery_url: str | None = None
    # UNUSED. mesa-mcp is an OAuth *resource server*: it validates inbound
    # JWTs and never runs the authorization-code flow, so it needs no
    # client credentials. Token validation binds on ``oidc_audience``.
    # Retained so an existing YAML keeps loading; a candidate for removal.
    oauth2_client_id: str | None = None
    # ``oauth2_client_secret`` was REMOVED. It was never read, and a
    # resource server has no use for one — setting it put a live secret
    # in a config file (and in the process environment) for no benefit,
    # widening the blast radius of a leaked deployment config. The
    # unknown-key warning in ``load_config`` makes the removal visible to
    # operators whose YAML still carries it.
    # Expected ``aud`` claim for inbound JWTs. When left ``None`` the
    # authenticator falls back to ``public_base_url`` — the canonical
    # resource identifier this server publishes in its RFC 9728
    # protected-resource metadata, which is what RFC 8707 resource
    # indicators bind a token to.
    oidc_audience: str | None = None

    # Enforce audience binding (MCP 2026-07-28 authorization hardening).
    #
    # When ``True`` (the default) a token must carry an ``aud`` claim
    # matching this resource, and the server refuses to start the HTTP
    # transport unless an audience can be resolved. This prevents the
    # confused-deputy case where a token minted for *another* CyVerse
    # service is replayed against mesa-mcp: without an audience check any
    # validly-signed realm token is accepted.
    #
    # Set ``False`` only for a legacy deployment that cannot yet issue
    # audience-bound tokens; it re-opens that replay path, so it warns
    # loudly on every request.
    oidc_require_audience: bool = True

    # Host/Origin allow-lists for the Streamable HTTP transport
    # (DNS-rebinding protection). Empty lists leave validation disabled,
    # which is correct behind a trusted reverse proxy that already
    # normalizes Host, but should be populated for a directly-exposed
    # deployment. ``public_base_url``'s host is added automatically.
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)

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

    _warn_unknown_keys(yaml_layer, source="config file")
    # The env layer needs the same check. Operators were previously told
    # to inject oauth2_client_secret as MESA_MCP_SERVER__OAUTH2_CLIENT_SECRET;
    # now that the field is gone, an unwarned env var would be dropped in
    # silence — exactly the failure this warning exists to prevent.
    _warn_unknown_keys(env_layer, source="environment")
    return Config.model_validate(merged)


def _warn_unknown_keys(
    yaml_layer: dict[str, Any], *, source: str = "config file"
) -> None:
    """Log a warning for keys no model field will consume.

    Pydantic's default is to ignore unknown keys, so a typo
    (``shared_dir`` for ``shared_dir_name``) or a setting removed in a
    later release is accepted in silence and the operator's intent is
    dropped. We warn rather than raise: failing to start over a stale key
    is worse than running with a documented default.
    """
    if not yaml_layer:
        return

    section_models = {
        "irods": IRODSConfig,
        "ols": OLSConfig,
        "ducklake": DuckLakeConfig,
        "server": ServerConfig,
    }
    for section, values in yaml_layer.items():
        model = section_models.get(section)
        if model is None:
            if section not in Config.model_fields:
                logger.warning(
                    "config: unknown section %r in %s ignored", section, source
                )
            continue
        if not isinstance(values, dict):
            continue
        unknown = sorted(set(values) - set(model.model_fields))
        for key in unknown:
            logger.warning(
                "config: unknown key %r in section %r from %s ignored "
                "(check spelling, or it may have been removed)",
                key,
                section,
                source,
            )


# ---------------------------------------------------------------------------
# Process-wide active config
# ---------------------------------------------------------------------------
# The entrypoint resolves config once with full precedence (flag > env > YAML)
# and records it here via set_active_config(). Lazily-initialized consumers
# (e.g. the DuckLake client) read it through get_active_config() so they see the
# SAME resolved config — including the --config YAML — instead of re-loading
# without the file path.
_active_config: Config | None = None


def set_active_config(config: Config | None) -> None:
    """Record (or clear) the process-wide resolved config. Called by the entrypoint."""
    global _active_config
    _active_config = config


def get_active_config() -> Config:
    """Return the active config set by the entrypoint.

    Falls back to ``load_config()`` (env vars + built-in defaults, no YAML) when
    no active config has been set — e.g. in unit tests or headless embedders that
    never went through the CLI entrypoint.
    """
    if _active_config is not None:
        return _active_config
    return load_config()
