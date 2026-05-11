# systemd

What this page covers: how to run mesa-mcp as a systemd service on the
deployment VM (Ubuntu 24.04, systemd 255, unprivileged user `exouser`,
repo at `/home/exouser/mesa-mcp/`). The unit file below is patterned
after the working
`/home/exouser/esiil-portal/esiil-portal.service` on the same VM, with
the iRODS-MCP-friendly bits cribbed from
`/home/exouser/irods-mcp-server/install/irods-mcp-server.service`.

Stdio-mode mesa-mcp is typically *launched by the MCP client itself*
(Claude Desktop, Claude Code) and does not need a long-running daemon.
A systemd unit is still useful as:

- A convenience supervisor when running under a local Inspector or
  test harness for hours at a time.
- A starting point for the SSE-mode daemon (planned) — same unit,
  different `--transport`.

## Unit file

Save this as `/etc/systemd/system/mesa-mcp.service`. Note the
`ExecStart` runs the SSE transport, which is **not implemented** today
— for stdio you would not normally need this unit at all. Adjust as
the project evolves.

```ini
[Unit]
Description=mesa-mcp MCP server
Documentation=https://github.com/cyverse/mesa-mcp
After=network-online.target nss-lookup.target postgresql.service
Wants=network-online.target

[Service]
Type=exec
User=exouser
Group=exouser
WorkingDirectory=/home/exouser/mesa-mcp

# Configuration: keep secrets in /etc/mesa-mcp/env (owner root, mode 0600).
# config.yaml in the repo is fine for non-secret defaults.
EnvironmentFile=-/etc/mesa-mcp/env
Environment=PYTHONUNBUFFERED=1

ExecStart=/home/exouser/mesa-mcp/.venv/bin/mesa-mcp \
    --config /home/exouser/mesa-mcp/config.yaml \
    --transport sse \
    --log-level info

ExecReload=/bin/kill -HUP $MAINPID
KillMode=mixed
KillSignal=SIGINT
TimeoutStartSec=30
TimeoutStopSec=30
Restart=on-failure
RestartSec=5
StartLimitInterval=300
StartLimitBurst=5

# Logging — journald is the default; the StandardOutput/Error lines
# below mirror the esiil-portal pattern if you want per-file logs.
SyslogIdentifier=mesa-mcp
# StandardOutput=append:/home/exouser/mesa-mcp/mesa-mcp.log
# StandardError=append:/home/exouser/mesa-mcp/mesa-mcp-error.log

# Security hardening, copied from esiil-portal.
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/home/exouser/mesa-mcp
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes

[Install]
WantedBy=multi-user.target
```

## Install steps

```bash
# 1. Place the unit file.
sudo install -m 0644 \
    /home/exouser/mesa-mcp/install/mesa-mcp.service \
    /etc/systemd/system/mesa-mcp.service

# (If you didn't check the file into the repo yet, write it directly
#  with: sudo nano /etc/systemd/system/mesa-mcp.service)

# 2. Create the secret env file (root-owned, mode 0600).
sudo mkdir -p /etc/mesa-mcp
sudo install -m 0600 -o root -g root /dev/null /etc/mesa-mcp/env
sudoedit /etc/mesa-mcp/env
# Populate with MESA_MCP_IRODS__PASSWORD=..., MESA_MCP_DUCKLAKE__CATALOG_DSN=...

# 3. Reload systemd and start the service.
sudo systemctl daemon-reload
sudo systemctl enable --now mesa-mcp.service

# 4. Tail the logs to confirm it came up.
journalctl -u mesa-mcp -f
```

## Why each line

- `Type=exec` — the process is the main one; mesa-mcp does not fork.
- `User=exouser` — same unprivileged user that runs the portal. Avoids
  a service-account sprawl.
- `WorkingDirectory=/home/exouser/mesa-mcp` — Pydantic loads
  `config.yaml` via a relative path when you pass `--config
  config.yaml` from the systemd `ExecStart`; pin the cwd so the path
  resolves predictably.
- `EnvironmentFile=-/etc/mesa-mcp/env` — secrets isolated from the
  unit file itself. The leading `-` makes the directive non-fatal if
  the file is missing (handy when bootstrapping).
- `ProtectSystem=strict` + `ReadWritePaths=/home/exouser/mesa-mcp` —
  filesystem is read-only except for the repo dir. The default
  `cachetools.TTLCache` is in-memory, so mesa-mcp does not need any
  other write paths today.
- `Restart=on-failure` with a 5s backoff — same policy as esiil-portal.
- `journalctl -u mesa-mcp` — default log sink, no extra config.

## Stdio mode under systemd (rare)

If you want mesa-mcp launched as a stdio process under systemd (e.g.
to expose it to an Inspector running locally as `exouser`), change
`ExecStart`'s `--transport sse` to `--transport stdio`. The service
will start, but you cannot interact with it from outside the local
shell — stdio servers expect a parent process holding their
stdin/stdout. This is unusual; the canonical stdio path is to let the
MCP client itself launch mesa-mcp.

## Health check

The service has no `ExecStartPost` health probe yet — once an HTTP
`/healthz` endpoint is wired (planned with SSE), drop in a
`curl --silent --fail http://127.0.0.1:8080/healthz` and supervise.
For now, `journalctl -u mesa-mcp -n 20` is the simplest live-check.

## Stop / restart

```bash
sudo systemctl restart mesa-mcp.service
sudo systemctl status mesa-mcp.service
sudo systemctl stop mesa-mcp.service
sudo systemctl disable mesa-mcp.service
```

`KillSignal=SIGINT` is intentional: it gives Python the chance to
unwind its asyncio loops and tear down the iRODS connection pool
cleanly. `KillMode=mixed` waits 30 s before escalating to `SIGKILL`
(per `TimeoutStopSec=30`).

## Log rotation

journald handles rotation when configured at the system level (see
`/etc/systemd/journald.conf`). If you choose the
`StandardOutput=append:/home/exouser/mesa-mcp/...` form instead, set
up `logrotate(8)` — see [Monitoring](./monitoring.md).

## See also

- [Overview](./overview.md)
- [HTTP / SSE transport](./http-sse.md)
- [Monitoring](./monitoring.md)
- [`/home/exouser/esiil-portal/esiil-portal.service`](../../README.md) —
  the reference systemd unit on this VM (cross-VM, you can find it in
  the esiil-portal repo).
