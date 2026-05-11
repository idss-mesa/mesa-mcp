# Connect to a hosted mesa-mcp

What this page covers: how to point an MCP client (Claude Desktop,
Claude Code, Claude.ai, Cline, Continue) at a *remote* mesa-mcp service
fronted by nginx + OIDC, instead of running mesa-mcp locally yourself.
This is the right page when:

- You already have a mesa-mcp instance running on a shared host (e.g.
  `https://mesa-mcp.cis240692.projects.jetstream-cloud.org`).
- You want to avoid installing Python + `python-irodsclient` on every
  laptop.
- You want centralised audit logging or per-token rate limits.

If instead you want to run mesa-mcp on your own machine, read
[`./local-install.md`](./local-install.md).

## What "hosted" means here

A hosted mesa-mcp is a single process running on a public VM that
serves the MCP protocol over HTTP/SSE behind nginx and TLS. Every
client request carries an `Authorization: Bearer <JWT>` header issued
by **CyVerse Keycloak** (`https://kc.cyverse.org/auth/realms/CyVerse`).
The server validates the JWT, binds an `AuthValue` to the request, and
runs your `ds_*` / `mesa_*` tool calls under that identity.

Routes the hosted service exposes:

| Path | Purpose | Auth |
| --- | --- | --- |
| `GET /healthz` | Liveness probe | public |
| `GET /.well-known/oauth-protected-resource` | RFC 9728 metadata (auth-server discovery) | public |
| `GET /sse` | MCP Server-Sent Events upgrade | Bearer JWT |
| `POST /messages/?session_id=…` | MCP JSON-RPC companion | Bearer JWT |

A `401` from `/sse` carries a `WWW-Authenticate: Bearer
resource_metadata="<url>"` header that points compliant MCP clients
(Claude.ai, mcp-remote, …) at the metadata endpoint so they can
discover the authorization server and start the OAuth dance
automatically.

## Two ways to connect

There are two paths in active use today. Pick by your client.

| Client | Path | Token source |
| --- | --- | --- |
| Claude Desktop | **A** — `mcp-remote` bridge | Manually-minted JWT |
| Claude Code | **A** — `mcp-remote` bridge | Manually-minted JWT |
| Cline / Continue | **A** — `mcp-remote` bridge | Manually-minted JWT |
| Claude.ai (web) | **B** — Custom connector | OAuth via Claude.ai |

Path B requires a Keycloak client registered for browser PKCE flows
with the Claude callback URIs allowlisted. As of this writing the
request to CyVerse IAM is in flight; the section below describes the
target state.

---

## Path A — Claude Desktop / Claude Code / Cline / Continue via `mcp-remote`

These clients are stdio-only by design. The `mcp-remote` npm package
bridges stdio ↔ remote SSE, attaching an `Authorization` header on
every upstream request.

### Step 1 — mint a Keycloak JWT

mesa-mcp's hosted instance uses the **client_credentials** grant for
this bridge. You will need the client secret of the `mesa-mcp` Keycloak
client; it lives on the deploy host at `/etc/mesa-mcp/secrets/
oidc-client.json` (mode 0640, group-readable to the service user).
Pull it once to your workstation:

```bash
ssh exouser@mesa-mcp.cis240692.projects.jetstream-cloud.org \
    'sudo jq -r .credentials.secret /etc/mesa-mcp/secrets/oidc-client.json' \
  > ~/.mesa-mcp-secret
chmod 600 ~/.mesa-mcp-secret
```

Then mint a token whenever you need a fresh one (validity is ~4 hours):

```bash
curl -sS -X POST \
  https://kc.cyverse.org/auth/realms/CyVerse/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=mesa-mcp \
  --data-urlencode "client_secret=$(cat ~/.mesa-mcp-secret)" \
  | jq -r .access_token
```

Caveat: the resulting JWT has **no user identity** — its `sub` is the
service-account user attached to the `mesa-mcp` Keycloak client. Tools
that talk to iRODS will operate as that service account, *not* as your
personal CyVerse user. Use Path B (when available) for user-delegated
access.

### Step 2 — wire into your MCP client

#### Claude Desktop

`~/Library/Application Support/Claude/claude_desktop_config.json` on
macOS; `%APPDATA%\Claude\claude_desktop_config.json` on Windows;
`~/.config/Claude/claude_desktop_config.json` on Linux:

```json
{
  "mcpServers": {
    "mesa-mcp": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse",
        "--header", "Authorization: Bearer ${MESA_MCP_TOKEN}"
      ],
      "env": { "MESA_MCP_TOKEN": "PASTE_JWT_HERE" }
    }
  }
}
```

Restart Claude Desktop. The mesa-mcp tools appear in the picker. Try
`ds_ping` first.

#### Claude Code

```bash
claude mcp add mesa-mcp \
  --transport stdio \
  --command npx \
  --args "-y,mcp-remote,https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse,--header,Authorization: Bearer ${MESA_MCP_TOKEN}" \
  --env MESA_MCP_TOKEN=PASTE_JWT_HERE
```

Or paste the same JSON shape as Claude Desktop into your project's
`.mcp.json`.

#### Cline / Continue

Same shape: `command: npx`, `args: [-y, mcp-remote, <url>, --header,
"Authorization: Bearer …"]`. The extension's "MCP Servers" UI is
usually the friendliest entry point — write the `Authorization` header
into the wrapper config and reload.

