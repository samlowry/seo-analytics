"""Скан главных страниц: аффилиат Mostbet / не аффилиат / не открылся.

Запуск:
  nice -n 10 uv run --with aiohttp --with selectolax python tools/affiliate-scan.py \
      <domains.csv> <out_dir> [--limit N] [--concurrency 40]

Только HTTP, без браузера и прокси. Пишет <out_dir>/scan.jsonl.gz — одна запись на сайт
со всеми ссылками, кандидатами и цепочками. Повторный запуск пропускает уже снятые домены.
Сводные CSV собирает tools/affiliate-report.py.

Рефка Mostbet — https://<чужой хост>/<4 символа [A-Za-z0-9], хотя бы одна заглавная>
(форма всех 567 рефок реестра skaner-bitykh-ssylok на 2026-09-23) или хост из этого реестра.
Сам адрес рефки НИКОГДА не запрашивается: цепочка останавливается на хопе, который на неё
указывает, — иначе накручивается статистика партнёрки.
"""
import argparse
import asyncio
import base64
import binascii
import csv
import gzip
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp
from selectolax.parser import HTMLParser

csv.field_size_limit(sys.maxsize)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
           "Accept-Language": "en-US,en;q=0.9"}
HOME_BODY_CAP = 3_000_000
HOP_BODY_CAP = 300_000
JS_BODY_CAP = 1_500_000
MAX_HOPS = 8
MAX_CANDIDATES = 25
MAX_JS_FILES = 6

REF_PATH = re.compile(r"^/[A-Za-z0-9]{4}/?$")
REF_PATH_LONG = re.compile(r"^/[A-Za-z0-9]{4}/")  # /ekfU/0/<uuid> — только на ref-похожем хосте
REF_HOST = re.compile(r"(mb|mst|most)\.[a-z]+$")
REGISTRY = Path.home() / "Developer/skaner-bitykh-ssylok/registry/entries.json"
KNOWN_REF_HOSTS = set()
if REGISTRY.exists():
    KNOWN_REF_HOSTS = {urlsplit(e["destination_url"]).hostname
                       for e in json.loads(REGISTRY.read_text())["entries"]}
MOSTBET_AFF_PARAMS = re.compile(r"(^|&)(pid|p|promo|promocode|btag|stag|ref|aff)=", re.I)

SKIP_HOSTS = re.compile(
    r"(^|\.)(facebook\.com|fb\.com|twitter\.com|x\.com|instagram\.com|youtube\.com|youtu\.be|"
    r"t\.me|telegram\.(me|org)|google\.[a-z.]+|googleapis\.com|gstatic\.com|googletagmanager\.com|"
    r"apple\.com|wikipedia\.org|linkedin\.com|pinterest\.com|tiktok\.com|vk\.com|ok\.ru|"
    r"whatsapp\.com|wa\.me|cloudflare\.com|wordpress\.org|w3\.org|schema\.org|gravatar\.com|"
    r"yandex\.[a-z]+|bing\.com|microsoft\.com|github\.com|reddit\.com|discord\.(gg|com)|"
    r"gamcare\.org\.uk|begambleaware\.org|gamblingtherapy\.org|jsdelivr\.net|cdnjs\.com)$", re.I)
STATIC_EXT = re.compile(r"\.(css|js|mjs|png|jpe?g|gif|svg|webp|avif|ico|pdf|xml|json|woff2?|ttf|"
                        r"eot|mp4|webm|mp3|zip|rar)(\?|$)", re.I)
REDIRECTY = re.compile(
    r"(^|/)(go|goto|out|link|links|visit|click|redirect|redir|r|ref|refer|aff|affiliate|partner|"
    r"promo|promocode|bonus|reg|register|registration|signup|sign-up|join|play|bet|download|apk|"
    r"app|apps|get|official|site|casino|mostbet|login|enter|vhod|kirish|giris|qeydiyyat|registro|"
    r"rejestracja|registrace)([/?#._-]|$)", re.I)
