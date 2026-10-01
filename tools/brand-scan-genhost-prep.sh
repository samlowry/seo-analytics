#!/usr/bin/env bash
# One-time (or refresh) prep of genhost for the uBlock rescan.
# Safe for prod: only creates ~/seo-analytics-brand-scan and copies the registry.
# Does NOT install Tailscale, does NOT set system proxy / exit node.
#
# Run on the Mac:
#   ./tools/brand-scan-genhost-prep.sh
set -euo pipefail

REMOTE="${BRAND_SCAN_SSH:-root@genhost.host}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REMOTE_DIR="${BRAND_SCAN_REMOTE_DIR:-/root/seo-analytics-brand-scan}"
REGISTRY="${BRAND_SCAN_REGISTRY_SRC:-$HOME/Developer/skaner-bitykh-ssylok/registry/entries.json}"

if [[ ! -f "$REGISTRY" ]]; then
  echo "registry not found: $REGISTRY" >&2
  exit 1
fi

echo "→ ${REMOTE}:${REMOTE_DIR}"
ssh "$REMOTE" "mkdir -p '${REMOTE_DIR}/registry' \
  '${REMOTE_DIR}/brand-protection/2026-09-28/brand-scan' \
  '${REMOTE_DIR}/brand-protection/2026-09-28/affiliate-scan'"

# Code + queue + redo lists (not the multi-GB growing browser-scan — sync that at start time).
rsync -az --delete \
  --exclude '.git' \
  --exclude 'brand-protection/2026-09-28/brand-scan/browser-scan.jsonl.gz' \
  --exclude 'brand-protection/2026-09-28/brand-scan/run-browser.log' \
  --exclude '**/__pycache__' \
  "${ROOT}/tools/" "${REMOTE}:${REMOTE_DIR}/tools/"

rsync -az \
  "${ROOT}/brand-protection/2026-09-28/affiliate-scan/camoufox-queue.csv" \
  "${REMOTE}:${REMOTE_DIR}/brand-protection/2026-09-28/affiliate-scan/"

rsync -az \
  "${ROOT}/brand-protection/2026-09-28/brand-scan/redo-ublock-all.txt" \
  "${ROOT}/brand-protection/2026-09-28/brand-scan/redo-ublock-suspect.txt" \
  "${ROOT}/brand-protection/2026-09-28/brand-scan/NOTES.md" \
  "${ROOT}/brand-protection/2026-09-28/brand-scan/SERVER-RESCAN.md" \
  "${REMOTE}:${REMOTE_DIR}/brand-protection/2026-09-28/brand-scan/"

rsync -az "$REGISTRY" "${REMOTE}:${REMOTE_DIR}/registry/entries.json"

ssh "$REMOTE" bash -s <<EOF
set -euo pipefail
cd '${REMOTE_DIR}'
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="\$HOME/.local/bin:\$PATH"
fi
export PATH="\$HOME/.local/bin:\$PATH"
# Install Camoufox browser binary once (geoip extra needed when geoip=True).
uv run --with 'camoufox[geoip]' python -c "from camoufox.sync_api import Camoufox; print('camoufox ok')"
echo "prep done on \$(hostname); free -h | head -2"
EOF

echo
echo "Prep OK. When the local scan finishes:"
echo "  1) flip residential IP"
echo "  2) ./tools/brand-scan-socks-tunnel.sh"
echo "  3) follow SERVER-RESCAN.md § start"
