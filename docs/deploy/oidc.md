# OIDC (CyVerse Keycloak)

What this page covers: registering a CyVerse Keycloak OIDC client for
mesa-mcp's planned HTTP/SSE transport, the values to plug into
`config.yaml` once you have them, and the request to send to CyVerse
operations to provision the client. OIDC is **only** required for the
SSE transport — stdio mode does not use bearer tokens. SSE itself is
not yet implemented; see [HTTP / SSE](./http-sse.md) for the wiring
status.

## Who provisions the client

CyVerse Keycloak (`https://kc.cyverse.org/`) is operated by the
CyVerse infrastructure team. You cannot self-serve client
registration — open a ticket with CyVerse admin (Tony Edgin / ops)
asking for a new OIDC client. Include:

1. **Client ID** — request `mesa-mcp` (or a tenant-specific id if
   you're running a private instance: `mesa-mcp-<institute>`).
2. **Client secret** — Keycloak generates this; CyVerse will hand it
   back over a secure channel. Treat it as a Tier-1 secret (env var
   only, never YAML).
3. **Discovery URL** — `https://kc.cyverse.org/realms/CyVerse/.well-
   known/openid-configuration` for the public CyVerse realm. If your
   tenant lives in a private realm, get the realm-scoped URL.
4. **Redirect URIs** — the URLs mesa-mcp will redirect through after
   user login. For an SSE deployment behind nginx, these are the
   public URLs of the mesa-mcp host. Provide all of:
   - `https://mesa-mcp.example.org/auth/callback` (production).
   - `http://localhost:8080/auth/callback` (local dev, optional).
   - Any staging hostnames you intend to support.

Once provisioned, copy the four values into the per-host config —
discovery URL and client id can be checked in to `config.yaml`; the
client secret stays in `/etc/mesa-mcp/env` (root-owned, mode 0600).

## Config wiring

The fields live in
[`src/mesa_mcp/config.py::ServerConfig`](../../src/mesa_mcp/config.py):

```yaml
server:
  transport: sse                # planned — raises NotImplementedError today
  bind_address: 127.0.0.1
  bind_port: 8080
  oidc_discovery_url: https://kc.cyverse.org/realms/CyVerse/.well-known/openid-configuration
  oauth2_client_id: mesa-mcp
  # oauth2_client_secret should come from the env, not the YAML file.
```

Companion env-var form (place these in `/etc/mesa-mcp/env`):

```bash
MESA_MCP_SERVER__TRANSPORT=sse
MESA_MCP_SERVER__OIDC_DISCOVERY_URL=https://kc.cyverse.org/realms/CyVerse/.well-known/openid-configuration
MESA_MCP_SERVER__OAUTH2_CLIENT_ID=mesa-mcp
MESA_MCP_SERVER__OAUTH2_CLIENT_SECRET=PLEASE_INJECT_FROM_SECRET_STORE
```

## Required client settings on the Keycloak side

When opening the ticket, ask CyVerse to set the new client up with:

| Setting              | Value                                                  |
| -------------------- | ------------------------------------------------------ |
| Client type          | Confidential (server-to-server with client secret).    |
| Standard flow        | Enabled (Authorization Code).                          |
| Service accounts     | Enabled if you plan to use proxy-auth (recommended).   |
| Valid redirect URIs  | As listed above.                                       |
| Web origins          | `+` (allow CORS from any of the redirect-URI origins). |
| Access token TTL     | 5–15 minutes (default).                                |
| Audience             | Include `mesa-mcp` so the JWT `aud` claim matches.     |

For the standard CyVerse realm, the issuer URL is
`https://kc.cyverse.org/realms/CyVerse`. The JWKS endpoint and
authorization/token URLs are discovered automatically via the
discovery URL.

## How mesa-mcp will use the tokens

Once the SSE transport lands, the planned flow is:

1. Client (e.g. Claude Desktop with an OIDC-enabled MCP launcher)
   obtains a Keycloak access token for the `mesa-mcp` audience via
   Authorization Code + PKCE.
2. Client opens `GET /sse` with `Authorization: Bearer <jwt>`.
3. mesa-mcp's `extract_from_headers` verifies the JWT signature
   against the Keycloak JWKS, checks `iss` and `aud`, and extracts
   the username + iRODS proxy mapping.
4. The resulting `AuthValue` flows through every tool call in the
   session, exactly as the stdio path's env-derived `AuthValue` does
   today.

The reference implementation patterns are in
`irods-mcp-server/common/oauth.go` and
`esiil-portal/portal/auth/keycloak_oauth.py`. Neither has been ported
to mesa-mcp yet.

## What to give CyVerse operations

A request template you can paste into the ticket:

> Hi CyVerse ops,
>
> Could you provision a Keycloak OIDC client for `mesa-mcp`
> (Python MCP server bridging CyVerse iRODS, OBO/OLS, and DuckLake)?
>
> - **Client ID:** `mesa-mcp` (or `mesa-mcp-<institute>` if scoping).
> - **Client type:** Confidential, Standard Flow enabled.
> - **Realm:** CyVerse public realm.
> - **Redirect URIs:**
>   - `https://mesa-mcp.example.org/auth/callback`
>   - `http://localhost:8080/auth/callback` (for dev)
> - **Audience:** include `mesa-mcp`.
> - **Service accounts:** enabled (we'll use this for proxy auth into
>   iRODS).
>
> Please send the client secret over secure channel. Thanks!

Replace `example.org` and the institute slug with your actual
hostnames before sending.

## See also

- [HTTP / SSE](./http-sse.md)
- [Nginx + TLS](./nginx-tls.md)
- [Overview](./overview.md)
- [`../user/configuration.md`](../user/configuration.md)
- [`../../CLAUDE.md`](../../CLAUDE.md) — Authentication section.
