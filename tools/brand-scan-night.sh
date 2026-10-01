#!/bin/bash
# Overnight browser pass on genhost: rendered home HTML, JS buttons clicked, destinations followed,
# all through the Mac SOCKS tunnel. Queue: night-queue.csv, ordered by priority (1: HTTP-only ad
# sites, 2: Cloudflare sites never opened in a browser, 3: browser sites with links left, 4: rendered
# HTML only). Waits for a running brand-scan to finish instead of killing it.
# Bot checks are only waited out passively by brand-scan.py; nothing here clicks them.
set -euo pipefail
cd /root/seo-analytics-brand-scan
export PATH="$HOME/.local/bin:$PATH"
export BRAND_SCAN_REGISTRY=/root/seo-analytics-brand-scan/registry/entries.json
OUT=brand-protection/2026-09-28/brand-scan-night
QUEUE=brand-protection/2026-09-28/brand-scan/night-queue.csv
mkdir -p "$OUT"

while pgrep -f "[p]ython tools/brand-scan.py" >/dev/null; do
  echo "$(date +%T) waiting for the running scan to finish"
  sleep 60
done

ip=$(curl -sS -m 8 -x socks5h://127.0.0.1:1080 https://ipinfo.io/ip || true)
echo "$(date +%T) proxy_ip=$ip"
echo "$ip" | grep -q '^109\.245\.' || { echo PROXY_FAIL; exit 1; }

exec nice -n 10 uv run --with 'camoufox[geoip]' --with aiohttp --with aiohttp-socks --with selectolax \
  python tools/brand-scan.py "$QUEUE" "$OUT" \
  --mode browser \
  --proxy socks5://127.0.0.1:1080 \
  --concurrency 8 \
  --max-follow 20 \
  --save-html
