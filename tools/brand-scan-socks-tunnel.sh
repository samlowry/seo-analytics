#!/usr/bin/env bash
# Mac side: local SOCKS that exits via the home line (Yettel) — pinned to BRAND_SCAN_IFACE (en0), so routes
# a corporate VPN takes (GlobalProtect) do not change the exit —
# reverse-forwarded to genhost as 127.0.0.1:1080. Does NOT join the server to
# Tailscale and does NOT change the server's default route.
#
# Usage (on the Mac, after flipping the residential IP):
#   ./tools/brand-scan-socks-tunnel.sh
# Leave this terminal open while the server scan runs. Ctrl-C tears both down.
set -euo pipefail

REMOTE="${BRAND_SCAN_SSH:-root@genhost.host}"
LOCAL_PORT="${BRAND_SCAN_SOCKS_PORT:-1080}"
REMOTE_PORT="${BRAND_SCAN_REMOTE_PORT:-1080}"

cleanup() {
  [[ -n "${PPROXY_PID:-}" ]] && kill "$PPROXY_PID" 2>/dev/null || true
  [[ -n "${SSH_PID:-}" ]] && kill "$SSH_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

IFACE="${BRAND_SCAN_IFACE:-en0}"
echo "local SOCKS on 127.0.0.1:${LOCAL_PORT} (exit = this Mac via ${IFACE})"
python3 "$(dirname "$0")/socks5-local.py" --port "$LOCAL_PORT" --iface "$IFACE" &
PPROXY_PID=$!
sleep 1
if ! kill -0 "$PPROXY_PID" 2>/dev/null; then
  echo "local SOCKS failed to start" >&2
  exit 1
fi

ME=$(curl -sS -m 10 -x "socks5h://127.0.0.1:${LOCAL_PORT}" https://ipinfo.io/json)
echo "Mac public IP: $(echo "$ME" | python3 -c 'import sys,json; j=json.load(sys.stdin); print(j.get("ip"), j.get("org"), j.get("country"))')"

echo "SSH reverse tunnel → ${REMOTE}:127.0.0.1:${REMOTE_PORT}"
# GatewayPorts not needed: bind remote side to loopback only (default).
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R "${REMOTE_PORT}:127.0.0.1:${LOCAL_PORT}" "$REMOTE" &
SSH_PID=$!
sleep 1
if ! kill -0 "$SSH_PID" 2>/dev/null; then
  echo "ssh reverse tunnel failed" >&2
  exit 1
fi

echo
echo "Verify on the server (should show THIS Mac's IP, not Amsterdam):"
echo "  ssh ${REMOTE} \"curl -sS -m 12 -x socks5h://127.0.0.1:${REMOTE_PORT} https://ipinfo.io/json\""
echo
echo "Tunnel up. Leave this running. Ctrl-C to stop."
wait "$SSH_PID"
