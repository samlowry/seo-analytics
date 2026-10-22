#!/bin/bash
# Mac side of the genhost SOCKS tunnel that heals itself: the local SOCKS (pinned to en0, the home line) and the
# ssh reverse forward each run in a loop. The ssh uses ~/.ssh/genhost-tunnel, a key that on the server may only
# listen on 127.0.0.1:1080 (restrict,port-forwarding,permitlisten; no shell), so a reconnect needs no 1Password.
# Revoke: delete its line ("genhost reverse SOCKS tunnel only") from /root/.ssh/authorized_keys on genhost.
cd "$(dirname "$0")/.."
PORT="${BRAND_SCAN_SOCKS_PORT:-1080}"
IFACE="${BRAND_SCAN_IFACE:-en0}"
( while true; do python3 tools/socks5-local.py --port "$PORT" --iface "$IFACE"; echo "$(date +%T) socks exited, restart"; sleep 2; done ) &
SOCKS_LOOP=$!
trap 'kill $SOCKS_LOOP 2>/dev/null; pkill -P $SOCKS_LOOP 2>/dev/null; exit' INT TERM EXIT
while true; do
  ssh -N -i ~/.ssh/genhost-tunnel -o IdentityAgent=none -o IdentitiesOnly=yes -o BatchMode=yes \
      -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -o ConnectTimeout=20 \
      -R "127.0.0.1:$PORT:127.0.0.1:$PORT" root@genhost.host
  echo "$(date +%T) tunnel ssh exited ($?), reconnect in 5 s"
  sleep 5
done
