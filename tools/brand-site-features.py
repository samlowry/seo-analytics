"""Features of every saved home page, for classifying sites by type (axis A) and by ads (axis B).

Run: uv run --with selectolax --with aiohttp python tools/brand-site-features.py brand-protection/2026-09-28/brand-scan
Reads <dir>/html/<domain>.{http,browser}.html.gz (the rendered page wins for text, both are scanned for
links), writes <dir>/site-features.jsonl.gz, one record per domain. No network.

Per page: visible text size and Mostbet density; where the Mostbet mentions sit (plain text, link text,
link addresses, hidden blocks) — a hacked site carries Mostbet only in links, often hidden; other
brands named in the text; article-feed signs (a blog lists many posts); affiliate-looking outbound
links with the brand their host names; APK links; a script that acts on a search-engine referrer.
"""
import gzip
import json
import multiprocessing as mp
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import landing_brand as lb  # noqa: E402

MB = re.compile(r"most\s?bet|мостбет|мостбэт", re.I)
HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|(left|top|text-indent)\s*:\s*-\d{3,}|font-size\s*:\s*0(px)?\s*(;|$)|"
    r"opacity\s*:\s*0(\.0+)?\s*(;|$)|(height|width)\s*:\s*[01]px[^\"]*overflow\s*:\s*hidden|"
    r"overflow\s*:\s*hidden[^\"]*(height|width)\s*:\s*[01]px|clip\s*:\s*rect\(\s*0", re.I)
AFF_Q = re.compile(lb.AFF_PARAMS.pattern + "|" + lb.TRACK_PARAMS.pattern, re.I)
GATE_PATH = re.compile(r"^/(go|goto|out|link|visit|click|redirect|redir|r|ref|aff|partner|promo|bonus|reg|"
                       r"register|signup|join|play|download|apk|get|official|recommends|refer|visit-site)"
                       r"([/?#._-]|$)", re.I)
DATE_PATH = re.compile(r"/20[012]\d/(0?[1-9]|1[0-2])/|/20[012]\d-\d\d-\d\d|/\d{4}/\d{2}/\d{2}/")
SLUG = re.compile(r"/[a-z0-9Ѐ-ӿ%]+(?:-[a-z0-9Ѐ-ӿ%]+){3,}/?$", re.I)
REFERRER_JS = re.compile(r"document\.referrer", re.I)
SEARCH_ENGINES = re.compile(r"google|bing|yandex|yahoo|duckduckgo|baidu|search", re.I)
POPUP = re.compile(r"window\.open|location(\.href)?\s*=|location\.(replace|assign)", re.I)
PLATFORMS = re.compile(
    r"(^|\.)(blogspot\.[a-z.]+|wordpress\.com|wixsite\.com|wix\.com|github\.io|netlify\.app|vercel\.app|"
    r"pages\.dev|workers\.dev|telegra\.ph|sites\.google\.com|weebly\.com|tilda\.ws|webflow\.io|medium\.com|"
    r"notion\.site|substack\.com|tumblr\.com|jimdosite\.com|jimdo\.com|ucoz\.[a-z]+|narod\.ru|"
    r"blogger\.com|squarespace\.com|strikingly\.com|mystrikingly\.com|site123\.me|webnode\.[a-z.]+|"
    r"yolasite\.com|carrd\.co|glitch\.me|herokuapp\.com|firebaseapp\.com|web\.app|onrender\.com|"
    r"surge\.sh|gitbook\.io|hashnode\.dev|livejournal\.com|over-blog\.com|hatenablog\.com|"
    r"canva\.site|framer\.website|framer\.app|bubbleapps\.io|godaddysites\.com|wpcomstaging\.com|"
    r"000webhostapp\.com|repl\.co|replit\.app|azurewebsites\.net|amazonaws\.com|appspot\.com|"
    r"b-cdn\.net|r2\.dev|linktr\.ee|taplink\.cc|bio\.link|about\.me|gitlab\.io|codeberg\.page|"
    r"neocities\.org|free\.fr|t\.me|typepad\.com|ghost\.io|teletype\.in|vc\.ru|dzen\.ru|zen\.yandex\.ru)$",
    re.I)
