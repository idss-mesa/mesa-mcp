---
type: Reference
title: Tools reference
description: Every one of the 52 built-in mesa-mcp tools (ds_*, mesa_ols_*, mesa_avu_*, mesa_datacite_*, mesa_ducklake_*, mesa_policy_*) with its description, input fields, defaults and notable outputs and errors, generated from the live tool registry.
tags:
  - tools
  - reference
  - mcp
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: registry
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/server.py"
    title: "mesa-mcp tool registry (register_tool, get_registered_tools)"
    author: "team:idss-mesa"
  - id: irods-mcp-server
    resource: "https://github.com/cyverse/irods-mcp-server"
    title: "cyverse/irods-mcp-server, the Go reference for the ds_* tools"
    author: "team:cyverse"
status: stable
stale_after: "2027-02-24T00:00:00Z"
---

# Tools reference

What this page covers: every MCP tool mesa-mcp registers at import time,
grouped by prefix and listed alphabetically within each group. Field
names, types, defaults and descriptions are copied from each tool's
Pydantic input model, which is also what clients receive as the tool's
`inputSchema` (JSON Schema 2020-12). A connected client's `tools/list`
response is the authoritative, live version of this page.

**52 built-in tools:** 35 `ds_*`, 6 `mesa_ols_*`, 2 ontology `mesa_avu_*`,
4 DataCite (`mesa_datacite_*` and `mesa_avu_apply_datacite`), 3
`mesa_ducklake_*`, 2 `mesa_policy_*`.

## How results and errors come back

- Each tool returns a JSON object. The server sends it both as
  `structuredContent` and as a single JSON text block. Only `ds_ping`
  also publishes an `outputSchema` today.
- A failure comes back with `isError: true` and
  `{"error": {"code", "message", "details"}}`. Common codes:
  `invalid_argument` (bad input), `unauthenticated`, `forbidden` (path
  outside your accessible paths, or an anonymous caller), `not_found`,
  `irods_error`, `upstream_error` (OLS), `ducklake_disabled`.
