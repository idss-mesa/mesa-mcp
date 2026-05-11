# Testing

What this page covers: the pytest layout, the shared fixtures, and the
mocking patterns we use for `python-irodsclient` and the OLS HTTP API.
mesa-mcp's test suite is asyncio-native, hermetic by default, and runs
in under a second on a laptop.

## Running the suite

```bash
source .venv/bin/activate
pytest -q                    # full suite
pytest tests/test_smoke.py   # one file
pytest -k ds_ping            # by name
```

`pyproject.toml` sets `asyncio_mode = "auto"`, so any test function
declared `async def` is automatically discovered and run via
`pytest-asyncio` — no `@pytest.mark.asyncio` decorator needed.

## Layout

```
tests/
├── conftest.py              # shared fixtures
├── test_smoke.py            # CLI + transport smoke
├── test_auth_models.py      # AuthValue invariants
├── test_irods_access.py     # path normalisation + assert_allowed
├── test_irods_pool.py       # IRODSClientPool LRU
├── test_ols_client.py       # OLSClient with requests-mock-style stubs
├── test_ols_tools.py        # mesa_ols_* tool dispatch
└── test_ols_transform.py    # AVU round-trip
```

Tool-specific tests should follow the pattern
`tests/<area>/test_<tool>.py` once subdirectories proliferate (mirrors
`src/mesa_mcp/<area>/tools/`).

## Shared fixtures

[`tests/conftest.py`](../../tests/conftest.py) exposes two:

### `config_fixture`

A `Config` with all defaults. Use it when the code under test needs a
`Config` but you don't care which fields it reads.

```python
def test_uses_config(config_fixture):
    assert config_fixture.irods.host == "data.cyverse.org"
```

### `mock_irods_session`

A `MagicMock` shaped like a `python-irodsclient` `iRODSSession`. It
exposes `collections`, `data_objects`, `metadata`, and `query`
attributes — also `MagicMock`s — so tool handlers can be exercised
without opening a TCP connection.

```python
def test_list_dir_calls_collections_get(mock_irods_session):
    mock_irods_session.collections.get.return_value.data_objects = []
    # ... wire the session into the pool / handler ...
    # ... call the handler ...
    mock_irods_session.collections.get.assert_called_once_with("/iplant/home/alice")
```

For tools that need the pool itself mocked, build an
`IRODSClientPool(session_factory=lambda **kw: mock_irods_session)`.
The `session_factory` injection point is documented inline in
`client_pool.py`.

## Mocking the OLS HTTP API

The `OLSClient` uses `requests` under the hood. The cleanest way to
stub it is to substitute the client wholesale via
`mesa_mcp.ols.set_default_client`:

```python
from unittest.mock import MagicMock
from mesa_mcp.ols import set_default_client

def test_search_terms_dispatch():
    client = MagicMock()
    client.search_terms.return_value = [
        {"label": "biome", "curie": "ENVO:00000428", "iri": "..."},
    ]
    set_default_client(client)
    try:
        # ... await the tool handler ...
        ...
    finally:
        set_default_client(None)  # reset
```

For tests that actually want to exercise `OLSClient`'s caching or URL
shaping, use `responses` or `requests-mock` to intercept the HTTP
call. Do not let the real OLS API into a unit test — that makes the
suite flaky and slow.

## Calling registered tools directly

`MesaServer.call(name, args)` is the unit-test entry point — no MCP
SDK needed:

```python
from mesa_mcp.config import Config
from mesa_mcp.server import MesaServer

async def test_ds_ping_smoke():
    server = MesaServer(config=Config())
    result = await server.call("ds_ping", {"message": "hi"})
    assert result == {"pong": "hi", "version": ANY_STRING}
```

This dispatches through the same `_invoke_handler` that the MCP
transport uses, so input validation and error translation are
exercised.

## `clear_registry`

If you need a clean registry inside a test (rare — only when a test
itself registers a tool with `@register_tool`), call
`mesa_mcp.server.clear_registry()` and re-import the modules you need.
Otherwise leave the global registry alone.

## Path-access negative tests

Every `ds_*` tool that takes a path should have a test that supplies a
path outside the caller's allowlist and asserts a `ToolError(code=
"forbidden")` comes back. The `assert_allowed` algorithm is in
[`access.py`](../../src/mesa_mcp/irods/access.py); negative cases are
worked through in `tests/test_irods_access.py`.

## AVU round-trip tests

For any OLS code change, exercise the round-trip:

```python
from mesa_mcp.ols.transform import (
    ontology_annotations_to_avus,
    avus_to_ontology_annotations,
)

def test_round_trip():
    annotations = [{"key": "biome", "value": "forest", "curie": "ENVO:0001"}]
    avus = ontology_annotations_to_avus("envo", annotations)
    out = avus_to_ontology_annotations("envo", avus)
    assert out == annotations
```

The `mcp-reviewer` agent checks for this kind of test on OLS-touching
diffs. See [Contributing](./contributing.md).

## Linting

```bash
ruff check src/ tests/
mypy src/
```

`pyproject.toml` configures both. ruff is set to py311 with the `E F I
UP B` rule sets enabled. `mypy` runs with `strict_optional = true` and
`ignore_missing_imports = true` (so missing stubs for `irods` and
`mcp` don't drown the output).

## CI expectations

This document does not yet describe a CI pipeline — there isn't one
checked in. The expectation is that contributors run `pytest -q`,
`ruff check`, and `mypy src/` locally before opening a PR. The
`mcp-reviewer` agent reviews the diff afterwards.

## See also

- [Architecture](./architecture.md)
- [Adding tools](./adding-tools.md)
- [Porting from Go](./porting-from-go.md)
- [Contributing](./contributing.md)
- [`tests/conftest.py`](../../tests/conftest.py)
