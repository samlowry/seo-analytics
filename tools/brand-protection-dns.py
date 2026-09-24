"""Выгрузка brand protection (xlsx) → CSV и деление доменов на ресолвится / не ресолвится.

Запуск:
  uv run --with openpyxl --with dnspython python tools/brand-protection-dns.py <file.xlsx> <out_dir>

Ресолв — A и AAAA через публичные резолверы (1.1.1.1, затем 8.8.8.8), а не через
системный: у системного бывают свои фильтры. IDN переводится в punycode.
Статусы:
  resolves    — есть хотя бы один A или AAAA;
  nxdomain    — имени нет;
  no_address  — имя есть, адресов нет (припаркован без записей, только MX и т. п.);
  error       — SERVFAIL, таймаут, нет ответа от NS — после повторов на обоих резолверах.
"""
import csv
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dns.resolver
import openpyxl

RESOLVERS = ["1.1.1.1", "8.8.8.8"]


def to_ascii(domain: str) -> str:
    return domain.strip().rstrip(".").encode("idna").decode("ascii")


def query(name: str, rtype: str, ns: str):
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = [ns]
    r.timeout = 4
    r.lifetime = 8
    try:
        return "ok", [x.to_text() for x in r.resolve(name, rtype)]
    except dns.resolver.NXDOMAIN:
        return "nxdomain", []
    except dns.resolver.NoAnswer:
        return "noanswer", []
    except (dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout, dns.exception.DNSException) as e:
        return "error", [type(e).__name__]


def resolve(domain: str) -> dict:
    try:
        name = to_ascii(domain)
    except UnicodeError:
        return {"dns_status": "error", "dns_ips": "", "dns_note": "bad idna"}
    last_err = ""
    for ns in RESOLVERS:
        s4, a = query(name, "A", ns)
        if s4 == "nxdomain":
            return {"dns_status": "nxdomain", "dns_ips": "", "dns_note": ""}
        s6, aaaa = query(name, "AAAA", ns)
        ips = (a if s4 == "ok" else []) + (aaaa if s6 == "ok" else [])
        if ips:
            return {"dns_status": "resolves", "dns_ips": " ".join(ips), "dns_note": ""}
        if s4 == "noanswer" and s6 in ("noanswer", "nxdomain"):
            return {"dns_status": "no_address", "dns_ips": "", "dns_note": ""}
        last_err = f"{ns}: A={s4} {a} AAAA={s6} {aaaa}"
    return {"dns_status": "error", "dns_ips": "", "dns_note": last_err}


def cell(v):
    return "" if v is None else v.isoformat(sep=" ") if hasattr(v, "isoformat") else v


def main(src: str, out_dir: str):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ws = openpyxl.load_workbook(src, read_only=True).worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    header, rows = list(rows[0]), [[cell(v) for v in r] for r in rows[1:]]
    domains = [r[header.index("domain_name")] for r in rows]

    with ThreadPoolExecutor(max_workers=64) as pool:
        dns_rows = list(pool.map(resolve, domains))

    extra = ["dns_status", "dns_ips", "dns_note"]
    full_header = ["domain_name", "domain_ascii"] + extra + [h for h in header if h != "domain_name"]
    merged = []
    for r, d in zip(rows, dns_rows):
        rec = dict(zip(header, r)) | d
        try:
            rec["domain_ascii"] = to_ascii(rec["domain_name"])
        except UnicodeError:
            rec["domain_ascii"] = ""
        merged.append(rec)

    def write(path, recs):
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=full_header)
            w.writeheader()
            w.writerows(sorted(recs, key=lambda x: x["domain_ascii"]))

    write(out / "all.csv", merged)
    write(out / "resolves.csv", [m for m in merged if m["dns_status"] == "resolves"])
    write(out / "not-resolving.csv", [m for m in merged if m["dns_status"] != "resolves"])

    from collections import Counter
    for k, v in Counter(m["dns_status"] for m in merged).most_common():
        print(k, v)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
