# OLS internals

What this page covers: the `OLSClient` HTTP wrapper, its seven-cache
layout, and the AVU shape contract that mesa-mcp shares with
`cyverse/esiil-portal`. If you are authoring `mesa_ols_*` or
`mesa_avu_*` tools, the inflexible bits live here.

## Origin

[`src/mesa_mcp/ols/client.py`](../../src/mesa_mcp/ols/client.py) is a
verbatim port (minus Django `cache` calls) of
`esiil-portal/portal/services/ols_client.py`. Public method signatures
and return shapes are preserved — parity work is mechanical. If you
need to extend the API surface, prefer adding a new method over
changing an existing one.

[`src/mesa_mcp/ols/transform.py`](../../src/mesa_mcp/ols/transform.py)
is a pure-Python port with no behavioural changes from
`esiil-portal/portal/services/ols_transform.py`. Reserved attribute
prefixes (`datacite`, `dc`, `eml`, `ipc-`, `irods::`, `ipc_`) are
unchanged.

## API endpoints

OLS4 is public. No authentication. Two base URLs are in play:

- `https://www.ebi.ac.uk/ols4/api/v2` — REST v2 (ontologies, classes,
  term details). `OLSClient.base_url` defaults here.
- `https://www.ebi.ac.uk/ols4/api/search` — v1-compat search endpoint
  with the `allChildrenOf` filter we use for descendant-of searches.
  Hard-coded in `OLSClient` as `OLS_SEARCH_URL`.

## Retry policy

The `requests.Session` inside `OLSClient` mounts an `HTTPAdapter` with
`Retry(total=2, backoff_factor=0.5, status_forcelist=[429, 502, 503,
504], allowed_methods=["GET"])`. So the client retries idempotent GETs
twice with 0.5s exponential backoff on the transient codes OLS itself
emits during deploys. Authoring code should not add another retry
layer on top.

## Cache layout

`OLSClient` ships seven distinct `cachetools.TTLCache` instances. Each
has `maxsize=4096`. The TTL choices are the portal's, preserved so
behaviour matches:

| Cache field           | Used for                          | TTL    |
| --------------------- | --------------------------------- | ------ |
| `_cache_catalog`      | full ontology catalog listings    | 24 h   |
| `_cache_ontology`     | per-ontology metadata             | 24 h   |
| `_cache_search`       | free-text searches                | 1 h    |
| `_cache_term`         | per-term records                  | 24 h   |
| `_cache_children`     | child listings of a term          | 12 h   |
| `_cache_desc_search`  | descendants-of searches           | 1 h    |
| `_cache_template`     | generated template documents      | 24 h   |

Cache keys are SHA-256 hex digests of the request signature so the
keyspace is stable across processes and free of secret material.

The `OLSConfig` fields (`ontology_cache_ttl`, `term_cache_ttl`,
`search_cache_ttl`) in `mesa_mcp.config` are honoured by the loader,
but the `OLSClient` constructor does **not** read them — it uses the
hard-coded portal values above. This is a known gap; wiring the
config-driven TTLs through is an open task. Until it lands, edits to
the config fields have no effect on cache behaviour.

## The AVU contract

This is the contract `esiil-portal` already writes and mesa-mcp must
match. It is **frozen**.

```python
{
    "attribute": f"{ontology_id}.{snake_case(label)}",  # e.g. "envo.biome"
    "value":     <user-supplied value or term label>,
    "unit":      <term CURIE>,                          # e.g. "ENVO:01000228"
}
```

Three things to internalise:

1. **`ontology_id` is lowercased.** Always. The transform calls
   `ontology_id.lower()` before composing the attribute.
2. **The unit field carries the CURIE.** That is the marker that
   identifies an AVU as ontology-sourced. The reverse transformation
   (AVU → annotation in `avus_to_ontology_annotations`) keys off
   `unit`'s `<PREFIX>:<localID>` pattern.
3. **The IRI does not appear in the AVU.** Only the CURIE. The IRI
   stays in metadata fields outside the AVU triple (e.g. the term
   record returned by `mesa_ols_get_term`).

The snake-case helper lives in `OLSClient._label_to_snake` and is the
function `mesa_avu_from_term` re-uses, so labels are converted
identically to how the portal does it. Do not roll your own.

## One ontology per AVU

A single AVU attribute carries one ontology prefix. If you need to
record terms from two ontologies, write two AVUs. The detection
function `detect_ontology_prefixes` in `transform.py` assumes this
convention and skips reserved prefixes (`datacite`, `dc`, `eml`,
`ipc-`, `irods::`, `ipc_`) automatically.

## Round-trip invariants

Round-trip with `esiil-portal/portal/services/ols_transform.py`:

- `ontology_annotations_to_avus(...)` → list of AVUs.
- `avus_to_ontology_annotations(...)` → reconstructs the original
  annotation list (modulo whitespace stripping).
- `extract_ontology_avus(...)` → filters a flat AVU list to one
  ontology's worth.

When you author a tool that writes AVUs, add a unit test exercising
the round-trip. The `mcp-reviewer` agent in
[`.claude/agents/mcp-reviewer.md`](../../.claude/agents/mcp-reviewer.md)
checks for this.

## Authoring `mesa_ols_*` and `mesa_avu_*` tools

The auto-discovery loop in
[`src/mesa_mcp/ols/tools/__init__.py`](../../src/mesa_mcp/ols/tools/__init__.py)
imports every non-underscore module in the directory, which is what
fires the `@register_tool` decorators. Drop a `.py` file in there and
the tool is registered on next `import mesa_mcp.ols`.

The currently registered tools are:

- `mesa_ols_list_ontologies`
- `mesa_ols_get_ontology`
- `mesa_ols_search_terms`
- `mesa_ols_get_term`
- `mesa_ols_get_term_hierarchy`
- `mesa_ols_generate_template`
- `mesa_avu_from_term` (pure transform — no iRODS write)

`mesa_avu_apply_term` (composite: pick term + path + value → write AVU
+ DuckLake record) is **planned**. It waits on iRODS auth and
`ds_add_avu`. See `CLAUDE.md` and
[`.claude/agents/ols-tool-author.md`](../../.claude/agents/ols-tool-author.md)
for the spec.

## Singleton client access

Tool handlers fetch the process-wide client through
`get_default_client()` in `mesa_mcp.ols.__init__`. The function builds
the singleton on first call; tests substitute a mock via
`set_default_client(MagicMock(...))` before invoking handlers. Calling
the constructor directly inside a handler is a smell — it bypasses the
cache and re-initialises seven `TTLCache`s every call.

## Error surface

`OLSClient` raises `OLSAPIError(message, status_code)` for upstream
issues. Tool handlers catch this and translate to a structured
response. The convention seen in `mesa_ols_search_terms` is to return
`{"results": [], "error": str(exc), "status_code": exc.status_code}`
rather than raising; for tools that semantically must succeed (`mesa_
avu_from_term` resolving a term), raise
`ToolError(code="upstream_error")`.

## See also

- [Architecture](./architecture.md)
- [Adding tools](./adding-tools.md)
- [Tools reference](../user/tools-reference.md)
- [`.claude/agents/ols-tool-author.md`](../../.claude/agents/ols-tool-author.md)
- [`src/mesa_mcp/ols/client.py`](../../src/mesa_mcp/ols/client.py)
- [`src/mesa_mcp/ols/transform.py`](../../src/mesa_mcp/ols/transform.py)
