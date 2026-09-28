"""Сводные таблицы по scan.jsonl.gz из tools/affiliate-scan.py.

Запуск: python3 tools/affiliate-report.py brand-protection/<дата>/affiliate-scan
Пишет affiliate.csv, not-affiliate.csv, failed.csv и печатает сводку.
"""
import collections
import csv
import gzip
import json
import sys
from pathlib import Path


def load(path: Path):
    recs = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                recs[r["domain"]] = r  # при повторном прогоне берём последнюю запись
    except (EOFError, OSError):
        pass
    return list(recs.values())


def chain_str(chain):
    return " → ".join(f"{h.get('status', h.get('error', '?'))} {h['url']}" for h in chain or [] if "url" in h)


def main(d: str):
    d = Path(d)
    recs = load(d / "scan.jsonl.gz")
    rows = collections.defaultdict(list)
    for r in recs:
        res = r["result"]
        g = res["group"]
        base = {"domain": r["domain"], "final_url": r.get("final_url", ""),
                "http_status": r.get("status", ""), "title": r.get("title", ""),
                "mostbet_mentions": r.get("mostbet_mentions", ""),
                "links_internal": len(r.get("links_internal", [])),
                "links_external": len(r.get("links_external", []))}
        if g == "affiliate":
            chk = next((c for c in r.get("checks", []) if c.get("found")), {})
            rows[g].append({**base, "method": res.get("method"), "ref_url": res.get("ref_url"),
                            "ref_host": (res.get("ref_url") or "").split("/")[2] if res.get("ref_url") else "",
                            "ref_kind": res.get("ref_kind"), "via": res.get("via", ""),
                            "chain": chain_str(chk.get("chain")) if chk else chain_str(r.get("home_chain")
                                                                                        if res.get("method") == "home_redirect" else [])})
        elif g == "not_affiliate":
            rows[g].append({**base, "flag": res.get("flag", ""),
                            "gate_dead": " ".join(res.get("gate_dead", [])),
                            "gate_other": " ".join(sorted(set(res.get("gate_other", [])))),
                            "candidates_checked": len(r.get("checks", []))})
        else:
            hc = r.get("home_chain") or []
            detail = ""
            if hc and isinstance(hc, list) and hc and "detail" in hc[-1]:
                detail = hc[-1]["detail"]
            rows["failed"].append({**base, "reason": res.get("reason"), "server": r.get("server", ""),
                                   "js_buttons": r.get("js_buttons", ""), "detail": detail})
    names = {"affiliate": "affiliate.csv", "not_affiliate": "not-affiliate.csv", "failed": "failed.csv"}
    for g, fn in names.items():
        rs = sorted(rows[g], key=lambda x: x["domain"])
        with open(d / fn, "w", newline="", encoding="utf-8") as f:
            if rs:
                w = csv.DictWriter(f, fieldnames=list(rs[0].keys()))
                w.writeheader()
                w.writerows(rs)
    print("всего", len(recs))
    for g in names:
        print(g, len(rows[g]))
    print("способ (аффилиаты):", collections.Counter(x["method"].split(":")[0] + ":" + x["method"].split(":")[-1]
                                                    for x in rows["affiliate"]).most_common(12))
    print("хосты рефок, топ:", collections.Counter(x["ref_host"] for x in rows["affiliate"]).most_common(10))
    print("причины (не открылись):", collections.Counter(x["reason"] for x in rows["failed"]).most_common(20))
    na = rows["not_affiliate"]
    print("не аффилиаты: thin_page", sum(1 for x in na if x["flag"]), "gate_dead", sum(1 for x in na if x["gate_dead"]),
          "gate_other", sum(1 for x in na if x["gate_other"]))
    print("gate_other хосты:", collections.Counter(h for x in na for h in x["gate_other"].split()).most_common(10))


if __name__ == "__main__":
    main(sys.argv[1])
