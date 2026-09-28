"""Очередь для прогона camoufox: сайты группы failed из affiliate-scan.

Запуск: python3 tools/camoufox-queue.py brand-protection/<дата>/affiliate-scan
Пишет camoufox-queue.csv: domain, url, reason, priority, mostbet_mentions.
priority 1 — главная открылась, но ссылку собирает скрипт (нужен браузер);
2 — защита от ботов (Cloudflare, капча, DDoS-Guard, Sucuri);
3 — сервер ответил ошибкой 4xx/5xx (часть — отсечка по стране, тогда прокси);
4 — сеть: таймаут, отказ соединения, TLS, петля редиректов — вероятно, сайт мёртв.
Внутри приоритета — по числу упоминаний Mostbet на главной, по убыванию.
"""
import csv
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)


def priority(reason: str) -> int:
    if reason in ("needs_browser_js_buttons", "js_shell"):
        return 1
    if reason in ("cloudflare_challenge", "captcha", "ddos_guard", "sucuri") or reason.startswith("cloudflare_"):
        return 2
    if reason.startswith("http_") or reason == "not_html":
        return 3
    return 4


def main(d: str):
    d = Path(d)
    rows = list(csv.DictReader(open(d / "failed.csv", encoding="utf-8")))
    out = []
    for r in rows:
        url = f"https://{r['domain']}/"  # редирект мог зависеть от клиента — пусть браузер пройдёт его сам
        m = int(r["mostbet_mentions"]) if (r["mostbet_mentions"] or "").isdigit() else 0
        out.append({"domain": r["domain"], "url": url, "reason": r["reason"],
                    "priority": priority(r["reason"]), "mostbet_mentions": m})
    out.sort(key=lambda x: (x["priority"], -x["mostbet_mentions"], x["domain"]))
    with open(d / "camoufox-queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    from collections import Counter
    print("в очереди", len(out), dict(sorted(Counter(x["priority"] for x in out).items())))


if __name__ == "__main__":
    main(sys.argv[1])
