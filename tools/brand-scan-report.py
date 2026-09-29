"""Tables from the logs written by tools/brand-scan.py.

Run: uv run --with aiohttp --with selectolax python tools/brand-scan-report.py brand-protection/<date>/brand-scan
Per domain the browser record wins; otherwise the HTTP record, with destinations the HTTP pass could
not decide filled in from the browser destination pass (dest-browser.jsonl.gz) and the group
recomputed. Writes groups.csv (one row per domain: group, reason, brands, partner ids) and
destinations.csv (every followed destination with its final page and brand), prints a summary.
On top of the scanner's groups: 0_mostbet_frontend, 7_unresolved, 8_no_mention (see post_group);
`incomplete` says why an ad group may still miss advertisers.
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
    """Apply rules added after a record was written, from what the record keeps.

    Registrar and hosting placeholders matched by the current PARKED -> 5_dead parked. Browser
    records written before group 6 carry reason protection:cloudflare; map them the way the scanner
    does now: an unsolved challenge -> 6_cf_check, the WAF block page -> 5_not_shown.
    """
    res, h = r["result"], r.get("home") or {}
    if res.get("group") in ("2_no_ads", "5_not_shown") and \
            bs.lb.PARKED.search(f'{h.get("title", "")} {h.get("text_sample", "")}'):
        return {**r, "result": {**res, "group": "5_dead", "reason": "parked", "was": res.get("group")}}
    if res.get("reason") != "protection:cloudflare":
        return r
    if bs.CF_BLOCK.search(f'{h.get("title", "")} {h.get("text_sample", "")}'):
        new = {**res, "reason": "protection:cloudflare_block"}
    else:
        new = {**res, "group": "6_cf_check", "reason": "cloudflare_challenge"}
    return {**r, "result": new}


OPENED = ("1_mostbet_only", "2_no_ads", "3_other_only", "4_mixed")


def refine_record(r: dict) -> dict:
    """Re-run landing_brand.refine() over the stored destinations of an opened site and regroup it,
    so corrections added after the scan apply without rescanning."""
    res = r["result"]
    if res.get("group") not in OPENED or not r.get("destinations"):
        return r
    dests = [bs.lb.refine(x) for x in r["destinations"]]
    if dests == r["destinations"]:
        return r
    live = [x for x in dests if x.get("kind") != "internal"]
    new = {**res, **bs.lb.site_group(live, (r.get("home") or {}).get("mostbet_mentions") or 0)}
    new["unresolved"] = sum(x.get("kind") in ("dead", "unknown", "needs_browser") for x in live)
    return {**r, "destinations": dests, "result": new}


def incomplete(r: dict) -> list:
    """Why an opened site's advertisers may be undercounted: links left unchecked or undecided, or
    script buttons on the home page that only the browser clicks while the record is HTTP-only."""
    res, h = r["result"], r.get("home") or {}
    why = []
    if int(res.get("not_followed") or 0):
        why.append(f"not_followed={res['not_followed']}")
    if int(res.get("unresolved") or 0):
        why.append(f"unresolved={res['unresolved']}")
    if r.get("mode") == "http" and int(h.get("js_buttons") or 0):
        why.append(f"js_buttons_not_clicked={h['js_buttons']}")
    return why


def post_group(r: dict) -> dict:
    """Groups the destination brands alone cannot tell.

    0_mostbet_frontend — the official Mostbet frontend itself (a mirror), not a third-party site;
    8_no_mention — no Mostbet mention on the home page and no Mostbet ads: not a brand user;
    7_unresolved — no ads found, but not every link was checked, so "no ads" is not established.
    """
    res, h = r["result"], r.get("home") or {}
    g = res.get("group")
    if g not in OPENED:
        return r
    why = incomplete(r)
    new = {**res, "incomplete": why}
    if bs.lb.MIRROR_TITLE.search(h.get("title") or ""):
        new.update(group="0_mostbet_frontend", reason="official_frontend_title", was=g)
    elif g in ("2_no_ads", "3_other_only") and not int(h.get("mostbet_mentions") or 0):
        new.update(group="8_no_mention", reason="no_mostbet_on_home", was=g)
    elif g == "2_no_ads" and why:
        new.update(group="7_unresolved", reason=" ".join(why), was=g)
    return {**r, "result": new}


def home_mentions(h: dict) -> list:
    """Other brands named on the home page. Azino777 was matched inside kazino/казино before the
    pattern fix, so a stored Azino777 is kept only when the title confirms it."""
    names = h.get("home_other_brand_mentions") or []
    rx = dict(bs.lb.BRAND_RES)["Azino777"]
    return [n for n in names if n != "Azino777" or rx.search(h.get("title") or "")]


def load(d: Path):
    http = bs.read_last(d / "http-scan.jsonl.gz")
    browser = bs.read_last(d / "browser-scan.jsonl.gz")
    dcache = bs.load_dest_cache(d / "dest-browser.jsonl.gz")
    recs = {k: post_group(refine_record(regroup_legacy(bs.resolve_record(r, dcache)))) for k, r in http.items()}
    recs.update({k: post_group(refine_record(regroup_legacy(r))) for k, r in browser.items()})
    return list(recs.values())


def hops_str(hops):
    return " → ".join(f"{s} {u}" for s, u in hops or [])


def main(d: str):
    d = Path(d)
    recs = load(d)
    groups, dests = [], []
    for r in recs:
        res, h = r["result"], r.get("home") or {}
        mentions, text_len = int(h.get("mostbet_mentions") or 0), int(h.get("text_len") or 0)
        groups.append({
            "domain": r["domain"], "group": res.get("group"), "reason": res.get("reason", ""),
            "was_group": res.get("was", ""), "incomplete": " ".join(res.get("incomplete") or []),
            "mostbet_in_domain": bool(bs.lb.MOSTBET_NAME.search(r["domain"])),
            "mostbet_in_title": bool(bs.lb.MOSTBET_NAME.search(h.get("title") or "")),
            "mentions_per_1k_chars": round(mentions * 1000 / text_len, 2) if text_len else "",
            "text_len": text_len or "",
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
            "home_other_brand_mentions": " | ".join(home_mentions(h)),
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
