"""Batches for checking every violator by subagents (review round 5).

Run: uv run --with 'selectolax<1' python tools/brand-review-batches.py brand-protection/2026-09-28/brand-scan
Writes review/round5/control.json — 60 violators checked in round 4 (to compare a cheaper model with the round-4
verdicts), and review/round5/batches/b001.json … — every other violator, 50 per batch, sorted by violation
confidence, lowest first. Each record has the same fields as the round-4 sample (classified.csv row, page features,
saved files).
"""
import collections
import csv
import gzip
import json
import random
import re
import sys
from pathlib import Path

import importlib.util

csv.field_size_limit(sys.maxsize)
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("brand_confidence", HERE / "brand-confidence.py")
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)
BATCH = 50
CONTROL = 60
SEED = 20261013

KEEP = ("domain", "category", "tags", "why", "mostbet_ads", "other_ads", "plain_gambling_links", "ad_links", "mb_text",
        "mb_per_1k", "mb_anchor", "mb_hidden_links", "text_len", "gambling_per_1k", "other_brands_text", "feed_links",
        "title", "h1", "lang", "final_url", "scan_group", "source")


def records(d: Path, rows: list) -> list:
    want = {r["domain"] for r in rows}
    feats = {}
    with gzip.open(d / "site-features.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            if x["domain"] in want:
                feats[x["domain"]] = next((x[k] for k in ("browser", "http", "http-google-mobile", "http-googlebot")
                                           if x.get(k)), {})
    names = collections.defaultdict(list)
    for p in (d / "html").iterdir():
        names[p.name.split(".", 1)[0]].append(p)
    out = []
    for r in rows:
        pg = feats.get(r["domain"], {})
        files = sorted(str(p.relative_to(d.parents[2])) for p in names.get(r["domain"].split(".", 1)[0], [])
                       if p.name.startswith(r["domain"] + ".")
                       and re.match(r"(http|browser|deep|mbpages)", p.name[len(r["domain"]) + 1:]))
        out.append({**{k: r.get(k, "") for k in KEEP}, "text_sample": (pg.get("text_sample") or "")[:600],
                    "aff_links": (pg.get("aff_links") or [])[:10], "gates": (pg.get("gates") or [])[:10],
                    "trackers": (pg.get("trackers") or [])[:10], "html_files": files})
    return out


def main(d: str):
    d = Path(d)
    rows = bc.load_rows(d)
    now = {r["domain"]: r["category"] for r in rows}
    conf = {r["domain"]: r for r in csv.DictReader(open(d / "confidence.csv", newline="", encoding="utf-8"))}
    viol = [r for r in rows if r["category"] in bc.VIOL]
    # Control: violators judged in round 4, spread over the classes and over confirmed / refuted.
    r4 = {}
    for p in sorted((d / "review" / "round4").glob("verdicts-*.json")):
        for v in json.loads(p.read_text()):
            if v.get("verdict") != "unsure" and now.get(v["domain"]) in bc.VIOL:
                exp = v["should_be"] if v["verdict"] == "wrong" else v["given"]
                r4[v["domain"]] = exp in bc.VIOL
    rnd = random.Random(SEED)
    no = sorted(k for k, y in r4.items() if not y)
    yes = sorted(k for k, y in r4.items() if y)
    pick = no[:CONTROL // 3] if len(no) <= CONTROL // 3 else rnd.sample(no, CONTROL // 3)
    pick += rnd.sample(yes, min(len(yes), CONTROL - len(pick)))
    control = [r for r in viol if r["domain"] in set(pick)]
    out = d / "review" / "round5"
    (out / "batches").mkdir(parents=True, exist_ok=True)
    (out / "control.json").write_text(json.dumps(records(d, control), ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "control-truth.json").write_text(json.dumps({k: r4[k] for k in sorted(pick)}, indent=1), encoding="utf-8")
    rest = [r for r in viol if r["domain"] not in set(pick)]
    rest.sort(key=lambda r: (int(conf.get(r["domain"], {}).get("violation") or 0), r["domain"]))
    recs = records(d, rest)
    for i in range(0, len(recs), BATCH):
        (out / "batches" / f"b{i // BATCH + 1:03d}.json").write_text(
            json.dumps(recs[i:i + BATCH], ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"control {len(control)} ({sum(1 for k in pick if not r4[k])} refuted in round 4), "
          f"batches {(len(recs) + BATCH - 1) // BATCH} × {BATCH} = {len(recs)}")


if __name__ == "__main__":
    main(sys.argv[1])
