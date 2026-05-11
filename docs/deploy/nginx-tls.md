# Nginx + TLS

What this page covers: an nginx reverse-proxy config for fronting the
mesa-mcp SSE transport with TLS via Let's Encrypt. SSE has strict
buffering and timeout requirements; the snippets below get them right.
**The SSE transport is not yet implemented in mesa-mcp** (see
[HTTP / SSE](./http-sse.md)), so this config is what to deploy when
the transport lands, not what to deploy today.

## Why a reverse proxy

- TLS termination outside the Python process — keeps mesa-mcp small.
- A single ingress for `/healthz`, `/sse`, and `/messages/` routes.
- HTTP/2 + Brotli for the metadata responses; pass-through for the SSE
  stream.
- Per-IP rate limiting and connection caps without modifying mesa-mcp.

## Prerequisites

- nginx 1.24+ (Ubuntu 24.04 ships with 1.24).
- `certbot` plus the `python3-certbot-nginx` plugin.
- DNS A/AAAA records for the hostname pointing at the VM.
- mesa-mcp listening on `127.0.0.1:8080` (set via `server.bind_*`).

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

## Get the certificate

```bash
sudo certbot --nginx -d mesa-mcp.example.org --redirect --email ops@example.org
```

The `--nginx` plugin will edit the relevant server block to add the
TLS listener and an HTTP→HTTPS redirect. The `--redirect` flag forces
HTTPS on the next reload.

## Server block

Drop this into `/etc/nginx/sites-available/mesa-mcp.conf` and symlink
into `sites-enabled/`. The `mesa_mcp_backend` upstream points at the
loopback-bound mesa-mcp process.

```nginx
upstream mesa_mcp_backend {
    server 127.0.0.1:8080;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name mesa-mcp.example.org;

    # certbot will manage these; placeholders shown here.
    ssl_certificate     /etc/letsencrypt/live/mesa-mcp.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mesa-mcp.example.org/privkey.pem;
    include             /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam         /etc/letsencrypt/ssl-dhparams.pem;

    # Modest body size — MCP frames are JSON, not file uploads.
    client_max_body_size 4m;

    # ---- SSE endpoint -------------------------------------------------
    location /sse {
        proxy_pass         http://mesa_mcp_backend;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Authorization     $http_authorization;
        proxy_set_header   Connection        "";

        # **Critical for SSE:** disable response buffering and keep the
        # connection alive long enough for slow streaming.
        proxy_buffering        off;
        proxy_cache            off;
        proxy_read_timeout     86400s;
        proxy_send_timeout     86400s;
        chunked_transfer_encoding on;
    }

    # ---- POST channel for client → server frames ----------------------
    location /messages/ {
        proxy_pass         http://mesa_mcp_backend;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_set_header   Authorization     $http_authorization;
        proxy_buffering    off;
        proxy_read_timeout 60s;
    }

    # ---- Health probe (planned) ---------------------------------------
    location = /healthz {
        proxy_pass         http://mesa_mcp_backend;
        proxy_http_version 1.1;
        access_log         off;
    }

    # Optional: catch-all 404 for paths mesa-mcp does not serve.
    location / {
        return 404;
    }
}

# HTTP → HTTPS redirect (certbot --redirect inserts this for you).
server {
    listen 80;
    listen [::]:80;
    server_name mesa-mcp.example.org;
    return 301 https://$host$request_uri;
}
```

## The three lines that matter for SSE

| Directive                            | Why                                                                                              |
| ------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `proxy_buffering off;`               | nginx would otherwise queue the SSE stream chunks; clients would never see updates until close. |
| `proxy_read_timeout 86400s;`         | SSE connections live for hours. The default 60 s would kill them.                                |
| `proxy_http_version 1.1;` + `Connection "";` | Forces HTTP/1.1 keep-alive between nginx and the upstream — required for streaming.       |

If your client reports "request completes immediately with no events"
the first thing to check is `proxy_buffering off;`.

## Apply the config

```bash
sudo ln -s /etc/nginx/sites-available/mesa-mcp.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

## Auto-renewal

certbot installs a `certbot.timer` systemd unit that renews
certificates twice a day. Confirm:

```bash
systemctl list-timers certbot.timer
sudo certbot renew --dry-run
```

The post-renewal hook reloads nginx automatically (see
`/etc/letsencrypt/renewal-hooks/deploy/`).

## Hardening (optional)

- Add `add_header Strict-Transport-Security "max-age=31536000;
  includeSubDomains" always;` once you're confident in the deployment.
- Limit `client_body_buffer_size` and `client_header_buffer_size` to
  modest values — the JSON payloads mesa-mcp accepts are small.
- Consider `limit_req_zone $binary_remote_addr zone=mesa:10m
  rate=10r/s;` in the `http` block plus `limit_req zone=mesa burst=20;`
  per location, especially for `/messages/`.

## See also

- [HTTP / SSE](./http-sse.md)
- [OIDC](./oidc.md)
- [Overview](./overview.md)
- [Monitoring](./monitoring.md)
