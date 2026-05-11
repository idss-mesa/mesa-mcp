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

## Deployment modes

mesa-mcp ships in three deployment modes. Pick the one that matches your
situation:

- **Mode A — Hosted service.** A single shared instance runs as a systemd
  unit behind nginx + Let's Encrypt + CyVerse Keycloak OIDC, and several
  users connect to it with their own bearer tokens. See
  [docs/deploy/overview.md](./docs/deploy/overview.md). A live instance is
  running on `mesa-mcp.cis240692.projects.jetstream-cloud.org`.
- **Mode B — Local on a workstation.** You `pip install` mesa-mcp into a
  venv on your laptop and your MCP client (Claude Desktop, Claude Code,
  Cline, Continue) launches it as a stdio subprocess. No HTTP, no OIDC,
  no public hostname. See [docs/user/local-install.md](./docs/user/local-install.md).
- **Mode C — Inside a CyVerse Discovery Environment VICE app.** You launch
  a JupyterLab, RStudio Server, or Cloud Shell app on
  [de.cyverse.org](https://de.cyverse.org/) and `pip install` mesa-mcp
  inside the pod, where your iRODS credentials are already mounted. See
  [docs/user/vice-apps.md](./docs/user/vice-apps.md).

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
