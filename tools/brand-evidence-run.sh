#!/bin/bash
# Full evidence run on genhost: 8 independent processes (one browser each, every 8th domain), each restarted
# by its own loop. A Playwright driver crash stops one shard for at most the watchdog time; the rest go on.
# The script exits 75 on a dead driver or a stall (killing its own browsers first); finished sites are skipped.
cd /root/seo-analytics-brand-scan
D=brand-protection/2026-09-28/brand-scan
export PATH=/root/bin:/root/.local/bin:/usr/bin:/bin BRAND_SCAN_REGISTRY=/root/seo-analytics-brand-scan/registry/entries.json
N=8
for k in $(seq 0 $((N - 1))); do
  (
    while true; do
      uv run -q --with "camoufox[geoip]" --with "selectolax<1" --with aiohttp python -u tools/brand-evidence-video.py \
        $D $D/evidence/domains.txt $D/evidence --proxy socks5://127.0.0.1:1080 --concurrency 1 --shard $k/$N \
        >> $D/evidence/run-$k.log 2>&1
      rc=$?
      [ $rc = 0 ] && break
      echo "$(date +%T) shard $k exited $rc, restarting" >> $D/evidence/run-$k.log
      sleep 10
    done
  ) &
  sleep 3
done
wait