### Step 3 — refresh the token when it expires

Tokens issued via `client_credentials` last ~4 hours. When tool calls
start failing with `unauthorized`, re-mint and reload:

```bash
# Re-mint
new_jwt=$(curl -sS -X POST \
  https://kc.cyverse.org/auth/realms/CyVerse/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=mesa-mcp \
  --data-urlencode "client_secret=$(cat ~/.mesa-mcp-secret)" \
  | jq -r .access_token)

# Update Claude Desktop config (macOS example), then restart Claude Desktop.
```

A small wrapper that auto-mints on every Claude Desktop launch is a
common ergonomic upgrade:

```bash
#!/usr/bin/env bash
# ~/.local/bin/mesa-mcp-launch
set -euo pipefail
JWT=$(curl -sS -X POST \
  https://kc.cyverse.org/auth/realms/CyVerse/protocol/openid-connect/token \
  -d grant_type=client_credentials \
  -d client_id=mesa-mcp \
  --data-urlencode "client_secret=$(cat "$HOME/.mesa-mcp-secret")" \
  | jq -r .access_token)
exec npx -y mcp-remote \
  https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse \
  --header "Authorization: Bearer $JWT"
```

Then in `claude_desktop_config.json` point `command` at the script
instead of `npx`.

---

## Path B — Claude.ai custom connector (OAuth flow)

For Claude.ai (the web app), the connector flow performs an OAuth 2.1
authorization-code + PKCE dance against CyVerse Keycloak. mesa-mcp's
server side is ready (the 401 challenge advertises the metadata
endpoint, and the metadata document points at the CyVerse realm) — what
is *still in flight* is a Keycloak client suitable for user-driven
browser auth.

### Status

- ⏳ **Awaiting CyVerse IAM:** registration of a public-PKCE client
  `mesa-mcp-public` with redirect URIs `https://claude.ai/api/mcp/
  auth_callback` and `https://claude.com/api/mcp/auth_callback`, *or*
  confirmation that the realm's Dynamic Client Registration endpoint is
  open / available with an initial access token.
- ✅ **Done on mesa-mcp:** `/.well-known/oauth-protected-resource`
  serves the protected-resource metadata; `401` responses on `/sse`
  emit `WWW-Authenticate: Bearer resource_metadata="…"` so MCP
  clients can self-discover the authorization server.

### Expected setup once the client lands

1. Open Claude.ai → Settings → Connectors → **Add custom connector**.
2. **MCP server URL:**
   `https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse`.
3. If Claude.ai auto-discovers everything: just click Connect, complete
   the CyVerse Keycloak login in the popup, done.
4. If Claude.ai asks for a Client ID / Secret in **Advanced settings:**
   paste the `mesa-mcp-public` client ID (no secret — it is a public
   client). The actual value will be added here once CyVerse IAM
   provisions the client.

This page will be updated with the concrete client ID and any quirks
discovered in the first end-to-end test.

---

## Verifying the connection

A few `curl`s confirm the hosted service is up and your client should
be able to reach it:

```bash
# Liveness — always reachable, no token.
curl -sS https://mesa-mcp.cis240692.projects.jetstream-cloud.org/healthz

# Metadata — always reachable, no token. Reports the authorization
# server (CyVerse Keycloak) and the canonical resource URL.
curl -sS https://mesa-mcp.cis240692.projects.jetstream-cloud.org/.well-known/oauth-protected-resource | jq

# Auth challenge — should return 401 with a WWW-Authenticate header.
curl -sSI https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse \
  | grep -iE "^(HTTP|WWW-Authenticate)"

# With a token — should hold the SSE stream open. ^C to exit.
curl -sN https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse \
  -H "Authorization: Bearer $YOUR_JWT"
```

The first SSE event you see is `event: endpoint` carrying the URL
suffix (`/messages/?session_id=…`) the client will POST messages to —
that's the MCP SDK telling the client where to send subsequent JSON-RPC
frames.

## Troubleshooting

- **`401 unauthorized` from `/sse` even with a fresh token.** Check
  the token hasn't expired (`jwt.io` or `jq` the JWT payload). Also
  confirm the `iss` claim matches the realm's discovery URL — if you
  minted a token against a different realm, mesa-mcp will reject it.
- **Claude Desktop shows no tools after restart.** Look at
  `~/Library/Logs/Claude/mcp*.log` (macOS) for stderr from `mcp-remote`.
  Most failures are surfaced as a one-line auth error there.
- **Token works for `curl` but not `mcp-remote`.** `mcp-remote`
  performs an MCP handshake right after upgrading the SSE stream — if
  the JWT is rejected mid-handshake, the bridge dies silently. Test
  with `curl -N` first to isolate transport vs. handshake.
- **iRODS calls fail with `CAT_INSUFFICIENT_PRIVILEGE`.** The
  service-account JWT (Path A) is not your personal CyVerse user; it
  has whatever iRODS permissions the deployment's service account
  carries. Once Path B is live, use that for user-scoped access.

## See also

- [Local install](./local-install.md) — run mesa-mcp on your own
  machine instead.
- [MCP client wiring](./claude-desktop.md) — stdio launch shapes for
  each client (the local-install equivalents of the snippets above).
- [Deployment — HTTP/SSE transport](../deploy/http-sse.md) — what the
  server-side looks like.
- [Deployment — OIDC](../deploy/oidc.md) — Keycloak client provisioning.
