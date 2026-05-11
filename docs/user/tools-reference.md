# Tools reference

What this page covers: every MCP tool registered by mesa-mcp at import
time, grouped by prefix. Tools are listed alphabetically within each
group. Each entry lists its description and input fields; for full
output shapes, read the source module linked at the end of each entry.

**Tools registered today: 44** across 4 groups.

To regenerate this page from a checkout:

```bash
.venv/bin/python -c "
import mesa_mcp.server, mesa_mcp.ols, mesa_mcp.irods.tools
for spec in sorted(mesa_mcp.server.get_registered_tools(), key=lambda s: s.name):
    print(spec.name)
"
```

## Contents

- [ds_*: CyVerse Data Store (iRODS)](#ds_-cyverse-data-store-irods)
- [mesa_avu_*: AVU helpers (ontology-driven)](#mesa_avu_-avu-helpers-ontology-driven)
- [mesa_ols_*: OBO Foundry / EBI Ontology Lookup Service](#mesa_ols_-obo-foundry--ebi-ontology-lookup-service)
- [mesa_policy_*: MESA project policies](#mesa_policy_-mesa-project-policies)

## ds_*: CyVerse Data Store (iRODS)

### `ds_add_avu`

Add a new AVU (attribute-value-unit) to a file (data-object), directory (collection), resource, or user.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `target_type` (required) | `string` | The type of the target to add AVU. It can be 'path', 'resource', or 'user'. |
| `target` (required) | `string` | The target to add AVU. Path for 'path' target_type, resource name for 'resource' target... |
| `attribute` (required) | `string` | The attribute of the AVU to add. |
| `value` (required) | `string` | The value of the AVU to add. |
| `unit` | `string` | The unit of the AVU to add. Default is an empty string. |

Source: search the codebase for `register_tool("ds_add_avu"`.

### `ds_copy_file`

Copy a file (data-object) or directory (collection) to a new location.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `source_path` (required) | `string` | The path to the source file (data-object) or directory (collection). If directory path ... |
| `destination_path` (required) | `string` | The new, complete path to copy the file (data-object) or directory (collection) to, inc... |

Source: search the codebase for `register_tool("ds_copy_file"`.

### `ds_create_ticket`

Create a read or write iRODS ticket on a data object or collection. Returns the ticket string plus the restrictions that were applied. Anonymous users may not create tickets.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The iRODS path the ticket grants access to. |
| `mode` (required) | `string` | Ticket access mode: 'read' or 'write'. |
| `uses_allowed` | `integer \| null` | Maximum number of times this ticket may be used. |
| `expiry` | `string \| null` | ISO-8601 timestamp at which the ticket expires. |
| `write_byte_limit` | `integer \| null` | Maximum bytes that may be written via this ticket (write tickets only). |
| `host_restriction` | `string \| null` | Restrict ticket usage to clients connecting from this host. |
| `user_restriction` | `string \| null` | Restrict ticket usage to this iRODS user. |

Source: search the codebase for `register_tool("ds_create_ticket"`.

### `ds_delete_avu`

Delete an AVU (attribute-value-unit) from a file, directory, resource, or user.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `target_type` (required) | `string` | The type of the target to delete AVU. It can be 'path', 'resource', or 'user'. |
| `target` (required) | `string` | The target to delete AVU. Path for 'path' target_type, resource name for 'resource' tar... |
| `id` | `integer` | The ID of the AVU to delete. |
| `attribute` | `string` | The attribute of the AVU to delete. This field can be ignored if ID is provided. |
| `value` | `string` | The value of the AVU to delete. Default is an empty string. |
| `unit` | `string` | The unit of the AVU to delete. Default is an empty string. |

Source: search the codebase for `register_tool("ds_delete_avu"`.

### `ds_delete_file`

Delete a file (data-object) or directory (collection).

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the file (data-object) or directory (collection) to delete. |

Source: search the codebase for `register_tool("ds_delete_file"`.

### `ds_delete_ticket`

Revoke an existing iRODS ticket. Issuer or admin only — the server enforces this. Anonymous callers are rejected at the tool layer.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ticket` (required) | `string` | The ticket string to delete. |

Source: search the codebase for `register_tool("ds_delete_ticket"`.

### `ds_directory_tree`

Get a recursive tree view of files (data-objects) and directories (collections).
		The specified path must be an iRODS path. The output is in JSON format.
		The output contains all entries in the given directory (collection) path.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the directory (collection) to list. |
| `depth` | `integer` | The depth of the directory tree to list. Default value is 3. Depth must be greater than... |

Source: search the codebase for `register_tool("ds_directory_tree"`.

### `ds_download_file`

Returns how to download the full contgent of a file (data-object) with the specified path.
		The specified path must be an iRODS path.
		Returns how to download the file using WebDAV, GoCommands (gocmd), and iCommands.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `irods_path` (required) | `string` | The iRODS path to the file (data-object) to download. |
| `local_path` (required) | `string` | The local path to download the file (data-object) to. Must be a full path including the... |

Source: search the codebase for `register_tool("ds_download_file"`.

### `ds_execute_rule`

Run an iRODS rule. Supply either rule_name (server-installed) or rule_text (inline iRL). Output parameters are returned as a dict; iRODS stdout/stderr are returned when output_parameters includes 'ruleExecOut'. Path-typed input parameters are checked against the caller's accessible paths before the rule fires.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `rule_name` | `string \| null` | Name of a server-installed rule to invoke. |
| `rule_text` | `string \| null` | Inline iRL fragment to execute. |
| `input_parameters` | `object` | Input parameters bound into the rule body. |
| `output_parameters` | `array` | Names of rule output parameters to return. |
| `instance_name` | `string` | Rule engine instance to target. |

Source: search the codebase for `register_tool("ds_execute_rule"`.

### `ds_get_file_info`

Retrieve detailed metadata about a file or directory.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the file (data-object) or directory (collection). |

Source: search the codebase for `register_tool("ds_get_file_info"`.

### `ds_get_metadata`

Fetch the full AVU metadata bundle for an iRODS path (data object or collection). Returns the resolved target type alongside the AVU list.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | Absolute iRODS path of the data object or collection whose metadata you want. |

Source: search the codebase for `register_tool("ds_get_metadata"`.

### `ds_get_policy_config`

Return the configuration of a named Policy Composition Framework policy. iRODS does not expose PCF config through PRC; this is a stub that returns ``config=None`` and a ``note`` documenting the limitation.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `name` (required) | `string` | Name of the PCF policy to introspect. |

Source: search the codebase for `register_tool("ds_get_policy_config"`.

### `ds_get_rule_definition`

Return the source of a named iRODS rule. iRODS does not expose rule sources through PRC; this is a best-effort tool whose ``definition`` field is None on most servers.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `name` (required) | `string` | Name of the rule to introspect. |

Source: search the codebase for `register_tool("ds_get_rule_definition"`.

### `ds_get_ticket_info`

Get information about a specific iRODS ticket, such as its ID and expiration time, in JSON format. Anonymous users are not allowed to get ticket information.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `name` (required) | `string` | The name of the iRODS ticket to get information about. |

Source: search the codebase for `register_tool("ds_get_ticket_info"`.

### `ds_list_allowed_directories`

Get a list of directories (collections) that this server is allowed to access.
		The output also contains API names that can be requested to each directory (collection).

Source: search the codebase for `register_tool("ds_list_allowed_directories"`.

### `ds_list_avus`

List AVUs (attribute-value-unit) from a file (data-object), directory (collection), resource, or user.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `target_type` (required) | `string` | The type of the target to list AVU. It can be 'path', 'resource', or 'user'. |
| `target` (required) | `string` | The target to list AVU. Path for 'path' target_type, resource name for 'resource' targe... |

Source: search the codebase for `register_tool("ds_list_avus"`.

### `ds_list_directory`

Get a list of files (data-objects) and directories (collections) in a specified path.
		The specified path must be an iRODS path. The output is in JSON format.
		The output contains entries in the given directory (collection) path. Use offset and limit parameters to paginate through large directories.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the directory (collection) to list. |
| `offset` | `integer` | Number of entries to skip (for pagination). Default: 0. |
| `limit` | `integer` | Maximum number of entries to return (for pagination). Default: 100, max: 500. |

Source: search the codebase for `register_tool("ds_list_directory"`.

### `ds_list_directory_details`

Get a list of files (data-objects) and directories (collections) in a specified path with full detailed info.
		The specified path must be an iRODS path. The output is in JSON format.
		The output contains entries in the given directory (collection) path, and users or groups who can access the files (data-ojects). Files (data-objects) will also have replica information. Use offset and limit parameters to paginate through large directories.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the directory (collection) to list. |
| `offset` | `integer` | Number of entries to skip (for pagination). Default: 0. |
| `limit` | `integer` | Maximum number of entries to return (for pagination). Default: 100, max: 500. |

Source: search the codebase for `register_tool("ds_list_directory_details"`.

### `ds_list_policies`

List active policies in the iRODS Policy Composition Framework. iRODS does not expose PCF state through PRC; this tool returns a documented stub envelope with a ``note`` describing the limitation.

Source: search the codebase for `register_tool("ds_list_policies"`.

### `ds_list_rules`

List iRODS rules visible to the caller. Returns a best-effort list of delayed rules; the static rule base is not exposed by PRC and the ``note`` field documents that limitation.

Source: search the codebase for `register_tool("ds_list_rules"`.

### `ds_list_tickets`

Get a list of iRODS tickets. Return information about the tickets, such as their IDs and expiration times, in JSON format. Anonymous users are not allowed to list tickets.

Source: search the codebase for `register_tool("ds_list_tickets"`.

### `ds_make_directory`

Make a new directory (collection).

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the new directory to create. |

Source: search the codebase for `register_tool("ds_make_directory"`.

### `ds_modify_access`

Modify data access of a user or group to a file (data-object) or directory (collection).

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `access_level` (required) | `string` | The access level to set to the user. It can be 'own', 'delete_object', 'modify_object',... |
| `user_or_group` (required) | `string` | The user or group to set access. You can specify a user by 'username#zone' or a group b... |
| `path` (required) | `string` | The path to the file (data-object) or directory (collection) to modify access. |
| `recurse` | `boolean` | If set, apply the given access to all entries within the given directory (collection) r... |

Source: search the codebase for `register_tool("ds_modify_access"`.

### `ds_modify_access_inheritance`

Modify data access inheritance flag of a file or directory.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the directory (collection) to modify access. |
| `inherit` (required) | `boolean` | If set, access to the directory (collection) will be inherited by all child entries. |
| `recurse` | `boolean` | If set, apply the inheritance flag to all entries within the given directory (collectio... |

Source: search the codebase for `register_tool("ds_modify_access_inheritance"`.

### `ds_modify_ticket`

Modify restrictions on an existing iRODS ticket. Cannot change the ticket's mode — that is set at issuance time. Returns the applied restrictions. Anonymous users are not allowed to modify tickets.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ticket` (required) | `string` | The ticket string to modify. |
| `uses` | `integer \| null` | New uses-allowed cap. |
| `expiry` | `string \| null` | New ISO-8601 expiry timestamp. |
| `write_byte_limit` | `integer \| null` | New write-byte limit (write tickets only). |
| `host_restriction` | `string \| null` | Add an allowed-host restriction. |
| `user_restriction` | `string \| null` | Add an allowed-user restriction. |

Source: search the codebase for `register_tool("ds_modify_ticket"`.

### `ds_move_file`

Move a file (data-object) or directory (collection) to a new location.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `old_path` (required) | `string` | The old path to the file (data-object) or directory (collection). |
| `new_path` (required) | `string` | The new, complete path to move the file (data-object) or directory (collection) to, inc... |

Source: search the codebase for `register_tool("ds_move_file"`.

### `ds_ping`

Liveness check. Echoes back the supplied message (or 'ok') and the running mesa-mcp version. No iRODS access required.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `message` | `string \| null` | — |

Source: search the codebase for `register_tool("ds_ping"`.

### `ds_read_file`

Read the partial content of a file (data-object) with the specified path and offset.
		The specified path must be an iRODS path.
		If the file is too large to be displayed inline, use the WebDAV URI to access it.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the file (data-object) to read. |
| `offset` | `integer` | The offset to start reading the file from. Default is 0. |
| `length` | `integer` | The maximum length of the file to read. Default value is 1048576. Length must be greate... |

Source: search the codebase for `register_tool("ds_read_file"`.

### `ds_search_files`

Recursively search for files (data-objects) and directories (collections) matching a pattern.
		The specified search root path must be an iRODS path. Use unix wildcards, such as '?' and '*', for the search pattern. 
		The matching entries are returned in JSON format.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The search path, which may include wildcard patterns such as '?' and '*'. |

Source: search the codebase for `register_tool("ds_search_files"`.

### `ds_search_files_by_avu`

Search for files (data-objects) and directories (collections) matching iRODS AVU (attribute-value-units) using specified attribute and value. The matching entries are returned in JSON format.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `attribute` (required) | `string` | The attribute to search for. |
| `value` (required) | `string` | The value of the attribute to search for. |

Source: search the codebase for `register_tool("ds_search_files_by_avu"`.

### `ds_search_metadata`

Search iRODS by AVU attribute/value/unit. More permissive than ds_search_files_by_avu: any combination of attribute, value, and unit can be supplied and you can restrict the result type to data objects, collections, or both.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `attribute` | `string \| null` | Match only AVUs with this attribute name. |
| `value` | `string \| null` | Match only AVUs with this value. |
| `unit` | `string \| null` | Match only AVUs with this unit (often an ontology CURIE). |
| `target` | `string` | Restrict results to data objects, collections, or both. |

Source: search the codebase for `register_tool("ds_search_metadata"`.

### `ds_upload_file`

Returns how to upload the full contgent of a file (data-object) to the specified path.
		The specified path must be an iRODS path.
		Returns how to upload the file using WebDAV, GoCommands (gocmd), and iCommands.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `local_path` (required) | `string` | The local path to the file (data-object) to upload. |
| `irods_path` (required) | `string` | The target iRODS path to upload the file (data-object) to. |
| `is_dir` | `boolean` | Set to true if uploading a directory (collection). Default is false. |

Source: search the codebase for `register_tool("ds_upload_file"`.

### `ds_use_ticket`

Bind an iRODS ticket to the current MCP call. Subsequent AVU writes made in the same call record the ticket id in DuckLake's via_ticket column. Does not modify the caller's primary session.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ticket` (required) | `string` | The ticket string to use for subsequent operations. |

Source: search the codebase for `register_tool("ds_use_ticket"`.

### `ds_write_file`

Write the partial content to a file (data-object) with the specified path and offset.
		The specified path must be an iRODS path.
		If the file is too large to be displayed inline, use the WebDAV URI to access it.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | The path to the file (data-object) to write to. |
| `offset` | `integer` | The offset to start writing the file from. Default is 0. |
| `content` (required) | `string` | The Base64-encoded content to write to the file (data-object). Maximum size is 1048576 ... |

Source: search the codebase for `register_tool("ds_write_file"`.

## mesa_avu_*: AVU helpers (ontology-driven)

### `mesa_avu_apply_term`

Resolve an OLS term, build the canonical AVU triple (<ontology>.<snake_label>, <value>, <CURIE>), write it to the iRODS path, and record the change in the project's DuckLake. Composite of mesa_avu_from_term + ds_add_avu, in one call.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `path` (required) | `string` | Absolute iRODS path of the data object or collection to tag. |
| `ontology_id` (required) | `string` | Ontology identifier (e.g. 'envo'). |
| `value` (required) | `string` | User-supplied AVU value. Often the term label, but free-form. |
| `iri` | `string \| null` | Full IRI of the OLS term. Either ``iri`` or ``curie`` is required. |
| `curie` | `string \| null` | CURIE of the OLS term (e.g. 'ENVO:00000428'). |
| `label` | `string \| null` | Optional term label. When omitted, the label is looked up via OLS so the AVU attribute ... |

Source: search the codebase for `register_tool("mesa_avu_apply_term"`.

### `mesa_avu_from_term`

Pure transformation: turn an OLS term + user value into the canonical AVU triple (attribute='<ontology>.<snake_case_label>', value=<value>, unit=<CURIE>) without writing to iRODS.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ontology_id` (required) | `string` | Ontology identifier (e.g. 'envo'). |
| `value` (required) | `string` | User-supplied AVU value. Often the term label, but free-form. |
| `iri` | `string \| null` | Full IRI of the term to use. Either ``iri`` or ``curie`` must be supplied, alongside ``... |
| `curie` | `string \| null` | Term CURIE (e.g. 'ENVO:00000428') — used directly as the AVU unit. |
| `label` | `string \| null` | Term label. If omitted, mesa-mcp fetches it from OLS using ``ontology_id`` + ``iri``. |

Source: search the codebase for `register_tool("mesa_avu_from_term"`.

## mesa_ols_*: OBO Foundry / EBI Ontology Lookup Service

### `mesa_ols_generate_template`

Generate a SCHEMAS-compatible template (prefix + top-level term fields) for an ontology. This is the function that drives the esiil-portal auto-generated AVU forms.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ontology_id` (required) | `string` | Ontology identifier to generate a template for (e.g. 'envo'). |

Source: search the codebase for `register_tool("mesa_ols_generate_template"`.

### `mesa_ols_get_ontology`

Fetch metadata for a single OLS ontology (term count, version, homepage, preferred prefix).

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ontology_id` (required) | `string` | Ontology identifier, e.g. 'envo', 'go', 'chebi'. Case-insensitive. |

Source: search the codebase for `register_tool("mesa_ols_get_ontology"`.

### `mesa_ols_get_term`

Get the full record (label, CURIE, synonyms, definition, parents/children) for a single OLS term by IRI.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ontology_id` (required) | `string` | Ontology identifier (e.g. 'envo'). |
| `iri` (required) | `string` | Full term IRI, e.g. 'http://purl.obolibrary.org/obo/ENVO_00000428'. |

Source: search the codebase for `register_tool("mesa_ols_get_term"`.

### `mesa_ols_get_term_hierarchy`

List the direct children of an OLS term. Use this to walk an ontology's class hierarchy one level at a time.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `ontology_id` (required) | `string` | Ontology identifier (e.g. 'envo'). |
| `iri` (required) | `string` | Full IRI of the parent term. |
| `size` | `integer` | Max children to return. |

Source: search the codebase for `register_tool("mesa_ols_get_term_hierarchy"`.

### `mesa_ols_list_ontologies`

List ontologies available in the EMBL-EBI Ontology Lookup Service (OLS4), paginated. Returns 266+ ontologies (ENVO, GO, CHEBI, etc.).

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `page` | `integer` | Zero-indexed page number. |
| `size` | `integer` | Results per page (1–200). |

Source: search the codebase for `register_tool("mesa_ols_list_ontologies"`.

### `mesa_ols_search_terms`

Search OLS terms across all ontologies or scoped to one. Optionally restrict to descendants of a parent IRI (hierarchy walk).

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `query` (required) | `string` | Free-text search string. |
| `ontology_id` | `string \| null` | Optional ontology to restrict the search (e.g. 'envo'). |
| `descendants_of` | `string \| null` | Optional parent term IRI. When set together with ``ontology_id``, only descendants of t... |
| `size` | `integer` | Max results. |

Source: search the codebase for `register_tool("mesa_ols_search_terms"`.

## mesa_policy_*: MESA project policies

### `mesa_policy_disable`

Disable a MESA policy on a project root collection by removing the ``mesa.policy.<policy_name>`` AVU. Records the change into the project's DuckLake when MESA-enabled.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `project_path` (required) | `string` | iRODS path of the project root collection. |
| `policy_name` (required) | `string` | Short policy identifier (becomes the suffix of the ``mesa.policy.<name>`` AVU). |

Source: search the codebase for `register_tool("mesa_policy_disable"`.

### `mesa_policy_enable`

Enable a MESA policy on a project root collection by writing the ``mesa.policy.<policy_name>=true`` AVU. Records the change into the project's DuckLake when MESA-enabled.

Input fields:

| Field | Type | Description |
| ----- | ---- | ----------- |
| `project_path` (required) | `string` | iRODS path of the project root collection. |
| `policy_name` (required) | `string` | Short policy identifier (becomes the suffix of the ``mesa.policy.<name>`` AVU). |

Source: search the codebase for `register_tool("mesa_policy_enable"`.

## See also

- [Configuration](./configuration.md)
- [Examples](./examples.md)
- [Adding tools](../dev/adding-tools.md)

Last synced: 2026-05-10. Re-run the enumeration command
at the top of this page after adding or removing tools.
