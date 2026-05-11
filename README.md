# mesa-mcp

**mesa-mcp** is an MCP (Model Context Protocol) server that exposes the
CyVerse Data Store (iRODS) as a set of `ds_*` tools, layers an
ontology-driven AVU metadata workflow on top using the EMBL-EBI Ontology
Lookup Service (OLS), and mirrors every AVU change into a per-project
DuckLake catalog so the full metadata history is queryable and
time-travelable. It is the Python sibling of `cyverse/irods-mcp-server` and
the agent-facing counterpart of the ontology UI in `cyverse/esiil-portal`.

For the full architecture, conventions, and design decisions, read
[`CLAUDE.md`](./CLAUDE.md). This README only covers running the scaffold.

## Documentation

Full docs live under [`docs/`](./docs/README.md), split by audience:

- **Users** — [getting started](./docs/user/getting-started.md),
  [configuration](./docs/user/configuration.md),
  [tools reference](./docs/user/tools-reference.md),
  [Claude Desktop wiring](./docs/user/claude-desktop.md),
  [examples](./docs/user/examples.md).
- **Developers** — [architecture](./docs/dev/architecture.md),
  [adding tools](./docs/dev/adding-tools.md),
  [porting from Go](./docs/dev/porting-from-go.md),
  [OLS internals](./docs/dev/ols-internals.md),
  [testing](./docs/dev/testing.md),
  [contributing](./docs/dev/contributing.md).
- **Operators** — [overview](./docs/deploy/overview.md),
  [systemd](./docs/deploy/systemd.md),
  [HTTP / SSE](./docs/deploy/http-sse.md),
  [OIDC](./docs/deploy/oidc.md),
  [Nginx + TLS](./docs/deploy/nginx-tls.md),
  [Postgres](./docs/deploy/postgres.md),
  [monitoring](./docs/deploy/monitoring.md).

## Status

Pre-alpha. Today the server registers a single liveness tool, `ds_ping`,
which echoes a message and the running version. The full `ds_*`, `mesa_ols_*`,
and `mesa_ducklake_*` tool surfaces land in subsequent PRs — see `CLAUDE.md`
for the plan.

## Quick start

Requires Python 3.11+.

```bash
# From a clean venv:
pip install -e ".[dev]"

# Run the server over stdio with an example config:
cp config.yaml.example config.yaml
mesa-mcp --config config.yaml

# Run the test suite:
pytest -q

# Lint:
ruff check src/ tests/
```

Configuration precedence is `flag > env > YAML file > defaults`. Environment
variables use the `MESA_MCP_` prefix with `__` as the section delimiter —
see `.env.example`.

## Repository layout

```
src/mesa_mcp/      Python package
  __main__.py      CLI entrypoint (flag parsing, dispatch to server.run)
  server.py        MCP server bootstrap + tool registry
  config.py        Pydantic config + loader
  errors.py        Structured ToolError
  logging.py       structlog setup
  irods/           Stubs for iRODS tools, client pool, access checks
  ols/             Stubs for OLS client, transform, and ontology tools
  ducklake/        Stubs for mesa-ducklake facade
tests/             pytest suite (asyncio mode)
config.yaml.example
.env.example
```

## License

BSD 3-Clause. See `LICENSE`.
