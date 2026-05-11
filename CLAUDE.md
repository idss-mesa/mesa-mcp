# mesa-mcp — Project Guide for Claude Code

## What this project is

**mesa-mcp** is an MCP (Model Context Protocol) server that connects to the
**CyVerse Data Store** (iRODS) with user authentication and exposes both
standard data-store operations *and* a unique feature: **ontology-driven AVU
metadata creation** using the **OBO Foundry** + **EMBL-EBI Ontology Lookup
Service (OLS)**.

It is the MCP counterpart to the ontology-aware metadata UI already shipped in
`esiil-portal`. Where the portal lets humans browse ontologies in a browser and
tag iRODS files with AVUs, mesa-mcp lets an agent (Claude or another MCP
client) do the same thing programmatically.

A sibling project, **mesa-ducklake**, tracks the AVU history for every file
and folder in a MESA-enabled project using DuckDB's DuckLake (Postgres catalog
+ object-storage data files, time-travel enabled), with data files living in a
hidden `/.mesa/ducklake/` collection inside each project.

## Goals

1. **iRODS feature parity** with `cyverse/irods-mcp-server` — every data-store
   operation that server exposes, mesa-mcp also exposes (read/write/list/move/
   copy/delete files, AVU CRUD, ACL changes, ticket inspection, WebDAV URL
   minting, etc.).
2. **OBO/OLS Explorer as MCP tools** — port the ontology browsing and
   AVU-emission logic from `esiil-portal/portal/services/ols_client.py` and
   `ols_transform.py` into MCP tools so an agent can: list ontologies, search
   terms, walk a class hierarchy, and write the chosen term to an iRODS path
   as a structured AVU.
3. **DuckLake-backed metadata history** — every AVU change made through
   mesa-mcp is mirrored into the project's DuckLake (via `mesa-ducklake`) so
   the full metadata history of every file and folder is queryable and
   time-travelable.

## Reference repositories

All cloned as siblings under `/home/exouser/`. Read these before changing
mesa-mcp — patterns we borrow live there, not here.

| Repo | Language | Role for mesa-mcp |
|---|---|---|
| `cyverse/irods-mcp-server` | Go (go-irodsclient, mark3labs/mcp-go) | **Primary template** for tool surface, auth middleware, path-access checks, AVU/ticket/ACL handlers. Mesa-mcp is the Python port + ontology extension. |
| `cyverse/terrain-mcp` | TypeScript (~200 tools wrapping Terrain REST) | Reference for tool *granularity*, encrypted credential storage (AES-256-GCM in `~/.terrain-mcp/`), browser-OAuth flow. We do **not** wrap Terrain — we go native iRODS — but borrow the auth-persistence pattern. |
| `cyverse-de/formation-mcp` | Go (mcp-go) | Smaller, cleaner example of dual stdio/SSE transport, config-precedence (flag > env > YAML), markdown-formatted tool output, workflows layer for multi-step ops. |
| `cyverse/esiil-portal` | Django + Python | **Source of the OBO/OLS code we port.** See `portal/services/ols_client.py`, `portal/services/ols_transform.py`, `portal/services/irods_client.py`. Auth is CyVerse Keycloak (OIDC). |
| `cyverse/mesa-ducklake` | Python (DuckDB + Postgres + python-irodsclient) | Metadata catalog + history. Postgres catalog, DuckDB compute, Parquet files in `/.mesa/ducklake/` per project, AVU time-travel. Built out: `DuckLakeClient` API + iRODS sync sidecar (push-before-commit + WAL recovery) + `mesa-ducklake recover` CLI + daily `pg_dump`-to-iRODS backup. mesa-mcp is its main writer. |

## Language & runtime

**Python 3.11+.** Chosen because:

- The OBO/OLS code we're porting (`ols_client.py`, `ols_transform.py`) is
  pure Python with only `requests` + a cache backend as runtime deps.
- `python-irodsclient` (the official PRC) gives us native iRODS auth (native /
  PAM), AVU CRUD, ACLs, tickets, and streaming reads/writes — feature-for-
  feature with `go-irodsclient`.
- DuckLake has first-class Python bindings via DuckDB.
- The MCP Python SDK (`mcp` package, `modelcontextprotocol/python-sdk`) is
  mature and supports both `stdio` and HTTP/SSE transports.

## Tool surface

### Group 1 — iRODS data store (mirror `irods-mcp-server`)

