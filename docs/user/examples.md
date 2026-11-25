---
type: Guide
title: Metadata workflows
description: Worked tool-call sequences for finding files by AVU, tagging data with OLS ontology terms (unit = CURIE), bulk AVU writes, enrolling a project, reading AVU history and time travel, and using iRODS tickets with via_ticket provenance.
tags:
  - avu
  - ontology
  - ols
  - ducklake
  - tickets
  - examples
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: irods-tools
    resource: "https://github.com/idss-mesa/mesa-mcp/tree/main/src/mesa_mcp/irods/tools"
    title: "ds_* tool modules"
    author: "team:idss-mesa"
  - id: ols-tools
    resource: "https://github.com/idss-mesa/mesa-mcp/tree/main/src/mesa_mcp/ols/tools"
    title: "mesa_ols_* and mesa_avu_* tool modules"
    author: "team:idss-mesa"
  - id: ducklake-tools
    resource: "https://github.com/idss-mesa/mesa-mcp/tree/main/src/mesa_mcp/ducklake/tools"
    title: "mesa_ducklake_* tool modules"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# Metadata workflows

What this page covers: end-to-end sequences of mesa-mcp tool calls for
the metadata tasks people ask about most. Each call is written as
`{"tool": …, "input": …}`; your MCP client sends the same JSON whatever
its syntax. For every field of every tool, see the
[Tools reference](tools-reference.md). For DataCite records, see
[DataCite metadata](datacite.md).

## Before you start

- An **AVU** is an iRODS metadata triple: attribute, value, unit. Data
  objects (files) and collections (folders) can carry any number of them.
- Every tool that takes a path checks it against your **accessible
  paths**: your home collection (`/<zone>/home/<user>`) and the shared
  tree (`/<zone>/home/shared`). Anything else fails with `forbidden`.
