# mesa-mcp — Where we left off

Snapshot of the live deployment and the outstanding work, written so a
future-you (or a teammate) can pick this up cold.

## What's running right now

**Host:** `mesa-mcp.cis240692.projects.jetstream-cloud.org` (Jetstream2,
public IP `149.165.175.52`, internal hostname `mesa-mcp.js2local`).

**Live URL:** <https://mesa-mcp.cis240692.projects.jetstream-cloud.org/healthz>
returns `{"status": "ok", "version": "0.1.0"}`.

**Systemd services (`systemctl is-active`):**

- `mesa-mcp.service` — active. SSE transport on `127.0.0.1:8080`. Unit
  at `/etc/systemd/system/mesa-mcp.service`, source in
  [`deploy/mesa-mcp.service`](deploy/mesa-mcp.service). Logs via
  `journalctl -u mesa-mcp -f`.
- `nginx.service` — active. Site config at
  `/etc/nginx/sites-enabled/mesa-mcp.conf` (symlink), source in
  [`deploy/nginx/mesa-mcp.conf`](deploy/nginx/mesa-mcp.conf). Default
  site still enabled for non-matching hostnames.
- `postgresql.service` — active. Postgres 16. `mesa` role +
  `mesa_ducklake` database, both owned by `mesa`. Password at
  `/etc/mesa-mcp/secrets/postgres_password` (root:exouser 0640).
- `certbot.timer` — enabled. Cert from Let's Encrypt E8, valid through
  **2026-08-09**, auto-renewal scheduled.

**Code state (commits pending push):**

- 44 MCP tools registered, 308 tests pass (mesa-mcp), 65 pass (mesa-ducklake).
- ruff clean across both.
- `/healthz` works HTTP and HTTPS; HTTP→HTTPS 301 redirect in place.

## What's NOT enabled yet (intentional)

**OIDC bearer-token auth.** The four OIDC lines in
`/etc/mesa-mcp/config.yaml` are commented. The service is running in
"anonymous dev mode" — `OIDCMiddleware` logs a `WARNING` on every
request and lets it through without a bearer token. Read-side risk is
bounded because `irods.user = anonymous` in the same config — callers
get the same access as the public iRODS anonymous user (the CyVerse
shared collection, read-only-ish).

**iRODS service account.** Same reason. Once OIDC lands, mesa-mcp needs
a real iRODS identity to operate as. Options: shared service account in
`MESA_MCP_IRODS__USER` / `_PASSWORD`, or per-request proxy auth keyed
off the OIDC username.

## To finish OIDC (tomorrow's checklist)

1. **Register a CyVerse Keycloak OIDC client** with CyVerse ops (Tony
   Edgin). Provide them:
   - Client name: `mesa-mcp`
   - Allowed redirect URI: `https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse`
     (and `/oauth/callback` if they want that pattern).
   - Client type: confidential (so we get a client_secret).
2. **When they send back** `client_id` + `client_secret`:
   ```bash
   sudoedit /etc/mesa-mcp/config.yaml
   # Uncomment under the `server:` block:
   #   oidc_discovery_url: https://kc.cyverse.org/auth/realms/CyVerse/.well-known/openid-configuration
   #   oauth2_client_id: <client_id>
   #   oidc_audience: mesa-mcp        # optional; matches `aud` claim
   # No client secret: mesa-mcp validates inbound JWTs and never runs
   # the authorization-code flow.
   ```
3. **Restart and verify:**
   ```bash
   sudo systemctl restart mesa-mcp
   journalctl -u mesa-mcp -n 30 --no-pager
   # The "OIDC disabled" warning should be gone.

   # An unauthenticated /sse call now returns 401:
   curl -i https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse

   # With a real bearer token, it opens the SSE stream:
   curl -N -H "Authorization: Bearer <token>" \
       https://mesa-mcp.cis240692.projects.jetstream-cloud.org/sse
   ```

## Other follow-ups (smaller)

- **ASGI `/sse` GET noise.** Plain `curl /sse` (no MCP handshake) logs
  `RuntimeError: Expected 'http.response.body', got 'http.response.start'`.
  The connection still returns 200 and MCP clients work — this is the
  SDK's SSE transport responding to a malformed GET. Worth fixing if it
  spams journald in production. Source: `src/mesa_mcp/transport/sse.py`.
- **Docs drift.** `docs/user/tools-reference.md` was regenerated to
  cover all 44 tools (up from 8 at the time `B1` wrote the docs). Other
  pages (e.g. `docs/dev/architecture.md`, `docs/user/examples.md`) may
  still describe some tools as "planned" — they all ship now. A quick
  re-read pass would catch those.
- **iRODS `imeta`-bypass callback.** `mesa-ducklake/irods-rules/`
  contains `mesa_avu_change.re` and `mesa_enroll_policy.re`, but they
  haven't been installed on the CyVerse iRODS server yet. Until then,
  AVU writes that bypass mesa-mcp (e.g., direct `imeta` calls,
  esiil-portal) won't be recorded in DuckLake.
- **Postgres-backed tests.** Run the 21 skipped tests from this VM with
  the live catalog:
  ```bash
  cd /home/exouser/mesa-ducklake
  export PGPASSWORD=$(sudo cat /etc/mesa-mcp/secrets/postgres_password)
  # The default pytest run uses the pytest-postgresql ephemeral instance,
  # which works fine. To exercise the production DB instead, write
  # ad-hoc scripts against MESA_DUCKLAKE_DSN.
  ```
- **The `.claude/agents/` sub-agents** — `irods-tool-porter`,
  `ols-tool-author`, `mcp-reviewer` (mesa-mcp) and `ducklake-engineer`
  (mesa-ducklake) — are project-level Claude Code agents. They become
  available as `subagent_type` values when the project is opened with
  Claude Code in interactive mode. Good for the next round of features.

## Useful pointers

- Architecture & design: [`CLAUDE.md`](CLAUDE.md).
- Public docs entry: [`docs/README.md`](docs/README.md).
- Deployment artifacts: [`deploy/`](deploy/) + [`deploy/README.md`](deploy/README.md).
- Plan record for this work:
  `~/.claude/plans/continue-with-the-next-refactored-russell.md`.
- Sibling project: [`/home/exouser/mesa-ducklake/`](../mesa-ducklake/)
  with its own `NEXT_STEPS.md`.

## Day-of commands cheatsheet

```bash
# Status
sudo systemctl status mesa-mcp nginx postgresql
journalctl -u mesa-mcp -f

# Health
curl https://mesa-mcp.cis240692.projects.jetstream-cloud.org/healthz

# Restart after config change
sudo systemctl restart mesa-mcp

# Refresh code (after pulling new commits)
cd /home/exouser/mesa-mcp
git pull
.venv/bin/pip install -e ".[dev]" --quiet
sudo systemctl restart mesa-mcp

# Inspect the Postgres catalog
PGPASSWORD=$(sudo cat /etc/mesa-mcp/secrets/postgres_password) \
    psql -h 127.0.0.1 -U mesa -d mesa_ducklake -c '\dt mesa.*'
```