Keep the existing `ds_*` prefix so existing MCP clients can swap servers
transparently:

- Directory/file: `ds_list_allowed_directories`, `ds_list_directory`,
  `ds_list_directory_details`, `ds_directory_tree`, `ds_search_files`,
  `ds_get_file_info`, `ds_read_file`, `ds_write_file`, `ds_upload_file`,
  `ds_download_file`, `ds_make_directory`, `ds_delete_file`, `ds_move_file`,
  `ds_copy_file`
- AVU metadata: `ds_list_avus`, `ds_add_avu`, `ds_delete_avu`,
  `ds_search_files_by_avu`, `ds_get_metadata`, `ds_search_metadata`
- Access control: `ds_modify_access`, `ds_modify_access_inheritance`
- Tickets (read-only, mirrors `irods-mcp-server`): `ds_list_tickets`,
  `ds_get_ticket_info`

For each: copy the JSON-schema shape from the Go source so input contracts
match byte-for-byte (the Go repo's `irods/*.go` files are the spec).

### Group 1b — iRODS tickets (full lifecycle, **new** vs `irods-mcp-server`)

`irods-mcp-server` only *inspects* tickets. mesa-mcp adds full lifecycle
so agents can mint and revoke them:

- `ds_create_ticket` — create read or write ticket on data object /
  collection. Inputs: `path`, `mode` (`read|write`), optional
  `uses_allowed`, `expiry`, `write_byte_limit`, `host_restriction`,
  `user_restriction`. Returns ticket string + metadata.
- `ds_modify_ticket` — update constraints (uses, expiry, host/user
  restrictions). Cannot change mode.
- `ds_delete_ticket` — revoke a ticket.
- `ds_use_ticket` — open a ticket-mediated session for subsequent
  read/write tool calls in the same MCP connection.

python-irodsclient provides `irods.ticket.Ticket` and supports
ticket-mediated sessions via `session.tickets`. Issuance must be done by
an authenticated user; revocation can be done by the issuer or an admin.

Every ticket creation/modification is recorded into the project's
DuckLake (when the path falls inside a MESA-enabled project), with the
ticket id appearing in the `via_ticket` provenance column. Subsequent
AVU writes performed *through* the ticket likewise record `via_ticket`
so an auditor can trace which changes were made via shared credentials.

### Group 1c — iRODS Rule Engine & Policy Composition (**new**)

CyVerse's iRODS server runs a Rule Engine (iRODS Rule Language and the
Python Rule Engine) and Policy Composition Framework. mesa-mcp exposes
client-side surface for both:

- `ds_execute_rule` — run a named rule or an inline iRL snippet against
  the connected server. Inputs: `rule_name` (xor `rule_text`),
  `input_parameters` (dict), `output_parameters` (list of names),
  `instance_name` (which rule engine instance, defaults to
  `irods_rule_engine_plugin-irods_rule_language-instance`). Returns the
  rule's `output_parameters` and any stdout/stderr.
- `ds_list_rules` — list named rules available on the server (read-only,
  scoped to what the user can introspect).
- `ds_get_rule_definition` — return the source of a named rule.
- `ds_list_policies` — list active policies in the Policy Composition
  Framework (e.g. data-replication policies, retention policies).
- `ds_get_policy_config` — read the configuration of a named policy.
- `mesa_policy_enable` / `mesa_policy_disable` — toggle *MESA-defined*
  policies (e.g. "auto-record AVU changes to DuckLake") on a specific
  project. These manipulate AVUs on the project root, not the iRODS
  server's global policy config.

Server-side rule installation/uninstallation is **not** exposed —
that's an iRODS admin operation and lives outside the MCP surface.

Rule execution flows through `python-irodsclient.rule.Rule`; the
input/output parameter conventions match `irule`. Path arguments in
rule input are still validated against the user's accessible paths.

### Group 2 — OBO/OLS Explorer (new, ported from esiil-portal)

- `mesa_ols_list_ontologies` — paginated catalog from EMBL-EBI OLS4
- `mesa_ols_get_ontology` — single ontology details (term count, version, URI)
- `mesa_ols_search_terms` — cross-ontology or scoped search, with
  `descendantsOf` filter for hierarchy walks
- `mesa_ols_get_term` — full term record (label, IRI, CURIE, synonyms,
  definition, parents/children)
