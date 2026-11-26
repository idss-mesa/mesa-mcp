---
type: Reference
title: DuckLake integration
description: How mesa-mcp uses mesa-ducklake in-process, how each AVU write is mirrored into the per-project history, and which history operations are MCP tools versus Python-API only.
tags:
  - mesa-ducklake
  - avu-history
  - architecture
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: facade
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/ducklake/client.py"
    title: "mesa-mcp DuckLake facade (get_default_client, record_avu_change)"
    author: "team:idss-mesa"
  - id: tools
    resource: "https://github.com/idss-mesa/mesa-mcp/tree/main/src/mesa_mcp/ducklake/tools"
    title: "mesa_ducklake_* tool modules"
    author: "team:idss-mesa"
  - id: mesa-ducklake-client
    resource: "https://github.com/idss-mesa/mesa-ducklake/blob/main/src/mesa_ducklake/client.py"
    title: "mesa-ducklake DuckLakeClient"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# DuckLake integration

What this page covers: how mesa-mcp talks to
[mesa-ducklake](https://github.com/idss-mesa/mesa-ducklake), the library
that keeps the AVU (attribute, value, unit) history of every file and
folder in a MESA-enabled project. It explains why the library runs
in-process, the exact path an AVU write takes into the history, and which
history operations an agent can call.

## In-process, behind one facade

mesa-ducklake is a Python package. mesa-mcp imports it **in-process**: the
`DuckLakeClient` and its DuckDB connections live inside the mesa-mcp
process. There is no separate history service and no socket.

This is decision 3 in the repository's
[CLAUDE.md](https://github.com/idss-mesa/mesa-mcp/blob/main/CLAUDE.md)
("mesa-ducklake API surface: Python import, in-process"). The reasons it
records are:

- mesa-ducklake ships as a Python package, so importing it is the direct
  route.
- The import surface stays narrow, a single facade in
  [`src/mesa_mcp/ducklake/client.py`](https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/ducklake/client.py),
  so the two repositories can evolve independently and a future
  **out-of-process** split stays cheap.

No other rationale (latency, transactions) is recorded. The facade
imports `mesa_ducklake` lazily inside its functions; the only other
import is `mesa_ducklake.time_travel.parse_as_of` in the time-travel
tool, also lazy, with a local fallback. These are the facade's entry
points:

| Facade entry point | What it does |
| --- | --- |
| `get_default_client()` | Returns the process-wide `mesa_ducklake.DuckLakeClient`, built lazily on first use from `ducklake.catalog_dsn`, `cache_dir`, `cache_cap_bytes` and `data_collection`. Returns `None` when DuckLake is disabled. |
| `record_avu_change(...)` | Mirrors one AVU add or delete for one path. Called by write tools after the iRODS write succeeds. |
| `record_avu_changes(...)` | Mirrors many AVU changes for one path as a **single** snapshot. |
| `ducklake_subpath(root, data_collection)` | Computes `<root>/.mesa/ducklake` (or the configured sub-collection) without importing mesa-ducklake. |

### Optional dependency

mesa-ducklake is the optional `ducklake` extra (`pip install
"mesa-mcp[ducklake]"`, version 0.2 or newer, which needs DuckDB 2.0). It is
not on PyPI, so install it from its checkout first. `get_default_client()`
returns `None`, and mirroring becomes a silent no-op, when either:

- `ducklake.catalog_dsn` (`MESA_MCP_DUCKLAKE__CATALOG_DSN`) is empty, or
- `import mesa_ducklake` fails (a warning `mesa_ducklake_unavailable` is
  logged once).

AVU writes still succeed in iRODS in both cases; they are just not
recorded. The three `mesa_ducklake_*` tools refuse to run instead, with
error code `ducklake_disabled`.

The DSN picks the catalog backend inside mesa-ducklake: `postgresql://…`
(hosted, several writers), `duckdb:///abs/path.duckdb` (one local
process), or `quack://host:port` (a DuckDB file shared through
`mesa-ducklake serve-catalog`). See [Configuration](../user/configuration.md#ducklake-avu-history-catalog).

## What makes a project MESA-enabled

A collection is a MESA project when it carries the AVU
`mesa.enabled=true`. `mesa_ducklake_init_project` sets that up in four
idempotent steps:

1. Check the root exists and is a collection.
2. Create `<root>/.mesa/ducklake/` (or `<root>/<ducklake.data_collection>`).
3. Add `mesa.enabled=true` to the root if it is not already there.
4. Find or register the project in the catalog
   (`DuckLakeClient.find_project_by_path` / `register_project`).

Each step fails with its own code (`init_project_failed_root_missing`,
`init_project_failed_irods_create`, `init_project_failed_avu_add`,
`init_project_failed_catalog_register`, and so on). The tool does not
change ACLs on the new sub-collection.

Detection reads only the AVU. The facade walks the path and each parent up
to `/`, and returns the first collection whose `mesa.enabled` value is
`true`, `yes` or `1`. Results are cached per `(zone, collection)` for 5
minutes, so an admin flipping the marker takes up to 5 minutes to be seen.

## How an AVU write reaches the history

These tools mirror their writes:

| Tool | Mirror call | Snapshots per call |
| --- | --- | --- |
| `ds_add_avu` | `record_avu_change(op="add")` | 1 |
| `ds_delete_avu` | `record_avu_change(op="delete")` | 1 |
| `ds_add_avus` | `record_avu_changes` | 1 for the whole batch |
| `mesa_avu_apply_term` | `record_avu_change(op="add")` | 1 |
| `mesa_avu_apply_datacite` | `record_avu_changes` | 1 for the whole record |
| `mesa_policy_enable` / `mesa_policy_disable` | `record_avu_change` on `mesa.policy.<name>` | 1 |

The sequence for one write:

1. The tool checks the path with `assert_allowed` and writes the AVU to
   iRODS through `python-irodsclient`.
2. **Only after that succeeds**, it calls `record_avu_change` with the
   caller's `AuthValue`, the normalized path, `target_type`
   (`data_object` or `collection`), the triple, `op` and its own tool name.
3. The facade returns early (no-op) if DuckLake is disabled, if no iRODS
   session was passed, or if no ancestor carries `mesa.enabled=true`.
4. It looks up the project with `find_project_by_path(project_root)`. If
   the marker is present but the catalog has no row, the write path
   **registers the project** on the spot. (The read tools do not; they
   fail with `*_project_not_registered`.)
5. It builds a `mesa_ducklake.models.AvuChange`:
   - `actor` = the iRODS username,
   - `source` = `"mesa-mcp:<tool name>"`, for example
     `mesa-mcp:mesa_avu_apply_term`,
   - `via_ticket` = the ticket bound to this caller's session by
     `ds_use_ticket` (the `mesa.via_ticket` session attribute), else
     `None`.
6. It calls `DuckLakeClient.record_changes(project_id, actor, changes,
   note, session=session)`. mesa-ducklake then runs its own
   push-before-commit protocol: it writes one Parquet file, pushes it to
   `<project>/.mesa/ducklake/` in iRODS, and commits the snapshot row.

Only **path** targets are mirrored. `ds_add_avu` and `ds_delete_avu` also
accept `target_type` `resource` or `user`; those AVUs go to iRODS but not
to the history, because the history is per project and a resource or user
is not inside one.

### When the mirror fails

The iRODS change is not rolled back. The facade raises
`DuckLakeMirrorError`, and the tool returns its normal result plus:

```json
"partial_failure": {
  "code": "ducklake_mirror_failed",
  "message": "DuckLake write failed for project …",
  "project_id": "…"
}
```

`mesa_policy_enable` and `mesa_policy_disable` are the exception: they
treat the mirror as best-effort and drop the error.

### What is not mirrored

- AVUs on resources and users (see above).
- AVU changes made outside mesa-mcp (`imeta`, other clients) unless the
  iRODS rule callbacks from mesa-ducklake's `irods-rules/` are installed on
  the server. mesa-mcp has no part in that path.
- Ticket creation and modification. `ds_create_ticket` and
  `ds_modify_ticket` do not write to the history; only AVU writes made
  *through* a ticket carry `via_ticket`.

## Reading the history

Two read-only tools use the same project lookup. Both require an
authenticated caller and a path inside a registered MESA project.

| Tool | mesa-ducklake call | Returns |
| --- | --- | --- |
| `mesa_ducklake_history` | `get_history`, or `get_avus_as_of` when `as_of` is set | The change log for a path, newest first, or the AVUs in effect at `as_of` |
| `mesa_ducklake_time_travel` | `get_avus_as_of` (`as_of` required) | The AVUs in effect at `as_of`, sorted by attribute, value, unit |

Rows are `AvuChange` records: `project_id`, `snapshot_id`, `irods_path`,
`target_type`, `attribute`, `value`, `unit`, `op`, `actor`, `ts`,
`source`, `via_ticket`, `rule_invocation`. The `attribute` and `unit`
filters are exact matches applied in mesa-mcp after the read, because
mesa-ducklake has no filter arguments. `limit` defaults to 100 and is
capped at 1000. `as_of` is an ISO-8601 timestamp; a timestamp without a
zone is read as UTC, and a bare integer (a snapshot id) is refused with
`invalid_argument`.

## MCP tools versus the Python API

An agent can call three history tools:

- `mesa_ducklake_init_project`
- `mesa_ducklake_history`
- `mesa_ducklake_time_travel`

Everything else on `mesa_ducklake.DuckLakeClient` is **Python API only**.
A program that imports mesa-ducklake can call it; an MCP client cannot:

| `DuckLakeClient` method | Exposed as an MCP tool? |
| --- | --- |
| `register_project`, `find_project_by_path` | Indirectly, through `mesa_ducklake_init_project` and the write mirror |
| `record_changes` | Indirectly, through the write tools listed above |
| `get_history`, `get_avus_as_of` | Yes, through `mesa_ducklake_history` and `mesa_ducklake_time_travel` |
| `get_avus` (current state from the history) | No. Use `ds_list_avus` for the live iRODS state. |
| `get_project` | No |
| `list_snapshots` | No |
| `diff` (between two snapshot ids) | No |
| `recover_pending_pushes` | No. Use the `mesa-ducklake recover` CLI. |

`mesa_ducklake_snapshot` and `mesa_ducklake_diff` appear in the tool plan
in CLAUDE.md but are **not registered**. The back-compat stub class
`mesa_mcp.ducklake.client.DuckLakeClient` still has `snapshot` and `diff`
methods; they raise `NotImplementedError` and point you at
`get_default_client()`.

## Tests

`tests/test_ducklake_client.py`, `test_ducklake_init_project.py`,
`test_ducklake_history.py` and `test_ducklake_time_travel.py` inject a fake
client with `set_default_client(...)`, so they run without mesa-ducklake.
`tests/test_config_active.py` exercises the real library and skips when the
extra is missing; CI's `ducklake-integration` job installs it and fails if
those tests skip. See [Testing](testing.md).

## See also

- [Architecture](architecture.md)
- [Metadata workflows](../user/examples.md) for the history tools from a
  user's point of view.
- mesa-ducklake's [architecture notes](https://github.com/idss-mesa/mesa-ducklake/blob/main/docs/dev/architecture.md)
  for the push-before-commit protocol and crash recovery.
