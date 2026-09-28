"""resolves.csv минус наши домены (brand-protection/our-domains.txt).

Запуск: python tools/brand-protection-minus-ours.py brand-protection/<дата>
Сравнение по punycode в нижнем регистре, без ведущего www.
Пишет <дата>/resolves-minus-ours.csv и печатает, где нашлись наши домены.
"""
import csv
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def norm(d: str) -> str:
    d = d.strip().lower().rstrip(".")
    d = d[4:] if d.startswith("www.") else d
    return d.encode("idna").decode("ascii")


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
    print("наших в списке", len(ours))
    print("  из них ресолвятся", len(found["resolves"]))
    print("  не ресолвятся", len(found["not-resolving"]))
    missing = ours - found["resolves"] - found["not-resolving"]
    print("  нет в базе Corsearch", len(missing))
    (day / "our-domains-not-in-base.txt").write_text("".join(d + "\n" for d in sorted(missing)))


if __name__ == "__main__":
    main(sys.argv[1])
