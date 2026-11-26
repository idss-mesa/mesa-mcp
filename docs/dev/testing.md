---
type: Guide
title: Testing
description: How to run mesa-mcp's hermetic pytest suite and linters, the test layout and fixtures, how iRODS, OLS and mesa-ducklake are mocked, and what each CI job (tests on Python 3.11-3.13, DuckLake integration, MCP 2026-07-28 conformance, docs) checks.
tags:
  - testing
  - pytest
  - ci
generated:
  by: "claude/opus-5.5"
  at: "2026-11-24T00:00:00Z"
sources:
  - id: ci
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/.github/workflows/ci.yml"
    title: "CI workflow"
    author: "team:idss-mesa"
  - id: tests
    resource: "https://github.com/idss-mesa/mesa-mcp/tree/main/tests"
    title: "mesa-mcp test suite"
    author: "team:idss-mesa"
  - id: pyproject
    resource: "https://github.com/idss-mesa/mesa-mcp/blob/main/pyproject.toml"
    title: "pytest, ruff and mypy settings"
    author: "team:idss-mesa"
status: stable
stale_after: "2027-05-24T00:00:00Z"
---

# Testing

What this page covers: how to run the test suite and linters, how the
tests are laid out, the mocking patterns for `python-irodsclient`, the
OLS API and mesa-ducklake, and what CI checks. The suite is hermetic: it
needs no iRODS server, no OLS network access and no Postgres, and it runs
in a few seconds.

## Run it

Python 3.11 or newer.

```bash
pip install -e ".[dev]"
pytest -q                       # full suite
pytest tests/test_smoke.py -q   # one file
pytest -k ds_ping -q            # by name
ruff check src/ tests/          # lint (CI gate)
mypy src/                       # types (advisory in CI)
```

`pyproject.toml` sets `asyncio_mode = "auto"`, so `async def` tests run
without a marker, and `addopts = "-ra"`, so skips are summarized at the
end. Read that summary: a green run can hide skipped tests.

**Skips to expect.** Three tests in `tests/test_config_active.py` skip
unless the optional `ducklake` extra is installed, with the reason
"requires the optional 'ducklake' extra". To run them:

```bash
pip install "mesa-ducklake @ git+https://github.com/idss-mesa/mesa-ducklake@main"
pip install -e ".[dev,ducklake]"
pytest -q tests/test_config_active.py
```

**Local iRODS files can leak in.** Credential resolution reads
`~/.irods/irods_environment.json`. On a machine where `iinit` has been
run, `tests/test_zone_configuration.py::test_anonymous_caller_gets_only_the_configured_shared_tree`
picks up that identity and fails. Point the variables at nothing to keep
the run hermetic:

```bash
IRODS_ENVIRONMENT_FILE=/nonexistent IRODS_AUTHENTICATION_FILE=/nonexistent pytest -q
```

## Layout

```
tests/
├── conftest.py                       # config_fixture, mock_irods_session
├── irods/                            # ds_* tools: files, directories, access, tickets,
│                                     #   rules, policies, via_ticket provenance
├── transport/                        # /healthz, OIDC, SSE auth, Streamable HTTP, RFC 9728
├── test_ds_avu_tools.py              # the AVU ds_* tools and their DuckLake mirror calls
├── test_ds_add_avus.py               # bulk AVU write + record_avu_changes
├── test_ducklake_*.py                # facade, init_project, history, time_travel
├── test_config_active.py             # real mesa-ducklake (skips without the extra)
├── test_mesa_avu_apply_term.py       # composite ontology write
├── test_mrtr_ontology.py             # multi-round-trip term selection
├── test_ols_*.py                     # OLSClient, OLS tools, AVU transforms
├── test_datacite_*.py                # schema, transform, export, tools
├── test_spec_conformance_2026_07_28.py
├── test_tool_plugins.py              # mesa_mcp.tools entry points
└── test_auth_models.py, test_irods_*.py, test_keycloak_claims.py,
    test_config_integrity.py, test_zone_configuration.py, test_smoke.py, …
```

## Calling tools directly

`MesaServer.call(name, args)` is the entry point for tests. It goes
through the same `_invoke_handler` as the MCP adapter, so validation and
error translation are exercised:

```python
from mesa_mcp.config import Config
from mesa_mcp.server import MesaServer


async def test_ds_ping():
    result = await MesaServer(config=Config()).call("ds_ping", {"message": "hi"})
    assert result["pong"] == "hi"
```

## Mocking iRODS

`tests/conftest.py` provides `mock_irods_session`, a `MagicMock` shaped
like an `iRODSSession` (`collections`, `data_objects`, `metadata`,
`query`). For tool tests:

- set the caller with `mesa_mcp.context.current_auth_value.set(AuthValue(...))`;
- replace the pool with `mesa_mcp.irods.client_pool.set_default_pool(...)`
  around a pool or stub that returns the mock session;
- for AVU write tools, monkeypatch `record_avu_change` on the tool module
  to assert the mirror call without a catalog.

`tests/test_ds_avu_tools.py` shows all three. Every path-taking tool
should also have a negative test that passes a path outside the caller's
home and shared trees and expects `ToolError(code="forbidden")`; the
algorithm and its edge cases are in `tests/test_irods_access.py`.

## Mocking OLS

Swap the process-wide client:

```python
from unittest.mock import MagicMock
from mesa_mcp.ols import set_default_client

client = MagicMock()
client.search_terms.return_value = [{"label": "biome", "curie": "ENVO:00000428", "iri": "…"}]
set_default_client(client)
try:
    ...  # call the tool
finally:
    set_default_client(None)
```

Never let the real OLS API into a unit test. For OLS code changes, add a
round-trip test of `ontology_annotations_to_avus` and
`avus_to_ontology_annotations`.

## Mocking mesa-ducklake

`mesa_mcp.ducklake.client.set_default_client(fake)` injects a fake
`DuckLakeClient`; `reset_default_client()` and `reset_project_cache()`
restore a clean state. The `test_ducklake_*.py` files use this, so they
run without mesa-ducklake installed.

## CI

`.github/workflows/ci.yml` runs on every pull request and on pushes to
`main`:

| Job | What it does |
| --- | --- |
| `test` (Python 3.11, 3.12, 3.13) | `pip install -e ".[dev]"`, `ruff check src/ tests/`, `mypy src/` (allowed to fail), `pytest -q`. |
| `ducklake-integration` | Installs mesa-ducklake from `idss-mesa/mesa-ducklake@main` with the `ducklake` extra and runs `tests/test_config_active.py`. **Fails if any of those tests skip**, so the real config-to-`DuckLakeClient` path is always exercised. |
| `spec-conformance` | Asserts the `mcp` SDK resolved to 2.x, runs `tests/test_spec_conformance_2026_07_28.py` and `tests/transport/`, and fails if `src/` uses deprecated MCP features (`sampling/createMessage`, `roots/list`, `logging/setLevel`). An extra run with `-W error::DeprecationWarning` is advisory. |

`.github/workflows/docs.yml` validates the documentation: OKF frontmatter
on every page, and that `docs/llms.txt` and `docs/llms-full.txt` match a
fresh `scripts/gen_llms_txt.py` run. On `main` it also builds and deploys
the site. See [Contributing](contributing.md#documentation-changes).

## See also

- [Adding tools](adding-tools.md)
- [DuckLake integration](ducklake-integration.md)
- [Contributing](contributing.md)
