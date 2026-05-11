# Adding tools

What this page covers: the `@register_tool` decorator pattern used by
every mesa-mcp tool, walked through with a real worked example
(`ds_ping`). When you finish reading you should be able to add a new
tool, validate its inputs, return a JSON-serializable result, and confirm
the registry picked it up.

## The pattern in one minute

```python
from pydantic import BaseModel
from mesa_mcp.server import register_tool


class MyToolInput(BaseModel):
    """Input schema."""
    name: str


@register_tool(
    "my_tool",
    "One-line description shown in the agent's tool list.",
    input_model=MyToolInput,
)
async def handle_my_tool(args: MyToolInput) -> dict:
    return {"hello": args.name}
```

The `@register_tool` decorator captures the handler, the description,
and the Pydantic input model into a `ToolSpec` and appends it to a
module-level registry. When `MesaServer` is constructed, the registry
is snapshotted and turned into MCP `Tool` records by
`_build_mcp_server` in [`server.py`](../../src/mesa_mcp/server.py).

## The `ds_ping` example

Open [`src/mesa_mcp/server.py`](../../src/mesa_mcp/server.py) and look
around line 113. The relevant block is:

```python
class DsPingInput(BaseModel):
    """Input schema for the ds_ping smoke-test tool."""

    message: str | None = None


@register_tool(
    "ds_ping",
    "Liveness check. Echoes back the supplied message (or 'ok') and the "
    "running mesa-mcp version. No iRODS access required.",
    input_model=DsPingInput,
)
async def handle_ds_ping(args: DsPingInput) -> dict[str, Any]:
    return {
        "pong": args.message if args.message else "ok",
        "version": __version__,
    }
```

Three things to notice:

1. **Pydantic model with optional fields.** `message: str | None = None`
   gives MCP clients a clean "string-or-omit" schema. Pydantic emits the
   correct JSON Schema via `model_json_schema()`; the MCP SDK forwards
   it to the client.
2. **Async handler taking the parsed model.** `handle_ds_ping` is
   `async def` and accepts `args: DsPingInput`. The dispatcher in
   `_invoke_handler` validates the raw `dict` against the model before
   calling the handler, so by the time your code runs the input is
   typed.
3. **Plain `dict` return.** The handler returns a JSON-serializable
   `dict`. The MCP SDK boundary in `_call_tool` JSON-encodes it into a
   single `TextContent` block. Non-dict returns raise an
   `internal_error` ToolError — a useful guardrail.

## Step-by-step: adding a new tool

1. **Pick the home directory.** Conventions:
   - `src/mesa_mcp/ols/tools/<name>.py` for `mesa_ols_*` /
     `mesa_avu_*` tools (auto-discovered).
   - `src/mesa_mcp/irods/tools/<name>.py` for `ds_*` tools.
   - Top-level `src/mesa_mcp/server.py` only for built-in / smoke-test
     tools (`ds_ping`).

2. **Define the input model.** Use Pydantic v2. Field descriptions are
   surfaced to the MCP client, so write them as if they were the
   tooltip:

   ```python
   from pydantic import BaseModel, Field

   class ListDirectoryInput(BaseModel):
       path: str = Field(..., description="Absolute iRODS logical path.")
       limit: int = Field(100, ge=1, le=1000, description="Max entries.")
   ```

3. **Write the handler.** Async function taking the parsed input model.
   Return a `dict`. Raise `ToolError` for user-visible failures.

   ```python
   from mesa_mcp.errors import ToolError

   async def handle_list_directory(args: ListDirectoryInput) -> dict:
       if args.limit > 1000:
           # Pydantic catches this — illustrative example only.
           raise ToolError(
               code="invalid_argument",
               message="limit must be <= 1000",
               details={"limit": args.limit},
           )
       # ... real iRODS work here ...
       return {"path": args.path, "entries": []}
   ```

4. **Decorate with `@register_tool`.** Match the name to the convention
   in `CLAUDE.md` (`ds_*`, `mesa_ols_*`, `mesa_avu_*`,
   `mesa_ducklake_*`).

