---
type: Reference
title: Configuration
description: Every mesa-mcp setting (irods, ols, ducklake, server) with its YAML key, MESA_MCP_* environment variable and default, the flag > env > YAML > default precedence, and how iRODS credentials are resolved.
tags:
  - configuration
  - credentials
  - environment-variables
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: config
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/config.py"
    title: "mesa-mcp config model and loader"
    author: "team:idss-mesa"
  - id: extract
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/auth/extract.py"
    title: "Credential resolution (resolve_credentials)"
    author: "team:idss-mesa"
  - id: irods-env
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/auth/irods_env.py"
    title: "~/.irods/irods_environment.json and .irodsA loader"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# Configuration

What this page covers: every field mesa-mcp reads from configuration, in
its YAML form, its environment-variable form and as command-line flags,
and how the server finds iRODS credentials. The loader lives in
[`src/mesa_mcp/config.py`](https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/config.py).

## Precedence

Higher rows override lower rows:

| Source              | Example                                                      |
| ------------------- | ------------------------------------------------------------ |
| CLI flag            | `mesa-mcp --transport stdio --log-level debug`               |
| Environment         | `MESA_MCP_IRODS__HOST=data.cyverse.org`                      |
| YAML config file    | `irods.host: data.cyverse.org` in the file given to `--config` |
| Built-in default    | `data.cyverse.org` (defined in `IRODSConfig.host`)           |

Only `--transport` and `--log-level` exist as CLI flags; everything else
comes from the environment or YAML. The entry point resolves the config
once and records it as the process-wide active config, so lazily built
clients (the DuckLake and OLS clients) see the same values, including the
YAML file.

## Environment-variable form

The prefix is `MESA_MCP_` and the section delimiter is a double
underscore:

```
MESA_MCP_<SECTION>__<FIELD>=<value>
```

`MESA_MCP_IRODS__HOST` sets `irods.host`. Values are coerced:
`true`/`yes`/`on` and `false`/`no`/`off` become booleans, integer and
float strings become numbers, and `null`, `none` or an empty string
becomes `None`. See `_coerce_scalar` in `config.py`.

A starter `.env.example` and `config.yaml.example` are at the repository
root.

Keys that no field uses (a typo, or a removed setting) are **logged as a
warning and ignored**, from both YAML and the environment; they do not
stop the server.

## Field reference

The config has four sections: `irods`, `ols`, `ducklake`, `server`.

### `irods` — CyVerse Data Store

| Field             | Default                          | Description                                                                 |
| ----------------- | -------------------------------- | --------------------------------------------------------------------------- |
| `host`            | `data.cyverse.org`               | iRODS host.                                                                 |
| `port`            | `1247`                           | iRODS port.                                                                 |
| `zone`            | `iplant`                         | iRODS zone name.                                                            |
| `user`            | `anonymous`                      | iRODS username. `anonymous` is read-only public access.                     |
| `password`        | *(unset)*                        | Password. **Never commit a real value.**                                    |
| `shared_dir_name` | `shared`                         | Name of the shared tree used by path checks (`/<zone>/home/shared`).        |
| `webdav_url`      | `https://data.cyverse.org/dav/`  | Base URL of the CyVerse WebDAV gateway, used in download and upload hints.  |
| `proxy_auth`      | `false`                          | Declared but not read by any code today.                                    |

```bash
MESA_MCP_IRODS__HOST=data.cyverse.org
MESA_MCP_IRODS__ZONE=iplant
MESA_MCP_IRODS__USER=alice
MESA_MCP_IRODS__PASSWORD=...
```

### `ols` — EMBL-EBI Ontology Lookup Service

| Field                 | Default                                  | Description                                                |
| --------------------- | ---------------------------------------- | ---------------------------------------------------------- |
| `base_url`            | `https://www.ebi.ac.uk/ols4/api/v2`      | OLS4 v2 API base. Keep the `/v2`.                          |
| `ontology_cache_ttl`  | `3600` seconds                           | TTL for the ontology catalog and per-ontology caches.      |
| `term_cache_ttl`      | `600` seconds                            | TTL for per-term records.                                  |
| `search_cache_ttl`    | `60` seconds                             | TTL for search and descendants-of search results.          |
| `request_timeout`     | `30.0` seconds                           | Per-request timeout for OLS calls.                         |

The OLS client reads these values. Child listings (12 hours) and
generated templates (24 hours) have fixed TTLs. See
[OLS internals](../dev/ols-internals.md).

### `ducklake` — AVU history catalog

| Field             | Default            | Description                                                        |
| ----------------- | ------------------ | ------------------------------------------------------------------ |
| `catalog_dsn`     | *(unset)*          | DSN of the mesa-ducklake catalog. Unset disables history mirroring. |
| `data_collection` | `.mesa/ducklake`   | Per-project iRODS sub-collection for the Parquet history files.     |
| `cache_dir`       | *(unset)*          | Local Parquet cache. Unset means mesa-ducklake's default (`platformdirs.user_cache_dir("mesa-ducklake")`). |
| `cache_cap_bytes` | `1073741824` (1 GiB) | Soft cap on the cache; oldest files are evicted after each mirror. `0` disables eviction. |

The history needs the `ducklake` extra (mesa-ducklake 0.2 or newer,
which requires DuckDB 2.0). mesa-ducklake picks the catalog backend from
the DSN:

