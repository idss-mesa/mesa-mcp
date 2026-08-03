# OIDC (CyVerse Keycloak)

What this page covers: registering CyVerse Keycloak OIDC clients for
mesa-mcp's HTTP/SSE transport, the values to plug into the running
configuration, and the requests to send to CyVerse IAM. OIDC is **only**
required for the SSE transport — stdio mode does not use bearer tokens.

The SSE transport is implemented and in use; see
[HTTP / SSE](./http-sse.md) for the route map.

## Who provisions the client

CyVerse Keycloak (`https://kc.cyverse.org/`) is operated by the
CyVerse infrastructure team. You cannot self-serve client
registration — open a ticket with CyVerse IAM asking for a new OIDC
client.

mesa-mcp uses **two** Keycloak clients in production, for two
different OAuth shapes:

| Client | Type | Grant | Purpose |
| --- | --- | --- | --- |
| `mesa-mcp` | confidential | `client_credentials` | Backend identity. mesa-mcp uses this to call CyVerse Terrain's `service-account-*` endpoints, and `mcp-remote` bridges use it to mint short-lived JWTs for stdio-only Claude clients. |
| `mesa-mcp-public` | public, PKCE-required | `authorization_code` | User-delegated browser flow for Claude.ai's custom-connector UI. |

The confidential `mesa-mcp` client is already provisioned. The public
`mesa-mcp-public` client is pending the CyVerse IAM request below.

## Config wiring

The relevant fields live in
[`src/mesa_mcp/config.py::ServerConfig`](../../src/mesa_mcp/config.py):

```yaml
server:
  transport: sse
  bind_address: 127.0.0.1
  bind_port: 8080
  # Canonical public URL — surfaced in the RFC 9728 metadata document
  # and used to build the `resource_metadata` URL on 401 challenges.
  public_base_url: https://mesa-mcp.example.org
  oidc_discovery_url: https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration
  oauth2_client_id: mesa-mcp
  # No client secret. mesa-mcp is a resource server: it validates
  # inbound JWTs and never runs the authorization-code flow, so it has
  # no use for one. `oauth2_client_secret` was removed; setting it now
  # logs an "unknown key" warning and is ignored.
  # oidc_audience: mesa-mcp     # uncomment for strict aud check
```

Companion env-var form (place these in `/etc/mesa-mcp/mesa-mcp.env`,
mode 0640, root:exouser):

```bash
MESA_MCP_SERVER__TRANSPORT=sse
MESA_MCP_SERVER__PUBLIC_BASE_URL=https://mesa-mcp.example.org
MESA_MCP_SERVER__OIDC_DISCOVERY_URL=https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration
MESA_MCP_SERVER__OAUTH2_CLIENT_ID=mesa-mcp
```

There is deliberately no client-secret variable here. A resource server
validating bearer tokens needs no client credentials, so injecting one
would place a live secret in the unit's environment for no benefit.

The Keycloak adapter JSON file (downloaded from the Keycloak admin
console after the client is created) is the canonical source for the
client secret. Stash it at `/etc/mesa-mcp/secrets/oidc-client.json`,
mode 0640 root:exouser, and extract `credentials.secret` into the env
file. Never commit either file.

## Required client settings — confidential `mesa-mcp`

