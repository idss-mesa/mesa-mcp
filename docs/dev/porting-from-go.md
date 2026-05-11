# Porting from Go (cyverse/irods-mcp-server)

What this page covers: how to translate a `ds_*` tool from the Go
reference implementation in
[`cyverse/irods-mcp-server`](https://github.com/cyverse/irods-mcp-server)
into mesa-mcp's Python tool surface. mesa-mcp is a **drop-in replacement**
at the MCP wire level: tool names, descriptions, input schemas, and
output shapes must match the Go source byte-for-byte.

This guide is the same checklist the `irods-tool-porter` sub-agent at
[`.claude/agents/irods-tool-porter.md`](../../.claude/agents/irods-tool-porter.md)
follows. Invoke that agent for batch ports; read on for the manual
walkthrough.

## Why parity matters

Existing MCP clients (Claude Desktop configs, Claude Code workflows,
integration scripts) bind to the wire shape of the Go server. If
mesa-mcp's `ds_list_directory` accepts a slightly different input
schema, every client breaks silently. Parity is a stable contract — the
ontology and DuckLake tools layer **on top** of it without disturbing
it.

## Source of truth

The Go file at
`/home/exouser/irods-mcp-server/irods/<tool_name>.go` is the spec.
Open it before writing any Python. The interface contract lives in
`irods-mcp-server/irods/interface.go`:

```go
type ToolAPI interface {
    GetName() string
    GetDescription() string
    GetTool() *mcp.Tool              // includes InputSchema
    GetHandler() mcp.ToolHandler
    GetAccessiblePaths(*common.AuthValue) []string
}
```

For each Go tool you port, extract:

1. `name` — the tool name (e.g. `ds_list_directory`).
2. `description` — the description string passed to `mcp.NewTool`.
3. Input schema — the `Properties` and `Required` fields. Each property
   has a name, type, and description; these become Pydantic fields with
   matching descriptions.
4. Handler body — the iRODS calls and the response shape.
5. Access policy — what paths the handler restricts itself to.

## Translation table

| Go (`go-irodsclient`)                            | Python (`python-irodsclient`)                                              |
| ------------------------------------------------ | -------------------------------------------------------------------------- |
| `fs.ListEntries(path)`                           | `session.collections.get(path).data_objects` + `.subcollections`           |
| `fs.ReadFile(path)`                              | `session.data_objects.open(path, 'r').read()`                              |
| `fs.WriteFile(path, data)`                       | `session.data_objects.open(path, 'w').write(data)`                         |
| `fs.AddMetadata(path, k, v, u)`                  | `session.metadata.add(DataObject, path, AVU(k, v, u))`                     |
| `fs.ListMetadata(path)`                          | `session.metadata.get(DataObject, path)`                                   |
| `fs.DeleteMetadata(path, k, v, u)`               | `session.metadata.remove(DataObject, path, AVU(k, v, u))`                  |
| `fs.SearchByMetadata(k, v)`                      | `session.query(...).filter(Criterion(...))`                                |
| `fs.GetCollection(path)`                         | `session.collections.get(path)`                                            |
| `fs.MoveFile / MoveCollection`                   | `session.data_objects.move(src, dst)` / `session.collections.move(...)`    |
| `fs.CopyFile / CopyCollection`                   | `session.data_objects.copy(src, dst)` / `session.collections.copy(...)`    |
| `fs.MakeCollection(path, recurse)`               | `session.collections.create(path, recurse=True)`                           |
| `fs.RemoveCollection(path, recurse, force)`      | `session.collections.remove(path, recursive=True, force=True)`             |

Collection vs data-object **matters**: the metadata model class
(`Collection` or `DataObject`) must match the iRODS thing you are
addressing or the call silently no-ops.

## Path-access enforcement

The Go side calls `GetAccessiblePaths(*common.AuthValue)` and the
middleware refuses any path outside the returned set. In Python:

```python
from mesa_mcp.irods.access import assert_allowed

async def handle_list_directory(args, ctx):
    path = assert_allowed(args.path, ctx.auth_value)
    # ... use `path` (normalised) in all iRODS calls below ...
```

`assert_allowed` returns the normalised path. **Use the return value** —
do not pass `args.path` to the iRODS calls — so handlers can never drift
off the access-checked path. The implementation lives in
[`access.py`](../../src/mesa_mcp/irods/access.py).

## Connection management

Don't open `iRODSSession` directly inside the handler. Take it from
the per-process `IRODSClientPool` keyed by `AuthValue.cache_key()`. The
pool lives in
[`client_pool.py`](../../src/mesa_mcp/irods/client_pool.py); it LRU-evicts
when the cap is hit. Construction looks like this from a fixture or
bootstrap:

```python
from mesa_mcp.irods.client_pool import IRODSClientPool

pool = IRODSClientPool(config=config)
session = pool.get(auth_value)
```

For a test, build the pool with a `session_factory=MagicMock` so no
TCP connection opens. See [Testing](./testing.md).

## Worked walkthrough: porting `ds_list_directory`

Imagine you are porting `ds_list_directory` from
`irods-mcp-server/irods/list_directory.go`.

1. **Read** the Go source. Note the tool name, description string, and
   the JSON Schema input (typically `{"path": "string", "limit":
   "integer"}` with `path` required).

2. **Create** `src/mesa_mcp/irods/tools/list_directory.py`:

   ```python
   from pydantic import BaseModel, Field
   from typing import Any

   from mesa_mcp.errors import ToolError
   from mesa_mcp.irods.access import assert_allowed
   from mesa_mcp.server import register_tool


   class ListDirectoryInput(BaseModel):
       path: str = Field(..., description="Absolute iRODS logical path.")
       limit: int = Field(100, ge=1, le=10000)


   @register_tool(
       "ds_list_directory",
       "List entries (subcollections + data objects) in an iRODS collection.",
       input_model=ListDirectoryInput,
   )
   async def handle_list_directory(args: ListDirectoryInput) -> dict[str, Any]:
       # context plumbing for auth_value + session pool will land with
       # the iRODS auth PR. For now this stub matches the wire shape.
       ...
   ```

3. **Register**. The file lives in `irods/tools/`; when that directory
   gains an auto-discovery `__init__.py` (mirroring `ols/tools/`), the
   tool wires itself up on import. Until then, register it manually
   from `irods/tools/__init__.py`.

4. **Test**. Add `tests/irods/test_list_directory.py` using the
   `mock_irods_session` fixture in `tests/conftest.py`. Assert against
   the call shape, not the network.

5. **Run** the registry-introspection one-liner from
   [Adding tools](./adding-tools.md) to confirm registration.

## Things that often trip people up

- **AVU shape is `(attribute, value, unit)`** with no extra fields. Do
  not invent `created_at` or `created_by` columns; iRODS doesn't store
  them and `esiil-portal` doesn't read them.
- **Collections and data objects are different model classes.** A path
  that is a collection cannot be passed to `session.data_objects.*`.
- **iRODS metadata queries are case-sensitive on values, not
  attributes**, matching the Go server's behaviour. Do not silently
  lowercase.
- **Path normalisation must happen before access checks.** Use
  `assert_allowed`, which itself calls `normalize` internally.
- **Errors must be `ToolError`, not raw exceptions.** Wrap
  `irods.exception.*` and re-raise with a stable `code` string the
  client can switch on.

## Reviewer checklist

Before opening a PR, run the `mcp-reviewer` sub-agent from
[`.claude/agents/mcp-reviewer.md`](../../.claude/agents/mcp-reviewer.md).
It checks MCP wire-format parity with the Go source, path-access
enforcement, AVU shape, DuckLake recording, security hygiene, and test
coverage. See [Contributing](./contributing.md) for the broader PR
workflow.

## See also

- [Architecture](./architecture.md)
- [Adding tools](./adding-tools.md)
- [Testing](./testing.md)
- [Contributing](./contributing.md)
- [`.claude/agents/irods-tool-porter.md`](../../.claude/agents/irods-tool-porter.md)
- [`.claude/agents/mcp-reviewer.md`](../../.claude/agents/mcp-reviewer.md)