URL_PARAM = re.compile(r"[?&](url|u|to|goto|target|dest|link|redirect|out)=", re.I)
JS_NAV = re.compile(
    r"""(?:location(?:\.href)?\s*=|location\.(?:assign|replace)\s*\(|window\.open\s*\()\s*["'`]([^"'`]+)""")
ABS_URL = re.compile(r"""https?:\\?/\\?/[^\s"'`<>()\\]+""")
META_REFRESH = re.compile(r"""url\s*=\s*['"]?([^'">\s]+)""", re.I)
CTA = re.compile(
    r"reg|sign|join|bonus|promo|play|bet|download|apk|app\b|login|log in|enter|claim|start|get|"
    r"mostbet|giri|kay[iı]t|oyna|y[uü]kl|qeyd|registr|rejestr|jugar|jogar|joac|juca|ob[tț]ine|"
    r"kirish|vhod|вход|регистр|скача|игра|бонус|получ|ставк|hraj|stáh|pobierz|graj|letölt|játs", re.I)
DATA_ATTRS = ("data-href", "data-url", "data-link", "data-go", "data-redirect", "data-target-url")


def base_host(h: str) -> str:
    h = (h or "").lower().rstrip(".")
    return h[4:] if h.startswith("www.") else h


def same_site(a: str, b: str) -> bool:
    a, b = base_host(a), base_host(b)
    return a == b or a.endswith("." + b) or b.endswith("." + a)


NOT_REF_HOSTS = re.compile(r"(^|\.)(onelink\.me|snapchat\.com|bit\.ly|urlz\.fr|bpl\.kr|switchy\.io|"
                           r"myworkdayjobs\.com|t\.co|linktr\.ee|1xlink\.org|shrtly\.to)$", re.I)


def random_host(host: str) -> bool:
    """Хост похож на рефочный: случайная строка, а не слово."""
    label = host.split(".")[-2] if host.count(".") >= 1 else host
    if "most" in host or REF_HOST.search(host):
        return True
    if any(c.isdigit() for c in label):
        return True
    letters = [c for c in label if c.isalpha()]
    return bool(letters) and sum(c in "aeiouy" for c in letters) / len(letters) < 0.3


def classify_ref(url: str, site: str):
    """→ 'ref' | 'known_ref_host' | 'mostbet_host' | None"""
    try:
        s = urlsplit(url)
    except ValueError:
        return None
    if s.scheme not in ("http", "https") or not s.hostname:
        return None
    host = s.hostname.lower()
    if same_site(host, site):
        return None
    if host in KNOWN_REF_HOSTS:
        return "known_ref_host"
    if SKIP_HOSTS.search(host) or NOT_REF_HOSTS.search(host) or not random_host(host):
        return None
    first = s.path[1:5]
    word = re.fullmatch(r"[A-Z][a-z]{3}", first)  # /News, /Home — в реестре таких рефок нет
    if REF_PATH.match(s.path) and any(c.isupper() for c in first) and (not word or REF_HOST.search(host)):
        return "ref"
    if REF_PATH_LONG.match(s.path) and any(c.isupper() for c in first) and REF_HOST.search(host):
        return "ref"
    if "mostbet" in host and MOSTBET_AFF_PARAMS.search(s.query or ""):
        return "mostbet_host"
    return None


B64_HTTP = re.compile(r"aHR0c[A-Za-z0-9+/_=-]{8,}")  # base64 от "http"


def b64_urls(s: str):
    """URL, спрятанные в base64 внутри ссылки (путь, параметр)."""
    out = []
    for m in B64_HTTP.findall(s):
        t = m.replace("-", "+").replace("_", "/")
        try:
            d = base64.b64decode(t + "=" * (-len(t) % 4)).decode("utf-8", "strict")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if d.startswith(("http://", "https://")):
            out.append(d)
    return out


def clean(u: str) -> str:
    return u.replace("\\/", "/").strip()


def text_of(tree: HTMLParser) -> str:
    body = tree.body
    if body is None:
        return ""
    for n in body.css("script,style,noscript"):
        n.decompose()
    return re.sub(r"\s+", " ", body.text(separator=" ")).strip()


