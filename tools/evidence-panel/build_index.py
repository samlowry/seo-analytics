"""Собрать data.json для панели доказательств из каталога скана 2026-09-28.

База — brand-scan/report/takedown-send.csv (весь список на снос). К каждой строке:
видео из evidence/results.jsonl (в пакете или отказ с причиной), строка страйка из
strike/strike-list.csv, метка Corsearch из all.csv, сохранённая главная из brand-scan/html/.

Поиск должен находить домен и там, где он не первый в цепочке: mostbet-kg.kg своего
ролика не имеет, но в 120 роликах редиректоры переезжают на него. Поэтому в `via`
лежат все хосты из журналов роликов и конечный адрес.

Срезов может быть несколько: первый — основной (2026-09-28), следующие — добавленные позже
(например, 2026-11-20 — ручная проверка двух доменов). Список на снос в срезе — либо
brand-scan/report/takedown-send.csv, либо takedown-send.csv в корне; strike/ и all.csv необязательны,
метка Corsearch ищется во всех срезах. Строка помнит свой срез (`src`), по нему сервер ищет файлы.

Запуск: python3 build_index.py <срез> [<срез> …] <выходной data.json>
"""

import csv
import gzip
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

CLASSES = {
    "mono_other": "Монобренд → реклама только чужих",
    "mono_hidden": "Монобренд → скрытые ссылки на чужих",
    "bait": "Приманка",
    "redirect_other": "Редирект на чужую рефку",
    "mono_mixed": "Монобренд → Mostbet и чужие",
    "discredit": "Дискредитация бренда",
    "mb_page_other": "Статья про Mostbet → реклама чужих",
}

# Сохранённые главные: какой вариант брать, если нарушение не находится ни в одном.
PAGE_KINDS = ["browser", "http", "http-mobile", "http-google-mobile", "http-googlebot"]
PAGE_LABEL = {
    "browser": "Человек, браузер",
    "http": "Исходник, компьютер",
    "http-mobile": "Исходник, телефон",
    "http-google-mobile": "Google, телефон",
    "http-googlebot": "Google, компьютер",
}

URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)")
HOSTS_RE = re.compile(r"hosts: ([A-Za-z0-9.\-, ]+)")
NOTE_HOST_RE = re.compile(r"\b((?:[a-z0-9\-]+\.)+[a-z]{2,})\b")
SCAN_RE = re.compile(r"\(scan: ([A-Za-z0-9.\-]+\.[a-z]{2,})\)")


def host(url: str) -> str:
    try:
        h = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return h.lower().removeprefix("www.")


def chain_hosts(rec: dict) -> tuple[list[str], list[str]]:
    """Все хосты из журналов ролика; отдельно — «улики» (скрытые и чужие ссылки)."""
    seen, clues = [], []
    for a in rec.get("attempts", []):
        for line in a.get("log", []):
            for h in URL_RE.findall(line):
                h = h.lower().removeprefix("www.")
                if h not in seen:
                    seen.append(h)
            for m in HOSTS_RE.findall(line):
                for h in m.split(","):
                    h = h.strip().lower()
                    if h and h not in clues:
                        clues.append(h)
            for h in SCAN_RE.findall(line):
                if h.lower() not in clues:
                    clues.append(h.lower())
    return seen, clues


def pick_page(html_dir: Path, domain: str, needles: list[str]) -> dict | None:
    """Вариант сохранённой главной: первый, где встречается улика, иначе первый по порядку."""
    found = [k for k in PAGE_KINDS if (html_dir / f"{domain}.{k}.html.gz").exists()]
    if not found:
        return None
    needles = [n for n in needles if n and n != domain]
    chosen, hit = found[0], ""
    for k in found:
        try:
            text = gzip.open(html_dir / f"{domain}.{k}.html.gz", "rt", errors="replace").read().lower()
        except (OSError, EOFError):
            continue
        n = next((n for n in needles if n in text), "")
        if n:
            chosen, hit = k, n
            break
    return {"kind": chosen, "label": PAGE_LABEL[chosen], "has": hit, "all": found}