- Each tool definition carries `_meta["io.mesa/surface"]`: `irods`,
  `ontology`, `datacite`, `history`, `policy` (or a plugin's own family),
  so a client can group tools without parsing names.
- `tools/list` is marked cacheable for 5 minutes (`ttlMs` 300000, public).

## Plugin tools

Packages can add tools through the `mesa_mcp.tools` entry-point group;
they are loaded when the server starts and are not counted above.

- `mesa_croissant_*` (MLCommons Croissant metadata) from
  [idss-mesa/mesa-croissant](https://github.com/idss-mesa/mesa-croissant),
  installed with the `croissant` extra.
- `mesa_decide_*` from mesa-anyjev, which the MESA installer adds.

A plugin that fails to import is skipped with a warning, unless
`MESA_MCP_SERVER__STRICT_PLUGINS=1` makes that a startup error.

## Regenerating this list

```bash
python -c "
import mesa_mcp.server as s
for spec in sorted(s.get_registered_tools(), key=lambda t: t.name):
    print(spec.name)
"
```

Importing `mesa_mcp.server` imports every built-in tool package. Plugin
tools appear only after `mesa_mcp.server.load_plugins()`.

## ds_*: CyVerse Data Store (iRODS)

Mirrors the tool surface of [cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server) (same names and input shapes), plus ticket lifecycle, rule and policy tools, `ds_add_avus`, `ds_search_metadata`, `ds_get_metadata` and `ds_ping`. Every path argument is checked against the caller's accessible paths (home and shared) and fails with `forbidden` otherwise; the search tools instead drop results outside those paths. `ds_add_avu`, `ds_add_avus` and `ds_delete_avu` mirror path-target AVU changes into the AVU history (see [DuckLake integration](../dev/ducklake-integration.md)).

### `ds_add_avu`

Add a new AVU (attribute-value-unit) to a file (data-object), directory (collection), resource, or user.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `target_type` (required) | `"path"` \| `"resource"` \| `"user"` |  | The type of the target to add AVU. It can be 'path', 'resource', or 'user'. |
| `target` (required) | string |  | The target to add AVU. Path for 'path' target_type, resource name for 'resource' target_type, and user name for 'user' target_type. |
| `attribute` (required) | string |  | The attribute of the AVU to add. |
| `value` (required) | string |  | The value of the AVU to add. |
| `unit` | string | `""` | The unit of the AVU to add. Default is an empty string. |

Only `path` targets are mirrored into the AVU history. On a mirror failure the result carries `partial_failure` with code `ducklake_mirror_failed`; the iRODS write stands.

### `ds_add_avus`

Add MULTIPLE AVUs to one data-object/collection in a single call and mirror them all into DuckLake as ONE snapshot (efficient bulk tagging).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `target_type` | `"path"` | `"path"` | — |
| `target` (required) | string |  | iRODS path of the data-object or collection. |
| `avus` (required) | array of AvuItem |  | AVUs to add in one batched call. |

Each `avus` item is `{attribute, value, unit}` (`unit` defaults to `""`). All AVUs are mirrored as one history snapshot.

### `ds_copy_file`

Copy a file (data-object) or directory (collection) to a new location.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `source_path` (required) | string |  | The path to the source file (data-object) or directory (collection). If directory path is given, the entire directory and its contents will be copied. |
| `destination_path` (required) | string |  | The new, complete path to copy the file (data-object) or directory (collection) to, including its new name. The path must not already exist. |

### `ds_create_ticket`

Create a read or write iRODS ticket on a data object or collection. Returns the ticket string plus the restrictions that were applied. Anonymous users may not create tickets.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The iRODS path the ticket grants access to. |
| `mode` (required) | `"read"` \| `"write"` |  | Ticket access mode: 'read' or 'write'. |
| `uses_allowed` | integer \| null | `null` | Maximum number of times this ticket may be used. |
| `expiry` | string \| null | `null` | ISO-8601 timestamp at which the ticket expires. |
| `write_byte_limit` | integer \| null | `null` | Maximum bytes that may be written via this ticket (write tickets only). |
| `host_restriction` | string \| null | `null` | Restrict ticket usage to clients connecting from this host. |
| `user_restriction` | string \| null | `null` | Restrict ticket usage to this iRODS user. |

### `ds_delete_avu`

Delete an AVU (attribute-value-unit) from a file, directory, resource, or user.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `target_type` (required) | `"path"` \| `"resource"` \| `"user"` |  | The type of the target to delete AVU. It can be 'path', 'resource', or 'user'. |
| `target` (required) | string |  | The target to delete AVU. Path for 'path' target_type, resource name for 'resource' target_type, and user name for 'user' target_type. |
| `id` | integer | `0` | The ID of the AVU to delete. |
| `attribute` | string | `""` | The attribute of the AVU to delete. This field can be ignored if ID is provided. |
| `value` | string | `""` | The value of the AVU to delete. Default is an empty string. |
| `unit` | string | `""` | The unit of the AVU to delete. Default is an empty string. |

Only `path` targets are mirrored into the AVU history, as an `op=delete` row.

### `ds_delete_file`

Delete a file (data-object) or directory (collection).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the file (data-object) or directory (collection) to delete. |

### `ds_delete_ticket`

Revoke an existing iRODS ticket. Issuer or admin only — the server enforces this. Anonymous callers are rejected at the tool layer.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ticket` (required) | string |  | The ticket string to delete. |

### `ds_directory_tree`

Get a recursive tree view of files (data-objects) and directories (collections). The specified path must be an iRODS path. The output is in JSON format. The output contains all entries in the given directory (collection) path.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the directory (collection) to list. |
| `depth` | integer | `3` | The depth of the directory tree to list. Default value is 3. Depth must be greater than or equal to 1. Depth must not be too large, otherwise the output may be too large. Maximum value is 10. |

### `ds_download_file`

Returns how to download the full contgent of a file (data-object) with the specified path. The specified path must be an iRODS path. Returns how to download the file using WebDAV, GoCommands (gocmd), and iCommands.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `irods_path` (required) | string |  | The iRODS path to the file (data-object) to download. |
| `local_path` (required) | string |  | The local path to download the file (data-object) to. Must be a full path including the file name. |

### `ds_execute_rule`

Run an iRODS rule. Supply either rule_name (server-installed) or rule_text (inline iRL). Output parameters are returned as a dict; iRODS stdout/stderr are returned when output_parameters includes 'ruleExecOut'. Path-typed input parameters are checked against the caller's accessible paths before the rule fires.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `rule_name` | string \| null | `null` | Name of a server-installed rule to invoke. |
| `rule_text` | string \| null | `null` | Inline iRL fragment to execute. |
| `input_parameters` | object |  | Input parameters bound into the rule body. |
| `output_parameters` | array of string |  | Names of rule output parameters to return. |
| `instance_name` | string | `"irods_rule_engine_plugin-irods_rule_language-instance"` | Rule engine instance to target. |

### `ds_get_file_info`

Retrieve detailed metadata about a file or directory.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the file (data-object) or directory (collection). |

### `ds_get_metadata`

Fetch the full AVU metadata bundle for an iRODS path (data object or collection). Returns the resolved target type alongside the AVU list.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | Absolute iRODS path of the data object or collection whose metadata you want. |

### `ds_get_policy_config`

Return the configuration of a named Policy Composition Framework policy. iRODS does not expose PCF config through PRC; this is a stub that returns ``config=None`` and a ``note`` documenting the limitation.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `name` (required) | string |  | Name of the PCF policy to introspect. |

### `ds_get_rule_definition`

Return the source of a named iRODS rule. iRODS does not expose rule sources through PRC; this is a best-effort tool whose ``definition`` field is None on most servers.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `name` (required) | string |  | Name of the rule to introspect. |

### `ds_get_ticket_info`

Get information about a specific iRODS ticket, such as its ID and expiration time, in JSON format. Anonymous users are not allowed to get ticket information.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `name` (required) | string |  | The name of the iRODS ticket to get information about. |

### `ds_list_allowed_directories`

Get a list of directories (collections) that this server is allowed to access. The output also contains API names that can be requested to each directory (collection).

No input fields.

### `ds_list_avus`

List AVUs (attribute-value-unit) from a file (data-object), directory (collection), resource, or user.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `target_type` (required) | `"path"` \| `"resource"` \| `"user"` |  | The type of the target to list AVU. It can be 'path', 'resource', or 'user'. |
| `target` (required) | string |  | The target to list AVU. Path for 'path' target_type, resource name for 'resource' target_type, and user name for 'user' target_type. |

### `ds_list_directory`

Get a list of files (data-objects) and directories (collections) in a specified path. The specified path must be an iRODS path. The output is in JSON format. The output contains entries in the given directory (collection) path. Use offset and limit parameters to paginate through large directories.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the directory (collection) to list. |
| `offset` | integer | `0` | Number of entries to skip (for pagination). Default: 0. |
| `limit` | integer | `100` | Maximum number of entries to return (for pagination). Default: 100, max: 500. |

### `ds_list_directory_details`

Get a list of files (data-objects) and directories (collections) in a specified path with full detailed info. The specified path must be an iRODS path. The output is in JSON format. The output contains entries in the given directory (collection) path, and users or groups who can access the files (data-ojects). Files (data-objects) will also have replica information. Use offset and limit parameters to paginate through large directories.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the directory (collection) to list. |
| `offset` | integer | `0` | Number of entries to skip (for pagination). Default: 0. |
| `limit` | integer | `100` | Maximum number of entries to return (for pagination). Default: 100, max: 500. |

### `ds_list_policies`

List policies in effect for the Data Store. With ``project_path``, returns the MESA policy AVUs (``mesa.policy.*``) set on that project root — the policies mesa-mcp itself honours. Always includes the server-side Policy Composition Framework envelope; iRODS does not expose PCF state through PRC, so that part is a documented stub.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `project_path` | string \| null | `null` | Project root collection whose MESA policy AVUs (`mesa.policy.*`) should be listed. Omit to return only the server-side Policy Composition Framework envelope. |

### `ds_list_rules`

List iRODS rules visible to the caller. Returns a best-effort list of delayed rules; the static rule base is not exposed by PRC and the ``note`` field documents that limitation.

No input fields.

### `ds_list_tickets`

Get a list of iRODS tickets. Return information about the tickets, such as their IDs and expiration times, in JSON format. Anonymous users are not allowed to list tickets.

No input fields.

### `ds_make_directory`

Make a new directory (collection).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the new directory to create. |

### `ds_modify_access`

Modify data access of a user or group to a file (data-object) or directory (collection).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `access_level` (required) | string |  | The access level to set to the user. It can be 'own', 'delete_object', 'modify_object', 'create_object', 'delete_metadata', 'modify_metadata', 'create_metadata', 'read_object', 'read_metadata', or 'null'. For iRODS version prior to 4.3.0, only 'own', 'write', 'read', and 'null' are allowed. |
| `user_or_group` (required) | string |  | The user or group to set access. You can specify a user by 'username#zone' or a group by 'groupname#zone' to set zone. if zone is not specified, the client's zone will be used. |
| `path` (required) | string |  | The path to the file (data-object) or directory (collection) to modify access. |
| `recurse` | boolean | `false` | If set, apply the given access to all entries within the given directory (collection) recursively. |

### `ds_modify_access_inheritance`

Modify data access inheritance flag of a file or directory.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the directory (collection) to modify access. |
| `inherit` (required) | boolean |  | If set, access to the directory (collection) will be inherited by all child entries. |
| `recurse` | boolean | `false` | If set, apply the inheritance flag to all entries within the given directory (collection) recursively. |

### `ds_modify_ticket`

Modify restrictions on an existing iRODS ticket. Cannot change the ticket's mode — that is set at issuance time. Returns the applied restrictions. Anonymous users are not allowed to modify tickets.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ticket` (required) | string |  | The ticket string to modify. |
| `uses` | integer \| null | `null` | New uses-allowed cap. |
| `expiry` | string \| null | `null` | New ISO-8601 expiry timestamp. |
| `write_byte_limit` | integer \| null | `null` | New write-byte limit (write tickets only). |
| `host_restriction` | string \| null | `null` | Add an allowed-host restriction. |
| `user_restriction` | string \| null | `null` | Add an allowed-user restriction. |

### `ds_move_file`

Move a file (data-object) or directory (collection) to a new location.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `old_path` (required) | string |  | The old path to the file (data-object) or directory (collection). |
| `new_path` (required) | string |  | The new, complete path to move the file (data-object) or directory (collection) to, including its new name. The path must not already exist. |

### `ds_ping`

Liveness check. Echoes back the supplied message (or 'ok') and the running mesa-mcp version. No iRODS access required.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `message` | string \| null | `null` | — |

### `ds_read_file`

Read the partial content of a file (data-object) with the specified path and offset. The specified path must be an iRODS path. If the file is too large to be displayed inline, use the WebDAV URI to access it.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the file (data-object) to read. |
| `offset` | integer | `0` | The offset to start reading the file from. Default is 0. |
| `length` | integer | `65536` | The maximum length of the file to read. Default value is 1048576. Length must be greater than or equal to 65536. Length must not be too large, otherwise the output may be too large. Maximum value is 1048576. |

### `ds_search_files`

Recursively search for files (data-objects) and directories (collections) matching a pattern. The specified search root path must be an iRODS path. Use unix wildcards, such as '?' and '*', for the search pattern. The matching entries are returned in JSON format.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The search path, which may include wildcard patterns such as '?' and '*'. |

### `ds_search_files_by_avu`

Search for files (data-objects) and directories (collections) matching iRODS AVU (attribute-value-units) using specified attribute and value. The matching entries are returned in JSON format.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `attribute` (required) | string |  | The attribute to search for. |
| `value` (required) | string |  | The value of the attribute to search for. |

### `ds_search_metadata`

Search iRODS by AVU attribute/value/unit. More permissive than ds_search_files_by_avu: any combination of attribute, value, and unit can be supplied and you can restrict the result type to data objects, collections, or both.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `attribute` | string \| null | `null` | Match only AVUs with this attribute name. |
| `value` | string \| null | `null` | Match only AVUs with this value. |
| `unit` | string \| null | `null` | Match only AVUs with this unit (often an ontology CURIE). |
| `target` | `"data_object"` \| `"collection"` \| `"both"` | `"both"` | Restrict results to data objects, collections, or both. |

### `ds_upload_file`

Returns how to upload the full contgent of a file (data-object) to the specified path. The specified path must be an iRODS path. Returns how to upload the file using WebDAV, GoCommands (gocmd), and iCommands.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `local_path` (required) | string |  | The local path to the file (data-object) to upload. |
| `irods_path` (required) | string |  | The target iRODS path to upload the file (data-object) to. |
| `is_dir` | boolean | `false` | Set to true if uploading a directory (collection). Default is false. |

### `ds_use_ticket`

Supply an iRODS ticket to the caller's iRODS session. Subsequent operations by the same caller run with the ticket applied, and their AVU writes record the ticket id in DuckLake's via_ticket column. Other callers' sessions are unaffected.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ticket` (required) | string |  | The ticket string to use for subsequent operations. |

### `ds_write_file`

Write the partial content to a file (data-object) with the specified path and offset. The specified path must be an iRODS path. If the file is too large to be displayed inline, use the WebDAV URI to access it.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | The path to the file (data-object) to write to. |
| `offset` | integer | `0` | The offset to start writing the file from. Default is 0. |
| `content` (required) | string |  | The Base64-encoded content to write to the file (data-object). Maximum size is 1048576 bytes. |

## mesa_ols_*: Ontology Lookup Service

Read-only browsing of the EMBL-EBI OLS4 API. No iRODS access and no credentials needed. Upstream OLS errors come back as an `error` field (search, hierarchy, list) or as `ToolError(code="upstream_error")`.

### `mesa_ols_generate_template`

Generate a SCHEMAS-compatible template (prefix + top-level term fields) for an ontology. This is the function that drives the esiil-portal auto-generated AVU forms.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ontology_id` (required) | string |  | Ontology identifier to generate a template for (e.g. 'envo'). |

### `mesa_ols_get_ontology`

Fetch metadata for a single OLS ontology (term count, version, homepage, preferred prefix).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ontology_id` (required) | string |  | Ontology identifier, e.g. 'envo', 'go', 'chebi'. Case-insensitive. |

### `mesa_ols_get_term`

Get the full record (label, CURIE, synonyms, definition, parents/children) for a single OLS term by IRI.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ontology_id` (required) | string |  | Ontology identifier (e.g. 'envo'). |
| `iri` (required) | string |  | Full term IRI, e.g. 'http://purl.obolibrary.org/obo/ENVO_00000428'. |

### `mesa_ols_get_term_hierarchy`

List the direct children of an OLS term. Use this to walk an ontology's class hierarchy one level at a time.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ontology_id` (required) | string |  | Ontology identifier (e.g. 'envo'). |
| `iri` (required) | string |  | Full IRI of the parent term. |
| `size` | integer | `50` | Max children to return. |

### `mesa_ols_list_ontologies`

List ontologies available in the EMBL-EBI Ontology Lookup Service (OLS4), paginated. Returns 266+ ontologies (ENVO, GO, CHEBI, etc.).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `page` | integer | `0` | Zero-indexed page number. |
| `size` | integer | `25` | Results per page (1–200). |

### `mesa_ols_search_terms`

Search OLS terms across all ontologies or scoped to one. Optionally restrict to descendants of a parent IRI (hierarchy walk).

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `query` (required) | string |  | Free-text search string. |
| `ontology_id` | string \| null | `null` | Optional ontology to restrict the search (e.g. 'envo'). |
| `descendants_of` | string \| null | `null` | Optional parent term IRI. When set together with `ontology_id`, only descendants of this term are returned (uses the v1-compat `allChildrenOf` search). |
| `size` | integer | `15` | Max results. |

## mesa_avu_*: ontology terms as AVUs

Turn an OLS term into the canonical AVU triple: attribute `<ontology_id>.<snake_case_label>`, value as supplied, unit the term's CURIE. See [Metadata workflows](examples.md#tag-a-file-with-an-ontology-term).

### `mesa_avu_apply_term`

Resolve an OLS term, build the canonical AVU triple (<ontology>.<snake_label>, <value>, <CURIE>), write it to the iRODS path, and record the change in the project's DuckLake. Composite of mesa_avu_from_term + ds_add_avu, in one call.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `path` (required) | string |  | Absolute iRODS path of the data object or collection to tag. |
| `ontology_id` (required) | string |  | Ontology identifier (e.g. 'envo'). |
| `value` (required) | string |  | User-supplied AVU value. Often the term label, but free-form. |
| `iri` | string \| null | `null` | Full IRI of the OLS term. Either `iri` or `curie` is required. |
| `curie` | string \| null | `null` | CURIE of the OLS term (e.g. 'ENVO:00000428'). |
| `label` | string \| null | `null` | Optional term label. When omitted, the label is looked up via OLS so the AVU attribute can be `<ontology>.<snake_case_label>`. |

If neither `iri` nor `curie` is given, the tool searches OLS for `value` and returns an MCP input request asking the user to choose among up to 8 candidate terms. On a history-mirror failure the result carries `partial_failure` with code `ducklake_mirror_failed`.

### `mesa_avu_from_term`

Pure transformation: turn an OLS term + user value into the canonical AVU triple (attribute='<ontology>.<snake_case_label>', value=<value>, unit=<CURIE>) without writing to iRODS.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `ontology_id` (required) | string |  | Ontology identifier (e.g. 'envo'). |
| `value` (required) | string |  | User-supplied AVU value. Often the term label, but free-form. |
| `iri` | string \| null | `null` | Full IRI of the term to use. Either `iri` or `curie` must be supplied, alongside `label` if you want to skip the OLS lookup. |
| `curie` | string \| null | `null` | Term CURIE (e.g. 'ENVO:00000428') — used directly as the AVU unit. |
| `label` | string \| null | `null` | Term label. If omitted, mesa-mcp fetches it from OLS using `ontology_id` + `iri`. |

## mesa_datacite_*: DataCite descriptive metadata

DataCite 4.x records stored as `datacite.*` AVUs. Only `mesa_avu_apply_datacite` touches iRODS; template, validate and export work on the data you pass in. See [DataCite metadata](datacite.md).

### `mesa_avu_apply_datacite`

Validate a DataCite 4.x record and write it to an iRODS path as AVUs (canonical and/or CyVerse-template naming), mirrored to DuckLake as one snapshot.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `target` (required) | string |  | iRODS path of the data-object or collection. |
| `record` (required) | object |  | A DataCite 4.x record (validated). |
| `naming` | string | `"both"` | canonical \| cyverse_template \| both |

Fails with `datacite_invalid` before writing anything if the record does not validate. Output: `target`, `path_target_type`, `written`, `errors`, and `partial_failure` on a history-mirror failure.

### `mesa_datacite_export`

Export DataCite AVUs as a DataCite 4.x XML (for DOI registration) or REST JSON document.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `avus` (required) | array of AvuItem |  | Canonical-naming DataCite AVUs from a path. |
| `format` | `"xml"` \| `"json"` | `"xml"` | — |

Takes AVUs, not a path: read them first with `ds_list_avus` or `ds_get_metadata`. Output: `{"format", "document"}`. Fails with `datacite_incomplete` when the AVUs do not form a valid record.

### `mesa_datacite_template`

Return the DataCite 4.x field scaffold (field, required?, repeatable?, controlled vocabulary, canonical AVU key) to drive a complete, valid record.

No input fields.

### `mesa_datacite_validate`

Validate DataCite AVUs against the 4.x kernel: report missing mandatory fields, invalid controlled-vocabulary values, and whether the record is DOI-ready.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `avus` (required) | array of AvuItem |  | The candidate DataCite AVUs to validate. |

Output: `doi_ready`, `missing_mandatory`, `errors`.

## mesa_ducklake_*: AVU history

All three need `ducklake.catalog_dsn` set and the `ducklake` extra installed; otherwise they fail with `ducklake_disabled`. They also need an authenticated caller. See [Configuration](configuration.md#ducklake-avu-history-catalog) and [DuckLake integration](../dev/ducklake-integration.md).

### `mesa_ducklake_history`

Read the DuckLake AVU history for an iRODS path inside a MESA-enabled project. Without as_of, returns the change log (newest first). With as_of, returns the AVUs that were in effect at that timestamp. Optional exact-match filters on attribute and unit. Read-only.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `irods_path` (required) | string |  | Absolute iRODS path of the data object or collection whose AVU history to read. Must sit inside a MESA-enabled project. |
| `attribute` | string \| null | `null` | Only return rows whose AVU attribute equals this string exactly. |
| `unit` | string \| null | `null` | Only return rows whose AVU unit equals this string exactly. Pass an empty string to match rows with no unit. |
| `as_of` | string \| null | `null` | ISO-8601 timestamp (`2026-09-01T12:00:00Z`). When set, return the AVUs in effect at that instant instead of the change log. A timestamp with no zone is read as UTC. |
| `limit` | integer | `100` | Maximum number of rows to return. Default 100; values above 1000 are capped at 1000. |

Output: `project_id`, `count` and `rows`. Each row is a mesa-ducklake `AvuChange`: `project_id`, `snapshot_id`, `irods_path`, `target_type`, `attribute`, `value`, `unit`, `op` (`add` or `delete`), `actor`, `ts`, `source`, `via_ticket`, `rule_invocation`. Errors: `not_mesa_project`, `history_project_not_registered`, `history_failed_catalog_lookup`, `history_failed_read`, `invalid_argument` (bad `as_of`).

### `mesa_ducklake_init_project`

Enroll an iRODS collection as a MESA project. Creates the <irods_path>/.mesa/ducklake/ sub-collection (or the configured ducklake.data_collection), sets the mesa.enabled=true AVU on the project root, and registers the project in the DuckLake catalog. Idempotent — safe to re-run.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `irods_path` (required) | string |  | Absolute iRODS path of the project's root collection — the collection that will carry the `mesa.enabled=true` AVU and host the DuckLake history sub-collection (`.mesa/ducklake/` unless `ducklake.data_collection` says otherwise). |

Output: `project_id`, `irods_path`, `irods_zone`, `ducklake_path`, `created_at`, `created_by`, `status`. Errors name the failing step: `init_project_failed_root_missing`, `init_project_failed_irods_create`, `init_project_failed_avu_add`, `init_project_failed_catalog_register`, and so on.

### `mesa_ducklake_time_travel`

Return the AVUs that were in effect on an iRODS path inside a MESA-enabled project at a past timestamp, read from the project's DuckLake. Changes stamped at exactly as_of are included. Optional exact-match filters on attribute and unit. Read-only.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `irods_path` (required) | string |  | Absolute iRODS path of the data object or collection whose AVUs to read. Must sit inside a MESA-enabled project. |
| `as_of` (required) | string |  | ISO-8601 timestamp (`2026-09-01T12:00:00Z`). Returns the AVUs in effect at that instant; a change stamped at exactly this time is included. A timestamp with no zone is read as UTC. Snapshot ids are not supported. |
| `attribute` | string \| null | `null` | Only return AVUs whose attribute equals this string exactly. |
| `unit` | string \| null | `null` | Only return AVUs whose unit equals this string exactly. Pass an empty string to match AVUs with no unit. |
| `limit` | integer | `100` | Maximum number of AVUs to return. Default 100; values above 1000 are capped at 1000. |

Output: `project_id`, `as_of` (normalized, UTC), `count` and `rows` (`AvuChange` records, sorted by attribute, value, unit). A bare integer `as_of` is refused: snapshot ids are not supported. Errors: `not_mesa_project`, `time_travel_project_not_registered`, `time_travel_failed_catalog_lookup`, `time_travel_failed_read`, `invalid_argument`.

## mesa_policy_*: MESA project policies

Toggle a MESA-defined policy on a project root by adding or removing the `mesa.policy.<name>=true` AVU. They do not change the iRODS server's own policy configuration. The change is mirrored to the AVU history when the root is MESA-enabled; a mirror failure is ignored.

### `mesa_policy_disable`

Disable a MESA policy on a project root collection by removing the ``mesa.policy.<policy_name>`` AVU. Records the change into the project's DuckLake when MESA-enabled.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `project_path` (required) | string |  | iRODS path of the project root collection. |
| `policy_name` (required) | string |  | Short policy identifier (becomes the suffix of the `mesa.policy.<name>` AVU). |

### `mesa_policy_enable`

Enable a MESA policy on a project root collection by writing the ``mesa.policy.<policy_name>=true`` AVU. Records the change into the project's DuckLake when MESA-enabled.

| Field | Type | Default | Description |
| ----- | ---- | ------- | ----------- |
| `project_path` (required) | string |  | iRODS path of the project root collection. |
| `policy_name` (required) | string |  | Short policy identifier (becomes the suffix of the `mesa.policy.<name>` AVU). |

## See also

- [Metadata workflows](examples.md) for these tools in sequence.
- [Configuration](configuration.md)
- [Adding tools](../dev/adding-tools.md)

Last synced with the registry: 2026-11-24.
