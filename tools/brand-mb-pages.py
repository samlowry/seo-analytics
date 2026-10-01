"""Find the pages about Mostbet on each live site: sitemaps (robots.txt, sitemap.xml, sitemap_index.xml,
wp-sitemap.xml, nested up to 3 levels) and the saved home page's own links whose address or text names Mostbet.

Run: uv run --with aiohttp --with selectolax python tools/brand-mb-pages.py brand-protection/2026-09-28/brand-scan
Writes mbpages-queue.csv (domain, site, pages — up to 8, home excluded) for brand-scan.py --mode mbpages.
Only the site's own files are requested; no outbound link is followed here.
"""
import asyncio
import csv
import gzip
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import aiohttp
from selectolax.parser import HTMLParser

csv.field_size_limit(sys.maxsize)
MB = re.compile(r"most-?bet|мостбет|mostbet", re.I)
LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
SKIP = {"dead", "parked", "stub", "not_shown", "mirror", "redirect_ref", "redirect_other"}
MAX_PAGES = 8


def base(h):
    return (h or "").lower().removeprefix("www.")


async def get(s, url, cap=4_000_000):
    try:
        async with s.get(url, timeout=aiohttp.ClientTimeout(total=10, sock_connect=5), ssl=False) as r:
            if r.status != 200:
                return ""
            b = await r.content.read(cap)
            if url.endswith(".gz") or b[:2] == b"\x1f\x8b":
                try:
                    b = gzip.decompress(b)
                except OSError:
                    return ""
            return b.decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — a site without a sitemap is the common case
        return ""


async def sitemap_urls(s, site):
    root = f"https://{site}/"
    robots = await get(s, root + "robots.txt", 200_000)
    queue = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots) or \
        [root + p for p in ("sitemap.xml", "sitemap_index.xml", "wp-sitemap.xml")]
    seen, pages = set(), []
    for depth in range(3):
        nxt = []
        for sm in queue[:6]:
            if sm in seen:
                continue
            seen.add(sm)
            for loc in LOC.findall(await get(s, sm))[:50000]:
                loc = loc.replace("&amp;", "&")
                (nxt if re.search(r"\.xml(\.gz)?($|\?)", loc, re.I) else pages).append(loc)
        # Prefer child sitemaps that name Mostbet or posts
        queue = sorted(nxt, key=lambda u: (not MB.search(unquote(u)), "post" not in u))
        if not queue:
            break
    return [p for p in pages if MB.search(unquote(p))]


def home_links(d: Path, domain):
    for src in ("browser", "http"):
        p = d / "html" / f"{domain}.{src}.html.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as f:
            head, _, html = f.read().partition("\n")
        m = re.search(r"final_url=(\S+)", head)
        final = m.group(1) if m else f"https://{domain}/"
        host = base(urlsplit(final).hostname)
        out = []
        for a in HTMLParser(html).css("a[href]"):
            try:
                u = urljoin(final, (a.attributes.get("href") or "").strip())
                su = urlsplit(u)
            except ValueError:
                continue
            if base(su.hostname) == host and su.path not in ("", "/") and \
                    (MB.search(unquote(su.path)) or MB.search(a.text(deep=True) or "")):
                out.append(u.split("#")[0])
        return host, out
    return domain, []


async def main(d):
    d = Path(d)
    with open(d / "classified.csv", newline="", encoding="utf-8") as f:
        sites = [r for r in csv.DictReader(f) if r["category"] not in SKIP]
    sem = asyncio.Semaphore(150)
    rows = []
    async with aiohttp.ClientSession(headers=UA) as s:
        async def one(r):
            host, links = home_links(d, r["domain"])
            async with sem:
                sm = await sitemap_urls(s, host)
            pages, seen = [], set()
            for u in links + sm:  # home links first: what the site itself puts forward
                k = u.rstrip("/")
                if k not in seen and urlsplit(u).path not in ("", "/"):
                    seen.add(k)
                    pages.append(u)
            if pages:
                rows.append({"domain": r["domain"], "site": host, "pages": " ".join(pages[:MAX_PAGES]),
                             "found": len(pages), "category": r["category"]})
        done = 0

        async def counted(r):
            nonlocal done
            await one(r)
            done += 1
            if done % 1000 == 0:
                print(f"{done}/{len(sites)} sites, {len(rows)} with Mostbet pages", flush=True)
        await asyncio.gather(*(counted(r) for r in sites))
        print(f"done {len(sites)} sites, {len(rows)} with Mostbet pages", flush=True)
    with open(d / "mbpages-queue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["domain", "site", "pages", "found", "category"])
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
