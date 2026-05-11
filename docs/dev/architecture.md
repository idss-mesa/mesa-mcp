# Architecture

What this page covers: how mesa-mcp's process is structured at runtime —
from CLI entry point to tool dispatch — and the moving parts each
subsystem is built around. This is a developer-oriented overview; for the
goals and rationale, read [`../../CLAUDE.md`](../../CLAUDE.md).

## Process layout

```
┌─────────────────────────────────────────────────────────────┐
│  mesa-mcp                                                   │
│                                                             │
│   __main__.py    argparse, --config / --transport / --log-* │
│        │                                                    │
│        ▼                                                    │
│   config.py      flag > env > YAML > defaults               │
│        │         (Pydantic Config model)                    │
│        ▼                                                    │
│   logging.py     structlog setup                            │
│        │                                                    │
│        ▼                                                    │
│   server.py      MesaServer(config) + registered tool table │
│        │                                                    │
│        ▼                                                    │
│   transport      stdio (shipping) | sse (planned)           │
│        │                                                    │
│        ▼                                                    │
│   MCP wire       list_tools / call_tool over MCP            │
└─────────────────────────────────────────────────────────────┘
```

Side-effect imports populate the tool registry before the server runs:

```text
mesa_mcp.server         registers ds_ping inline
        │
        └─ imports mesa_mcp.ols
                          └─ imports mesa_mcp.ols.tools (auto-discovery)
                                        ├─ list_ontologies.py
                                        ├─ search_terms.py
                                        ├─ get_ontology.py
                                        ├─ get_term.py
                                        ├─ get_term_hierarchy.py
                                        ├─ generate_template.py
                                        └─ avu_from_term.py
```

Each tool module decorates its handler with `@register_tool`, which
appends a `ToolSpec` to a module-level `_REGISTRY` dict in
[`server.py`](../../src/mesa_mcp/server.py). When `MesaServer` is
constructed, it snapshots the registry into `self.tools`, then
`_build_mcp_server` translates each `ToolSpec` into an MCP SDK `Tool`
record. The handler stays a plain async function — the SDK-specific
wrapping happens at the boundary.

## Subsystems

### Configuration — `mesa_mcp.config`

A Pydantic-validated tree with four sections: `irods`, `ols`,
`ducklake`, `server`. The loader merges YAML, env, and CLI overrides in
that order (CLI wins) via `_deep_merge`. Scalar coercion lets env vars
say `MESA_MCP_IRODS__PORT=1247` and get a real `int` out the other side.

See [`docs/user/configuration.md`](../user/configuration.md) for the full
field reference.

### Tool registry — `mesa_mcp.server`

The registry is intentionally MCP-SDK-agnostic. A `ToolSpec` carries:

- `name` — the wire-visible tool name (`ds_ping`, `mesa_ols_search_terms`).
- `description` — what surfaces to the agent.
- `handler` — an async callable taking the Pydantic-validated input model
  (or no args).
- `input_model` — optional Pydantic class for schema + validation.

`register_tool` is idempotent-protective: a duplicate name raises
`ValueError` at import time. Tests can call `clear_registry()` to wipe
state between runs.

### Transport — stdio shipping, SSE planned

`MesaServer.serve(transport)` dispatches to `_serve_stdio` or
`_serve_sse`. The stdio path imports `mcp.server.stdio.stdio_server`
lazily, wires the SDK's `list_tools` / `call_tool` callbacks against the
registry, and runs until the streams close.

`_serve_sse` is a stub today. It raises `NotImplementedError`. The SSE
transport will land alongside the OIDC PR — see
[`../deploy/http-sse.md`](../deploy/http-sse.md).

### Authentication — `mesa_mcp.auth`

The auth package mirrors `irods-mcp-server/common/auth.go`:

- `AuthValue` (`auth/models.py`) — frozen Pydantic model describing the
  caller. Carries username, zone, password (`repr=False`), auth scheme,
  proxy user, ticket, home/shared path. `accessible_paths()` and
  `cache_key()` are the read APIs.
