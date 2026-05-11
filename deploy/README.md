# mesa-mcp deployment artifacts

This directory holds everything an operator needs to run mesa-mcp as a
long-running service on a Linux host. It is referenced by
[`../docs/deploy/`](../docs/deploy/) (overview) and the matching
sub-pages.

**These artifacts apply to Mode A (hosted service) only.** mesa-mcp has
three deployment modes — see [`../docs/README.md`](../docs/README.md) for
the framing. The systemd unit, nginx config, and install scripts in this
directory are needed only when you are standing up a shared, OIDC-fronted
mesa-mcp service that multiple users connect to. The other two modes
(Mode B = local workstation install, Mode C = inside a CyVerse VICE app)
do not use anything here — they install mesa-mcp into a user-owned venv
and let an MCP client launch it as a stdio subprocess. For those, see
[`../docs/user/local-install.md`](../docs/user/local-install.md) and
[`../docs/user/vice-apps.md`](../docs/user/vice-apps.md).

## Layout

```
deploy/
├── README.md                    ← you are here
├── mesa-mcp.service             ← systemd unit (User=exouser, hardened)
├── mesa-mcp.env.example         ← env-var overrides for secrets (Keycloak, Postgres)
├── install-systemd.sh           ← idempotent installer (sudo)
├── install-nginx.sh              ← installs nginx site, optionally runs certbot (sudo)
└── nginx/
    └── mesa-mcp.conf            ← nginx reverse-proxy site (SSE-friendly, TLS-ready)
```

## Quick deploy sequence (Ubuntu 24.04)

The plan in `../../.claude/plans/continue-with-the-next-refactored-russell.md`
has the full picture. Short version:

```bash
# --- one-time, with sudo ---
sudo apt update
sudo apt install -y postgresql postgresql-contrib nginx certbot python3-certbot-nginx

# 1. Catalog Postgres (matches the iCAT engine).
sudo -u postgres psql <<'SQL'
CREATE ROLE mesa LOGIN PASSWORD 'replace-me-with-something-strong';
CREATE DATABASE mesa_ducklake OWNER mesa;
SQL

# 2. Apply mesa-ducklake migrations.
cd /home/exouser/mesa-ducklake
MESA_DUCKLAKE_DSN='postgresql://mesa:replace-me@127.0.0.1:5432/mesa_ducklake' \
    .venv/bin/python -c "from mesa_ducklake.schema import apply_migrations; print(apply_migrations('$MESA_DUCKLAKE_DSN'))"

# 3. Drop in mesa-mcp config (operator edits to fill in secrets).
sudo install -d -m 0750 -o root -g exouser /etc/mesa-mcp
sudo cp /home/exouser/mesa-mcp/config.yaml.example /etc/mesa-mcp/config.yaml
sudoedit /etc/mesa-mcp/config.yaml

# 4. Install systemd unit (does NOT start the service — operator does that
#    once the config is real).
sudo bash /home/exouser/mesa-mcp/deploy/install-systemd.sh
sudoedit /etc/mesa-mcp/mesa-mcp.env             # optional env overrides
sudo systemctl enable --now mesa-mcp
sudo systemctl status mesa-mcp

# 5. Reverse proxy + TLS.
sudo MESA_MCP_HOSTNAME=mesa-mcp.example.org \
    bash /home/exouser/mesa-mcp/deploy/install-nginx.sh
sudo certbot --nginx -d mesa-mcp.example.org
curl -fsS https://mesa-mcp.example.org/healthz
```

## What needs your input before this VM can fully run

The deploy scripts cover the mechanics, but a few inputs are external:

1. **Public hostname** — DNS A/AAAA record pointing at this host. Without
   it, certbot fails and you stay on HTTP.
2. **CyVerse Keycloak OIDC client** — registered with CyVerse admin
   (Tony Edgin / ops). You need client id, client secret, allowed
   redirect URI(s).
3. **Postgres password** — chosen by you on first install; record it
   somewhere safe (the example DSN above uses `replace-me`).
4. **iRODS service account or proxy-auth setup** — the OIDC flow returns
   a username, not an iRODS password. For now, mesa-mcp uses a configured
   service account from `MESA_MCP_IRODS__USER` /
   `MESA_MCP_IRODS__PASSWORD`. Long-term, proxy-auth or per-user ticket
   minting takes over (see `../docs/deploy/oidc.md`).

## Notes for this VM

- Hostname today: `mesa-mcp.js2local` (Jetstream2 internal). The
  install-nginx script accepts any hostname via `MESA_MCP_HOSTNAME=`.
- The systemd unit hardens the process (NoNewPrivileges, ProtectSystem
  strict, etc.). If you need write access to a path outside
  `/home/exouser/mesa-mcp/`, add it to `ReadWritePaths=` in the unit
  file or in a drop-in at `/etc/systemd/system/mesa-mcp.service.d/`.
- All logging goes to journald. `journalctl -u mesa-mcp -f` follows live;
  `journalctl -u mesa-mcp --since "1 hour ago"` for recent history.
- The nginx config disables `proxy_buffering` and bumps
  `proxy_read_timeout` to 24h to support MCP SSE streams.

## See also

- [`../docs/deploy/overview.md`](../docs/deploy/overview.md) — production topology.
- [`../docs/deploy/systemd.md`](../docs/deploy/systemd.md) — systemd specifics.
- [`../docs/deploy/nginx-tls.md`](../docs/deploy/nginx-tls.md) — nginx + Let's Encrypt details.
- [`../docs/deploy/postgres.md`](../docs/deploy/postgres.md) — catalog DB setup.
- [`../docs/deploy/oidc.md`](../docs/deploy/oidc.md) — Keycloak client registration.