def load_root(root: Path, cors: dict, added: bool) -> list[dict]:
    ev = root / "evidence"
    html_dir = root / "brand-scan" / "html"
    results = {}
    if (ev / "results.jsonl").exists():
        for line in open(ev / "results.jsonl", encoding="utf-8"):
            d = json.loads(line)
            results[d["domain"]] = d
    strike = {r["domain"]: r for r in load_csv(root / "strike" / "strike-list.csv")}
    send = root / "brand-scan" / "report" / "takedown-send.csv"
    if not send.exists():
        send = root / "takedown-send.csv"

    rows = []
    for r in load_csv(send):
        dom = r["domain"]
        rec = results.get(dom)
        via, clues = chain_hosts(rec) if rec else ([], [])
        final_host = host(r["final_url"])
        video = None
        if rec:
            mp4 = rec["files"].get("mp4") if rec.get("files") else None
            if not rec["accepted"] and mp4 and not mp4.startswith("rejected/"):
                mp4 = "rejected/" + mp4
            files = rec.get("files") or {}
            png = files.get("png") or files.get("jpg")
            if png and not rec["accepted"] and not png.startswith("rejected/"):
                png = "rejected/" + png
            if mp4 and not (ev / mp4).exists():
                mp4 = None
            video = {
                "accepted": rec["accepted"],
                "reason": rec.get("reason", ""),
                "mp4": mp4,
                "png": png if png and (ev / png).exists() else None,
                "landing": (rec.get("landing") or {}).get("brand") or "",
                "final_url": rec.get("final_url") or "",
            }
            if rec.get("final_url"):
                via.append(host(rec["final_url"]))
        if final_host:
            via.append(final_host)
        via = [h for h in dict.fromkeys(via) if h and h != dom]
        s = strike.get(dom)
        rows.append({
            "domain": dom,
            "cls": r["category"],
            "cls_name": CLASSES.get(r["category"], r["category"]),
            "note": r["checker_note"],
            "reason": r["reason"],
            "conf": r["checker_confidence"],
            "final_url": r["final_url"],
            "via": via,
            "video": video,
            "strike": {"tag": s["tag"], "label": s["label"]} if s else None,
            "corsearch": cors.get(dom),
            "src": root.name,
            "added": root.name if added else "",
            "page": pick_page(html_dir, dom, clues + NOTE_HOST_RE.findall(r["checker_note"].lower()) + via),
        })
    return rows


def load_csv(p: Path) -> list[dict]:
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def main() -> None:
    roots, out = [Path(x) for x in sys.argv[1:-1]], Path(sys.argv[-1])
    cors = {}
    for root in roots:
        for r in load_csv(root / "all.csv"):
            cors[r["domain_name"]] = {
                "label": r["infringement_type"],
                "taken_down": r["taken_down"] == "True",
                "moderated": r["moderation_date"][:10],
            }
    by_dom = {}
    for n, root in enumerate(roots):
        for row in load_root(root, cors, added=n > 0):
            by_dom[row["domain"]] = row  # более поздний срез заменяет строку раннего
    rows = list(by_dom.values())

    # Обратная связь: «через этот домен снято N роликов в пакете».
    through = {}
    for row in rows:
        if row["video"] and row["video"]["accepted"]:
            for h in row["via"]:
                through.setdefault(h, []).append(row["domain"])
    for row in rows:
        row["through"] = through.get(row["domain"], [])

    rows.sort(key=lambda x: x["domain"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "classes": CLASSES}, ensure_ascii=False), encoding="utf-8")
    acc = sum(1 for x in rows if x["video"] and x["video"]["accepted"])
    pages = sum(1 for x in rows if x["page"])
    print(f"{len(rows)} доменов, роликов в пакете {acc}, сохранённых страниц {pages} → {out}")


if __name__ == "__main__":
    main()