BRAND_ALT = [(n, rx) for n, rx in lb.BRAND_RES]
# Dictionary names that are ordinary words in running text; counted only next to gambling words.
COMMON_WORDS = {"Admiral", "Aurora", "Joker", "Fortuna", "Glory", "Fresh", "Sol", "Drip", "Rox", "Lex",
                "Kent", "Monro", "Lev", "Banda", "Jet", "Daddy", "Volna", "Kometa", "Selector", "Gama",
                "Leon", "Eldorado", "Pinnacle", "Blaze", "Stake", "Caliente", "Meridian", "Irwin", "Arkada",
                "Crickex", "Baji", "Beef", "Cat Casino", "Up-X", "Vulkan", "Booi", "Flagman"}


def read(path: Path):
    try:
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
            s = f.read()
    except (OSError, EOFError):
        return "", ""
    head, _, body = s.partition("\n")
    m = re.search(r"final_url=(\S+)", head)
    return body, (m.group(1) if m else "")


def hidden(node) -> bool:
    n, depth = node, 0
    while n is not None and depth < 12:
        a = n.attributes or {}
        if "hidden" in a or (a.get("aria-hidden") == "true" and n.tag == "div") or \
                HIDDEN_STYLE.search(a.get("style") or ""):
            return True
        n, depth = n.parent, depth + 1
    return False


def visible_text(tree) -> str:
    body = tree.body
    if body is None:
        return ""
    for n in body.css("script,style,noscript,template,svg"):
        n.decompose()
    return re.sub(r"\s+", " ", body.text(separator=" ")).strip()


def page_features(html: str, final_url: str, domain: str) -> dict:
    tree = HTMLParser(html)
    host = (urlsplit(final_url).hostname or domain).lower()
    title_n = tree.css_first("title")
    title = (title_n.text() if title_n else "").strip()[:200]
    h1 = " / ".join(n.text(deep=True).strip()[:120] for n in tree.css("h1")[:3])
    heads = [n.text(deep=True).strip() for n in tree.css("h1,h2,h3")][:200]
    html_tag = tree.css_first("html")
    lang = ((html_tag.attributes.get("lang") if html_tag else "") or "")[:10]
    gen = tree.css_first('meta[name="generator"]')
    generator = ((gen.attributes.get("content") if gen else "") or "")[:60]
    scripts = " ".join((n.text() or "")[:50000] for n in tree.css("script") if not n.attributes.get("src"))

    links, mb_anchor, mb_hidden_links, hidden_links = [], 0, 0, 0
    internal, date_links, slug_links, ext_hosts = 0, 0, 0, Counter()
    apk, gates, aff_links, seen_aff = [], [], [], set()
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            u = urljoin(final_url or f"https://{domain}/", href)
            s = urlsplit(u)
        except ValueError:
            continue
        text = re.sub(r"\s+", " ", a.text(deep=True) or "").strip()[:80]
        h = (s.hostname or "").lower()
        is_int = lb_same(h, host)
        mb_here = bool(MB.search(text)) or bool(MB.search(h)) or bool(MB.search(s.path))
        hid = hidden(a)
        if hid:
            hidden_links += 1
        if mb_here:
            mb_anchor += len(MB.findall(text)) or 1
            if hid:
                mb_hidden_links += 1
        if s.path.lower().endswith(".apk"):
            apk.append(u[:200])
        if is_int:
            internal += 1
            if DATE_PATH.search(s.path):
                date_links += 1
            if SLUG.search(s.path):
                slug_links += 1
            if GATE_PATH.search(s.path):
                gates.append({"url": u[:200], "text": text})
            continue
        ext_hosts[h] += 1
        ref_kind = lb_ref(u, host)
        affq = bool(AFF_Q.search(s.query or ""))
        if (ref_kind or affq) and u not in seen_aff:
            seen_aff.add(u)
            aff_links.append({"url": u[:300], "text": text, "host": h, "brand": lb.brand_of_host(h),
                              "ref_kind": ref_kind or "", "hidden": hid})
        links.append((h, mb_here, hid))

    for n in tree.css("[data-href],[data-url],[data-link],[data-go],[onclick]"):
        for k in ("data-href", "data-url", "data-link", "data-go"):
            v = n.attributes.get(k)
            if v and v.startswith("http"):
                h = (urlsplit(v).hostname or "").lower()
                if not lb_same(h, host) and (lb_ref(v, host) or AFF_Q.search(urlsplit(v).query or "")):
                    aff_links.append({"url": v[:300], "text": "", "host": h, "brand": lb.brand_of_host(h),
                                      "ref_kind": lb_ref(v, host) or "", "hidden": False, "src": k})

    text = visible_text(tree)
    tl = max(len(text), 1)
    mb_text = len(MB.findall(text))
    gambling = len(lb.GAMBLING.findall(text[:300000]))
    others = Counter()
    sample = text[:300000]
    for name, rx in BRAND_ALT:
        c = len(rx.findall(sample))
        if c and (name not in COMMON_WORDS or gambling >= 5):
            others[name] += c
    ref_js = bool(REFERRER_JS.search(scripts) and SEARCH_ENGINES.search(scripts) and POPUP.search(scripts))
    return {
        "host": host, "title": title, "h1": h1, "lang": lang, "generator": generator,
        "text_len": len(text), "mb_text": mb_text, "mb_per_1k": round(mb_text * 1000 / tl, 2),
        "mb_title": bool(MB.search(title)), "mb_h1": bool(MB.search(h1)),
        "mb_heads": sum(bool(MB.search(x)) for x in heads), "heads": len(heads),
        "mb_anchor": mb_anchor, "mb_hidden_links": mb_hidden_links, "hidden_links": hidden_links,
        "gambling_words": gambling, "gambling_per_1k": round(gambling * 1000 / tl, 2),
        "other_brands": dict(others.most_common(12)),
        "links_int": internal, "links_ext": sum(ext_hosts.values()), "ext_hosts": len(ext_hosts),
        "date_links": date_links, "slug_links": slug_links, "articles": len(tree.css("article")),
        "wp": "wp-content" in html[:400000], "aff_links": aff_links[:60], "gates": gates[:30],
        "apk": apk[:10], "referrer_js": ref_js,
        "mirror_title": bool(lb.MIRROR_TITLE.search(title)), "mostbet_assets": bool(lb.MOSTBET_STRONG.search(html)),
        "parked": bool(lb.PARKED.search(f"{title} {text[:3000]}") or lb.PARKED_HTML.search(html[:200000])),
        "text_sample": text[:400],
    }


