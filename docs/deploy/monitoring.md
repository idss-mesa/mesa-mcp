# Monitoring

What this page covers: where mesa-mcp's logs land, how to rotate them,
and what minimal monitoring you should set up on the VM. mesa-mcp has
no Prometheus exporter yet — this is operational hygiene, not
observability deep-dive.

## Logs

`mesa_mcp.logging.setup_logging` (called from `__main__`) configures
`structlog` to write structured key=value lines to stderr. When the
process is supervised by systemd (see [systemd](./systemd.md)),
stderr flows directly into journald.

### journald

The simplest log sink. Tail live:

```bash
journalctl -u mesa-mcp -f
```

Search by time / level:

```bash
journalctl -u mesa-mcp --since "1 hour ago"
journalctl -u mesa-mcp -p err --since today
```

Storage and rotation are configured at the system level in
`/etc/systemd/journald.conf`. The defaults are sensible:
`Storage=auto`, `SystemMaxUse=10% of disk`, `SystemMaxFileSize=128M`.
Adjust if mesa-mcp is chattier than expected in your deployment.

### File logs (optional)

If you prefer file logs (e.g. to ship via Filebeat / Vector), set
`StandardOutput=append:/home/exouser/mesa-mcp/mesa-mcp.log` and
`StandardError=append:/home/exouser/mesa-mcp/mesa-mcp-error.log` in
the systemd unit. The
`/home/exouser/esiil-portal/esiil-portal.service` unit uses this
pattern; mesa-mcp can mirror it.

In that case, configure `logrotate(8)` so the files don't grow
unbounded. Drop the following at
`/etc/logrotate.d/mesa-mcp`:

```text
/home/exouser/mesa-mcp/mesa-mcp.log
/home/exouser/mesa-mcp/mesa-mcp-error.log
{
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0644 exouser exouser
    postrotate
        systemctl reload mesa-mcp.service > /dev/null 2>&1 || true
    endscript
}
```

Then verify with `sudo logrotate -d /etc/logrotate.d/mesa-mcp`.

### What gets logged

`structlog` is configured with sensible defaults — key=value lines at
the level configured in `server.log_level`. Recommended verbosity:

- `info` for production.
- `debug` only while reproducing a bug — `debug` enables HTTP request
  logging in `OLSClient` (URL + params) and verbose iRODS account
  construction in `auth/irods_auth.py`.

What does **not** get logged:

- Passwords. `AuthValue.password` is `repr=False`, so even a
  `logger.info("auth=%r", auth_value)` skips the field.
- Plaintext bearer tokens or client secrets. The `mcp-reviewer`
  sub-agent checks for accidental log statements that interpolate
  these.

## Health check (planned)

`/healthz` is not yet exposed. Once the SSE transport lands, the
intended pattern is:

- `GET /healthz` returns 200 with a small JSON body
  (`{"status": "ok", "tools": <count>, "version": "..."}`).
- systemd: a `WatchdogSec=` directive + `sd_notify(WATCHDOG=1)` from
  the mesa-mcp process.
- External liveness check from the load balancer or uptime monitor.

For stdio mode, there is no equivalent — the only liveness signal is
the process being alive in `journalctl`. Today, the smoke test is
`ds_ping` over the MCP wire (see
[Getting started](../user/getting-started.md)).

## Disk

mesa-mcp does not write to disk during normal operation (caches are
all in-memory `cachetools.TTLCache`). Things that may use disk:

- File logs (if you opt into `StandardOutput=append:...`).
- Future DuckLake catalog (Postgres data dir under
  `/var/lib/postgresql/` — see [Postgres](./postgres.md)).
- Future encrypted credential store under `~/.mesa-mcp/`
  (terrain-mcp's pattern, planned).

Watch `/var/lib/postgresql/`, `/var/log/journal/`, and
`/home/exouser/mesa-mcp/*.log` (if used). A `df -h` cron + alerting on
> 80% is plenty.

## Process supervision

systemd does the supervision. Useful one-liners:

```bash
systemctl status mesa-mcp.service                    # uptime + last 10 log lines
systemctl restart mesa-mcp.service                   # apply config changes
systemctl --user list-timers | grep mesa-mcp         # any timers
journalctl -u mesa-mcp -p err -n 50                  # recent errors
journalctl -u mesa-mcp --since "today" | grep ERROR  # ERROR-level lines
```

Crash loops: if `Restart=on-failure` + `StartLimitBurst=5` hit, the
service refuses to start until you `systemctl reset-failed mesa-mcp`.
Investigate the journalctl output before clearing.

## Metrics (not yet)

mesa-mcp does not expose Prometheus metrics today. If you need
observability beyond logs, the cleanest place to add it is the
`MesaServer._build_mcp_server` boundary in
[`server.py`](../../src/mesa_mcp/server.py), instrumenting the
`call_tool` callback with per-tool counters and latency histograms.
This is on the roadmap; tracking issue not yet filed.

## See also

- [Overview](./overview.md)
- [systemd](./systemd.md)
- [Postgres](./postgres.md)
- [HTTP / SSE](./http-sse.md)
- [`../user/configuration.md`](../user/configuration.md) — log level
  field.