- `mesa_ols_get_term_hierarchy` — children/ancestors of a term
- `mesa_ols_generate_template` — top-level terms of an ontology as a schema
  template (the function that drives the portal's auto-generated forms)
- `mesa_avu_from_term` — given an ontology term + a user-supplied value,
  produce the AVU triple `(attribute=<ontology>.<snake_case_label>,
  value=<value>, unit=<CURIE>)` — *the same shape esiil-portal writes*
- `mesa_avu_apply_term` — composite: pick a term, supply a value, write the
  AVU to a CyVerse path, and emit a DuckLake change record

### Group 3 — DuckLake integration (calls into `mesa-ducklake`)


- `mesa_ducklake_init_project` — create `/.mesa/ducklake/` collection in an
  iRODS project, bootstrap the Postgres catalog row(s) for it
- `mesa_ducklake_snapshot` — capture current AVU state for a path/subtree
- `mesa_ducklake_history` — list all AVU changes for a path, with timestamps
  and authors
- `mesa_ducklake_time_travel` — return the AVU set for a path *as of* a given
  timestamp or snapshot id
- `mesa_ducklake_diff` — diff AVU state between two snapshots

These tools are thin wrappers — the SQL and DuckLake schema live in
`mesa-ducklake`. mesa-mcp imports it (or calls it over a local socket — TBD).

## Architecture sketch

```
mesa-mcp/
├── src/mesa_mcp/
│   ├── __main__.py              # entrypoint, flag parsing, transport selection
│   ├── server.py                # MCP server bootstrap, tool registry, auth middleware
│   ├── config.py                # flag > env > YAML precedence
│   ├── auth/
│   │   ├── irods_auth.py        # native iRODS + PAM auth via python-irodsclient
│   │   ├── keycloak.py          # optional CyVerse OIDC for HTTP transport
│   │   └── credential_store.py  # AES-256-GCM encrypted on-disk store (terrain-mcp pattern)
│   ├── irods/
│   │   ├── client_pool.py       # connection pool keyed by account (irods-mcp-server pattern)
│   │   ├── tools/               # one file per ds_* tool, mirrors irods-mcp-server/irods/*.go
│   │   ├── tickets.py           # ticket lifecycle helpers (create/modify/delete/use)
│   │   ├── rules.py             # rule execution + introspection helpers
│   │   ├── policies.py          # Policy Composition Framework client + mesa policies
│   │   └── access.py            # path-allowlist enforcement
│   ├── ols/
│   │   ├── client.py            # ported from esiil-portal/portal/services/ols_client.py
│   │   ├── transform.py         # ported from ols_transform.py
│   │   └── tools/               # mesa_ols_*, mesa_avu_*
│   └── ducklake/
│       ├── client.py            # thin client into mesa-ducklake
│       └── tools/               # mesa_ducklake_*
├── tests/
├── config.yaml.example
├── pyproject.toml
└── README.md
```

## Conventions to follow

- **Tool names:** keep `ds_*` for the iRODS surface (matches existing server,
  drop-in replacement). Use `mesa_ols_*`, `mesa_avu_*`, `mesa_ducklake_*` for
  new tools so they're clearly attributable.
- **Input schemas:** use Pydantic models, emit JSON Schema via the MCP SDK.
- **Output:** structured JSON for machine-readable fields, plus a short
  human-readable text summary (formation-mcp pattern).
- **AVU shape:** always `(attribute, value, unit)` with unit reserved for the
  ontology CURIE when the AVU originated from OBO/OLS — this is the
  convention esiil-portal already writes, so portal-written and mesa-written
  AVUs are interchangeable.
- **Path safety:** every tool that takes a path must validate it against the
  authenticated user's accessible paths (home + shared + ticket-granted
  paths). See `irods-mcp-server/irods/common/` for the algorithm.
- **No silent fallbacks for auth.** If credentials are missing or expired,
  fail loud with a structured error the client can act on.

## Authentication

Two supported modes (start with the first; add the second when HTTP transport
is wired):

1. **Native iRODS** (stdio transport) — username + password (or PAM) supplied
   via env vars or `.irods/irods_environment.json`. Connection pooled per
   user. Mirror `irods-mcp-server`'s middleware.
2. **CyVerse Keycloak OIDC** (HTTP/SSE transport) — bearer token in
   `Authorization` header, exchanged for an iRODS proxy session. Follow the
   pattern in `irods-mcp-server/common/oauth.go` and `esiil-portal/portal/
   auth/keycloak_oauth.py`.

