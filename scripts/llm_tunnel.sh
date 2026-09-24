#!/usr/bin/env bash
# Open / close an SSH tunnel from this box to the CARC LiteLLM gateway on
# sparky-2, so the live LLM tests (tests/live/) can reach the local vLLM
# models (ab-moe, carc-fast, carc-tools, carc-embed).
#
# The gateway listens on a docker-bridge address on sparky-2
# (172.19.0.1:8000) which is deliberately not routable from the LAN; the
# three chat backends behind it bind loopback there. One tunnel to the
# gateway is therefore the only thing needed.
#
#   scripts/llm_tunnel.sh up       # start (idempotent), print the exports
#   scripts/llm_tunnel.sh status   # is the local end answering?
#   scripts/llm_tunnel.sh down     # close it
#
# This script never touches credentials. The gateway key is
# `general_settings.master_key` in /opt/carc/carc-agents/gateway/
# litellm.config.yaml on sparky-2 (root-readable), or a virtual key minted
# from it via the gateway's /key/generate endpoint. Put it in your shell or
# in the repo-root `.env` (gitignored) as MESA_LLM_API_KEY.
set -euo pipefail

REMOTE="${MESA_LLM_TUNNEL_HOST:-sparky2}"            # ssh_config alias
GATEWAY="${MESA_LLM_TUNNEL_TARGET:-172.19.0.1:8000}"  # as seen from sparky-2
LOCAL_PORT="${MESA_LLM_TUNNEL_PORT:-18000}"
SOCK="${XDG_RUNTIME_DIR:-/tmp}/mesa-llm-tunnel-${LOCAL_PORT}.sock"
BASE_URL="http://127.0.0.1:${LOCAL_PORT}/v1"

alive() {
  curl -fsS -m 5 "http://127.0.0.1:${LOCAL_PORT}/health/liveliness" >/dev/null 2>&1
}

case "${1:-up}" in
  up)
    if alive; then
      echo "tunnel already up on ${BASE_URL}"
    else
      ssh -M -S "${SOCK}" -f -N \
          -o BatchMode=yes -o ExitOnForwardFailure=yes \
          -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
          -L "127.0.0.1:${LOCAL_PORT}:${GATEWAY}" "${REMOTE}"
      for _ in 1 2 3 4 5; do alive && break; sleep 1; done
      alive || { echo "tunnel opened but ${BASE_URL} is not answering" >&2; exit 1; }
      echo "tunnel up: 127.0.0.1:${LOCAL_PORT} -> ${REMOTE}:${GATEWAY}"
    fi
    cat <<EOT

export MESA_LIVE=1
export MESA_LLM_BASE_URL=${BASE_URL}
export MESA_LLM_API_KEY=...      # LiteLLM key, see header comment
pytest tests/live -q
EOT
    ;;
  status)
    if alive; then echo "up: ${BASE_URL}"; else echo "down"; exit 1; fi
    ;;
  down)
    if [ -S "${SOCK}" ]; then
      ssh -S "${SOCK}" -O exit "${REMOTE}" 2>/dev/null || true
      echo "tunnel closed"
    else
      # Started outside this script? Best effort on the exact forward spec.
      pkill -f -- "-L 127.0.0.1:${LOCAL_PORT}:${GATEWAY}" 2>/dev/null && echo "tunnel closed" || echo "no tunnel found"
    fi
    ;;
  *)
    echo "usage: $0 {up|status|down}" >&2; exit 2 ;;
esac
