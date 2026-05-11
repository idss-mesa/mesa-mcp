# mesa-mcp documentation

What this page covers: the entry point to mesa-mcp's docs. mesa-mcp is an MCP
(Model Context Protocol) server that bridges the CyVerse Data Store (iRODS),
the EMBL-EBI Ontology Lookup Service (OLS), and the per-project DuckLake
metadata catalog. The pages below are split by audience: users running the
server, developers extending it, and operators deploying it.

For the high-level architecture rationale and design decisions, read
[`../CLAUDE.md`](../CLAUDE.md). For the running-on-this-machine quick start,
read [`../README.md`](../README.md).

## Status snapshot

mesa-mcp is in pre-alpha. As of the latest sync (see footer of each tools
page) the following tools are registered:

- `ds_ping` — liveness check.
- Seven `mesa_ols_*` / `mesa_avu_*` tools for ontology browsing and pure AVU
  computation.

The full `ds_*` iRODS surface, write-side `mesa_avu_apply_term`, and
`mesa_ducklake_*` tools are being added by parallel agents. Pages here
document what is implemented today; planned-but-not-shipped features are
flagged inline as "planned".

## For users

- [Getting started](./user/getting-started.md) — install the package, supply
  credentials, run `ds_ping` end-to-end.
- [Configuration](./user/configuration.md) — every field in `config.yaml` and
  its `MESA_MCP_*` environment-variable equivalent.
- [Tools reference](./user/tools-reference.md) — every registered tool, its
  input schema, and output shape.
- [Claude Desktop / Claude Code wiring](./user/claude-desktop.md) — JSON
  snippets for the popular MCP clients.
- [Examples](./user/examples.md) — end-to-end OBO/OLS-driven metadata flow
  and a ticket-based workflow.

## For developers

- [Architecture](./dev/architecture.md) — registry, transport, auth, and the
  dependency graph.
- [Adding tools](./dev/adding-tools.md) — the `@register_tool` decorator,
  walked through with `ds_ping` as the worked example.
- [Porting from Go](./dev/porting-from-go.md) — cookbook for matching
  `irods-mcp-server`'s wire format byte-for-byte.
- [OLS internals](./dev/ols-internals.md) — `OLSClient` cache layers and the
  AVU transform contract with `esiil-portal`.
- [Testing](./dev/testing.md) — pytest fixtures and how to mock `python-
  irodsclient` and the OLS API.
- [Contributing](./dev/contributing.md) — PR conventions and the
  `.claude/agents/` roster.

## For operators

- [Overview](./deploy/overview.md) — production topology as ASCII.
- [systemd](./deploy/systemd.md) — `.service` file and install commands for
  this Ubuntu 24.04 VM.
- [HTTP / SSE transport](./deploy/http-sse.md) — bind addresses, current
  status (not yet wired up — stdio only today).
- [OIDC](./deploy/oidc.md) — registering a CyVerse Keycloak client.
- [Nginx + TLS](./deploy/nginx-tls.md) — reverse proxy with proper SSE
  buffering and Let's Encrypt.
- [Postgres](./deploy/postgres.md) — local Postgres database for the
  mesa-ducklake catalog.
- [Monitoring](./deploy/monitoring.md) — journald, log rotation,
  health-check endpoint.

## See also

- [`../CLAUDE.md`](../CLAUDE.md) — full architecture brief.
- [`../README.md`](../README.md) — top-level quick start.
- [cyverse/irods-mcp-server](https://github.com/cyverse/irods-mcp-server) —
  the Go reference implementation mesa-mcp tracks for `ds_*` parity.
- [cyverse/esiil-portal](https://github.com/cyverse/esiil-portal) — the
  ontology-aware portal whose OLS code mesa-mcp ports.
