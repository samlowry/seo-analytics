"""resolves.csv минус наши домены (brand-protection/our-domains.txt).

Запуск: python tools/brand-protection-minus-ours.py brand-protection/<дата>
Сравнение по punycode в нижнем регистре, без ведущего www.
Пишет <дата>/resolves-minus-ours.csv и печатает, где нашлись наши домены.
Плюс resolves-minus-ours-unique.csv — одна строка на домен: IDN бывает в базе дважды,
юникодом и punycode. Оставляется строка с заполненным infringement_type, при равенстве —
с поздним crawling_date; website_id остальных — в колонке other_website_ids.
"""
import csv
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def norm(d: str) -> str:
    d = d.strip().lower().rstrip(".")
    d = d[4:] if d.startswith("www.") else d
    return d.encode("idna").decode("ascii")


def write_unique(path, rows, fields):
    groups = {}
    for x in rows:
        groups.setdefault(norm(x["domain_name"]), []).append(x)
    out = []
    for g in groups.values():
        g.sort(key=lambda x: (bool(x["infringement_type"]), x["crawling_date"]), reverse=True)
        best = dict(g[0], other_website_ids=" ".join(x["website_id"] for x in g[1:]))
        out.append(best)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fields) + ["other_website_ids"])
        w.writeheader()
        w.writerows(out)
    print(f"уникальных доменов {len(out)} (склеено дублей {len(rows) - len(out)})")


def main(day: str):
    day = Path(day)
    ours = {norm(l) for l in open(day.parent / "our-domains.txt", encoding="utf-8") if l.strip()}
    found = {}
    for name in ("resolves", "not-resolving"):
        with open(day / f"{name}.csv", newline="", encoding="utf-8") as f:
            r = csv.DictReader(f)
            rows = list(r)
        hits = {norm(x["domain_name"]) for x in rows} & ours
        found[name] = hits
        if name == "resolves":
            with open(day / "resolves-minus-ours.csv", "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=r.fieldnames)
                w.writeheader()
                kept = [x for x in rows if norm(x["domain_name"]) not in ours]
                w.writerows(kept)
            print(f"resolves {len(rows)} − наших {len(rows) - len(kept)} = {len(kept)}")
            write_unique(day / "resolves-minus-ours-unique.csv", kept, r.fieldnames)
    print("наших в списке", len(ours))
    print("  из них ресолвятся", len(found["resolves"]))
    print("  не ресолвятся", len(found["not-resolving"]))
    missing = ours - found["resolves"] - found["not-resolving"]
    print("  нет в базе Corsearch", len(missing))
    (day / "our-domains-not-in-base.txt").write_text("".join(d + "\n" for d in sorted(missing)))


if __name__ == "__main__":
    main(sys.argv[1])