def lb_same(a: str, b: str) -> bool:
    a, b = a.removeprefix("www."), b.removeprefix("www.")
    return bool(a) and (a == b or a.endswith("." + b) or b.endswith("." + a))


_aff = None


def lb_ref(url: str, site: str):
    global _aff
    if _aff is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("affiliate_scan", HERE / "affiliate-scan.py")
        _aff = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_aff)
    return _aff.classify_ref(url, site)


def one(args):
    domain, files = args
    rec = {"domain": domain, "sources": sorted(files), "platform": bool(PLATFORMS.search(domain))}
    for src in ("browser", "http"):
        if src not in files:
            continue
        html, final = read(files[src])
        if not html:
            continue
        try:
            f = page_features(html, final, domain)
        except Exception as e:  # noqa: BLE001 — one broken page must not stop the batch
            f = {"error": f"{type(e).__name__}: {e}"[:200]}
        f["final_url"] = final
        rec[src] = f
        if f.get("host") and PLATFORMS.search(f["host"]):
            rec["platform"] = True
    return rec


def main(d: str):
    d = Path(d)
    files = {}
    for p in (d / "html").iterdir():
        m = re.match(r"(.+)\.(http|browser)\.html\.gz$", p.name)
        if m:
            files.setdefault(m.group(1), {})[m.group(2)] = p
    out = d / "site-features.jsonl.gz"
    n = 0
    with mp.Pool(max(2, mp.cpu_count() - 2)) as pool, gzip.open(out, "wt", encoding="utf-8") as f:
        for rec in pool.imap_unordered(one, sorted(files.items()), chunksize=20):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            if n % 2000 == 0:
                print(n, "/", len(files), flush=True)
    print("done", n, out)


if __name__ == "__main__":
    main(sys.argv[1])
