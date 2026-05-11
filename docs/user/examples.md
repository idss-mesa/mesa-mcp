# Examples

What this page covers: end-to-end usage walkthroughs using the tools that
ship today. mesa-mcp's iRODS write side is still being built, so the
worked examples lean on the OLS browsing tools and the pure-transform AVU
helper that **are** wired up. The intended end-state flows (full
read/write, ticket lifecycle, DuckLake time-travel) are sketched at the
end of the page so you can see where each piece will plug in.

All examples below are written as a series of MCP tool calls. The exact
syntax depends on your MCP client (Claude Desktop, Claude Code, the
Inspector). The JSON payload shape is identical in every client.

## Worked example: ontology browsing → AVU computation

This is the working subset of the OBO/OLS metadata flow. You can run it
end-to-end against today's mesa-mcp build.

### 1. List the available ontologies

```json
{"tool": "mesa_ols_list_ontologies", "input": {"page": 1, "size": 10}}
```

Response (truncated):

```json
{
  "ontologies": [
    {"ontologyId": "envo", "title": "Environment Ontology", "numberOfTerms": 8284, ...},
    {"ontologyId": "go", "title": "Gene Ontology", "numberOfTerms": 50000, ...},
    ...
  ],
  "totalElements": 266
}
```

### 2. Pick an ontology and search for a term

```json
{
  "tool": "mesa_ols_search_terms",
  "input": {
    "query": "tropical forest",
    "ontology_id": "envo",
    "size": 5
  }
}
```

Response (truncated):

```json
{
  "results": [
    {
      "label": "tropical moist broadleaf forest",
      "curie": "ENVO:00000428",
      "iri": "http://purl.obolibrary.org/obo/ENVO_00000428",
      "ontologyId": "envo"
    },
    ...
  ],
  "count": 5
}
```

### 3. Walk the hierarchy if you want narrower terms

```json
{
  "tool": "mesa_ols_get_term_hierarchy",
  "input": {
    "ontology_id": "envo",
    "iri": "http://purl.obolibrary.org/obo/ENVO_00000428"
  }
}
```

You get the direct children of the chosen term. Recurse via successive
calls to walk further down. The `descendants_of` filter on
`mesa_ols_search_terms` is the equivalent search-side primitive.

### 4. Inspect the chosen term in detail

```json
{
  "tool": "mesa_ols_get_term",
  "input": {
    "ontology_id": "envo",
    "iri": "http://purl.obolibrary.org/obo/ENVO_00000428"
  }
}
```

You get the full record — definition, synonyms, parents, children. Use
this to surface a definition to a researcher before they commit to a
metadata tag.

### 5. Build the AVU triple

```json
{
  "tool": "mesa_avu_from_term",
  "input": {
    "ontology_id": "envo",
    "value": "tropical moist broadleaf forest",
    "iri": "http://purl.obolibrary.org/obo/ENVO_00000428"
  }
}
```

Response:

```json
{
  "avu": {
    "attribute": "envo.biome",
    "value": "tropical moist broadleaf forest",
    "unit": "ENVO:00000428"
  },
  "term": {
    "ontologyId": "envo",
    "label": "biome",
    "curie": "ENVO:00000428",
    "iri": "http://purl.obolibrary.org/obo/ENVO_00000428"
  }
}
```

The AVU triple is **exactly** the shape `esiil-portal` already writes —
attribute is `<ontology_id>.<snake_case_label>`, unit is the CURIE,
value is whatever the user supplied. This contract is the centrepiece of
mesa-mcp / portal interoperability.

### 6. Write it to iRODS *(planned)*

The composite tool `mesa_avu_apply_term` will take the inputs above plus
an iRODS path and:

1. Validate the path against the caller's accessible paths.
2. Resolve the OLS term (if not already supplied).
3. Build the AVU triple via the same transform you saw above.
4. Write the AVU via the same code path as `ds_add_avu`.
5. Record a change row into the project's DuckLake.

`mesa_avu_apply_term` is **not implemented yet**. It is deferred until
iRODS auth + `ds_add_avu` land. See
[`../../CLAUDE.md`](../../CLAUDE.md) for the plan and
[`../dev/contributing.md`](../dev/contributing.md) for who is working on
each piece.

## Worked example: template-driven form generation

If you have an MCP client that renders schema forms, the
`mesa_ols_generate_template` tool gives you a SCHEMAS-compatible template
for an ontology's top-level classes:

```json
{
  "tool": "mesa_ols_generate_template",
  "input": {
    "ontology_id": "envo",
    "template_name": "ENVO top-level"
  }
}
```

This is the same function that drives `esiil-portal`'s auto-generated
metadata forms. Use it to expose a structured form to an end user without
hand-writing the schema.

## Planned: ticket-based workflow

When the ticket lifecycle tools land, the intended flow looks like this:

```text
ds_create_ticket     -> mint a read-or-write ticket against a path
ds_use_ticket        -> open a ticket-mediated session on the MCP server
ds_read_file / ds_add_avu / ... -> tools run as the ticket bearer
ds_modify_ticket     -> tighten uses, expiry, or host restrictions
ds_delete_ticket     -> revoke
```

Every ticket-mediated AVU write will be recorded into DuckLake with a
`via_ticket` provenance column, so auditors can trace which changes came
through shared credentials. See `CLAUDE.md` Group 1b for the full
description; none of these tools are registered today.

## Planned: AVU time-travel

Once `mesa_ducklake_*` lands:

```text
mesa_ducklake_init_project  -> bootstrap /.mesa/ducklake on a project
mesa_avu_apply_term         -> writes AVU + records change row
mesa_ducklake_history       -> list every AVU change for a path
mesa_ducklake_time_travel   -> reconstruct AVU set at a past timestamp
mesa_ducklake_diff          -> diff two snapshots
```

The DuckLake facade in
[`src/mesa_mcp/ducklake/client.py`](../../src/mesa_mcp/ducklake/client.py)
defines the interface but every method currently raises
`NotImplementedError`.

## See also

- [Tools reference](./tools-reference.md)
- [Configuration](./configuration.md)
- [OLS internals](../dev/ols-internals.md) for the AVU shape contract.
- [`../../CLAUDE.md`](../../CLAUDE.md) for the full goal list.
