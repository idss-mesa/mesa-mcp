---
type: Reference
title: Architecture
description: How the mesa-mcp process is put together, from the CLI entry point through config, the tool registry and plugins, the stdio and HTTP transports, authentication, the iRODS pool, OLS, DataCite and DuckLake subsystems, and the error contract.
tags:
  - architecture
  - mcp
  - python
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: server
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/server.py"
    title: "mesa-mcp server bootstrap, registry and SDK adapter"
    author: "team:idss-mesa"
  - id: claude-md
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/CLAUDE.md"
    title: "mesa-mcp project guide (goals and resolved decisions)"
    author: "team:idss-mesa"
  - id: pyproject
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/pyproject.toml"
    title: "mesa-mcp dependencies and extras"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# Architecture

What this page covers: how mesa-mcp is structured at runtime, from the
CLI entry point to tool dispatch, and the subsystems behind the tools. For
goals and recorded design decisions, read
[CLAUDE.md](https://github.com/idss-mesa/mesa-mcp/blob/main/CLAUDE.md).

## Process layout

```
mesa-mcp (console script -> mesa_mcp.__main__:main)
  │
  ├─ __main__.py   argparse: --config, --transport, --log-level, --version
  ├─ config.py     load_config(): flag > env > YAML > defaults; set_active_config()
  ├─ logging.py    structlog setup
  └─ server.py     run(config) -> MesaServer(config).serve(transport)
                     │  __post_init__: load_plugins(), snapshot the tool registry
                     ├─ stdio: resolve_credentials() once, bind contextvars,
                     │         mcp.server.Server over stdio
                     └─ sse:   Starlette app under uvicorn (transport/sse.py)
                               /sse + /messages/ (old SSE), /mcp (Streamable HTTP),
                               /healthz, /.well-known/oauth-protected-resource
```

The server targets the **MCP 2026-07-28** specification through the `mcp`
Python SDK 2.x (`mcp>=2.0,<3`). Registration uses SDK 2.x constructor
callbacks (`on_list_tools`, `on_call_tool`); the 1.x decorator API is not
used.

## Package map

| Package / module | Role |
| --- | --- |
| `server.py` | Tool registry (`register_tool`, `ToolSpec`), plugin loader, `_invoke_handler`, `MesaServer`, `ds_ping`. |
| `config.py` | Pydantic config model (`irods`, `ols`, `ducklake`, `server`) and loader. |
| `context.py` | Contextvars for the current `AuthValue`, config, client pool and ticket; session-ticket binding. |
| `errors.py` | `ToolError` (structured failure) and `InputRequired` (multi-round-trip question). |
| `auth/` | `AuthValue` model, credential resolution (`extract.py`, `irods_env.py`), `iRODSAccount` building, Keycloak claims. |
| `transport/` | HTTP app (`sse.py`), Streamable HTTP manager, OIDC verifier, `/healthz`, RFC 9728 metadata. |
| `irods/` | Session pool, path checks (`access.py`), AVU/ticket/rule/policy helpers, WebDAV URL minting, and `tools/` (one module per `ds_*` tool). |
| `ols/` | `OLSClient` (ported from esiil-portal), AVU transforms, and `tools/` (`mesa_ols_*`, `mesa_avu_from_term`, `mesa_avu_apply_term`, `mesa_policy_*`). |
| `datacite/` | DataCite 4.x schema, AVU transform, XML/JSON export, and `tools/`. |
| `ducklake/` | Facade over mesa-ducklake (`client.py`) and `tools/` (`mesa_ducklake_*`). |

## Tool registry

Each tool module decorates an async handler with `@register_tool(name,
description, input_model=..., output_model=..., meta=...)`, which stores a
`ToolSpec` in the module-level `_REGISTRY` dict. A duplicate name raises
`ValueError` at import time.

Registration happens by import side effect. At the bottom of `server.py`,
`mesa_mcp.datacite.tools`, `mesa_mcp.ols`, `mesa_mcp.ducklake.tools` and
`mesa_mcp.irods.tools` are imported. Each `tools/__init__.py` walks its
directory with `pkgutil.iter_modules` and imports every module whose name
does not start with `_`. Importing `mesa_mcp.server` therefore registers
all 52 built-in tools.

Third-party packages add tools through the **`mesa_mcp.tools` entry-point
group**. `MesaServer.__post_init__` calls `load_plugins()`, which imports
each entry point once. A plugin that fails to import is skipped with a
warning unless `server.strict_plugins` is true. A plugin can set its own
surface family with `meta={"io.mesa/surface": "<family>"}`.

`MesaServer._tool_definitions()` turns each `ToolSpec` into an MCP `Tool`:
the input model's JSON Schema with an explicit `$schema` of JSON Schema
2020-12, an `outputSchema` when `output_model` is set (only `ds_ping`
today), and `_meta["io.mesa/surface"]` (`irods`, `ontology`, `datacite`,
`history`, `policy`, `croissant`, or the plugin's own). `tools/list` is
served with a 5-minute public cache hint.

## Dispatch

1. The SDK's `on_call_tool` callback calls `MesaServer.call(name,
   arguments)`.
2. `_invoke_handler` validates the arguments against `input_model`
   (failure becomes `ToolError(code="invalid_argument")`).
3. Handlers that declare an `auth_value` keyword get the current caller's
   `AuthValue` from the contextvar. Handlers that declare `elicited` get
   the user's answer on a multi-round-trip follow-up.
4. The handler's `dict` result is returned as `structuredContent` and as
   one JSON text block. A non-dict result is an `internal_error`.
5. A `ToolError` becomes `{"error": {code, message, details}}` with
   `isError: true`. An `InputRequired` becomes an MCP `InputRequiredResult`
   carrying a form schema and a base64 `requestState` (at most 16 KiB),
   which the client returns on the follow-up. `mesa_avu_apply_term` uses
   this to ask the user to choose an ontology term.

## Transports

**stdio** (default). One user per process. `resolve_credentials()` picks
the identity once at startup (explicit settings, then `~/.irods`, then
anonymous; see [Configuration](../user/configuration.md#how-credentials-are-resolved)),
binds it into the contextvars, and runs the SDK loop. Clients on either
the legacy handshake or the 2026-07-28 per-request era work.

**HTTP** (`--transport sse`). A Starlette app under uvicorn, bound to
`server.bind_address:bind_port`:

- `GET /sse` and `POST /messages/`: the older SSE transport, used by
  `mcp-remote` bridges.
- `/mcp`: Streamable HTTP, used by claude.ai custom connectors.
- `GET /healthz`: unauthenticated liveness, `{"status": "ok", "version"}`.
- `GET /.well-known/oauth-protected-resource`: RFC 9728 metadata pointing
  at CyVerse Keycloak.

Every other route requires a CyVerse Keycloak bearer JWT, checked by
`OIDCAuthenticator` (signature against the realm JWKS, `exp`, `iss`, and
`aud` unless `oidc_require_audience` is false). With no
`oidc_discovery_url` set, requests are let through without authentication
for local development. Operator details are in
[HTTP / SSE transport](../deploy/http-sse.md) and [OIDC](../deploy/oidc.md).

## Authentication and path safety

- `AuthValue` (`auth/models.py`) is a frozen model of the caller:
  username, zone, password (`repr=False`), auth scheme (`native`, `pam`
  or `anonymous`), proxy user, ticket, home and shared paths.
- `accessible_paths()` returns the caller's home collection plus the
  shared tree; anonymous callers get only the shared tree. A ticket does
  not add a path today.
- `irods.access.assert_allowed(path, auth_value)` normalizes the path
  (collapses `//`, resolves `..`, strips a trailing slash) and raises
  `ToolError(code="forbidden")` for anything outside those paths. Every
  path-taking tool calls it before touching iRODS and uses the returned
  path.

## iRODS

`irods.client_pool.IRODSClientPool` keeps one `python-irodsclient`
`iRODSSession` per caller identity, keyed by `AuthValue.cache_key()` (a
SHA-256 digest), with LRU eviction at 32 entries. `ds_use_ticket` supplies
a ticket to the caller's pooled session and records it as a session
attribute, which is how `via_ticket` survives across calls. The `ds_*`
tools copy their names and input shapes from
[cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server);
see [Porting from Go](porting-from-go.md).

Some tools are limited by what `python-irodsclient` exposes:
`ds_list_policies` and `ds_get_policy_config` return a documented stub
with a `note`, `ds_get_rule_definition` usually returns no definition, and
`ds_list_rules` lists delayed rules only.

## OLS

`ols.client.OLSClient` wraps the public OLS4 API with seven in-process TTL
caches and two retries on 429/502/503/504. Tools get a process-wide
instance from `mesa_mcp.ols.get_default_client()`. `ols/transform.py`
holds the AVU transforms shared with esiil-portal. See
[OLS internals](ols-internals.md).

## DataCite

`datacite/schema.py` is the DataCite 4.x kernel as Pydantic models and
enums; `transform.py` converts records to and from `datacite.*` AVUs;
`export.py` writes kernel-4 XML and REST JSON. No network calls. See
[DataCite metadata](../user/datacite.md).

## DuckLake

`ducklake/client.py` is the only place mesa-mcp touches mesa-ducklake. It
builds one `DuckLakeClient` lazily from config and exposes
`record_avu_change` / `record_avu_changes`, which AVU-writing tools call
after a successful iRODS write. mesa-ducklake is the optional `ducklake`
extra; without it, or without `ducklake.catalog_dsn`, mirroring is a
no-op. See [DuckLake integration](ducklake-integration.md).

## Dependencies

From `pyproject.toml`:

| Package | Role |
| --- | --- |
| `mcp>=2.0,<3` | MCP SDK (2026-07-28 spec). |
| `python-irodsclient>=2.0` | iRODS client. |
| `pydantic>=2.6` | Config and tool input models. |
| `pyyaml` | YAML config. |
| `requests`, `cachetools` | OLS HTTP calls and TTL caches. |
| `structlog` | Logging. |
| `pyjwt[crypto]>=2.10`, `httpx>=0.28` | OIDC token verification, discovery and JWKS fetches. |
| `uvicorn>=0.30`, `starlette>=0.40` | HTTP transport. |

Extras: `ducklake` (`mesa-ducklake>=0.2`), `croissant`
(`mesa-croissant>=1.3`), and `dev` (`pytest`, `pytest-asyncio`,
`pytest-mock`, `ruff`, `mypy`, type stubs). Neither mesa-ducklake nor
mesa-croissant is on PyPI.

## Error contract

Handlers raise `ToolError(code, message, details)` for anything a client
should see. Python tracebacks never reach the client. Codes are short and
stable (`invalid_argument`, `forbidden`, `not_found`, `irods_error`,
`upstream_error`, `ducklake_disabled`, and per-tool codes such as
`init_project_failed_root_missing`). An AVU write whose history mirror
fails still succeeds and reports `partial_failure`.

## See also

- [DuckLake integration](ducklake-integration.md)
- [Adding tools](adding-tools.md)
- [Testing](testing.md)
- [Porting from Go](porting-from-go.md)
- [OLS internals](ols-internals.md)
