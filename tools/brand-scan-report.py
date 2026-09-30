"""Tables from the logs written by tools/brand-scan.py.

Run: uv run --with aiohttp --with selectolax python tools/brand-scan-report.py brand-protection/<date>/brand-scan
Per domain the browser record wins; otherwise the HTTP record, with destinations the HTTP pass could
not decide filled in from the browser destination pass (dest-browser.jsonl.gz) and the group
recomputed. Ads found by any earlier scan are merged into the group (with_history); latest_group
keeps what the last scan alone showed, destinations.csv lists earlier ad destinations with their scan. Writes groups.csv (one row per domain: group, reason, brands, partner ids) and
destinations.csv (every followed destination with its final page and brand), prints a summary.
On top of the scanner's groups: 0_mostbet_frontend, 7_unresolved, 8_no_mention (see post_group);
`incomplete` says why an ad group may still miss advertisers.
"""
import collections
import csv
import gzip
import importlib.util
import json
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


MB_GROUPS = ("1_mostbet_only", "4_mixed")
AD_KINDS = ("mostbet", "other_gambling")
# Opened sites whose ads a single scan may miss: rotating /go/ links, injected scripts shown now and then.
UNION_GROUPS = OPENED + ("7_unresolved", "8_no_mention")


def read_all(path: Path) -> dict:
    """Every record per domain from a jsonl.gz log, in file order."""
    out = collections.defaultdict(list)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out[r["domain"]].append(r)
    except (EOFError, OSError):
        pass
    return out


def ad_signature(r: dict):
    res = r["result"]
    return res.get("group") in MB_GROUPS, tuple(sorted(res.get("other_brands") or []))


def with_history(r: dict, hist: list) -> dict:
    """Ads seen in any scan count: a site that sent traffic to a casino once did so, even if the
    latest scan caught a rotation without it. The latest record stays the base; groups only go up
    (no ads -> Mostbet / other / mixed), and dead or unshown sites keep their current state."""
    res = r["result"]
    g = res.get("group")
    opened = [h for h in hist if h["result"].get("group") in UNION_GROUPS]
    mb_ever = any(h["result"].get("group") in MB_GROUPS for h in opened)
    other_ever = sorted({b for h in opened for b in h["result"].get("other_brands") or []})
    new = {**res, "scans": len(hist),
           "ever_mostbet_pids": sorted({p for h in opened for p in h["result"].get("mostbet_pids") or []}),
           "ever_other_brands": other_ever,
           "ads_differ": len({ad_signature(h) for h in opened}) > 1,
           "group_history": [h["result"].get("group") for h in hist]}
    if g in UNION_GROUPS:
        mb = g in MB_GROUPS or mb_ever
        other = bool(res.get("other_brands")) or bool(other_ever)
        if mb or (other and g != "8_no_mention"):
            ng = "4_mixed" if mb and other else "1_mostbet_only" if mb else "3_other_only"
            if ng != g:
                new.update(group=ng, reason="ads_seen_in_earlier_scan", latest_group=g)
    return {**r, "result": new}


def load(d: Path):
    """Latest record per domain (browser over HTTP, rest over the browser record it extends), with
    ads from every earlier record merged in (with_history). Returns (records, history)."""
    dcache = bs.load_dest_cache(d / "dest-browser.jsonl.gz")
    http_all = read_all(d / "http-scan.jsonl.gz")
    browser_all = read_all(d / "browser-scan.jsonl.gz")
    rest_all = {k: [r for r in rs if r.get("mode") == "browser+rest"]
                for k, rs in read_all(d / "rest-scan.jsonl.gz").items()}
    prep_http = lambda r: post_group(refine_record(regroup_legacy(bs.resolve_record(r, dcache))))  # noqa: E731
    prep = lambda r: post_group(refine_record(regroup_legacy(r)))  # noqa: E731
    hist = collections.defaultdict(list)
    for k, rs in http_all.items():
        hist[k] += [prep_http(r) for r in rs]
    for logs in (browser_all, rest_all):
        for k, rs in logs.items():
            hist[k] += [prep(r) for r in rs]
    latest = {k: hist[k][len(rs) - 1] for k, rs in http_all.items()}
    latest.update({k: hist[k][len(http_all.get(k, [])) + len(rs) - 1] for k, rs in browser_all.items()})
    # Rest-pass records extend a browser record; a later browser rescan supersedes them again.
    # Timestamps are local to the host that wrote them, so logs merged after a rest pass drop
    # the rest records of the domains they rescan.
    for k, rs in rest_all.items():
        if rs and (k not in browser_all or rs[-1]["ts"] >= browser_all[k][-1].get("ts", "")):
            latest[k] = hist[k][-1]
    return [with_history(r, hist[k]) for k, r in latest.items()], hist


def hops_str(hops):
    return " → ".join(f"{s} {u}" for s, u in hops or [])


def main(d: str):
    d = Path(d)
    recs, hist = load(d)
    groups, dests = [], []
    for r in recs:
        res, h = r["result"], r.get("home") or {}
        mentions, text_len = int(h.get("mostbet_mentions") or 0), int(h.get("text_len") or 0)
        history = []
        for x in res.get("group_history") or []:
            if not history or history[-1] != x:
                history.append(x)
        groups.append({
            "domain": r["domain"], "group": res.get("group"), "reason": res.get("reason", ""),
            "latest_group": res.get("latest_group", res.get("group")), "ads_differ": res.get("ads_differ", ""),
            "ever_mostbet_pids": " ".join(res.get("ever_mostbet_pids") or []),
            "ever_other_brands": " | ".join(res.get("ever_other_brands") or []),
            "scans": res.get("scans", ""), "group_history": " > ".join(history),
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
        rows = [("latest", x) for x in r.get("destinations") or [] if x.get("kind") != "internal"]
        seen = {(x.get("url"), x.get("final_url")) for _, x in rows}
        for e in hist[r["domain"]]:
            if e is r or e["result"].get("group") not in UNION_GROUPS:
                continue
            for x in e.get("destinations") or []:
                if x.get("kind") in AD_KINDS and (x.get("url"), x.get("final_url")) not in seen:
                    seen.add((x.get("url"), x.get("final_url")))
                    rows.append((f'{e.get("mode", "")} {e.get("ts", "")}', x))
        for scan, x in rows:
            dests.append({"domain": r["domain"], "scan": scan, "via": x.get("via", ""), "url": x.get("url", ""),
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