5. **Confirm registration.** From the repo root:

   ```bash
   .venv/bin/python -c "
   import mesa_mcp.server
   import mesa_mcp.ols       # populates OLS tools
   try:
       import mesa_mcp.irods.tools  # populates iRODS tools when wired
   except Exception:
       pass
   for spec in sorted(mesa_mcp.server.get_registered_tools(), key=lambda s: s.name):
       print(spec.name)
   "
   ```

   Your tool should appear in the alphabetical list.

6. **Write a unit test.** See [Testing](./testing.md). The convention is
   `tests/<area>/test_<tool>.py`; for `ds_*` tools, use the
   `mock_irods_session` fixture in `tests/conftest.py`.

## What `register_tool` does under the hood

```python
def register_tool(name, description, *, input_model=None):
    def decorator(handler):
        if name in _REGISTRY:
            raise ValueError(f"Tool {name!r} already registered")
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            handler=handler,
            input_model=input_model,
        )
        return handler
    return decorator
```

The registry is a plain `dict[str, ToolSpec]`. There is no metaclass,
no plugin system — just import-time side effects. The trick that makes
auto-discovery work is at the bottom of
[`src/mesa_mcp/ols/tools/__init__.py`](../../src/mesa_mcp/ols/tools/__init__.py):

```python
for _module_info in pkgutil.iter_modules([str(_PACKAGE_PATH)]):
    if _module_info.name.startswith("_"):
        continue
    importlib.import_module(f"{__name__}.{_module_info.name}")
```

So any `.py` file you drop into `src/mesa_mcp/ols/tools/` is imported
as soon as `mesa_mcp.ols` is imported. The same pattern is intended for
`src/mesa_mcp/irods/tools/` once it is populated.

## Dispatch path

When a client calls your tool, the request walks this path:

1. MCP SDK's `call_tool` callback in
   [`server.py`](../../src/mesa_mcp/server.py) receives `(name,
   arguments)`.
2. `MesaServer.call(name, arguments)` looks up the `ToolSpec` and calls
   `_invoke_handler`.
3. `_invoke_handler` validates `arguments` against `spec.input_model`
   (raising `ToolError(code="invalid_argument")` on failure) and calls
   `spec.handler(parsed)`.
4. The handler's `dict` return is JSON-encoded into a single
   `TextContent` block and shipped back to the client.

Any `ToolError` raised inside the handler is caught at the boundary and
turned into `{"error": {code, message, details}}`. Other exceptions
propagate — wrap broad I/O in `try/except` and re-raise as `ToolError`
when you want the client to see a clean message.

## Conventions

- **Naming.** Keep the prefix (`ds_*`, `mesa_ols_*`, `mesa_avu_*`,
  `mesa_ducklake_*`) consistent with `CLAUDE.md`. The prefix is the
  observable contract — agents key off it.
- **Descriptions.** Two-or-three sentence. Mention any side effects.
- **Output shape.** Structured JSON for machine-readable fields plus a
  short human-readable summary if you want (`formation-mcp`'s pattern).
- **Path safety.** Every `ds_*` tool that takes a path must call
  `mesa_mcp.irods.access.assert_allowed(path, auth_value)` before
  touching iRODS. Use the returned normalised path.
- **DuckLake hook.** AVU-write tools call
  `ducklake_client.record_changes(...)` *after* a successful iRODS
  write. Skip silently if the project is not MESA-enabled.

## See also

- [Architecture](./architecture.md)
- [Porting from Go](./porting-from-go.md) — when the tool you are
  adding has a `irods-mcp-server` counterpart.
- [Testing](./testing.md)
- [`src/mesa_mcp/server.py`](../../src/mesa_mcp/server.py) — the
  registry implementation.
- [`src/mesa_mcp/ols/tools/avu_from_term.py`](../../src/mesa_mcp/ols/tools/avu_from_term.py)
  — a non-trivial worked example.
