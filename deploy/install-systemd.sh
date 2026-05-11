#!/usr/bin/env bash
# Install mesa-mcp as a systemd service on this Ubuntu host.
#
# Prerequisites:
#   - This script must be run from the repo root (or with $REPO set).
#   - mesa-mcp is installed in /home/exouser/mesa-mcp/.venv/.
#   - /etc/mesa-mcp/config.yaml exists (use config.yaml.example as a template).
#
# What it does (all sudo):
#   1. Creates /etc/mesa-mcp/ with a sane group + mode.
#   2. Copies mesa-mcp.env.example → /etc/mesa-mcp/mesa-mcp.env.example
#      (operator copies to mesa-mcp.env and fills in secrets).
#   3. Installs deploy/mesa-mcp.service into /etc/systemd/system/.
#   4. Runs `systemctl daemon-reload`.
#
# What it does NOT do (operator decides):
#   - `systemctl enable --now mesa-mcp` — gated on the config file being
#     real, the Postgres catalog being live, and the OIDC client being
#     registered with CyVerse admin.
#
# Usage:
#   sudo ./deploy/install-systemd.sh

set -euo pipefail

REPO="${REPO:-/home/exouser/mesa-mcp}"
SERVICE_NAME="mesa-mcp"
SERVICE_FILE="${REPO}/deploy/${SERVICE_NAME}.service"
ENV_EXAMPLE="${REPO}/deploy/${SERVICE_NAME}.env.example"

if [[ "${EUID}" -ne 0 ]]; then
    echo "error: this script needs root (sudo). Re-run with sudo." >&2
    exit 1
fi

if [[ ! -f "${SERVICE_FILE}" ]]; then
    echo "error: ${SERVICE_FILE} not found. Are you running from the repo root?" >&2
    exit 1
fi

install -d -m 0750 -o root -g exouser /etc/mesa-mcp
install -m 0640 -o root -g exouser "${ENV_EXAMPLE}" /etc/mesa-mcp/mesa-mcp.env.example

if [[ ! -f /etc/mesa-mcp/mesa-mcp.env ]]; then
    echo "note: /etc/mesa-mcp/mesa-mcp.env does not exist."
    echo "      Copy mesa-mcp.env.example and fill in secrets:"
    echo "        sudo cp /etc/mesa-mcp/mesa-mcp.env.example /etc/mesa-mcp/mesa-mcp.env"
    echo "        sudo chmod 0640 /etc/mesa-mcp/mesa-mcp.env"
    echo "        sudoedit /etc/mesa-mcp/mesa-mcp.env"
fi

if [[ ! -f /etc/mesa-mcp/config.yaml ]]; then
    echo "note: /etc/mesa-mcp/config.yaml does not exist."
    echo "      Copy from the repo and fill in:"
    echo "        sudo cp ${REPO}/config.yaml.example /etc/mesa-mcp/config.yaml"
    echo "        sudoedit /etc/mesa-mcp/config.yaml"
fi

install -m 0644 -o root -g root "${SERVICE_FILE}" /etc/systemd/system/${SERVICE_NAME}.service
systemctl daemon-reload

echo
echo "Installed:"
echo "  /etc/systemd/system/${SERVICE_NAME}.service"
echo "  /etc/mesa-mcp/mesa-mcp.env.example  (copy to mesa-mcp.env and fill in)"
echo
echo "Next steps (when config + secrets are ready):"
echo "  sudo systemctl enable --now ${SERVICE_NAME}"
echo "  sudo systemctl status ${SERVICE_NAME}"
echo "  journalctl -u ${SERVICE_NAME} -f"
