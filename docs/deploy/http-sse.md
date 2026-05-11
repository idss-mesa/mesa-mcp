# HTTP / SSE transport

What this page covers: the HTTP/SSE transport mesa-mcp serves when run
with `--transport sse`. The transport is **implemented and in use** —
the running instance at
`https://mesa-mcp.cis240692.projects.jetstream-cloud.org` speaks SSE.

For the client-side recipe (Claude Desktop, Claude.ai, etc.), see
[`../user/hosted-mcp.md`](../user/hosted-mcp.md).

## Why SSE

stdio works fine when the MCP client and the server live on the same
machine. SSE matters when:

- The MCP client is on a researcher's laptop and the iRODS access
  policy / OIDC session lives on a shared VM.
- Multiple agents need to share a single mesa-mcp process (and its
  pooled iRODS sessions + OLS cache).
- You want centralised audit logging, per-token rate limits, or any
  middleware that doesn't fit in a per-invocation stdio process.

## Routes

The Starlette app assembled by
[`src/mesa_mcp/transport/sse.py::build_sse_app`](../../src/mesa_mcp/transport/sse.py)
exposes five routes across two MCP transports plus health/metadata:

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/healthz` | public | Liveness probe. |
| `GET` | `/.well-known/oauth-protected-resource` | public | RFC 9728 metadata — points clients at the CyVerse Keycloak realm. |
| `GET` | `/sse` | Bearer JWT | **Old SSE transport** upgrade. First event carries `data: /messages/?session_id=…`. Drives `mcp-remote` bridges from stdio-only Claude clients. |
| `POST` | `/messages/?session_id=…` | Bearer JWT | Companion channel for the old SSE transport. |
| any | `/mcp` | Bearer JWT | **Streamable HTTP transport** (MCP spec 2025-03-26+) — Claude.ai's custom-connector UI. POST for JSON-RPC; GET for resumable streams; DELETE to close a session. Session keyed by `Mcp-Session-Id` header. |

The two transports coexist intentionally. Claude.ai's web UI speaks
Streamable HTTP only; existing `mcp-remote` bridges in Claude Desktop /
Code / Cline / Continue speak old SSE only. Same OIDC middleware
applies to both.

A `401` on any of the bearer-gated routes carries `WWW-Authenticate:
Bearer realm="mesa-mcp", resource_metadata="<URL of the metadata
endpoint>"` per RFC 6750 + RFC 9728, so a compliant MCP client can
discover the authorization server from a cold start.

## Bind addresses

The recommended deployment binds uvicorn to loopback and lets nginx
terminate TLS:

- `bind_address = 127.0.0.1`
- `bind_port = 8080`
- nginx reverse-proxies `https://<host>/` to `http://127.0.0.1:8080/`
  with `proxy_buffering off` for SSE. See
  [Nginx + TLS](./nginx-tls.md).

Binding mesa-mcp directly to `0.0.0.0:443` is **not** recommended —
the security hardening, OIDC token handling, and TLS termination are
all best done in nginx.

## Auth model

Every non-public request must carry `Authorization: Bearer <JWT>`. The
JWT is verified by
[`src/mesa_mcp/transport/oidc.py::OIDCAuthenticator`](../../src/mesa_mcp/transport/oidc.py)
against the CyVerse Keycloak realm's JWKS, with `iss`, `exp`, and
(optionally) `aud` checks. A valid token yields an
[`AuthValue`](../../src/mesa_mcp/auth/models.py) bound to the
request-scoped contextvar; every `ds_*` tool reads it from there.

Two practical token shapes:

- **`client_credentials`** — backend service identity. Used today by
  `mcp-remote` bridges from stdio-only clients. The token's `sub` is a
  Keycloak service-account user, not a human.
- **`authorization_code` + PKCE** — user-delegated identity. The
  target shape for Claude.ai's custom-connector flow. Requires a
  public Keycloak client with PKCE; that registration is in flight
  with CyVerse IAM (see [OIDC](./oidc.md)).

The auth gate is implemented as a raw ASGI middleware (not Starlette's
`BaseHTTPMiddleware`) because SSE returns a streaming response that
`BaseHTTPMiddleware` buffers — which would deadlock long-lived streams.

### Local-development escape hatch

When `ServerConfig.oidc_discovery_url` is empty, the middleware logs a
loud warning per request and lets every call through with an anonymous
`AuthValue`. This is intentional so a developer can `curl /healthz`
against a fresh checkout without wiring Keycloak. **Production
deployments must set a discovery URL** — leaving it empty in
`config.yaml` is unsafe in any multi-tenant context.

## Protected-resource metadata

`GET /.well-known/oauth-protected-resource` returns an RFC 9728
document of the form:

```json
{
  "resource": "https://mesa-mcp.example.org",
  "authorization_servers": [
    "https://kc.cyverse.org/auth/realms/CyVerse"
  ],
  "bearer_methods_supported": ["header"],
  "scopes_supported": []
}
```

`resource` comes from `ServerConfig.public_base_url`; when unset, it is
rebuilt from the inbound request's `Host` + `X-Forwarded-Proto`
headers. `authorization_servers` is derived by stripping the
`/.well-known/openid-configuration` suffix from
`ServerConfig.oidc_discovery_url`.

## Operator checklist

To enable SSE on a fresh host:

1. Set `MESA_MCP_SERVER__TRANSPORT=sse` (or pass `--transport sse`).
2. Set `MESA_MCP_SERVER__PUBLIC_BASE_URL` to the canonical HTTPS URL.
3. Set `MESA_MCP_SERVER__OIDC_DISCOVERY_URL` to the realm's discovery
   URL (e.g. `https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration`).
4. Optionally set `MESA_MCP_SERVER__OIDC_AUDIENCE` to lock tokens to a
   specific `aud` claim.
5. Provision the Keycloak client(s) and stash the secret as
   `MESA_MCP_SERVER__OAUTH2_CLIENT_SECRET`. See [OIDC](./oidc.md).
6. Restart mesa-mcp and probe the four routes in the table above with
   `curl`.

## See also

- [Connect to a hosted mesa-mcp](../user/hosted-mcp.md) — client-side
  recipe for the deployed service.
- [OIDC](./oidc.md) — Keycloak client provisioning.
- [Nginx + TLS](./nginx-tls.md) — proxy configuration with SSE-friendly
  buffering.
- [Overview](./overview.md) — full deploy topology.
- [`../user/configuration.md`](../user/configuration.md) — config field
  reference, including `public_base_url`.
- [`../../CLAUDE.md`](../../CLAUDE.md) — Authentication section.