- The `anonymous` user (no credentials) gets only the shared tree, and
  iRODS gives it read-only access. Writes and tickets need a real CyVerse
  account. See [Configuration](configuration.md#how-credentials-are-resolved).

## Find files by AVU

Two search tools query the iRODS catalog (iCAT). Both return data objects
and collections, and both drop any hit outside your accessible paths.

**Exact attribute and value**, the shape `irods-mcp-server` uses:

```json
{"tool": "ds_search_files_by_avu",
 "input": {"attribute": "envo.biome", "value": "tropical moist broadleaf forest"}}
```

The result lists `matching_entries`, each with `path`, `entry_type`
(`data_object` or `collection`) and `name`.

**Any combination of attribute, value and unit**, with a type filter:

```json
{"tool": "ds_search_metadata",
 "input": {"unit": "ENVO:00000428", "target": "data_object"}}
```

Each of `attribute`, `value` and `unit` is an exact match; at least one is
required. `target` is `data_object`, `collection` or `both` (the default).
Searching by `unit` finds every AVU tagged with one ontology term,
whatever value was typed.

**Find MESA-enabled projects** by searching for the project marker:

```json
{"tool": "ds_search_files_by_avu", "input": {"attribute": "mesa.enabled", "value": "true"}}
```

To read what is on one path, use `ds_list_avus` (`target_type: "path"`;
it also handles `resource` and `user`) or `ds_get_metadata`, which
resolves whether the path is a data object or collection and returns its
AVUs. Each AVU comes back with `id`, `attribute`, `value` and `unit`.

## Tag a file with an ontology term

mesa-mcp browses the [EMBL-EBI Ontology Lookup Service](https://www.ebi.ac.uk/ols4/)
(OLS4) and writes the chosen term as an AVU of a fixed shape:

| AVU field | Content | Example |
| --- | --- | --- |
| `attribute` | `<ontology_id>.<snake_case term label>`, ontology id lowercased | `envo.biome` |
| `value` | Free text the user supplies (often a label, but not checked) | `tropical moist broadleaf forest` |
| `unit` | The term's **CURIE** | `ENVO:00000428` |

The term's IRI is not stored in the AVU. The `unit` slot holding a CURIE
is what marks an AVU as ontology-sourced. This is the same shape
`cyverse/esiil-portal` writes, so AVUs written by the portal and by
mesa-mcp are interchangeable. The label is converted by
`_label_to_snake` in `ols/client.py`: non-alphanumeric characters are
removed, whitespace becomes `_`, and the result is lowercased (`pH value`
becomes `ph_value`).

### 1. Find the term

```json
{"tool": "mesa_ols_search_terms", "input": {"query": "biome", "ontology_id": "envo", "size": 5}}
```

The result is `{"results": [...], "count": n}`; each hit has `label`,
`curie`, `iri` and `ontologyId`. Other browsing tools:

- `mesa_ols_list_ontologies` (`page` from 0, `size` up to 200) lists the
  OLS catalog.
- `mesa_ols_get_term` (`ontology_id`, `iri`) returns the full record:
  definition, synonyms, parents and children.
- `mesa_ols_get_term_hierarchy` (`ontology_id`, `iri`, `size` default 50)
  lists a term's direct children, so you can walk down one level at a
  time. `mesa_ols_search_terms` with `descendants_of` (and `ontology_id`)
  searches within a branch.

### 2. Preview the AVU (optional)

`mesa_avu_from_term` builds the triple without writing anything:

```json
{"tool": "mesa_avu_from_term",
 "input": {"ontology_id": "envo",
           "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
           "value": "tropical moist broadleaf forest"}}
```

```json
{"avu": {"attribute": "envo.biome",
         "value": "tropical moist broadleaf forest",
         "unit": "ENVO:00000428"},
 "term": {"ontologyId": "envo", "label": "biome",
          "curie": "ENVO:00000428",
          "iri": "http://purl.obolibrary.org/obo/ENVO_00000428"}}
```

With an `iri`, the label and CURIE are looked up in OLS. With only a
`curie`, you must also pass `label`.

### 3. Write it

`mesa_avu_apply_term` takes the same inputs plus `path`, writes the AVU
through the same code as `ds_add_avu`, and mirrors it to the project's
AVU history:

```json
{"tool": "mesa_avu_apply_term",
 "input": {"path": "/iplant/home/alice/proj/plot7.csv",
           "ontology_id": "envo",
           "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
           "value": "tropical moist broadleaf forest"}}
```

If you give neither `iri` nor `curie`, the tool searches OLS for `value`
in that ontology and, instead of failing, returns an **input request**
(MCP 2026-07-28 multi-round-trip) asking the user to pick one of up to 8
candidate terms. The client sends the choice back in a follow-up call and
the write goes ahead. A choice that was not among the offered candidates
is refused. If OLS finds nothing, the tool fails with `invalid_argument`.

### Template forms

`mesa_ols_generate_template` (`ontology_id`) returns an ontology's
top-level terms as a form template. It is the function behind
esiil-portal's auto-generated metadata forms.

## Add several AVUs at once

`ds_add_avus` writes many AVUs to one path in one call and records them as
a single history snapshot:

```json
{"tool": "ds_add_avus",
 "input": {"target": "/iplant/home/alice/proj/plot7.csv",
           "avus": [{"attribute": "site", "value": "plot 7"},
                    {"attribute": "envo.biome", "value": "tropical moist broadleaf forest",
                     "unit": "ENVO:00000428"}]}}
```

## Enroll a project for history

AVU history is kept only for paths inside a **MESA-enabled project**: a
collection carrying `mesa.enabled=true`. Enroll one once:

```json
{"tool": "mesa_ducklake_init_project", "input": {"irods_path": "/iplant/home/alice/proj"}}
```

It creates `/iplant/home/alice/proj/.mesa/ducklake/`, where the history's
Parquet files live, sets `mesa.enabled=true` on the root, and registers
the project in the catalog. It is safe to re-run. From then on, every AVU
written through `ds_add_avu`, `ds_add_avus`, `ds_delete_avu`,
`mesa_avu_apply_term`, `mesa_avu_apply_datacite`, `mesa_policy_enable` or
`mesa_policy_disable` under that root is recorded. The server needs
`ducklake.catalog_dsn` and the `ducklake` extra; otherwise the history
tools fail with `ducklake_disabled`.

## See how metadata changed

**The change log for a path**, newest first:

```json
{"tool": "mesa_ducklake_history",
 "input": {"irods_path": "/iplant/home/alice/proj/plot7.csv", "attribute": "envo.biome"}}
```

The result is `{"project_id", "count", "rows"}`. Each row is one AVU
change: `snapshot_id`, `irods_path`, `target_type`, `attribute`, `value`,
`unit`, `op` (`add` or `delete`), `actor` (the iRODS user), `ts`,
`source` (for example `mesa-mcp:mesa_avu_apply_term`), `via_ticket` and
`rule_invocation`. `attribute` and `unit` are optional exact-match filters
(pass `unit: ""` for AVUs with no unit). `limit` defaults to 100 and is
capped at 1000.

**The AVUs a path had at a past instant** (time travel):

```json
{"tool": "mesa_ducklake_time_travel",
 "input": {"irods_path": "/iplant/home/alice/proj/plot7.csv",
           "as_of": "2026-09-01T12:00:00Z"}}
```

`as_of` is required and must be an ISO-8601 timestamp. A timestamp with no
zone is read as UTC. A change stamped exactly at `as_of` is included (the
library reads rows with `ts <= as_of`). **Snapshot ids are not supported**:
a bare number is refused with `invalid_argument`. The result adds the
normalized `as_of` and sorts the AVUs by attribute, value and unit.
`mesa_ducklake_history` with `as_of` returns the same set without the
sorting.

Errors you may see: `not_mesa_project` (no ancestor carries
`mesa.enabled=true`), `history_project_not_registered` or
`time_travel_project_not_registered` (the marker is there but the catalog
has no row; run `mesa_ducklake_init_project`), and `ducklake_disabled`.

There is no MCP tool for diffing two snapshots or listing snapshots; see
[DuckLake integration](../dev/ducklake-integration.md#mcp-tools-versus-the-python-api).

## Share access with a ticket

An iRODS ticket is a token that grants read or write access to one path.
mesa-mcp manages the whole lifecycle. **Anonymous users cannot create,
use, modify, list or inspect tickets.**

```text
ds_create_ticket    path, mode ("read" | "write"), optional uses_allowed, expiry (ISO-8601),
                    write_byte_limit, host_restriction, user_restriction -> ticket string
ds_use_ticket       ticket -> binds it to your own pooled iRODS session
  ...               later calls run with the ticket applied
ds_modify_ticket    ticket, new uses / expiry / limits (the mode cannot change)
ds_list_tickets     list tickets
ds_get_ticket_info  name -> one ticket's details
ds_delete_ticket    ticket -> revoke (issuer or admin, enforced by iRODS)
```

`ds_use_ticket` attaches the ticket to the session mesa-mcp keeps for your
identity, so it applies to your later calls and never to another
caller's. Every AVU write you make on that session is recorded in the
history with the ticket id in the **`via_ticket`** column, so an auditor
can see which changes came through shared credentials. Creating or
modifying a ticket is not itself recorded in the history. Binding a
ticket does not widen mesa-mcp's own path check: paths must still be in
your home or shared tree.

## See also

- [Tools reference](tools-reference.md)
- [DataCite metadata](datacite.md)
- [DuckLake integration](../dev/ducklake-integration.md) for how writes are
  mirrored.
- [OLS internals](../dev/ols-internals.md) for the AVU contract with
  esiil-portal.
