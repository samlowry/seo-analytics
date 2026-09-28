"""Tables from the logs written by tools/brand-scan.py.

Run: uv run --with aiohttp --with selectolax python tools/brand-scan-report.py brand-protection/<date>/brand-scan
Per domain the browser record wins; otherwise the HTTP record, with destinations the HTTP pass could
not decide filled in from the browser destination pass (dest-browser.jsonl.gz) and the group
recomputed. Writes groups.csv (one row per domain: group, reason, brands, partner ids) and
destinations.csv (every followed destination with its final page and brand), prints a summary.
"""
import collections
import csv
import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("brand_scan", Path(__file__).resolve().parent / "brand-scan.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)


def regroup_legacy(r: dict) -> dict:
    """Browser records written before group 6 carry reason protection:cloudflare; map them the way
    the scanner does now: an unsolved challenge -> 6_cf_check, the WAF block page -> 5_not_shown."""
    res, h = r["result"], r.get("home") or {}
    if res.get("reason") != "protection:cloudflare":
        return r
    if bs.CF_BLOCK.search(f'{h.get("title", "")} {h.get("text_sample", "")}'):
        new = {**res, "reason": "protection:cloudflare_block"}
    else:
        new = {**res, "group": "6_cf_check", "reason": "cloudflare_challenge"}
    return {**r, "result": new}


def load(d: Path):
    http = bs.read_last(d / "http-scan.jsonl.gz")
    browser = bs.read_last(d / "browser-scan.jsonl.gz")
    dcache = bs.load_dest_cache(d / "dest-browser.jsonl.gz")
    recs = {k: bs.resolve_record(r, dcache) for k, r in http.items()}
    recs.update({k: regroup_legacy(r) for k, r in browser.items()})
    return list(recs.values())


def hops_str(hops):
    return " → ".join(f"{s} {u}" for s, u in hops or [])


def main(d: str):
    d = Path(d)
    recs = load(d)
    groups, dests = [], []
    for r in recs:
        res, h = r["result"], r.get("home") or {}
        groups.append({
            "domain": r["domain"], "group": res.get("group"), "reason": res.get("reason", ""),
            "mostbet_pids": " ".join(res.get("mostbet_pids") or []),
            "other_brands": " | ".join(res.get("other_brands") or []),
            "mostbet_weak_only": res.get("mostbet_weak_only", ""),
            "brand_site_links": " ".join(res.get("brand_site_links") or []),
            "gambling_site_links": " ".join(res.get("gambling_site_links") or []),
            "method": res.get("method", ""), "thin_page": res.get("thin_page", ""),
            "no_brand_mention": res.get("no_brand_mention", ""), "unresolved": res.get("unresolved", ""),
            "not_followed": res.get("not_followed", ""), "mostbet_mentions": h.get("mostbet_mentions", ""),
            "http_status": h.get("status", ""), "final_url": h.get("final_url", ""),
            "moved_to": h.get("moved_to", ""), "title": h.get("title", ""),
            "protection": h.get("protection", ""), "error": h.get("error", ""),
            "text_sample": (h.get("text_sample") or "")[:200] if str(res.get("group", "")).startswith(("5", "6")) else "",
            "home_other_brand_mentions": " | ".join(h.get("home_other_brand_mentions") or []),
            "mode": r.get("mode", ""), "http_group": res.get("http_group", ""),
            "queue_reason": r.get("queue_reason", ""), "network": r.get("network", ""),
            "elapsed_s": r.get("elapsed_s", ""), "ts": r.get("ts", ""),
        })
        for x in r.get("destinations") or []:
            if x.get("kind") == "internal":
                continue
            dests.append({"domain": r["domain"], "via": x.get("via", ""), "url": x.get("url", ""),
                          "final_url": x.get("final_url", ""), "kind": x.get("kind", ""),
                          "brand": x.get("brand", ""), "evidence": x.get("evidence", ""), "pid": x.get("pid", ""),
                          "ad_route": x.get("ad_route", ""), "title": x.get("title", ""),
                          "cached": x.get("cached", ""), "from_dest_pass": x.get("from_dest_pass", ""),
                          "hops": hops_str(x.get("hops"))})
    groups.sort(key=lambda x: (x["group"] or "", x["domain"]))
    for fn, rows in (("groups.csv", groups), ("destinations.csv", dests)):
        with open(d / fn, "w", newline="", encoding="utf-8") as f:
            if rows:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
    print("sites", len(recs))
    print("groups:", dict(sorted(collections.Counter(x["group"] for x in groups).items())))
    print("group 5 / 6 / needs_browser reasons:", collections.Counter(
        f'{x["group"]}:{x["reason"]}' for x in groups
        if str(x["group"]).startswith(("5", "6")) or x["group"] == "needs_browser").most_common(30))
    print("other brands:", collections.Counter(b for x in groups for b in x["other_brands"].split(" | ") if b)
          .most_common(20))
    print("mostbet pids:", collections.Counter(p for x in groups for p in x["mostbet_pids"].split() if p)
          .most_common(15))
    print("destination kinds:", dict(collections.Counter(x["kind"] for x in dests)))


if __name__ == "__main__":
    main(sys.argv[1])
