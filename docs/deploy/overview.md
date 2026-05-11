# Deployment overview

What this page covers: the **hosted-service** production topology
mesa-mcp is built for — the components, the data flow, and where each
piece runs on the as-deployed VM (Ubuntu 24.04, systemd 255, repo at
`/home/exouser/mesa-mcp/`). Detailed setup instructions for each
component live in the sibling pages.

## Three deployment modes — this page covers Mode A

mesa-mcp deploys in three modes. **This page covers Mode A: a shared,
hosted service fronted by nginx + OIDC.** A single mesa-mcp systemd unit
listens on a local SSE port; nginx terminates TLS and forwards to it;
CyVerse Keycloak provides per-user bearer tokens. Multiple users connect
to one mesa-mcp process. The pages in this directory (`systemd`,
`http-sse`, `oidc`, `nginx-tls`, `postgres`, `monitoring`) all describe
Mode A artifacts.

For the other two modes, read:

- **Mode B (local on a workstation):** [`../user/local-install.md`](../user/local-install.md).
  pip-install into a venv on your laptop, run as a stdio subprocess of
  Claude Desktop / Claude Code / Cline / Continue. No nginx, no OIDC, no
  systemd unit.
- **Mode C (inside a CyVerse VICE app):** [`../user/vice-apps.md`](../user/vice-apps.md).
  pip-install inside a JupyterLab / RStudio / Cloud Shell pod where the
  user's iRODS credentials are already mounted. Stdio transport, in-pod
  Claude Code is the natural client.

The topology, component table, and run-mode notes below describe
**Mode A only**. They do not apply to Modes B or C.

## Topology

```
                                                              ┌──────────────────────┐
                                                              │  CyVerse iRODS       │
                                                              │  data.cyverse.org    │
                                                              │  port 1247           │
                                                              └──────────▲───────────┘
                                                                         │ iRODS native
                                                                         │ protocol
                              ┌──────────────────────────────────────────┴───────────┐
                              │                                                      │
                              │             VM (Ubuntu 24.04)                        │
                              │             /home/exouser/mesa-mcp                   │
                              │                                                      │
   ┌──────────────────────┐   │   ┌─────────────────────────────────────────────┐    │
   │  MCP client          │   │   │  mesa-mcp (systemd unit, exouser)            │    │
   │  Claude Desktop /    │◀─ stdio ─▶│  src/mesa_mcp/server.py                   │    │
   │  Claude Code /       │   │   │   tool registry + auth + iRODS pool         │    │
   │  Inspector           │   │   └─────────────┬───────────────────────────────┘    │
   └──────────────────────┘   │                 │                                    │
                              │                 │  Postgres (planned)                │
                              │                 ▼                                    │
                              │   ┌─────────────────────────────────────────────┐    │
                              │   │  postgresql@15-main (systemd)               │    │
                              │   │  database: mesa_ducklake                    │    │
                              │   │  (catalog for mesa-ducklake — planned)      │    │
                              │   └─────────────────────────────────────────────┘    │
                              │                                                      │
                              │   ┌─────────────────────────────────────────────┐    │
                              │   │  nginx + Let's Encrypt (planned, when SSE)  │    │
                              │   └─────────────────────────────────────────────┘    │
                              │                                                      │
                              └──────────────────────────────────────────────────────┘

                              ┌──────────────────────┐
                              │  EMBL-EBI OLS4 API   │
                              │  www.ebi.ac.uk       │
                              │  (public, no auth)   │
                              └──────────────────────┘
                                         ▲
                                         │ HTTPS (cached via cachetools.TTLCache)
                                         │
                              ┌──────────┴───────────┐
                              │  mesa-mcp (in proc)  │
                              └──────────────────────┘

                              ┌──────────────────────┐
                              │  CyVerse Keycloak    │
                              │  kc.cyverse.org      │
                              │  (planned, for SSE)  │
                              └──────────────────────┘
```