- `extract_from_env` (`auth/extract.py`) — builds an `AuthValue` from
  the loaded config plus optional `MESA_MCP_IRODS_*` env overrides
  (single-underscore form for ergonomic CLI use).
- `extract_from_headers` — placeholder for the OIDC PR.
  `NotImplementedError` today.
- `build_account` (`auth/irods_auth.py`) — translates an `AuthValue`
  into a `python-irodsclient` `iRODSAccount`.

### iRODS — `mesa_mcp.irods`

- `client_pool.IRODSClientPool` — LRU cache of `iRODSSession` objects,
  keyed by `AuthValue.cache_key()`. Thread-locked around the cache map;
  individual sessions are owned by their callers. Default cap is 32
  entries.
- `access.assert_allowed` — path-allowlist enforcement. Normalises the
  path (collapses `//`, resolves `..`, strips trailing slash) and rejects
  anything outside the caller's `accessible_paths()`.
- `tools/` — directory where individual `ds_*` tool modules will live.
  Currently only an `__init__.py`; tools are being landed by the
  `irods-tool-porter` sub-agent.

### OLS — `mesa_mcp.ols`

- `client.OLSClient` — HTTP wrapper over the public OLS4 API. Ported
  from `esiil-portal/portal/services/ols_client.py`; Django `cache`
  replaced with `cachetools.TTLCache`. The portal's TTLs are preserved
  (24 h catalogs and terms, 12 h child listings, 1 h searches).
- `transform.py` — pure AVU ↔ annotation transforms; ported verbatim
  from `ols_transform.py`. The contract is sealed: AVU
  `attribute=<ontology>.<snake_case_label>`, `unit=<CURIE>`.
- `tools/` — auto-discovered tool modules. `__init__.py` iterates
  `pkgutil.iter_modules` so a new tool file in this directory registers
  on package import.

See [`./ols-internals.md`](./ols-internals.md) for the cache layout and
the AVU contract in detail.

### DuckLake — `mesa_mcp.ducklake`

`DuckLakeClient` is a stub facade. Every method raises
`NotImplementedError`. The intent is that `mesa-ducklake` will publish
the real implementation as a sibling Python package; mesa-mcp imports
it through this narrow surface. See `CLAUDE.md` "DuckLake integration"
for design constraints.

## Dependency surface

From `pyproject.toml`:

| Package              | Role                                                 |
| -------------------- | ---------------------------------------------------- |
| `mcp>=1.0`           | MCP SDK — transport and wire format.                 |
| `python-irodsclient` | iRODS native protocol client (PRC).                  |
| `pydantic>=2.6`      | Config validation, tool input models.                |
| `pyyaml`             | YAML config loader.                                  |
| `requests`           | OLS HTTP calls.                                      |
| `cachetools`         | TTL caches inside `OLSClient`.                       |
| `structlog`          | Structured logging.                                  |

Dev extras add `pytest`, `pytest-asyncio`, `pytest-mock`, `ruff`,
`mypy`, and the typing stubs (`types-PyYAML`, `types-requests`).

## Error contract

Every tool handler should raise
[`ToolError`](../../src/mesa_mcp/errors.py) for user-visible failures.
The `_call_tool` boundary in `server.py` catches it and emits a JSON
payload with `{code, message, details}`. Python tracebacks never reach
the client.

Validation failures (Pydantic) are translated to
`ToolError(code="invalid_argument")` by `_invoke_handler`.

## See also

- [Adding tools](./adding-tools.md) — the `@register_tool` decorator
  walked through.
- [Porting from Go](./porting-from-go.md) — `irods-mcp-server` parity
  cookbook.
- [OLS internals](./ols-internals.md) — the OLS client and AVU
  transforms.
- [Testing](./testing.md)
- [Contributing](./contributing.md)
- [`../../CLAUDE.md`](../../CLAUDE.md) — design rationale.