| `catalog_dsn` | Backend |
| --- | --- |
| `postgresql://…` | Postgres. Hosted and multi-writer deployments. |
| `duckdb:///abs/path/catalog.duckdb` | DuckDB file. Local installs; one process at a time. Append `?storage_version=v1.5.0` so DuckDB 1.x can still open a newly created file. |
| `quack://host:port` | A DuckDB file served by `mesa-ducklake serve-catalog` (DuckDB 2.0 Quack, beta), shared by several writers. Set `MESA_DUCKLAKE_QUACK_TOKEN` to the server's token. |

See mesa-ducklake's `docs/deploy/quack-catalog.md` for running the Quack
server.

With `catalog_dsn` unset or the extra missing, the AVU write tools
(`ds_add_avu`, `ds_delete_avu`, `mesa_avu_apply_term`, …) keep working and
skip the mirror, and the three `mesa_ducklake_*` tools
(`mesa_ducklake_init_project`, `mesa_ducklake_history`,
`mesa_ducklake_time_travel`) fail with `ducklake_disabled`. See
[DuckLake integration](../dev/ducklake-integration.md).

### `server` — transport, OIDC, plugins, logging

| Field                   | Default      | Description |
| ----------------------- | ------------ | ----------- |
| `transport`             | `stdio`      | `stdio`, or `sse` for the HTTP transport (old-style SSE at `/sse` plus Streamable HTTP at `/mcp`). |
| `bind_address`          | `127.0.0.1`  | HTTP bind address. |
| `bind_port`             | `8080`       | HTTP bind port. |
| `public_base_url`       | *(unset)*    | Canonical public URL, advertised in the RFC 9728 metadata at `/.well-known/oauth-protected-resource`. Set it in production. |
| `oidc_discovery_url`    | *(unset)*    | CyVerse Keycloak discovery URL. Empty lets every HTTP request through unauthenticated, for local development only. |
| `oidc_audience`         | *(unset)*    | Expected `aud` claim; falls back to `public_base_url`. |
| `oidc_require_audience` | `true`       | Require an audience-bound token. `false` re-opens token replay from other services and warns on every request. |
| `allowed_hosts`         | `[]`         | Host allow-list for Streamable HTTP (DNS-rebinding protection). Empty disables the check. |
| `allowed_origins`       | `[]`         | Origin allow-list for Streamable HTTP. |
| `oauth2_client_id`      | *(unset)*    | Unused; kept so old YAML still loads. |
| `strict_plugins`        | `false`      | Fail at startup when a `mesa_mcp.tools` plugin cannot be imported, instead of skipping it. |
| `log_level`             | `info`       | `debug`, `info`, `warning`, `error` or `critical`. |

`oauth2_client_secret` was removed; a config that still sets it gets the
unknown-key warning. See [HTTP / SSE transport](../deploy/http-sse.md)
and [OIDC](../deploy/oidc.md) for the HTTP settings in context.

## CLI flags

```text
mesa-mcp [--config PATH] [--transport {stdio,sse}]
         [--log-level {debug,info,warning,error,critical}] [--version]
```

## How credentials are resolved

For the stdio transport, mesa-mcp resolves one identity at startup, in
this order:

1. **Explicit settings.** `MESA_MCP_IRODS_USER` / `MESA_MCP_IRODS_PASSWORD`
   (single underscore), or `irods.user` / `irods.password` from the
   environment (`MESA_MCP_IRODS__USER`, double underscore) or YAML. These
   win when a non-anonymous user is set together with a password.
   `MESA_MCP_IRODS_AUTH_SCHEME` (`native` or `pam`),
   `MESA_MCP_IRODS_TICKET` and `MESA_MCP_IRODS_PROXY_USER` are read here
   too.
2. **The iRODS client files** written by `iinit`:
   `~/.irods/irods_environment.json` (user, zone, host, auth scheme) and
   `~/.irods/.irodsA` (the scrambled password). The `IRODS_ENVIRONMENT_FILE`
   and `IRODS_AUTHENTICATION_FILE` variables override those paths, as in
   the iCommands. This is what makes a local install after `iinit`, or a
   CyVerse VICE app, work with no `MESA_MCP_*` variables.
3. **Anonymous.** Access to the zone's shared tree only, which iRODS
   makes read-only. The ticket tools refuse anonymous callers outright.

For the HTTP transport, each request carries a CyVerse Keycloak bearer
JWT instead, verified against the realm's JWKS. See
[HTTP / SSE transport](../deploy/http-sse.md#auth-model).

## Secret handling

- Never commit `.env` or a `config.yaml` with real credentials. The
  repository's `.gitignore` lists them.
- Prefer environment variables, or a root-owned env file loaded by
  systemd, over a YAML file for secrets.
- `AuthValue` marks `password` as `repr=False`, and the session-pool
  cache key is a SHA-256 digest, so the plaintext does not appear in logs,
  reprs or pool keys. A log
  statement that prints a password is a bug.

## See also

- [Getting started](getting-started.md)
- [Local install](local-install.md) for the credential options step by
  step.
- [Tools reference](tools-reference.md)
- [`config.yaml.example`](https://github.com/idss-mesa/mesa-mcp/blob/main/config.yaml.example)
  and [`.env.example`](https://github.com/idss-mesa/mesa-mcp/blob/main/.env.example)