## Component table

| Component                           | Role                                                                 | Status                          |
| ----------------------------------- | -------------------------------------------------------------------- | ------------------------------- |
| `mesa-mcp` (systemd service)        | The Python MCP server. Stdio transport today, SSE planned.           | Shipping (stdio only)           |
| `python-irodsclient` (in process)   | Native iRODS protocol to `data.cyverse.org:1247`.                    | Library installed; tools land   |
| OLS HTTP client (in process)        | `https://www.ebi.ac.uk/ols4/api`, cached via `cachetools.TTLCache`.  | Shipping                        |
| Postgres `mesa_ducklake` database   | DuckLake catalog (for the sibling `mesa-ducklake` project).          | Planned                         |
| nginx + Let's Encrypt               | Reverse proxy fronting the SSE port, terminating TLS.                | Planned (only needed for SSE)   |
| CyVerse Keycloak                    | OIDC IdP for the SSE transport.                                      | Planned                         |
| journald                            | Log sink for the systemd unit.                                       | Shipping                        |

## Run modes

mesa-mcp has two intended run modes:

1. **stdio under an MCP client.** The client launches `mesa-mcp` as a
   subprocess, talks to it over stdin/stdout. No port, no TLS, no
   IdP. This is what works today. See
   [`../user/claude-desktop.md`](../user/claude-desktop.md) for client
   wiring.
2. **Long-running daemon, SSE over HTTP.** mesa-mcp runs as a systemd
   service listening on a local TCP port; nginx fronts it with TLS; a
   CyVerse Keycloak bearer token authenticates each connection. This
   is the planned remote-access path. The implementation is gated on
   the OIDC PR; see [`./http-sse.md`](./http-sse.md) and
   [`./oidc.md`](./oidc.md).

Mode (1) does not need most of what follows — no nginx, no Keycloak,
no remote port. The systemd unit in [`./systemd.md`](./systemd.md) is
still useful as a convenience launcher under one consistent user, and
the Postgres setup in [`./postgres.md`](./postgres.md) is required for
the eventual DuckLake integration regardless of transport.

## VM facts (the as-deployed environment)

- OS: Ubuntu 24.04 LTS.
- systemd: 255.
- Unprivileged user: `exouser`.
- Repository: `/home/exouser/mesa-mcp` (git checkout).
- Venv: `/home/exouser/mesa-mcp/.venv` (created with `python3.11 -m
  venv`).
- Console entry point: `/home/exouser/mesa-mcp/.venv/bin/mesa-mcp`.
- Sibling services on the same VM:
  - `esiil-portal.service` runs the Django portal — its unit file at
    `/home/exouser/esiil-portal/esiil-portal.service` is the reference
    pattern we mirror.

## Reference units

- [`/home/exouser/esiil-portal/esiil-portal.service`](../../README.md)
  — the security-hardened systemd unit on this VM. Mesa-mcp's unit
  borrows its `ProtectSystem=strict`, `ProtectHome=read-only`,
  `ReadWritePaths`, and append-only log file patterns.
- [`/home/exouser/irods-mcp-server/install/irods-mcp-server.service`](../../README.md)
  — the much simpler reference unit from the Go sibling. Useful for
  cross-checking the minimum viable `[Unit]` / `[Service]` block.

## See also

- [systemd](./systemd.md)
- [HTTP / SSE transport](./http-sse.md)
- [OIDC](./oidc.md)
- [Nginx + TLS](./nginx-tls.md)
- [Postgres](./postgres.md)
- [Monitoring](./monitoring.md)
- [`../user/local-install.md`](../user/local-install.md) — Mode B on a
  workstation.
- [`../user/vice-apps.md`](../user/vice-apps.md) — Mode C inside a
  CyVerse VICE app.
- [`../user/configuration.md`](../user/configuration.md)
- [`../../CLAUDE.md`](../../CLAUDE.md)