def extract(html: str, page_url: str):
    """Все ссылки страницы: [(url, source)]."""
    out = []
    tree = HTMLParser(html)
    for n in tree.css("a[href],area[href]"):
        out.append((n.attributes.get("href") or "", "a"))
    for n in tree.css("form[action]"):
        out.append((n.attributes.get("action") or "", "form"))
    for n in tree.css("[formaction]"):
        out.append((n.attributes.get("formaction") or "", "formaction"))
    for attr in DATA_ATTRS:
        for n in tree.css(f"[{attr}]"):
            out.append((n.attributes.get(attr) or "", attr))
    for n in tree.css("[onclick]"):
        oc = n.attributes.get("onclick") or ""
        out += [(m, "onclick") for m in JS_NAV.findall(oc)]
        out += [(m, "onclick") for m in ABS_URL.findall(oc)]
    for n in tree.css("meta[http-equiv]"):
        if (n.attributes.get("http-equiv") or "").lower() == "refresh":
            m = META_REFRESH.search(n.attributes.get("content") or "")
            if m:
                out.append((m.group(1), "meta_refresh"))
    scripts_src = []
    for n in tree.css("script"):
        src = n.attributes.get("src")
        if src:
            scripts_src.append(src)
            continue
        code = n.text() or ""
        out += [(m, "script_nav") for m in JS_NAV.findall(code)]
        out += [(m, "script_url") for m in ABS_URL.findall(code)]
    js_buttons, js_cta = 0, 0  # кликабельное без адреса: ссылку подставляет скрипт
    for n in tree.css('button,[role=button],[onclick],a[href="#"],a[href^="javascript:"],a:not([href])'):
        if n.tag == "button" and (n.attributes.get("type") or "").lower() == "submit":
            continue
        js_buttons += 1
        snippet = " ".join(f"{k}={v}" for k, v in n.attributes.items() if k != "class") + " " + \
            (n.text(deep=True) or "")[:80]
        if CTA.search(snippet):
            js_cta += 1
    title = (tree.css_first("title").text().strip() if tree.css_first("title") else "")[:200]
    txt = text_of(tree)
    links = []
    seen = set()
    for raw, src in out:
        raw = clean(raw)
        if not raw or "{" in raw or raw.startswith(("#", "mailto:", "tel:", "javascript:", "data:", "sms:", "viber:")):
            continue
        try:
            u = urljoin(page_url, raw)
        except ValueError:
            continue
        if (u, src) in seen:
            continue
        seen.add((u, src))
        links.append((u, src))
        for d in b64_urls(raw):
            if (d, src + ":b64") not in seen:
                seen.add((d, src + ":b64"))
                links.append((d, src + ":b64"))
    return links, scripts_src, (js_buttons, js_cta), title, txt


def protection(status: int, headers, body: str):
    server = (headers.get("server") or "").lower()
    low = body[:200_000].lower()
    if headers.get("cf-mitigated") or "challenge-platform" in low or "cf-chl" in low or \
            ("cloudflare" in server and status in (403, 503, 429) and "just a moment" in low):
        return "cloudflare_challenge"
    blocked = status >= 400 or len(body) < 8_000
    if not blocked:
        return None
    if "ddos-guard" in server or "ddos-guard" in low[:5000]:
        return "ddos_guard"
    if "sucuri" in server or "sucuri website firewall" in low:
        return "sucuri"
    if "g-recaptcha" in low or "h-captcha" in low or "hcaptcha.com" in low or "captcha" in low[:20000]:
        return "captcha"
    if "cloudflare" in server and status >= 400:
        return f"cloudflare_{status}"
    return None


async def read_capped(resp, cap):
    chunks, size = [], 0
    async for chunk in resp.content.iter_chunked(65536):
        chunks.append(chunk)
        size += len(chunk)
        if size >= cap:
            break
    raw = b"".join(chunks)[:cap]
    enc = resp.charset or "utf-8"
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


