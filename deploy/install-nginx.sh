#!/usr/bin/env bash
# Install the mesa-mcp nginx site and (optionally) provision a Let's
# Encrypt cert via certbot.
#
# Usage:
#   sudo MESA_MCP_HOSTNAME=mesa-mcp.example.org ./deploy/install-nginx.sh
#   sudo MESA_MCP_HOSTNAME=mesa-mcp.example.org CERT_EMAIL=ops@example.org \
#        ./deploy/install-nginx.sh --run-certbot
#
# Prerequisites:
#   - nginx + python3-certbot-nginx installed (`sudo apt install nginx certbot python3-certbot-nginx`).
#   - DNS A/AAAA record for $MESA_MCP_HOSTNAME pointing at this host.
#   - Port 80 reachable from the public internet (certbot HTTP challenge).
#   - mesa-mcp is running on 127.0.0.1:8080 (verify with `systemctl status mesa-mcp`).

set -euo pipefail

REPO="${REPO:-/home/exouser/mesa-mcp}"
SITE_NAME="mesa-mcp"
SOURCE_CONF="${REPO}/deploy/nginx/${SITE_NAME}.conf"
TARGET_AVAIL="/etc/nginx/sites-available/${SITE_NAME}.conf"
TARGET_ENABLED="/etc/nginx/sites-enabled/${SITE_NAME}.conf"

if [[ "${EUID}" -ne 0 ]]; then
    echo "error: this script needs root (sudo). Re-run with sudo." >&2
    exit 1
fi

: "${MESA_MCP_HOSTNAME:?must be set, e.g. MESA_MCP_HOSTNAME=mesa-mcp.example.org}"

if [[ ! -f "${SOURCE_CONF}" ]]; then
    echo "error: ${SOURCE_CONF} not found. Are you running from the repo root?" >&2
    exit 1
fi

# Substitute hostname and install the site.
install -m 0644 -o root -g root "${SOURCE_CONF}" "${TARGET_AVAIL}"
sed -i "s/MESA_MCP_HOSTNAME/${MESA_MCP_HOSTNAME}/g" "${TARGET_AVAIL}"

# Comment out the HTTPS server block on first install — certbot uncomments
# (re-writes) it. Until then, nginx -t would fail because the cert files
# don't exist yet.
if [[ ! -f "/etc/letsencrypt/live/${MESA_MCP_HOSTNAME}/fullchain.pem" ]]; then
    echo "note: no Let's Encrypt cert found for ${MESA_MCP_HOSTNAME} — commenting out HTTPS block."
    # Comment everything in the second `server {` block.
    sed -i '/^# HTTPS/,/^}$/ s/^/#/' "${TARGET_AVAIL}"
fi

ln -sf "${TARGET_AVAIL}" "${TARGET_ENABLED}"

# Validate nginx config and reload.
nginx -t
systemctl reload nginx

echo "Installed:"
echo "  ${TARGET_AVAIL}"
echo "  ${TARGET_ENABLED}"
echo

if [[ "${1:-}" == "--run-certbot" ]]; then
    : "${CERT_EMAIL:?must be set when --run-certbot is given, e.g. CERT_EMAIL=ops@example.org}"
    echo "Running certbot for ${MESA_MCP_HOSTNAME}..."
    certbot --nginx -d "${MESA_MCP_HOSTNAME}" \
        --email "${CERT_EMAIL}" --agree-tos --no-eff-email --redirect
    echo
    echo "Certbot done. To verify:"
    echo "  curl -fsS https://${MESA_MCP_HOSTNAME}/healthz"
else
    echo "Next: run certbot to get the TLS cert:"
    echo "  sudo certbot --nginx -d ${MESA_MCP_HOSTNAME}"
    echo "Or re-run this script with --run-certbot:"
    echo "  sudo MESA_MCP_HOSTNAME=${MESA_MCP_HOSTNAME} CERT_EMAIL=... ${0} --run-certbot"
fi
