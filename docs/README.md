# mesa-mcp documentation

What this page covers: the entry point to mesa-mcp's docs. mesa-mcp is an MCP
(Model Context Protocol) server that bridges the CyVerse Data Store (iRODS),
the EMBL-EBI Ontology Lookup Service (OLS), and the per-project DuckLake
metadata catalog. The pages below are split first by deployment mode, then
by audience: users running the server, developers extending it, and
operators deploying it.

For the high-level architecture rationale and design decisions, read
[`../CLAUDE.md`](../CLAUDE.md). For the running-on-this-machine quick start,
read [`../README.md`](../README.md).

## Pick your mode

mesa-mcp deploys in three modes. Read the one that matches your situation:

- **Want to connect *to* an already-deployed hosted mesa-mcp from your
  MCP client?** Point Claude Desktop / Claude Code / Claude.ai at a
  remote URL behind nginx + OIDC. Read
  [`user/hosted-mcp.md`](./user/hosted-mcp.md).
- **Want to *operate* a hosted mesa-mcp yourself?** A single shared
  mesa-mcp instance fronted by nginx + OIDC, with several users
  connecting via bearer tokens. Read
  [`deploy/overview.md`](./deploy/overview.md).
- **Want to install on your laptop and use with Claude Desktop, Claude
  Code, Cline, or Continue?** Local stdio install in a venv on macOS or
  Linux. Read [`user/local-install.md`](./user/local-install.md).
- **Want to use mesa-mcp inside a CyVerse VICE app (JupyterLab, RStudio
  Server, Cloud Shell)?** Per-user install inside the VICE pod, reusing
  the iRODS credentials already mounted there. Read
  [`user/vice-apps.md`](./user/vice-apps.md).

If you are not sure, start with **local-install** — it is the smallest
moving target.

## Status snapshot

mesa-mcp is in pre-alpha. As of the latest sync (see footer of each tools
page) the server registers 44 tools:

- `ds_*` — full iRODS data-store surface (read, write, AVU, ACL, tickets,
  rules, policies).
- `mesa_ols_*` / `mesa_avu_*` — ontology browsing and OBO/OLS-driven AVU
  emission.
- `mesa_policy_*` — toggle MESA project policies.

Some sub-features (server-side rule introspection, full PCF policy
listing, native loading of `~/.irods/.irodsA`) are stubs or future-work;
the relevant pages flag them inline.

## For users

- [Getting started](./user/getting-started.md) — the cross-mode entry
  point that points you at the right install page.
- [Local install](./user/local-install.md) — Mode B: pip-install into a
  venv on your workstation.
- [VICE app install](./user/vice-apps.md) — Mode C: install inside a
  CyVerse Discovery Environment app.
- [Configuration](./user/configuration.md) — every field in `config.yaml`
  and its `MESA_MCP_*` environment-variable equivalent.
- [Tools reference](./user/tools-reference.md) — every registered tool,
  its input schema, and output shape.
- [MCP client wiring](./user/claude-desktop.md) — JSON snippets for
  Claude Desktop, Claude Code, Cline, and Continue (stdio / local).
- [Hosted mesa-mcp](./user/hosted-mcp.md) — connect an MCP client to a
  remote mesa-mcp service over HTTP/SSE + OIDC.
- [Examples](./user/examples.md) — end-to-end OBO/OLS-driven metadata
  flow and a ticket-based workflow.

## For developers

- [Architecture](./dev/architecture.md) — registry, transport, auth, and
  the dependency graph.
- [Adding tools](./dev/adding-tools.md) — the `@register_tool` decorator,
  walked through with `ds_ping` as the worked example.
- [Porting from Go](./dev/porting-from-go.md) — cookbook for matching
  `irods-mcp-server`'s wire format byte-for-byte.
- [OLS internals](./dev/ols-internals.md) — `OLSClient` cache layers and
  the AVU transform contract with `esiil-portal`.
- [Testing](./dev/testing.md) — pytest fixtures and how to mock
  `python-irodsclient` and the OLS API.
- [Contributing](./dev/contributing.md) — PR conventions and the
  `.claude/agents/` roster.

## For operators (Mode A — hosted service)

- [Overview](./deploy/overview.md) — production topology as ASCII.
- [systemd](./deploy/systemd.md) — `.service` file and install commands
  for this Ubuntu 24.04 VM.
- [HTTP / SSE transport](./deploy/http-sse.md) — bind addresses and
  current status.
- [OIDC](./deploy/oidc.md) — registering a CyVerse Keycloak client.
- [Nginx + TLS](./deploy/nginx-tls.md) — reverse proxy with proper SSE
  buffering and Let's Encrypt.
- [Postgres](./deploy/postgres.md) — local Postgres database for the
  mesa-ducklake catalog.
- [Monitoring](./deploy/monitoring.md) — journald, log rotation,
  health-check endpoint.

The `deploy/*.md` pages all assume Mode A. In Mode B and Mode C there is
no nginx, no systemd unit, and no OIDC — see the user pages above.

## See also

- [`../CLAUDE.md`](../CLAUDE.md) — full architecture brief.
- [`../README.md`](../README.md) — top-level quick start.
- [cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server) —
  the Go reference implementation mesa-mcp tracks for `ds_*` parity.
- [cyverse/esiil-portal](https://github.com/cyverse/esiil-portal) — the
  ontology-aware portal whose OLS code mesa-mcp ports.
