---
type: Reference
title: Deployment overview
description: 'Topology and components of a hosted mesa-mcp (Mode A): a systemd service running the HTTP transport behind nginx and TLS, CyVerse Keycloak tokens, an optional Postgres catalog for AVU history, and the as-deployed VM.'
tags:
- deploy
- hosted
- topology
generated:
  by: claude/opus-5.5
  at: '2026-11-24T00:00:00Z'
sources:
- id: deploy-dir
  resource: https://github.com/idss-mesa/mesa-mcp/tree/main/deploy
  title: Deployment artifacts (systemd, nginx, installers)
  author: team:idss-mesa
status: stable
stale_after: '2027-02-24T00:00:00Z'
---

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
  MCP clients                         VM (Ubuntu 24.04)
  ───────────                         ─────────────────────────────────────────────
  claude.ai connector ──HTTPS /mcp──┐
  mcp-remote bridge  ──HTTPS /sse───┼─▶ nginx + Let's Encrypt (TLS, SSE-safe proxying)
  (Claude Desktop, Code,            │        │ http://127.0.0.1:8080
   Cline, Continue)                 │        ▼
                                    │   mesa-mcp --transport sse   (systemd unit)
                                    │     Starlette + uvicorn
                                    │     OIDC bearer check on every route except
                                    │     /healthz and /.well-known/oauth-protected-resource
                                    │        │            │              │
                                    │        │            │              └─▶ Postgres: mesa_ducklake
                                    │        │            │                  (mesa-ducklake catalog;
                                    │        │            │                   only for AVU history)
                                    │        │            └─▶ EMBL-EBI OLS4 API (HTTPS, public)
                                    │        └─▶ CyVerse iRODS, data.cyverse.org:1247
                                    │             (incl. <project>/.mesa/ducklake/ Parquet)
  CyVerse Keycloak (kc.cyverse.org) ◀── JWKS / discovery fetched by mesa-mcp; tokens minted by clients
```

## Component table

| Component | Role | Page |
| --- | --- | --- |
| `mesa-mcp` systemd service | The MCP server, run with `--transport sse`: old-style SSE at `/sse`, Streamable HTTP at `/mcp`, `/healthz`, RFC 9728 metadata. | [systemd](./systemd.md), [HTTP / SSE](./http-sse.md) |
| nginx + Let's Encrypt | Terminates TLS and proxies to the local port with SSE buffering turned off. | [Nginx + TLS](./nginx-tls.md) |
| CyVerse Keycloak | Issues the bearer JWTs mesa-mcp verifies. | [OIDC](./oidc.md) |
| `python-irodsclient` (in process) | Native iRODS protocol to `data.cyverse.org:1247`. | — |
| OLS client (in process) | `https://www.ebi.ac.uk/ols4/api/v2`, with in-process TTL caches. | — |
| mesa-ducklake (in process) + Postgres `mesa_ducklake` | AVU history catalog. Optional: without `ducklake.catalog_dsn`, history is off. | [Postgres](./postgres.md) |
| journald | Log sink for the unit. | [Monitoring](./monitoring.md) |

## Run modes

1. **stdio under an MCP client.** The client launches `mesa-mcp` as a
   subprocess. No port, TLS or IdP. This is Modes B and C; see
   [`../user/claude-desktop.md`](../user/claude-desktop.md).
2. **Long-running HTTP service.** mesa-mcp runs as a systemd service on
   a local port, nginx fronts it with TLS, and a CyVerse Keycloak bearer
   token authenticates each request. This is Mode A, described on the
   pages in this section. Users connect as in
   [Hosted mesa-mcp](../user/hosted-mcp.md).

The Postgres setup in [`./postgres.md`](./postgres.md) is needed only for
the AVU history, in either mode.

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

- [`/home/exouser/esiil-portal/esiil-portal.service`](https://github.com/idss-mesa/mesa-mcp/blob/main/README.md)
  — the security-hardened systemd unit on this VM. Mesa-mcp's unit
  borrows its `ProtectSystem=strict`, `ProtectHome=read-only`,
  `ReadWritePaths`, and append-only log file patterns.
- [`/home/exouser/irods-mcp-server/install/irods-mcp-server.service`](https://github.com/idss-mesa/mesa-mcp/blob/main/README.md)
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
- [`../../CLAUDE.md`](https://github.com/idss-mesa/mesa-mcp/blob/main/CLAUDE.md)
