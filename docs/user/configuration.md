# Configuration

What this page covers: every field that mesa-mcp reads from configuration,
including the YAML form, the environment-variable form, and the
command-line flags. mesa-mcp's loader lives in
[`src/mesa_mcp/config.py`](../../src/mesa_mcp/config.py).

## Precedence

Higher rows override lower rows:

| Source              | Example                                                      |
| ------------------- | ------------------------------------------------------------ |
| CLI flag            | `mesa-mcp --transport stdio --log-level debug`               |
| Environment         | `MESA_MCP_IRODS__HOST=data.cyverse.org`                      |
| YAML config file    | `irods.host: data.cyverse.org`                               |
| Built-in default    | `data.cyverse.org` (defined in `IRODSConfig.host`)           |

Only `--transport` and `--log-level` are exposed as CLI flags today;
everything else flows through env or YAML.

## Environment-variable form

The env-var prefix is `MESA_MCP_`, the section delimiter is double
underscore (`__`):

```
MESA_MCP_<SECTION>__<FIELD>=<value>
```

For example, `MESA_MCP_IRODS__HOST` populates `config.irods.host`. Scalars
are coerced: `true`/`false`/`yes`/`no`/`on`/`off` become booleans, numeric
strings become ints or floats, and `null`/`none`/empty becomes `None`. See
[`config.py::_coerce_scalar`](../../src/mesa_mcp/config.py) for the exact
rules.

A starter `.env.example` is checked in at the repo root.

## Field reference

The config tree has four top-level sections: `irods`, `ols`, `ducklake`,
`server`. All fields are Pydantic-validated; unknown fields are rejected by
the loader.

### `irods` — CyVerse Data Store

| Field             | Default                          | Description                                                                 |
| ----------------- | -------------------------------- | --------------------------------------------------------------------------- |
| `host`            | `data.cyverse.org`               | iRODS host (iCAT or load balancer).                                         |
| `port`            | `1247`                           | iRODS port.                                                                 |
| `zone`            | `iplant`                         | iRODS zone name.                                                            |
| `user`            | `anonymous`                      | iRODS username. `anonymous` is read-only public access.                     |
| `password`        | *(empty)*                        | Password / PAM secret. **Never commit a real value.**                       |
| `shared_dir_name` | `shared`                         | Used by path-allowlist checks (`/<zone>/home/shared`).                      |
| `webdav_url`      | `https://data.cyverse.org/dav/`  | Base URL of the CyVerse WebDAV gateway (used by URL-minting tools).         |
| `proxy_auth`      | `false`                          | Reserved for service-account proxy auth (planned).                          |

Env var examples:

```bash
MESA_MCP_IRODS__HOST=data.cyverse.org
MESA_MCP_IRODS__PORT=1247
MESA_MCP_IRODS__ZONE=iplant
MESA_MCP_IRODS__USER=alice
MESA_MCP_IRODS__PASSWORD=hunter2
```

The auth extractor in [`auth/extract.py`](../../src/mesa_mcp/auth/extract.py)
also honours single-underscore overrides (`MESA_MCP_IRODS_USER`,
`MESA_MCP_IRODS_PASSWORD`, `MESA_MCP_IRODS_AUTH_SCHEME`,
`MESA_MCP_IRODS_TICKET`, `MESA_MCP_IRODS_PROXY_USER`) for ergonomic CLI
sessions. These take precedence over the canonical double-underscore form
for the user/password fields.

### `ols` — EMBL-EBI Ontology Lookup Service

| Field                 | Default                                  | Description                                                |
| --------------------- | ---------------------------------------- | ---------------------------------------------------------- |
| `base_url`            | `https://www.ebi.ac.uk/ols4/api`         | OLS4 API base.                                             |
| `ontology_cache_ttl`  | `3600` seconds                           | Cache TTL for the ontology catalog.                        |
| `term_cache_ttl`      | `600` seconds                            | Cache TTL for per-term records.                            |
| `search_cache_ttl`    | `60` seconds                             | Cache TTL for search results.                              |
| `request_timeout`     | `30.0` seconds                           | Per-request timeout for OLS calls.                         |

The actual `OLSClient` in [`ols/client.py`](../../src/mesa_mcp/ols/client.py)
ships with longer hard-coded TTLs (24 h catalogs, 12 h child listings, 1 h
searches) ported verbatim from `esiil-portal`. These config fields are
honoured by the loader but the client does not currently read them; this is
a known gap. See [`docs/dev/ols-internals.md`](../dev/ols-internals.md) for
detail.

### `ducklake` — AVU history catalog

| Field             | Default            | Description                                                        |
| ----------------- | ------------------ | ------------------------------------------------------------------ |
| `catalog_dsn`     | *(empty)*          | Postgres DSN for the DuckLake catalog. Empty disables mirroring.   |
| `data_collection` | `.mesa/ducklake`   | Per-project iRODS subcollection for Parquet data files.            |

`mesa_ducklake_*` tools are planned; today the `DuckLakeClient` facade in
[`ducklake/client.py`](../../src/mesa_mcp/ducklake/client.py) is stubbed
and every method raises `NotImplementedError`.

### `server` — transport, OIDC, logging

| Field                 | Default                | Description                                                                                                |
| --------------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------- |
| `transport`           | `stdio`                | `stdio` (working) or `sse` (planned — raises `NotImplementedError` today).                                 |
| `bind_address`        | `127.0.0.1`            | Reserved for the SSE transport.                                                                            |
| `bind_port`           | `8080`                 | Reserved for the SSE transport.                                                                            |
| `oidc_discovery_url`  | *(empty)*              | CyVerse Keycloak discovery URL — required only once SSE lands.                                             |
| `oauth2_client_id`    | *(empty)*              | Keycloak client id.                                                                                        |

| `log_level`           | `info`                 | One of `debug`, `info`, `warning`, `error`, `critical`.                                                    |

## CLI flags

```text
mesa-mcp --help

Options:
  --config PATH                 Path to a YAML config file.
  --transport {stdio,sse}       Transport to bind (overrides config).
  --log-level {debug,info,warning,error,critical}
                                Logging verbosity (overrides config).
  --version                     Print version and exit.
```

## Secret handling

- Never commit `.env` or a `config.yaml` containing real credentials. The
  repo's `.gitignore` lists these defensively.
- Prefer the env-var path for secrets so they live in process memory and
  systemd/Docker secret stores rather than on disk.
- Logs scrub passwords by virtue of `AuthValue` marking `password`
  `repr=False` and not including the plaintext in any cache key. Hand-rolled
  log statements that interpolate the password are a bug — open an issue.

## See also

- [Getting started](./getting-started.md)
- [Tools reference](./tools-reference.md)
- [`../../config.yaml.example`](../../config.yaml.example)
- [`../../.env.example`](../../.env.example)
- [Deployment OIDC](../deploy/oidc.md) for Keycloak setup.