Credentials at rest (when persistence is needed) use AES-256-GCM with
scrypt-derived keys — *same pattern as terrain-mcp's `passwordCrypto.ts` /
`tokenCrypto.ts`*. Never commit plaintext credentials, never log them.

## DuckLake integration (mesa-ducklake)

mesa-ducklake stores **AVU history per project**. A "project" is an iRODS
collection that has been MESA-enabled (i.e. has a `/.mesa/ducklake/` child).

Design constraints (from project spec):

- **Catalog:** Postgres (same engine iRODS iCAT uses; one Postgres instance
  can host both if desired).
- **Data files:** Parquet under `/.mesa/ducklake/` *inside the iRODS
  collection itself* — so the metadata history travels with the data.
- **Schema (initial):** AVU triples plus provenance — `(path, attribute,
  value, unit, op, actor, ts, snapshot_id)` where `op ∈ {add, delete}`.
- **Time-travel:** every change appends; reads at time T reconstruct the
  effective AVU set as of T. DuckLake's snapshot mechanism handles this
  natively.

mesa-mcp's job at the integration boundary:

- On every write tool (`ds_add_avu`, `ds_delete_avu`, `mesa_avu_apply_term`),
  emit a change record into the project's DuckLake.
- On `mesa_ducklake_*` tools, query the DuckLake directly.
- Project bootstrap (`mesa_ducklake_init_project`) creates the
  `/.mesa/ducklake/` collection, sets ACLs (project owner only by default),
  and registers the project in the Postgres catalog.

mesa-ducklake is built out (see its own CLAUDE.md for current state).
mesa-mcp keeps the dependency narrow via the wrapper at
`src/mesa_mcp/ducklake/client.py`: a process-wide singleton
`DuckLakeClient`, the `record_avu_change` helper that the AVU-writing
tools call after a successful iRODS write, and the
`mesa_ducklake_init_project` MCP tool that bootstraps a project
(creates `<root>/.mesa/ducklake/`, sets `mesa.enabled=true`,
registers in the catalog). The two repos can still evolve
independently — only those entry points are imported across the
boundary.

## Resolved architectural decisions

1. **iRODS client library: `python-irodsclient` (PRC).** Official Python
   library from the iRODS project, pure-Python install, feature-parity with
   the Go client used by `irods-mcp-server` (native + PAM auth, AVU CRUD,
   ACLs, tickets, streaming I/O). No `gocmd` subprocess, no extra binaries
   in the container.
2. **OLS code reuse: vendor (copy) into mesa-mcp.** Copy
   `portal/services/ols_client.py` and `ols_transform.py` from esiil-portal
   into `src/mesa_mcp/ols/`. Strip the Django `cache` dependency — replace
   with a small in-memory TTL cache (or `functools.lru_cache` where TTL
   isn't needed). The OLS API surface is stable enough that drift between
   the two copies is manageable; if it becomes painful, extract to a shared
   `cyverse-ols` package later.
3. **mesa-ducklake API surface: Python import, in-process.** mesa-ducklake
   ships as a Python package; mesa-mcp imports it and DuckDB connections
   live in the mesa-mcp process. Pin versions in `pyproject.toml`. Keep the
   import surface narrow (a single `DuckLakeClient` facade in
   `src/mesa_mcp/ducklake/client.py`) so a future out-of-process split
   stays cheap.
4. **MESA-enabled marker: AVU + directory.** The source of truth is a
   `mesa.enabled=true` AVU on the project's root collection. The
   `/.mesa/ducklake/` collection is created by `mesa_ducklake_init_project`
   and holds the Parquet data files. Both are checked: AVU present + dir
   present = MESA-enabled; either alone = drift, surface a warning.
   Discovery of all MESA projects uses `ds_search_files_by_avu` against
   `mesa.enabled`.

## Working with this repo

- The package is built out: full `ds_*` iRODS surface, OLS tool group,
  `mesa_ducklake_init_project`, OIDC + Streamable HTTP transports, and
  the `record_avu_change` mirror that pushes AVU changes through
  mesa-ducklake into iRODS. Tests cover all of that.
- Don't pre-build features that aren't on the goal list above. The reference
  repos are full of patterns; we want the *relevant* patterns, not a
  faithful port of everything.
- When in doubt about an iRODS tool's input shape, the answer is in the
  matching Go file in `cyverse/irods-mcp-server/irods/`.
- When in doubt about ontology behavior, the answer is in
  `cyverse/esiil-portal/portal/services/ols_client.py`.
