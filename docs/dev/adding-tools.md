---
type: Guide
title: Adding tools
description: Step-by-step guide to adding an MCP tool to mesa-mcp with @register_tool (input and output models, auth_value, path checks, ToolError, the DuckLake mirror hook, tests), or shipping tools from another package through the mesa_mcp.tools entry point.
tags:
  - tools
  - development
  - register_tool
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: server
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/server.py"
    title: "register_tool, load_plugins and _invoke_handler"
    author: "team:idss-mesa"
  - id: add-avu
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/irods/tools/add_avu.py"
    title: "ds_add_avu, a write tool with path checks and the DuckLake mirror"
    author: "team:idss-mesa"
  - id: plugin-tests
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/tests/test_tool_plugins.py"
    title: "Plugin registration tests"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# Adding tools

What this page covers: how to add a tool to mesa-mcp, from the input
model to the test, and how another package can contribute tools without
changing this repository.

## The pattern in one minute

```python
from typing import Any

from pydantic import BaseModel, Field

from mesa_mcp.server import register_tool


class MyToolInput(BaseModel):
    """Input schema."""

    name: str = Field(..., description="Shown to the agent as the field's help text.")


@register_tool(
    "mesa_my_tool",
    "One- to three-sentence description shown in the agent's tool list. Mention side effects.",
    input_model=MyToolInput,
)
async def handle_my_tool(args: MyToolInput) -> dict[str, Any]:
    return {"hello": args.name}
```

`register_tool(name, description, *, input_model=None, output_model=None,
meta=None)` stores a `ToolSpec` in the registry. A duplicate name raises
`ValueError` at import time. The input model's JSON Schema becomes the
tool's `inputSchema`; `output_model`, when given, becomes its
`outputSchema` (see `ds_ping` in `server.py` for the only current
example); `meta` seeds the tool's `_meta` block.

## Step by step

### 1. Put the module in the right package

| Tool family | Directory |
| --- | --- |
| `ds_*` (iRODS) | `src/mesa_mcp/irods/tools/` |
| `mesa_ols_*`, `mesa_avu_*` (ontology), `mesa_policy_*` | `src/mesa_mcp/ols/tools/` |
| `mesa_datacite_*`, `mesa_avu_apply_datacite` | `src/mesa_mcp/datacite/tools/` |
| `mesa_ducklake_*` | `src/mesa_mcp/ducklake/tools/` |

Each of these `tools/__init__.py` files imports every module in its
directory whose name does not start with `_`, so a new file registers
itself as soon as `mesa_mcp.server` is imported. Nothing else needs
editing. Keep the prefixes: agents and the `_meta["io.mesa/surface"]`
family are keyed off them (`_tool_surface` in `server.py`). A `ds_*` tool
that exists in `cyverse/irods-mcp-server` must match its name and input
shape exactly; see [Porting from Go](porting-from-go.md).

### 2. Define the input model

Use Pydantic v2. Field descriptions reach the client, so write them as
help text. Use `Literal[...]` for fixed choices and validators for
cross-field rules (see `ds_search_metadata`, which requires at least one
of `attribute`, `value`, `unit`).

### 3. Write the handler

- `async def`, takes the parsed model, returns a JSON-serializable
  `dict`. A non-dict return becomes an `internal_error`.
- **Caller identity.** Declare a keyword-only `auth_value: AuthValue |
  None = None`. The dispatcher fills it from the request context; raise
  `ToolError(code="unauthenticated")` when it is `None`. Handlers that do
  not declare it (most OLS tools) never see it.
- **Path safety.** Call `mesa_mcp.irods.access.assert_allowed(path,
  auth_value)` before touching iRODS and use the normalized path it
  returns. It raises `forbidden` for paths outside the caller's home and
  shared trees.
- **iRODS session.** `mesa_mcp.irods.client_pool.default_pool().get(auth_value)`.
- **Failures.** Raise `ToolError(code=..., message=..., details=...)`.
  Wrap `python-irodsclient` and HTTP errors; anything else propagates.
- **Asking the user.** To ask a question instead of failing, raise
  `mesa_mcp.errors.InputRequired(message, schema, state, key)` and declare
  an `elicited` keyword to receive the answer on the follow-up call.
  `mesa_avu_apply_term` is the worked example. Treat the returned `state`
  as untrusted and re-check everything from `auth_value`.

### 4. Mirror AVU writes into the history

A tool that writes AVUs to a path calls the DuckLake facade **after** the
iRODS write succeeds:

```python
from mesa_mcp.ducklake.client import DuckLakeMirrorError, record_avu_change

try:
    await record_avu_change(
        auth_value=auth_value, irods_path=norm, target_type=path_target,
        attribute=avu["attribute"], value=avu["value"], unit=avu["unit"],
        op="add", tool_name=TOOL_NAME, session=session,
    )
except DuckLakeMirrorError as exc:
    result["partial_failure"] = {"code": "ducklake_mirror_failed", "message": str(exc)}
```

Use `record_avu_changes` (a list of `(attribute, value, unit, op)` tuples)
when one user action writes several AVUs, so they land as one snapshot.
Both are no-ops outside a MESA-enabled project or with DuckLake disabled.
`add_avu_to_irods` and `resolve_path_target` in `irods/_avu_helpers.py`
are the shared write helpers. See [DuckLake integration](ducklake-integration.md).

### 5. Test it

Drive the tool through `MesaServer.call`, which uses the same dispatcher
as the MCP adapter:

```python
from mesa_mcp.config import Config
from mesa_mcp.server import MesaServer


async def test_my_tool():
    server = MesaServer(config=Config())
    assert await server.call("mesa_my_tool", {"name": "x"}) == {"hello": "x"}
```

For iRODS tools, set `mesa_mcp.context.current_auth_value`, replace the
pool with `set_default_pool(...)` around a `MagicMock` session, and
monkeypatch `record_avu_change` on the tool module;
`tests/test_ds_avu_tools.py` shows the pattern. Add a negative test for a
path outside the allow-list. See [Testing](testing.md).

### 6. Update the docs

Add the tool to [Tools reference](../user/tools-reference.md) (the
registry listing command is at the top of that page) and to
[Metadata workflows](../user/examples.md) if users will call it in a
sequence. Then regenerate `docs/llms.txt` (see
[Contributing](contributing.md#documentation-changes)).

## Shipping tools from another package

A separate package can register tools without touching mesa-mcp. Declare
an entry point in the **`mesa_mcp.tools`** group whose module calls
`register_tool` at import time:

```toml
[project.entry-points."mesa_mcp.tools"]
decide = "mesa_anyjev.mcp_tools"
```

`MesaServer` calls `load_plugins()` at construction and imports each entry
point once. Set `meta={"io.mesa/surface": "<family>"}` on the plugin's
tools to name their family. A plugin that fails to import is skipped with
a warning, or stops the server when `MESA_MCP_SERVER__STRICT_PLUGINS=1`.
mesa-croissant (`mesa_croissant_*`) and mesa-anyjev (`mesa_decide_*`) are
built this way. `tests/test_tool_plugins.py` covers the loader.

## See also

- [Architecture](architecture.md)
- [Porting from Go](porting-from-go.md)
- [Testing](testing.md)
- [`src/mesa_mcp/ols/tools/avu_from_term.py`](https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/ols/tools/avu_from_term.py),
  a small read-only example, and
  [`src/mesa_mcp/irods/tools/add_avu.py`](https://github.com/idss-mesa/mesa-mcp/blob/main/src/mesa_mcp/irods/tools/add_avu.py),
  a write tool with the mirror.
