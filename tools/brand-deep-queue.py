"""Queue for brand-scan.py --mode deep: inner pages and own scripts of sites whose home page did not settle
where their traffic goes.

Run: uv run --with selectolax python tools/brand-deep-queue.py brand-protection/2026-09-28/brand-scan
Takes monobrand sites (every mono_* category), article sites and multibrand sites from classified.csv; from each
saved home page picks up to 4 inner pages — posts or links that name Mostbet, then registration / app / bonus /
login pages — and up to 6 of the site's own script files (skipping common libraries). Writes deep-queue.csv.
"""
import csv
import gzip
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

csv.field_size_limit(sys.maxsize)
CATS = {"mono_unresolved", "mono_no_ads", "mono_mostbet", "mono_xlink", "mono_other", "mono_mixed", "article",
        "multibrand"}
MB = re.compile(r"most\s?bet|мостбет", re.I)
USEFUL = re.compile(r"regist|signup|sign-up|login|vhod|kirish|giris|app|apk|download|skach|bonus|promo|casino|"
                    r"kazino|bet|stavk|zerkal|mirror|official", re.I)
LIBS = re.compile(r"jquery|wp-includes|wp-emoji|gtag|googletagmanager|google-analytics|cloudflare|recaptcha|"
                  r"bootstrap|swiper|slick|lazysizes|fontawesome|yandex|metrika|cookie|polyfill|react-dom|"
                  r"elementor|wp-content/plugins/(contact|woocommerce|wordfence)", re.I)


def base(h: str) -> str:
    return (h or "").lower().removeprefix("www.")


def pick(domain: str, html: str, final: str):
    tree = HTMLParser(html)
    host = base(urlsplit(final).hostname or domain)
    posts, useful, scripts = [], [], []
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            u = urljoin(final or f"https://{domain}/", href)
            s = urlsplit(u)
        except ValueError:
            continue  # template placeholders like [GLOBAL_DOWNLOAD_AFF_LINK]
        if base(s.hostname) != host or s.path in ("", "/"):
            continue
        text = a.text(deep=True) or ""
        if MB.search(text) or MB.search(s.path):
            posts.append(u)
        elif USEFUL.search(s.path):
            useful.append(u)
    for n in tree.css("script[src]"):
        try:
            u = urljoin(final or f"https://{domain}/", n.attributes.get("src") or "")
        except ValueError:
            continue
        if base(urlsplit(u).hostname) == host and not LIBS.search(u):
            scripts.append(u)
    uniq = lambda xs: list(dict.fromkeys(xs))  # noqa: E731
    return uniq(posts)[:3] + [u for u in uniq(useful) if u not in posts][:4 - min(3, len(uniq(posts)))], uniq(scripts)[:6], host


def main(d: str):
    d = Path(d)
    rows = []
    with open(d / "classified.csv", newline="", encoding="utf-8") as f:
        sites = [r for r in csv.DictReader(f) if r["category"] in CATS]
    for r in sites:
        for src in ("http", "browser"):
            p = d / "html" / f"{r['domain']}.{src}.html.gz"
            if not p.exists():
                continue
            with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
                head, _, html = f.read().partition("\n")
            m = re.search(r"final_url=(\S+)", head)
            pages, scripts, host = pick(r["domain"], html, m.group(1) if m else "")
            if pages or scripts:
                rows.append({"domain": r["domain"], "site": host, "pages": " ".join(pages), "scripts": " ".join(scripts),
                             "category": r["category"]})
            break
    with open(d / "deep-queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["domain", "site", "pages", "scripts", "category"])
        w.writeheader()
        w.writerows(rows)
    print(len(sites), "sites,", len(rows), "with inner pages or scripts;",
          sum(len(x["pages"].split()) for x in rows), "pages,", sum(len(x["scripts"].split()) for x in rows), "scripts")


if __name__ == "__main__":
    main(sys.argv[1])