async def hop(session, url, cap, timeout):
    """Один запрос без следования редиректам."""
    async with session.get(url, allow_redirects=False, timeout=timeout, ssl=False) as r:
        loc = r.headers.get("location")
        body = ""
        ctype = r.headers.get("content-type", "")
        if not (300 <= r.status < 400 and loc) and "html" in ctype.lower():
            body = await read_capped(r, cap)
        return r.status, loc, dict(r.headers), body, ctype


def err_name(e: Exception) -> str:
    n = type(e).__name__
    if isinstance(e, asyncio.TimeoutError):
        return "timeout"
    if "SSL" in n or "Certificate" in n:
        return "tls_error"
    if isinstance(e, aiohttp.ClientConnectorError):
        return "connect_error"
    return n


async def fetch_home(session, domain):
    """Главная с ручным проходом редиректов. Возвращает dict."""
    tries = []
    for start in (f"https://{domain}/", f"http://{domain}/"):
        chain, url = [], start
        try:
            for _ in range(MAX_HOPS + 2):
                st, loc, hdr, body, ctype = await hop(session, url, HOME_BODY_CAP,
                                                      aiohttp.ClientTimeout(total=25, sock_connect=10))
                chain.append({"url": url, "status": st, "location": loc})
                if 300 <= st < 400 and loc:
                    nxt = urljoin(url, loc)
                    kind = classify_ref(nxt, domain)
                    if kind:
                        return {"ok": True, "chain": chain, "home_ref": nxt, "home_ref_kind": kind}
                    url = nxt
                    continue
                return {"ok": True, "chain": chain, "status": st, "headers": hdr, "body": body,
                        "ctype": ctype, "final_url": url}
            return {"ok": False, "chain": chain, "error": "too_many_redirects"}
        except Exception as e:  # noqa: BLE001 — любая сетевая ошибка = причина «не открылся»
            tries.append({"start": start, "chain": chain, "error": err_name(e), "detail": str(e)[:200]})
            if chain:  # https ответил, упало дальше по цепочке — http не поможет
                break
    return {"ok": False, "tries": tries, "error": tries[-1]["error"] if tries else "unknown"}


async def follow(session, url, site):
    """Цепочка от кандидата до рефки. Рефку не запрашиваем."""
    chain = []
    kind = classify_ref(url, site)
    if kind:
        return {"found": url, "kind": kind, "chain": chain}
    for _ in range(MAX_HOPS):
        host = urlsplit(url).hostname or ""
        if SKIP_HOSTS.search(host):
            return {"found": None, "chain": chain, "stop": "platform_host"}
        try:
            st, loc, hdr, body, _ = await hop(session, url, HOP_BODY_CAP,
                                              aiohttp.ClientTimeout(total=15, sock_connect=8))
        except Exception as e:  # noqa: BLE001
            chain.append({"url": url, "error": err_name(e)})
            return {"found": None, "chain": chain, "stop": "error"}
        chain.append({"url": url, "status": st, "location": loc})
        nxt = None
        if 300 <= st < 400 and loc:
            nxt = urljoin(url, loc)
        elif body:
            page_links, *_ = extract(body, url)
            for u, src in page_links:
                k = classify_ref(u, site)
                if k:
                    return {"found": u, "kind": k, "chain": chain, "via": f"page_link:{src}"}
            m = META_REFRESH.search(body) if "http-equiv" in body.lower() else None
            navs = JS_NAV.findall(body[:HOP_BODY_CAP])
            cand = [clean(x) for x in navs] + ([m.group(1)] if m else [])
            for c in cand:
                u = urljoin(url, c)
                if classify_ref(u, site):
                    return {"found": u, "kind": classify_ref(u, site), "chain": chain, "via": "page_js"}
            if len(body) < 20_000 and cand:
                nxt = urljoin(url, cand[0])
        if not nxt:
            return {"found": None, "chain": chain, "stop": "no_redirect"}
        kind = classify_ref(nxt, site)
        if kind:
            return {"found": nxt, "kind": kind, "chain": chain}
        url = nxt
    return {"found": None, "chain": chain, "stop": "max_hops"}


