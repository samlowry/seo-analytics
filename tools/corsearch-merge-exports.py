import csv, glob, sys, openpyxl
from pathlib import Path
src = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "Downloads/corsearch-export"
out = Path(sys.argv[1])
header, seen, dup = [], {}, 0
for f in sorted(glob.glob(str(src / "*.xlsx"))):
    rows = openpyxl.load_workbook(f, read_only=True).worksheets[0].iter_rows(values_only=True)
    h = next(rows)
    header += [c for c in h if c not in header]
    n = 0
    for r in rows:
        n += 1
        rec = {k: ("" if v is None else v.isoformat(sep=" ") if hasattr(v, "isoformat") else v) for k, v in zip(h, r)}
        if rec["website_id"] in seen: dup += 1; continue
        seen[rec["website_id"]] = rec
    print(Path(f).name.split("__")[0], n)
print("columns", len(header), "unique", len(seen), "dups", dup)
with open(out, "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=header, restval=""); w.writeheader(); w.writerows(seen.values())