| Setting | Value |
| --- | --- |
| Client type | Confidential (server-to-server with client secret). |
| Standard flow | Off (this client doesn't drive browser auth). |
| Direct access grants | Off. |
| Service accounts | **On.** Tokens from this client carry a service-account `sub`. |
| Client authentication | On. |
| Valid redirect URIs | None required. |
| Web origins | Empty. |
| Access token TTL | 5–15 minutes default; we observed 14400s on the live realm. |

For Terrain service-account calls to work, CyVerse IAM must also
attach the `service-account-*` realm roles relevant to the endpoints
you plan to use. See the matching memory note: when adding a tool that
hits a Terrain `service-account-*` Swagger category, flag the role
need to the user so they can request it.

## Required client settings — public `mesa-mcp-public` (pending)

| Setting | Value |
| --- | --- |
| Client type | **Public** (no client secret). |
| Standard flow | **On** (Authorization Code). |
| Direct access grants | Off. |
| Service accounts | Off. |
| Client authentication | Off (PKCE replaces the secret). |
| PKCE method | **S256 required.** |
| Valid redirect URIs | `https://claude.ai/api/mcp/auth_callback` and `https://claude.com/api/mcp/auth_callback` (both — Claude routes some users through `.com`). |
| Web origins | `+` (echo redirect URIs) or empty. |
| Default scopes | `openid`, `profile`, `email`. |

mesa-mcp itself does not need to know this client's ID — discovery is
driven entirely by the RFC 9728 metadata document, which advertises
the CyVerse Keycloak realm as the authorization server. The
`mesa-mcp-public` client ID is something users may paste into
Claude.ai's "Add custom connector → Advanced settings" if Claude.ai
does not auto-pick it (or use Dynamic Client Registration; see below).

## How tokens flow through mesa-mcp

1. MCP client opens `GET /sse` without a token.
2. mesa-mcp responds `401` with `WWW-Authenticate: Bearer realm="mesa-mcp",
   resource_metadata="<base>/.well-known/oauth-protected-resource"`.
3. Compliant clients fetch the metadata document, learn the
   authorization server (`https://kc.cyverse.org/auth/realms/CyVerse`),
   and start the OAuth dance — typically PKCE-protected authorization
   code, opening a browser tab for the Keycloak login.
4. The client retries `GET /sse` with `Authorization: Bearer <jwt>`.
5. `OIDCAuthenticator.authenticate` verifies the signature against the
   realm's JWKS, checks `iss`/`exp`/optional `aud`, and yields an
   `AuthValue` (`username` from `preferred_username` or `sub`, `zone`
   from `ServerConfig`).
6. Every `ds_*` tool downstream reads the `AuthValue` from the
   request-scoped contextvar.

Server-side details of (2) and (5) live in
[`transport/sse.py`](../../src/mesa_mcp/transport/sse.py),
[`transport/wellknown.py`](../../src/mesa_mcp/transport/wellknown.py), and
[`transport/oidc.py`](../../src/mesa_mcp/transport/oidc.py).

## Dynamic Client Registration

The CyVerse realm advertises a registration endpoint
(`https://kc.cyverse.org/auth/realms/CyVerse/clients-registrations/openid-connect`)
in its discovery document. If CyVerse IAM has DCR open (or grants an
initial access token), MCP clients can self-register a fresh PKCE
client on first connect — no `mesa-mcp-public` pre-registration is
required.

Whether the endpoint is open, gated, or disabled is part of the
pending IAM request below.

## Request template for CyVerse IAM

A draft you can paste into a ticket / email. Replace the deployment
hostname before sending if you are not on the Jetstream2 instance.

> Hi CyVerse IAM team,
>
> Thanks for setting up the existing `mesa-mcp` Keycloak client. The
> server is now running at
> `https://mesa-mcp.cis240692.projects.jetstream-cloud.org` and
> successfully validates JWTs minted from your realm via the
> client_credentials flow. Three follow-up asks:
>
> **1. Status of Dynamic Client Registration.** The realm's discovery
> doc lists a `registration_endpoint` at
> `https://kc.cyverse.org/auth/realms/CyVerse/clients-registrations/openid-connect`.
> Is DCR open, gated by an initial access token, or disabled? If gated,
> can you issue an initial access token (or document the intended
> client-policy gate)?
>
> **2. If DCR is not viable, register `mesa-mcp-public`.** A public
> PKCE client for user-delegated browser flows from Claude.ai's
> custom-connector UI. Settings:
>
> - Access type: public, no client secret.
> - Standard flow on; Direct access grants off; Service accounts off.
> - PKCE required, method S256.
> - Valid redirect URIs:
>   - `https://claude.ai/api/mcp/auth_callback`
>   - `https://claude.com/api/mcp/auth_callback`
> - Default scopes: `openid`, `profile`, `email`.
>
> **3. Service-account roles for the existing `mesa-mcp` client.** The
> Terrain Swagger at `https://de.cyverse.org/terrain/docs/index.html`
> exposes `service-account-*` categories. Please attach the matching
> realm roles to the `mesa-mcp` client's service account for the
> categories relevant to our tool surface (data-store user lookup,
> quotas, group introspection to start; happy to enumerate further once
> we know your role groupings).
>
> Thanks!

## See also

- [HTTP / SSE transport](./http-sse.md)
- [Nginx + TLS](./nginx-tls.md)
- [Overview](./overview.md)
- [Connect to a hosted mesa-mcp](../user/hosted-mcp.md) — client-side recipe.
- [`../user/configuration.md`](../user/configuration.md)
- [`../../CLAUDE.md`](../../CLAUDE.md) — Authentication section.