def pick_candidates(links, site):
    """Ссылки для проверки цепочкой, с причиной выбора, в порядке приоритета."""
    pri = {}
    for u, src in links:
        s = urlsplit(u)
        if s.scheme not in ("http", "https") or STATIC_EXT.search(s.path or ""):
            continue
        host = s.hostname or ""
        internal = same_site(host, site)
        if not internal and SKIP_HOSTS.search(host):
            continue
        path_q = (s.path or "/") + ("?" + s.query if s.query else "")
        if src not in ("a", "area"):
            reason, p = f"js:{src}", 0
        elif internal and (REDIRECTY.search(s.path or "") or URL_PARAM.search("?" + (s.query or ""))):
            reason, p = "internal_redirect_like", 1
        elif not internal:
            reason, p = "external", 2
        else:
            continue
        if internal and path_q in ("/", ""):
            continue
        key = u.split("#")[0]
        if key not in pri or pri[key][0] > p:
            pri[key] = (p, reason)
    ordered = sorted(pri.items(), key=lambda kv: kv[1][0])
    return [{"url": k, "reason": v[1]} for k, v in ordered]


async def scan_site(session, domain):
    rec = {"domain": domain, "ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    home = await fetch_home(session, domain)
    rec["home_chain"] = home.get("chain") or home.get("tries")
    if home.get("home_ref"):
        rec["result"] = {"group": "affiliate", "method": "home_redirect",
                         "ref_url": home["home_ref"], "ref_kind": home["home_ref_kind"]}
        return rec
    if not home["ok"]:
        rec["result"] = {"group": "failed", "reason": home["error"]}
        return rec
    st, body, hdr = home["status"], home["body"], home["headers"]
    rec.update(status=st, final_url=home["final_url"], content_type=home["ctype"],
               body_bytes=len(body), server=hdr.get("Server") or hdr.get("server"))
    prot = protection(st, {k.lower(): v for k, v in hdr.items()}, body)
    if prot:
        rec["result"] = {"group": "failed", "reason": prot, "http_status": st}
        return rec
    if st >= 400:
        rec["result"] = {"group": "failed", "reason": f"http_{st}"}
        return rec
    if "html" not in (home["ctype"] or "").lower():
        rec["result"] = {"group": "failed", "reason": "not_html"}
        return rec

    site = urlsplit(home["final_url"]).hostname or domain
    links, scripts, (js_buttons, js_cta), title, txt = extract(body, home["final_url"])
    mentions = len(re.findall(r"mostbet|мостбет", body, re.I))
    rec.update(title=title, text_len=len(txt), mostbet_mentions=mentions, js_buttons=js_buttons, js_cta=js_cta,
               final_host=site)
    rec["links_internal"] = [[u, s] for u, s in links if same_site(urlsplit(u).hostname or "", site)]
    rec["links_external"] = [[u, s] for u, s in links if not same_site(urlsplit(u).hostname or "", site)]
    rec["scripts"] = scripts

    direct = [(u, s, classify_ref(u, site)) for u, s in links]
    direct = [d for d in direct if d[2]]
    if direct:
        u, s, kind = direct[0]
        rec["direct_refs"] = [[u, s, k] for u, s, k in direct]
        rec["result"] = {"group": "affiliate", "method": f"direct:{s}", "ref_url": u, "ref_kind": kind}
        return rec

    cands = pick_candidates(links, site)[:MAX_CANDIDATES]
    rec["candidates"] = cands
    rec["checks"] = []
    for i, c in enumerate(cands):
        res = await follow(session, c["url"], site)
        rec["checks"].append({"url": c["url"], **res})
        if res.get("found"):
            rec["unchecked"] = [x["url"] for x in cands[i + 1:]]
            rec["result"] = {"group": "affiliate", "method": f"chain:{c['reason']}",
                             "ref_url": res["found"], "ref_kind": res["kind"],
                             "via": c["url"], "hops": len(res["chain"])}
            return rec

    # Ссылка может собираться внешним JS — смотрим свои скрипты, если сайт о Mostbet.
    if mentions >= 3 and js_buttons:
        found_js = []
        for src in scripts[:MAX_JS_FILES]:
            su = urljoin(home["final_url"], src)
            if not same_site(urlsplit(su).hostname or "", site):
                continue
            try:
                async with session.get(su, timeout=aiohttp.ClientTimeout(total=15), ssl=False) as r:
                    code = await read_capped(r, JS_BODY_CAP)
            except Exception:  # noqa: BLE001
                continue
            for m in ABS_URL.findall(code) + JS_NAV.findall(code):
                u = urljoin(home["final_url"], clean(m))
                if classify_ref(u, site):
                    found_js.append([u, su])
        rec["js_file_refs"] = found_js
        if found_js:
            rec["result"] = {"group": "affiliate", "method": "js_file", "ref_url": found_js[0][0],
                             "ref_kind": classify_ref(found_js[0][0], site), "via": found_js[0][1]}
            return rec
        rec["result"] = {"group": "failed", "reason": "needs_browser_js_buttons"}
        return rec

    flags = {}
    for c, chk in zip(cands, rec["checks"]):
        if c["reason"] != "internal_redirect_like" or not chk["chain"]:
            continue
        if (chk["chain"][0].get("status") or 0) >= 400:
            flags.setdefault("gate_dead", []).append(c["url"])
        offsite = [h["url"] for h in chk["chain"] if not same_site(urlsplit(h["url"]).hostname or "", site)]
        if offsite:
            flags.setdefault("gate_other", []).append(urlsplit(offsite[0]).hostname)

    if len(txt) < 200 and len(links) < 5:
        if scripts or "<script" in body.lower():
            rec["result"] = {"group": "failed", "reason": "js_shell"}
            return rec
        rec["result"] = {"group": "not_affiliate", "flag": "thin_page", **flags}
        return rec
    rec["result"] = {"group": "not_affiliate", **flags}
    return rec


def done_domains(path: Path):
    done = set()
    if not path.exists():
        return done
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    done.add(json.loads(line)["domain"])
                except (json.JSONDecodeError, KeyError):
                    pass
    except (EOFError, OSError):
        pass  # последний кусок оборван при остановке — дочитали, что было
    return done


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("domains_csv")
    ap.add_argument("out_dir")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=40)
    ap.add_argument("--redo", help="файл со списком доменов, которые снять заново (запись дописывается, "
                                   "в отчёт идёт последняя)")
    a = ap.parse_args()
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scan = out / "scan.jsonl.gz"
    with open(a.domains_csv, newline="", encoding="utf-8") as f:
        domains = [r["domain_ascii"] or r["domain_name"] for r in csv.DictReader(f)]
    if a.limit:
        domains = domains[:a.limit]
    done = done_domains(scan)
    if a.redo:
        redo = {l.strip() for l in open(a.redo, encoding="utf-8") if l.strip()}
        done -= redo
        domains = [d for d in domains if d in redo]
    todo = [d for d in domains if d not in done]
    print(f"всего {len(domains)}, уже снято {len(done)}, осталось {len(todo)}", flush=True)

    conn = aiohttp.TCPConnector(limit=a.concurrency * 2, limit_per_host=4, ttl_dns_cache=600,
                                enable_cleanup_closed=True)
    sem = asyncio.Semaphore(a.concurrency)
    lock = asyncio.Lock()
    stats, t0, n = {}, time.time(), 0
    fh = gzip.open(scan, "at", encoding="utf-8")

    async def one(d):
        nonlocal n
        async with sem:
            try:
                rec = await asyncio.wait_for(scan_site(session, d), timeout=240)
            except Exception as e:  # noqa: BLE001
                rec = {"domain": d, "result": {"group": "failed", "reason": "scan_error:" + err_name(e)}}
        async with lock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
            g = rec["result"]["group"]
            stats[g] = stats.get(g, 0) + 1
            if n % 200 == 0:
                fh.flush()
                rate = n / (time.time() - t0)
                print(f"{n}/{len(todo)} {rate:.1f}/с {stats}", flush=True)

    async with aiohttp.ClientSession(connector=conn, headers=HEADERS, cookie_jar=aiohttp.DummyCookieJar()) as session:
        await asyncio.gather(*(one(d) for d in todo))
    fh.close()
    print("готово", stats, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
