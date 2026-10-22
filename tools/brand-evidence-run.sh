#!/bin/bash
# Full evidence run on genhost with restarts: the script exits 75 when stalled; finished sites are skipped.
cd /root/seo-analytics-brand-scan
D=brand-protection/2026-09-28/brand-scan
export PATH=/root/bin:/root/.local/bin:/usr/bin:/bin BRAND_SCAN_REGISTRY=/root/seo-analytics-brand-scan/registry/entries.json
while true; do
  uv run -q --with "camoufox[geoip]" --with "selectolax<1" --with aiohttp python -u tools/brand-evidence-video.py \
    $D $D/evidence/domains.txt $D/evidence --proxy socks5://127.0.0.1:1080 --concurrency 8 >> $D/evidence/run.log 2>&1
  rc=$?
  [ $rc = 0 ] && break
  echo "$(date +%T) run exited $rc, restarting" >> $D/evidence/run.log
  pkill -9 -f "playwright/driver/node"; pkill -9 -f camoufox-bin
  sleep 10
done
