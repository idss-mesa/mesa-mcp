# Deploy

Run mesa-mcp as a shared HTTP service (Mode A) that several users reach with CyVerse Keycloak tokens. Local and VICE installs need none of this; see [Use mesa-mcp](../user/index.md).

* [Overview](overview.md) - Topology and components of a hosted mesa-mcp, and the as-deployed VM.
* [systemd](systemd.md) - A hardened unit for the HTTP transport, install steps, health checks and log rotation.
* [HTTP / SSE transport](http-sse.md) - Routes, bearer-token auth, bind addresses, RFC 9728 metadata, and an operator checklist.
* [OIDC](oidc.md) - Register CyVerse Keycloak clients, wire the config, and how tokens flow through mesa-mcp.
* [Nginx + TLS](nginx-tls.md) - Reverse proxy with Let's Encrypt and the buffering settings streaming needs.
* [Postgres](postgres.md) - A Postgres database for the mesa-ducklake catalog behind the AVU history.
* [Monitoring](monitoring.md) - Logs, `/healthz`, disk use and process supervision.
