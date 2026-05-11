# HTTP / SSE transport

What this page covers: the planned HTTP/SSE transport for mesa-mcp,
why you might want it, and exactly which pieces are already in place
versus still to be built. **This transport is not implemented today** —
`mesa-mcp --transport sse` raises `NotImplementedError`. The page
exists so operators know what the eventual deployment looks like and
how to prepare.

## Why SSE

stdio works fine when the MCP client and the server live on the same
machine. SSE matters when:

- The MCP client is on a researcher's laptop and the iRODS access
  policy / OIDC session lives on a shared VM.
- Multiple agents need to share a single mesa-mcp process (and its
  pooled iRODS sessions + OLS cache).
- You want centralised audit logging, per-token rate limits, or any
  middleware that doesn't fit in a per-invocation stdio process.

## Current status

The transport selector in
[`src/mesa_mcp/server.py`](../../src/mesa_mcp/server.py) dispatches
`--transport sse` to `MesaServer._serve_sse`, which raises
`NotImplementedError` with the message:

> SSE transport is not yet wired up. Use --transport stdio for now;
> HTTP/SSE arrives with the OIDC auth PR.

The companion auth extractor at
[`src/mesa_mcp/auth/extract.py::extract_from_headers`](../../src/mesa_mcp/auth/extract.py)
is similarly stubbed. The signature is stable so handler code can be
written against it; the body raises `NotImplementedError` until the
OIDC PR lands.

## What's already in place

- `config.yaml` carries `server.transport`, `server.bind_address`,
  `server.bind_port`, `server.oidc_discovery_url`,
  `server.oauth2_client_id`, and `server.oauth2_client_secret`. The
  Pydantic model accepts these now; the values just are not consumed
  by an actual transport yet.
- The MCP Python SDK supports SSE under `mcp.server.sse`. The
  scaffolding is a thin wrapper analogous to `_serve_stdio`.

## What still needs to be built

1. `MesaServer._serve_sse` — bind to `bind_address:bind_port`, wire
   the MCP SDK's `sse_server` against the same registered tools that
   stdio uses.
2. `extract_from_headers` — translate `Authorization: Bearer <jwt>` to
   an `AuthValue`. Verify the JWT against the Keycloak JWKS, look up
   (or proxy-auth) the iRODS account, and populate `username`,
   `zone`, `auth_scheme`, `proxy_user`.
3. A `/healthz` endpoint distinct from MCP — for systemd / nginx /
   loadbalancer liveness probes.

The pattern to copy is `irods-mcp-server/common/oauth.go` plus
`irods-mcp-server`'s SSE setup; the JWT-to-iRODS-account flow already
lives in `esiil-portal/portal/auth/keycloak_oauth.py`.

## Planned bind addresses

When SSE lands, the recommended deployment is:

- `bind_address = 127.0.0.1` (loopback only).
- `bind_port = 8080`.
- nginx reverse-proxies `https://mesa-mcp.example.org/` to
  `http://127.0.0.1:8080/` with proper SSE buffering off. See
  [Nginx + TLS](./nginx-tls.md).

Binding mesa-mcp directly to `0.0.0.0:443` is **not** recommended —
the security hardening, OIDC token handling, and TLS termination are
all best done in nginx.

## Planned URL routes

The MCP SDK's SSE server exposes two routes:

- `GET /sse` — SSE event stream. Clients open this with
  `Authorization: Bearer <token>`.
- `POST /messages/?session_id=...` — message channel for client → server
  frames.

Both routes will be present once `_serve_sse` is filled in. The
specific URL paths are determined by the SDK; verify against the
running build before fronting them in nginx.

## OIDC integration

The transport-level auth is OIDC bearer tokens issued by CyVerse
Keycloak. The setup work for the IdP side lives in
[OIDC](./oidc.md). On the mesa-mcp side, set
`server.oidc_discovery_url`, `server.oauth2_client_id`, and
`server.oauth2_client_secret` (the last from the env, never YAML).

## What you can do today

If you need remote access right now, the workaround is to run
mesa-mcp behind `ssh -L` (port-forward the stdio process via a
helper). That's less ergonomic than SSE but works without the
transport implemented.

## See also

- [Overview](./overview.md)
- [OIDC](./oidc.md)
- [Nginx + TLS](./nginx-tls.md)
- [`../user/configuration.md`](../user/configuration.md)
- [`../../CLAUDE.md`](../../CLAUDE.md) — Authentication section.
- [`.claude/agents/`](../../.claude/agents/) — there is no specific
  agent for the SSE transport yet; this is hand-coded work.
