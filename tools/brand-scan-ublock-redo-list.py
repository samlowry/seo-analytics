#!/usr/bin/env python3
"""Rebuild redo-ublock-*.txt from browser-scan.jsonl.gz (uBlock era = first seen ≤ cutoff)."""
import argparse
import json
import zlib
from pathlib import Path

CUTOFF = "2026-09-29T11:42:41"


def load_members(path: Path):
    raw = path.read_bytes()
    out = b""
    while raw:
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            out += d.decompress(raw)
        except Exception:
            break
        raw = d.unused_data
    return out.decode("utf-8", "replace").splitlines()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_dir", type=Path, help="brand-protection/.../brand-scan")
    ap.add_argument("--cutoff", default=CUTOFF)
    a = ap.parse_args()
    path = a.scan_dir / "browser-scan.jsonl.gz"
    first, last = {}, {}
    for line in load_members(path):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        d, ts = r.get("domain"), r.get("ts") or ""
        if not d:
            continue
        if d not in first or ts < first[d][0]:
            first[d] = (ts, r)
        if d not in last or ts >= last[d][0]:
            last[d] = (ts, r)
    ubo = sorted((d for d, (ts, _) in first.items() if ts and ts <= a.cutoff),
                 key=lambda d: first[d][0])
    suspect = [d for d in ubo
               if (last[d][1].get("result") or {}).get("group") in ("1_mostbet_only", "2_no_ads")]
    (a.scan_dir / "redo-ublock-all.txt").write_text("\n".join(ubo) + "\n")
    (a.scan_dir / "redo-ublock-suspect.txt").write_text("\n".join(suspect) + "\n")
    print(f"all={len(ubo)} suspect_1_2={len(suspect)} cutoff={a.cutoff}")


if __name__ == "__main__":
    main()
