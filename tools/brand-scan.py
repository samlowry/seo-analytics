"""Brand scan: who does each site advertise — Mostbet, someone else, both or nobody.

Run, HTTP pass first (fast, no browser):
  nice -n 10 uv run --with aiohttp --with selectolax \\
      python tools/brand-scan.py <queue.csv> <out_dir> --mode http [--concurrency 40]
then the browser pass over what HTTP could not settle:
  nice -n 10 uv run --with 'camoufox[geoip]' --with aiohttp --with selectolax \\
      python tools/brand-scan.py <queue.csv> <out_dir> --mode browser --from-http [--concurrency 5]

Input: a CSV with a `domain` column (camoufox-queue.csv or resolves-minus-ours-unique.csv).
Output: <out_dir>/http-scan.jsonl.gz and <out_dir>/browser-scan.jsonl.gz, one record per site;
reruns skip scanned domains, --redo FILE rescans the listed ones (the report takes the last record).
Filters: --priority 1,2 (queue priority), --domains FILE, --limit N.
--mode gates follows the button addresses given in the queue column `urls` (from saved home pages) by
HTTP, logs to gates-scan.jsonl.gz; tools/brand-classify.py reads them as extra destinations.
--mode deep follows links found on inner pages (column `pages`) and in the site's own scripts (`scripts`),
logs to deep-scan.jsonl.gz; read the same way.
Keeping home pages: --save-html [DIR] (default <out_dir>/html, <domain>.<http|browser>.html.gz; the browser also
keeps the scripts and JSON the page loaded, libraries aside, in <domain>.browser-res.json.gz);
--mode home only fetches and keeps home pages, follows nothing, logs to home-dump.jsonl.gz.
Exit via Mac SOCKS for the browser and HTTP follows (server scan, host default route untouched):
  --proxy socks5://127.0.0.1:1080  (add --with aiohttp-socks to uv run)
  see brand-protection/.../brand-scan/SERVER-RESCAN.md

Per site:
1. Open the home page. HTTP mode: plain request with redirects followed by hand. Browser mode:
   a fresh context per site, bot checks are left to clear on their own — never clicked.
2. Collect links, including URLs in any data-* attribute (templates keep the ref in data-sf-a and
   the like). Browser mode also clicks up to MAX_CLICKS call-to-action buttons without an address;
   the navigation they trigger is captured and aborted, so the home page stays put.
3. Follow every candidate destination to its final page and identify the brand by content
   (tools/landing_brand.py) — plain HTTP first, the browser only when HTTP cannot decide. Foreign
   refs and other operators are followed to the end: this scan runs once, so their stats do not
   matter. Our own refs from the skaner-bitykh-ssylok registry are never requested — the daily
   checker's stats depend on them.
4. Group: 1_mostbet_only, 2_no_ads, 3_other_only, 4_mixed; sites that do not open go to 5_dead
   (network, DNS, parked) or 5_not_shown (alive, but protection, HTTP error or geo block), always
   with a reason. A Cloudflare challenge or Turnstile still standing after the wait goes to
   6_cf_check — to be re-run with clicking. HTTP mode marks what needs a browser as needs_browser
   with a reason.
"""
import argparse
import asyncio
import base64
import binascii
import csv
import gzip
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import aiohttp

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import landing_brand as lb  # noqa: E402

_spec = importlib.util.spec_from_file_location("affiliate_scan", HERE / "affiliate-scan.py")
aff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aff)

csv.field_size_limit(sys.maxsize)

NAV_TIMEOUT = 30_000
FOLLOW_TIMEOUT = 25_000
CHALLENGE_WAIT_MS = 25_000
MAX_CLICKS = 4
MAX_FOLLOW = 12
MAX_BRANDED_PLAIN = 3
MAX_INNER_LINKS = 4
SITE_TIMEOUT = 300
LAUNCH_TIMEOUT = 90
CLOSE_TIMEOUT = 30
READ_TIMEOUT = 15  # one page read (title, content, evaluate)
FOLLOW_BUDGET = 90  # one destination, HTTP hops plus browser
FOLLOW_DEADLINE = SITE_TIMEOUT - 110  # after this many seconds on a site, the rest is not followed
BATCH = 150  # browser restarts between batches to cap memory growth

# Override on the server: BRAND_SCAN_REGISTRY=/path/to/entries.json
REGISTRY = Path(os.environ.get(
    "BRAND_SCAN_REGISTRY",
    str(Path.home() / "Developer/skaner-bitykh-ssylok/registry/entries.json"),
))


def ref_key(url: str) -> str:
    s = urlsplit(url)
    return (s.hostname or "").lower() + (s.path.rstrip("/") or "/")


OUR_REFS = set()
if REGISTRY.exists():
    OUR_REFS = {ref_key(e["destination_url"]) for e in json.loads(REGISTRY.read_text())["entries"]}


def parse_proxy(url: str | None) -> dict | None:
    """Playwright/Camoufox proxy dict from a URL like socks5://127.0.0.1:1080."""
    if not url:
        return None
    s = urlsplit(url)
    if not s.scheme or not s.hostname:
        raise SystemExit(f"bad --proxy {url!r}: need scheme://host:port")
    server = f"{s.scheme}://{s.hostname}" + (f":{s.port}" if s.port else "")
    out = {"server": server}
    if s.username:
        out["username"] = s.username
    if s.password:
        out["password"] = s.password
    return out

CHALLENGE_TITLE = re.compile(
    r"just a moment|один момент|attention required|checking (your|the) browser|ddos-guard|"
    r"verify(ing)? you are (a )?human|security check|проверка браузера|please wait|bot verification", re.I)
CHALLENGE_MARK = re.compile(r"challenges\.cloudflare\.com|cf-chl|challenge-platform|ddos-guard|sucuri|"
                            r"hcaptcha|g-recaptcha|turnstile|captcha", re.I)
EXTERNAL_KEEP = re.compile(r"casino|kazino|bet|bonus|promo|slot|play|win|spin|lucky|vegas|jackpot", re.I)
NOISE_HOSTS = re.compile(
    r"(^|\.)(s\.w\.org|wp\.com|wordpress\.com|gravatar\.com|cloudflareinsights\.com|jquery\.com|"
    r"bootstrapcdn\.com|unpkg\.com|googlesyndication\.com|doubleclick\.net|google-analytics\.com|"
    r"hotjar\.com|clarity\.ms|facebook\.net|yandex\.(ru|net)|yastatic\.net|cdnjs\.cloudflare\.com|"
    r"fontawesome\.com|recaptcha\.net|gstatic\.com|sentry\.io|onesignal\.com|jsdelivr\.net|"
    r"livechatinc\.com|jivosite\.com|tawk\.to|trustpilot\.com|schema\.org|w3\.org|ogp\.me)$", re.I)

CTA_JS = """(rx) => {
  const re = new RegExp(rx, 'i');
  const sel = 'button,[role=button],[onclick],a[href="#"],a[href^="javascript:"],a:not([href]),[data-href],[data-url],[data-link]';
  const out = [], seen = new Set();
  let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (el.tagName === 'BUTTON' && (el.type || '').toLowerCase() === 'submit' && el.form) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 5 || r.height < 5) continue;
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
    const attrs = [...el.attributes].filter(a => a.name !== 'class' && a.name !== 'style')
      .map(a => a.name + '=' + a.value).join(' ').slice(0, 200);
    if (!re.test(t + ' ' + attrs)) continue;
    const key = t.toLowerCase() || attrs;
    if (seen.has(key)) continue;
    seen.add(key);
    el.setAttribute('data-bps-i', String(i));
    out.push({i, text: t});
    i++;
  }
  return out;
}"""


def err_reason(e: Exception) -> str:
    """Firefox/Playwright navigation error -> short reason."""
    m = str(e)
    for pat, name in (("NS_ERROR_UNKNOWN_HOST", "dns_fail"), ("NS_ERROR_CONNECTION_REFUSED", "connection_refused"),
                      ("NS_ERROR_NET_TIMEOUT", "timeout"), ("Timeout", "timeout"),
                      ("NS_ERROR_NET_RESET", "connection_reset"), ("NS_ERROR_NET_INTERRUPT", "connection_reset"),
                      ("NS_ERROR_NET_EMPTY_RESPONSE", "empty_response"), ("NS_ERROR_REDIRECT_LOOP", "redirect_loop"),
                      ("SSL_ERROR", "tls_error"), ("SEC_ERROR", "tls_error"), ("NS_ERROR_OFFLINE", "offline"),
                      ("Download is starting", "download"), ("NS_BINDING_ABORTED", "aborted"),
                      ("NS_ERROR_ABORT", "aborted"), ("Target page, context or browser has been closed", "closed")):
        if pat in m:
            return name
    return "nav_error"


DEAD_REASONS = {"dns_fail", "connection_refused", "connection_reset", "empty_response", "timeout", "tls_error",
                "redirect_loop", "parked", "empty_page", "nav_error"}
FIREFOX_ERROR_TITLE = re.compile(r"(problem loading page|server not found|unable to connect|"
                                 r"secure connection failed|the connection has timed out)$", re.I)


async def settle(page, load_ms=10_000, extra_ms=6_000, quiet_ms=1_500):
    """Wait for load, then until the URL stops changing (JS redirects)."""
    try:
        await page.wait_for_load_state("load", timeout=load_ms)
    except Exception:  # noqa: BLE001 — slow subresources must not fail the page
        pass
    last, stable, spent = page.url, 0, 0
    while spent < extra_ms:
        await page.wait_for_timeout(500)
        spent += 500
        if page.url == last:
            stable += 500
            if stable >= quiet_ms:
                break
        else:
            last, stable = page.url, 0


TEXT_JS = "() => (document.body ? (document.body.innerText || document.body.textContent || '') : '').slice(0, 300000)"


async def wait_content(page, max_ms=6_000):
    """Wait until scripts stop adding text: length above a floor and unchanged over two polls."""
    last, same, spent = -1, 0, 0
    while spent < max_ms:
        try:
            n = await asyncio.wait_for(
                page.evaluate("() => document.body ? (document.body.innerText || '').length : 0"), READ_TIMEOUT)
        except Exception:  # noqa: BLE001
            n = 0
        if n == last and n > 200:
            same += 1
            if same >= 2:
                return
        else:
            same = 0
        last = n
        await page.wait_for_timeout(700)
        spent += 700


async def snapshot(page):
    """(title, html, visible text) of the current page; tolerant to mid-navigation errors and to a
    page whose scripts keep the main thread busy (reads are bounded)."""
    for _ in range(3):
        try:
            title = await asyncio.wait_for(page.title(), READ_TIMEOUT)
            html = await asyncio.wait_for(page.content(), READ_TIMEOUT)
            text = await asyncio.wait_for(page.evaluate(TEXT_JS), READ_TIMEOUT)
            return title or "", html or "", re.sub(r"\s+", " ", text or "").strip()
        except Exception:  # noqa: BLE001 — page navigated while reading
            await page.wait_for_timeout(1000)
    return "", "", ""


# Cloudflare injects its bot-detection script into ordinary proxied pages: not a challenge by itself.
CF_JSD = re.compile(r"/cdn-cgi/challenge-platform/scripts/jsd/[^\"'\s]*", re.I)
CF_INTERSTITIAL = re.compile(r"cf_chl_opt|cf-chl|cf_chl|/cdn-cgi/challenge-platform/", re.I)
CF_TURNSTILE = re.compile(r"cf-turnstile|challenges\.cloudflare\.com/turnstile", re.I)
CF_BLOCK = re.compile(r"sorry, you have been blocked|you are unable to access|cf-error-details", re.I)
CF_KINDS = ("cloudflare_challenge", "cloudflare_turnstile")  # left unsolved -> 6_cf_check, re-run with clicks
FORM_CAPTCHA_KINDS = ("captcha", "recaptcha", "hcaptcha", "cloudflare_turnstile")


def challenge_kind(title: str, html: str, text: str):
    """Kind of bot check on the page, or None.

    cloudflare_challenge — the "Just a moment" interstitial; cloudflare_turnstile — a Turnstile widget
    on the site's own page; cloudflare_block — the WAF "you have been blocked" page (no challenge);
    ddos_guard, sucuri, hcaptcha, recaptcha, captcha (other), bot_check (title only).
    """
    low = CF_JSD.sub("", html[:300_000].lower())
    if not (CHALLENGE_TITLE.search(title) or (len(text) < 1000 and CHALLENGE_MARK.search(low))):
        return None
    if CF_BLOCK.search(low) and not CF_TURNSTILE.search(low):
        return "cloudflare_block"
    if CF_INTERSTITIAL.search(low):
        return "cloudflare_challenge"
    if CF_TURNSTILE.search(low):
        return "cloudflare_turnstile"
    if "challenges.cloudflare.com" in low or ("cloudflare" in low and CHALLENGE_TITLE.search(title)):
        return "cloudflare_challenge"
    if "ddos-guard" in low:
        return "ddos_guard"
    if "sucuri" in low:
        return "sucuri"
    if "hcaptcha" in low:
        return "hcaptcha"
    if "recaptcha" in low:
        return "recaptcha"
    if "captcha" in low or "turnstile" in low:
        return "captcha"
    return "bot_check"


async def pass_challenge(page):
    """Wait for a bot check to clear by itself. Returns (kind or None, snapshot)."""
    title, html, text = await snapshot(page)
    kind = challenge_kind(title, html, text)
    waited = 0
    while kind and waited < CHALLENGE_WAIT_MS:
        await page.wait_for_timeout(2500)
        waited += 2500
        title, html, text = await snapshot(page)
        kind = challenge_kind(title, html, text)
    if waited and not kind:
        await settle(page, load_ms=5000)
        title, html, text = await snapshot(page)
    return kind, (title, html, text), waited


DATA_URL_SKIP = re.compile(r"src|img|image|bg|background|poster|thumb|icon|lazy|video|audio|font|embed|game|"
                           r"demo|share|canonical|permalink|ajax|api|endpoint|action", re.I)
# Tracker links are one random token: /FxSqQyw, /qWXgvD, /2NsSMU4 (Keitaro-style, Mostbet 4-char refs aside).
TRACKER_PATH = re.compile(r"^/[A-Za-z0-9]{5,12}/?$")


def tracker_shaped(url: str) -> bool:
    s = urlsplit(url)
    tok = (s.path or "").strip("/")
    return bool(TRACKER_PATH.match(s.path or "")) and any(c.isupper() for c in tok) and \
        any(c.islower() for c in tok) and not re.fullmatch(r"[A-Z][a-z]+", tok)


B64_TOKEN = re.compile(r"^[A-Za-z0-9+/_-]{4,}={0,2}$")


def b64_path(v: str) -> str:
    """Decode a data-* value that is a base64-encoded path or URL (L2dvLw== -> /go/); '' otherwise."""
    if not B64_TOKEN.match(v) or len(v) % 4 == 1:
        return ""
    t = v.replace("-", "+").replace("_", "/")
    try:
        d = base64.b64decode(t + "=" * (-len(t) % 4)).decode("utf-8", "strict")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return ""
    return d if d.startswith(("/", "http://", "https://")) and " " not in d else ""


def links_of(html: str, page_url: str):
    """aff.extract() plus URLs held in any data-* attribute, plain or base64. Returns (links, js_buttons,
    js_cta, text)."""
    links, _scripts, (js_buttons, js_cta), _title, text = aff.extract(html, page_url)
    seen = {u for u, _ in links}
    try:
        tree = aff.HTMLParser(html)
        nodes = tree.css("*")
    except Exception:  # noqa: BLE001
        nodes = []
    encoded = set()
    for n in nodes:
        for k, v in (n.attributes or {}).items():
            if not v or not k.startswith("data-") or DATA_URL_SKIP.search(k):
                continue
            v = aff.clean(v)
            dec = b64_path(v)
            if dec:
                encoded.add(v)
                v, k = dec, k + ":b64"
            elif k in aff.DATA_ATTRS:
                continue  # plain values of these are already collected by aff.extract()
            if not (v.startswith(("http://", "https://", "//")) or (v.startswith("/") and len(v) > 1)):
                continue
            try:
                u = urljoin(page_url, v)
            except ValueError:
                continue
            if u not in seen:
                seen.add(u)
                links.append((u, k))
    if encoded:  # aff.extract() joined the raw base64 token as a path — a 404, not a link
        links = [(u, s) for u, s in links
                 if not (s in aff.DATA_ATTRS and urlsplit(u).path.lstrip("/") in encoded)]
    return links, js_buttons, js_cta, text


AD_SHAPED = re.compile(r"^(js:|internal_redirect_like|internal_page_link|js_click|data-)")


def pick(links, site):
    """Candidate destinations from rendered links, ordered, with the reason for each."""
    out, skipped = [], 0
    for c in aff.pick_candidates(links, site):
        u, reason = c["url"], c["reason"]
        s = urlsplit(u)
        host = s.hostname or ""
        internal = aff.same_site(host, site)
        if NOISE_HOSTS.search(host):
            continue
        refish = bool(aff.classify_ref(u, site)) or (not internal and tracker_shaped(u))
        branded = not internal and bool(lb.brand_of_host(host))
        redirecty = bool(aff.REDIRECTY.search(s.path or "") or aff.URL_PARAM.search("?" + (s.query or "")))
        if reason.startswith("js:script"):
            # Inline scripts are full of CDN, analytics and emoji URLs: keep only ad-shaped ones.
            if internal and not redirecty:
                continue
            if not internal and not (refish or branded or lb.AFF_PARAMS.search(s.query or "")):
                skipped += 1
                continue
        elif reason == "external" and not internal:
            if not (refish or branded or redirecty or aff.random_host(host) or EXTERNAL_KEEP.search(host)):
                skipped += 1
                continue
        adparams = bool(lb.AFF_PARAMS.search(s.query or ""))
        rank = 0 if refish else 1 if (adparams and not internal) or reason.startswith("js:") else \
            2 if reason == "internal_redirect_like" else 3 if branded else 4
        out.append({"url": u, "reason": reason, "refish": refish, "rank": rank})
    out.sort(key=lambda x: x["rank"])
    # Plain links to other Mostbet-named sites are mostly link networks cross-linking each other:
    # a few are enough to tell, the rest only eat the follow budget.
    kept, branded_plain = [], 0
    for c in out:
        if c["rank"] == 3:
            branded_plain += 1
            if branded_plain > MAX_BRANDED_PLAIN:
                skipped += 1
                continue
        kept.append(c)
    return kept, skipped


def cache_key(url: str, site: str) -> str:
    host = urlsplit(url).hostname or ""
    if aff.same_site(host, site):
        return ""
    return ref_key(url) if aff.classify_ref(url, site) or tracker_shaped(url) else url.split("#")[0]


def read_last(path: Path, key="domain") -> dict:
    """Last record per key from a jsonl.gz log (a rescan overrides earlier records)."""
    out = {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out[r[key]] = r
    except (EOFError, OSError):
        pass
    return out


def dest_key(url: str, site: str) -> str:
    return cache_key(url, site) or url.split("#")[0]


def load_dest_cache(path: Path) -> dict:
    """Destinations resolved by the browser destination pass: key -> result."""
    return {k: {kk: vv for kk, vv in r["result"].items() if kk != "group"} for k, r in read_last(path).items()
            if r["result"].get("kind")}  # scan errors stay out, so a rerun retries them


def pending_destinations(http_recs: dict) -> list:
    """Unique destinations the HTTP pass could not decide, with the site each was found on."""
    out = {}
    for r in http_recs.values():
        site = (r.get("home") or {}).get("final_url") or f"https://{r['domain']}/"
        site = urlsplit(site).hostname or r["domain"]
        for d in r.get("destinations") or []:
            if d.get("kind") == "needs_browser":
                k = dest_key(d["url"], site)
                out.setdefault(k, {"domain": k, "url": d["url"], "site": site})
    return list(out.values())


def resolve_record(r: dict, dcache: dict) -> dict:
    """Fill needs_browser destinations of an HTTP record from the destination cache and regroup."""
    res = r["result"]
    if res.get("group") != "needs_browser" or res.get("reason") != "destination_needs_browser":
        return r
    site = urlsplit((r.get("home") or {}).get("final_url") or "").hostname or r["domain"]
    dests, pending = [], False
    for d in r.get("destinations") or []:
        if d.get("kind") == "needs_browser":
            got = dcache.get(dest_key(d["url"], site))
            if got:
                d = {"url": d["url"], "via": d.get("via"), **got, "from_dest_pass": True}
            elif AD_SHAPED.search(d.get("via", "")) or aff.classify_ref(d["url"], site) or tracker_shaped(d["url"]):
                pending = True
        dests.append(d)
    h = r.get("home") or {}
    live = [d for d in dests if d.get("kind") != "internal"]
    new = lb.site_group(live, h.get("mostbet_mentions") or 0)
    new["unresolved"] = sum(d.get("kind") in ("dead", "unknown", "needs_browser") for d in live)
    new["not_followed"] = res.get("not_followed", 0)
    if res.get("thin_page"):
        new["thin_page"] = True
    if pending:
        new = {**new, "group": "needs_browser", "reason": "destination_needs_browser", "http_group": new["group"]}
    return {**r, "destinations": dests, "result": new}


def save_html(html_dir: Path | None, domain: str, source: str, html: str, final_url: str, status) -> str:
    """Keep a home page for later re-classification: as fetched (source=http) or as rendered
    (source=browser). The first line records the source, time, status and final URL.
    Returns the file name inside html_dir, or "" when nothing was saved."""
    if not html_dir or not html:
        return ""
    name = f"{domain}.{source}.html.gz"
    head = (f"<!-- brand-scan {source} {time.strftime('%Y-%m-%dT%H:%M:%S')} "
            f"status={status} final_url={final_url} -->\n")
    with gzip.open(html_dir / name, "wt", encoding="utf-8") as f:
        f.write(head + html)
    return name


# Common libraries and trackers: their code says nothing about where a site sends its visitors.
LIB_URL = re.compile(r"jquery|googletagmanager|google-analytics|gtag/js|recaptcha|gstatic\.com|cloudflareinsights|"
                     r"fontawesome|bootstrap(\.min)?\.js|mc\.yandex|metrika|facebook\.net|hotjar|clarity\.ms|"
                     r"wp-includes/js|wp-emoji|polyfill|cdnjs\.cloudflare\.com/ajax/libs|unpkg\.com|jsdelivr\.net/npm/"
                     r"(swiper|slick|lazysizes)|doubleclick|googlesyndication|youtube\.com|ytimg", re.I)
RES_CAP, RES_TOTAL = 1_500_000, 8_000_000


async def save_resources(html_dir, domain: str, responses) -> str:
    """Keep the scripts and JSON (xhr/fetch) a rendered page loaded, next to its HTML:
    <domain>.browser-res.json.gz, a list of {url, type, status, body}. Libraries are skipped, bodies capped."""
    if not html_dir or not responses:
        return ""
    out, total = [], 0
    for r in responses[:80]:
        try:
            body = await asyncio.wait_for(r.body(), 10)
        except Exception:  # noqa: BLE001 — redirects, aborted or evicted bodies
            continue
        if not body or len(body) > RES_CAP or total + len(body) > RES_TOTAL:
            continue
        total += len(body)
        out.append({"url": r.url[:500], "type": r.request.resource_type, "status": r.status,
                    "body": body.decode("utf-8", "replace")})
    if not out:
        return ""
    name = f"{domain}.browser-res.json.gz"
    with gzip.open(Path(html_dir) / name, "wt", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    return name


def hosts_changed(start_url: str, hops) -> bool:
    start = aff.base_host(urlsplit(start_url).hostname or "")
    return any(aff.base_host(urlsplit(u).hostname or "") != start for _s, u in hops)


REST_RETRY = {"follow_timeout", "timeout", "aborted"}  # destinations the rest pass tries again
DOWNLOAD_CT = re.compile(r"android|octet-stream|x-msdownload|zip", re.I)


class Scanner:
    def __init__(self, network: str, session, proxy: dict | None = None, html_dir: Path | None = None):
        self.network = network
        self.session = session
        self.proxy = proxy  # Playwright dict; the aiohttp session must exit through the same proxy
        self.html_dir = html_dir  # --save-html: home pages are kept here
        self.html_src = "http"  # file suffix of HTTP-saved pages; "http-<as>" when scanning --as another visitor
        self.cache = {}  # external destination -> result, shared across sites

    async def follow(self, ctx, url, site, state):
        """Identify one destination: plain HTTP first, the browser only when HTTP cannot decide.

        With --proxy both HTTP and the browser exit via the SOCKS: from the host's own IP
        (e.g. Amsterdam) Mostbet landings answer 451.
        """
        key = cache_key(url, site)
        if key and key in self.cache:
            return {**self.cache[key], "cached": True}
        if ref_key(url) in OUR_REFS:
            state["our_refs"].append(url)
            return {"kind": "our_ref_skipped", "brand": "Mostbet", "evidence": "registry"}
        try:
            res = await bounded(self._follow_any(ctx, url, site, state), FOLLOW_BUDGET)
        except TimeoutError:
            return {"kind": "unknown", "brand": "", "evidence": "follow_timeout", "final_url": url}
        if key and res.get("kind") not in ("dead", "internal", "our_ref_skipped") and \
                not str(res.get("evidence", "")).startswith("protected"):
            self.cache[key] = {k: v for k, v in res.items() if not k.startswith("_")}
        return res

    async def _follow_any(self, ctx, url, site, state):
        res = await self.http_follow(url, site, state)
        return res if res is not None else await self.browser_follow(ctx, url, site)

    async def http_follow(self, url, site, state):
        """Hop-by-hop HTTP follow. Returns a result, or None when the page needs a browser."""
        chain, cur = [], url
        for _ in range(12):
            if ref_key(cur) in OUR_REFS:
                state["our_refs"].append(cur)
                return {"kind": "our_ref_skipped", "brand": "Mostbet", "evidence": "registry", "hops": chain}
            try:
                st, loc, hdr, body, ctype = await aff.hop(self.session, cur, 800_000,
                                                          aiohttp.ClientTimeout(total=15, sock_connect=8))
            except Exception as e:  # noqa: BLE001
                name = aff.err_name(e)
                if name == "timeout":
                    return None
                return {"kind": "dead", "brand": "", "evidence": name, "final_url": cur, "hops": chain}
            chain.append([st, cur[:200]])
            if 300 <= st < 400 and loc:
                cur = urljoin(cur, loc)
                continue
            if aff.protection(st, {k.lower(): v for k, v in hdr.items()}, body) or st in (401, 403, 429, 503):
                return None
            if st >= 400:
                return {"kind": "dead", "brand": "", "evidence": f"http_{st}", "final_url": cur, "hops": chain}
            if "html" not in (ctype or "").lower():
                if DOWNLOAD_CT.search(ctype or ""):
                    mb = bool(lb.MOSTBET_NAME.search(cur))
                    return {"kind": "mostbet" if mb else "download", "brand": "Mostbet" if mb else "",
                            "evidence": f"download:{ctype}", "final_url": cur, "hops": chain}
                return {"kind": "unknown", "brand": "", "evidence": f"not_html:{ctype[:40]}", "final_url": cur,
                        "hops": chain}
            if aff.same_site(urlsplit(cur).hostname or "", site):
                return {"kind": "internal", "brand": "", "evidence": "stayed_on_site", "final_url": cur,
                        "hops": chain, "_html": body}
            if len(body) < 30_000:
                navs = [aff.clean(x) for x in aff.JS_NAV.findall(body)]
                m = aff.META_REFRESH.search(body) if "http-equiv" in body.lower() else None
                nxt = (m.group(1) if m else None) or (navs[0] if navs else None)
                if nxt and not lb.MOSTBET_STRONG.search(body):
                    cur = urljoin(cur, nxt)
                    continue
            tree = aff.HTMLParser(body)
            title = (tree.css_first("title").text().strip() if tree.css_first("title") else "")[:200]
            text = aff.text_of(tree)
            res = lb.classify_destination(url, cur, title, body, text, hosts_changed(url, chain))
            decisive = res["evidence"] == "mostbet_assets" or res["evidence"].startswith("fields:")
            if not decisive and len(text) < 500:
                return None  # rendered by scripts or a "Redirecting…" stub
            return {**res, "final_url": cur, "title": title[:120], "hops": chain, "via_http": True}
        return {"kind": "dead", "brand": "", "evidence": "too_many_redirects", "final_url": cur, "hops": chain}

    async def browser_follow(self, ctx, url, site):
        page = await ctx.new_page()
        hops = []
        page.on("response", lambda r: hops.append([r.status, r.url[:200]])
                if r.request.is_navigation_request() and r.frame == page.main_frame else None)
        try:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=FOLLOW_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                reason = err_reason(e)
                if reason == "download":
                    name = urlsplit(url).path.rsplit("/", 1)[-1]
                    mb = bool(lb.MOSTBET_NAME.search(url))
                    return {"kind": "mostbet" if mb else "download", "brand": "Mostbet" if mb else "",
                            "evidence": f"download:{name}", "final_url": url}
                if page.url in ("about:blank", "") or reason in ("dns_fail", "connection_refused", "tls_error"):
                    return {"kind": "dead", "brand": "", "evidence": reason, "final_url": page.url, "hops": hops}
            await settle(page, load_ms=5000)
            await wait_content(page)
            kind, (title, html, text), _ = await pass_challenge(page)
            final = page.url
            if kind in FORM_CAPTCHA_KINDS:
                # Operator registration pages are short and carry a captcha in the sign-up form:
                # that is the operator itself, not a bot wall in front of it.
                res = lb.classify_destination(url, final, title, html, text, hosts_changed(url, hops))
                if res["kind"] in ("mostbet", "other_gambling"):
                    return {**res, "final_url": final, "title": title[:120], "hops": hops, "form_captcha": kind}
            if kind:
                return {"kind": "unknown", "brand": "", "evidence": f"protected:{kind}", "final_url": final,
                        "hops": hops}
            if aff.same_site(urlsplit(final).hostname or "", site):
                return {"kind": "internal", "brand": "", "evidence": "stayed_on_site", "final_url": final,
                        "hops": hops, "_html": html}
            res = lb.classify_destination(url, final, title, html, text, hosts_changed(url, hops))
            return {**res, "final_url": final, "title": title[:120], "hops": hops}
        finally:
            await page.close()

    async def new_guarded_context(self, browser, state):
        """Browser context that never lets our registry refs out and captures clicks when asked."""
        opts = {"ignore_https_errors": True}
        if self.proxy:
            opts["proxy"] = self.proxy
        ctx = await browser.new_context(**opts)
        ctx.set_default_timeout(15_000)

        async def route(r, req):
            u = req.url
            if ref_key(u) in OUR_REFS:
                state["our_refs"].append(u)
                return await r.abort()
            if req.resource_type in ("media", "font"):
                return await r.abort()
            if state["capture"] and req.is_navigation_request():
                try:
                    top = req.frame.parent_frame is None
                except Exception:  # noqa: BLE001
                    top = True
                if top and not u.startswith(("about:", "data:", "blob:")):
                    state["captured"].append(u)
                    return await r.abort()
            await r.continue_()

        await ctx.route("**/*", route)
        ctx.on("page", lambda p: p.on("dialog", lambda d: asyncio.ensure_future(d.dismiss())))
        return ctx

    async def resolve_destination(self, browser, item):
        """Destination pass: one destination the HTTP pass could not decide, in the browser."""
        state = {"capture": False, "captured": [], "our_refs": []}
        ctx = await self.new_guarded_context(browser, state)
        try:
            if ref_key(item["url"]) in OUR_REFS:
                res = {"kind": "our_ref_skipped", "brand": "Mostbet", "evidence": "registry"}
            else:
                res = await self.browser_follow(ctx, item["url"], item["site"])
        finally:
            try:
                await ctx.close()
            except Exception:  # noqa: BLE001
                pass
        res.pop("_html", None)
        return {"domain": item["domain"], "url": item["url"], "site": item["site"],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network, "mode": "destinations",
                "our_refs_skipped": state["our_refs"], "result": {"group": res.get("kind"), **res}}

    async def scan_site(self, browser, item):
        domain = item["domain"]
        rec = {"domain": domain, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network,
               "mode": "browser", "queue_reason": item.get("reason"), "queue_priority": item.get("priority")}
        state = {"capture": False, "captured": [], "our_refs": []}
        ctx = await self.new_guarded_context(browser, state)
        try:
            if item.get("referer"):
                rec["referer"] = item["referer"]
            rec.update(await self._scan(ctx, domain, state, referer=item.get("referer") or None))
        finally:
            rec["our_refs_skipped"] = state["our_refs"]
            try:
                await asyncio.wait_for(ctx.close(), CLOSE_TIMEOUT)
            except Exception:  # noqa: BLE001
                pass
        return rec

    async def _scan(self, ctx, domain, state, referer=None):
        started = time.time()
        page = await ctx.new_page()
        hops = []
        page.on("response", lambda r: hops.append([r.status, r.url[:200]])
                if r.request.is_navigation_request() and r.frame == page.main_frame else None)
        resources = []  # scripts and JSON the page loaded: kept with the HTML (--save-html)
        if self.html_dir:
            page.on("response", lambda r: resources.append(r)
                    if r.request.resource_type in ("script", "xhr", "fetch") and not LIB_URL.search(r.url) else None)
        resp, error = None, None
        for start in (f"https://{domain}/", f"http://{domain}/"):
            try:
                # referer: arrive as a visitor from a search engine (queue column `referer`), for cloaking sites
                resp = await page.goto(start, wait_until="domcontentloaded", timeout=NAV_TIMEOUT, referer=referer)
                error = None
                break
            except Exception as e:  # noqa: BLE001
                error = err_reason(e)
                if error == "download" or page.url not in ("about:blank", ""):
                    break
        home = {"hops": hops}
        if error and page.url in ("about:blank", ""):
            home["error"] = error
            grp = "5_dead" if error in DEAD_REASONS else "5_not_shown"
            return {"home": home, "result": {"group": grp, "reason": error}}

        await settle(page, load_ms=8000)
        await wait_content(page)
        kind, (title, html, text), waited = await pass_challenge(page)
        final = page.url
        status = hops[-1][0] if hops else (resp.status if resp else None)
        mentions = len(re.findall(r"mostbet|мостбет", html, re.I))
        home.update(final_url=final, status=status, title=title[:200], text_len=len(text),
                    mostbet_mentions=mentions, challenge_waited_ms=waited, text_sample=text[:300],
                    html_file=save_html(self.html_dir, domain, "browser", html, final, status),
                    resources_file=await save_resources(self.html_dir, domain, resources))
        if kind in ("captcha", "recaptcha", "hcaptcha") and not CHALLENGE_TITLE.search(title) and \
                len(links_of(html, final)[0]) >= 10:
            home["form_captcha"] = kind  # a captcha in a form on a real page, not a wall: scan on
            kind = None
        if kind:
            home["protection"] = kind
            if kind in CF_KINDS:
                return {"home": home, "result": {"group": "6_cf_check", "reason": kind}}
            return {"home": home, "result": {"group": "5_not_shown", "reason": f"protection:{kind}"}}
        if lb.PARKED.search(title + " " + text[:3000]) or lb.PARKED_HTML.search(html[:300_000]):
            return {"home": home, "result": {"group": "5_dead", "reason": "parked"}}
        if status and status >= 400:
            geo = bool(lb.GEO_BLOCK.search(title + " " + text[:3000])) or status == 451
            return {"home": home, "result": {"group": "5_not_shown",
                                             "reason": "geo_block" if geo else f"http_{status}"}}
        if FIREFOX_ERROR_TITLE.match(title) and len(text) < 30:
            # A JS or tracker redirect ended on a host that does not answer: Firefox shows its own
            # error page, which is not the site's content.
            moved = not aff.same_site(urlsplit(final).hostname or "", domain)
            return {"home": home, "result": {"group": "5_dead",
                                             "reason": "redirect_target_dead" if moved else "nav_error"}}
        if len(text) < 30 and len(html) < 3000:
            return {"home": home, "result": {"group": "5_dead", "reason": "empty_page"}}

        site = urlsplit(final).hostname or domain
        destinations = []
        if not aff.same_site(site, domain):
            landing = lb.classify_destination(f"https://{domain}/", final, title, html, text, True)
            operator = landing["evidence"] == "mostbet_assets" or \
                (landing["kind"] == "other_gambling" and landing["evidence"].startswith("fields:"))
            if operator:
                destinations.append({"url": f"https://{domain}/", "via": "home_redirect", "final_url": final,
                                     **landing})
                return {"home": home, "destinations": destinations,
                        "result": {**lb.site_group(destinations, mentions), "method": "home_redirect"}}
            home["moved_to"] = site  # the site lives on another domain now — scan it there

        links, js_buttons, js_cta, _txt = links_of(html, final)
        home.update(links=len(links), js_buttons=js_buttons, js_cta=js_cta,
                    home_other_brand_mentions=sorted({n for n, rx in lb.BRAND_RES if rx.search(text)})[:20])
        cands, skipped = pick(links, site)
        home["external_skipped"] = skipped

        clicked = []
        if js_cta:
            try:
                marks = await asyncio.wait_for(page.evaluate(CTA_JS, aff.CTA.pattern), READ_TIMEOUT)
            except Exception:  # noqa: BLE001
                marks = []
            state["capture"] = True
            for m in marks[:MAX_CLICKS]:
                before = len(state["captured"])
                loc = page.locator(f'[data-bps-i="{m["i"]}"]')
                try:
                    await loc.click(force=True, timeout=3000, no_wait_after=True)
                except Exception:  # noqa: BLE001 — overlay or detached: fire the handler directly
                    try:
                        await loc.dispatch_event("click", timeout=2000)
                    except Exception:  # noqa: BLE001
                        pass
                await page.wait_for_timeout(2500)
                got = state["captured"][before:]
                clicked.append({"text": m["text"], "captured": got})
            state["capture"] = False
            for p in ctx.pages:
                if p != page:
                    try:
                        await asyncio.wait_for(p.close(), READ_TIMEOUT)
                    except Exception:  # noqa: BLE001 — a stuck popup is dropped with the context
                        pass
        home["clicked"] = clicked
        click_urls = []
        for c in clicked:
            for u in c["captured"]:
                if u not in click_urls and u.rstrip("/") != final.rstrip("/"):
                    click_urls.append(u)
        queue = [{"url": u, "reason": "js_click", "refish": bool(aff.classify_ref(u, site)), "rank": -1}
                 for u in click_urls] + cands
        rec_cands, dests, not_followed = await self.follow_all(
            queue, site, lambda u: self.follow(ctx, u, site, state), deadline=started + FOLLOW_DEADLINE)
        destinations += dests
        result = self.conclude(destinations, mentions, text, links, not_followed)
        return {"home": home, "candidates": rec_cands, "destinations": destinations, "result": result}

    async def follow_all(self, queue, site, follow_fn, deadline=None):
        """Follow candidates in order, up to MAX_FOLLOW and until the deadline (epoch seconds), so a
        site keeps what it found instead of timing out as a whole; expand internal gate pages one
        level deep. The rest counts as not_followed."""
        seen, todo = set(), []
        for c in queue:
            k = cache_key(c["url"], site) or c["url"].split("#")[0]
            if k in seen:
                continue
            seen.add(k)
            todo.append(c)
        rec_cands = [{"url": c["url"][:300], "reason": c["reason"]} for c in todo]
        destinations, i = [], 0
        while i < len(todo) and i < MAX_FOLLOW and not (deadline and time.time() > deadline):
            c = todo[i]
            i += 1
            res = await follow_fn(c["url"])
            inner_html = res.pop("_html", None)
            destinations.append({"url": c["url"][:300], "via": c["reason"], **res})
            # An internal /go/ page that stays on the site may itself hold the outbound link.
            if res.get("kind") == "internal" and inner_html and c["reason"] != "internal_page_link":
                sub, *_ = links_of(inner_html, res.get("final_url") or c["url"])
                added = 0
                for u, src in sub:
                    if added >= MAX_INNER_LINKS:
                        break
                    h = urlsplit(u).hostname or ""
                    if aff.same_site(h, site) or aff.SKIP_HOSTS.search(h) or NOISE_HOSTS.search(h):
                        continue
                    if src.startswith("script") and not aff.classify_ref(u, site):
                        continue
                    if aff.classify_ref(u, site) or aff.random_host(h) or lb.brand_of_host(h) or \
                            src.startswith("data-"):
                        k = cache_key(u, site)
                        if k not in seen:
                            seen.add(k)
                            added += 1
                            todo.insert(i, {"url": u, "reason": "internal_page_link", "rank": 0})
        return rec_cands, destinations, max(0, len(todo) - i)

    @staticmethod
    def conclude(destinations, mentions, text, links, not_followed):
        dest = [d for d in destinations if d.get("kind") != "internal"]
        result = lb.site_group(dest, mentions)
        result["unresolved"] = sum(d.get("kind") in ("dead", "unknown", "needs_browser") for d in dest)
        result["not_followed"] = not_followed
        if len(text) < 200 and len(links) < 5:
            result["thin_page"] = True
        return result

    async def http_scan_site(self, item):
        """HTTP-only pass: settle the site or mark it needs_browser with the reason."""
        domain = item["domain"]
        rec = {"domain": domain, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network,
               "mode": "http", "queue_reason": item.get("reason"), "queue_priority": item.get("priority")}
        state = {"our_refs": []}
        follow = lambda u: self.follow_http_only(u, site, state)  # noqa: E731
        home_raw = await aff.fetch_home(self.session, domain, is_ours=lambda u: ref_key(u) in OUR_REFS)
        home = {"hops": [[h.get("status"), h.get("url")] for h in (home_raw.get("chain") or [])]}
        rec["home"] = home
        site = domain
        if home_raw.get("home_ref"):
            res = await follow(home_raw["home_ref"])
            d = [{"url": home_raw["home_ref"][:300], "via": "home_redirect", **res}]
            rec.update(destinations=d, result={**lb.site_group(d, 0), "method": "home_redirect"})
            if res.get("kind") == "needs_browser":
                rec["result"] = {"group": "needs_browser", "reason": "home_redirect_needs_browser"}
            rec["our_refs_skipped"] = state["our_refs"]
            return rec
        if not home_raw["ok"]:
            tries = home_raw.get("tries") or []
            detail = (tries[-1].get("detail") if tries else "") or ""
            err = home_raw.get("error") or "unknown"
            if err == "connect_error":
                err = "dns_fail" if re.search(r"nodename|servname|not known|getaddrinfo", detail, re.I) else \
                    "connection_refused" if re.search(r"refused|Connect call failed", detail, re.I) else err
            home["error"], home["detail"] = err, detail[:200]
            rec["result"] = {"group": "5_dead", "reason": err}  # network level: no HTTP answer at all
            return rec
        st, body, hdr, final = home_raw["status"], home_raw["body"], home_raw["headers"], home_raw["final_url"]
        tree = aff.HTMLParser(body or "")
        title = (tree.css_first("title").text().strip() if tree.css_first("title") else "")[:200]
        mentions = len(re.findall(r"mostbet|мостбет", body or "", re.I))
        links, js_buttons, js_cta, text = links_of(body or "", final)
        home.update(final_url=final, status=st, title=title, text_len=len(text), mostbet_mentions=mentions,
                    links=len(links), js_buttons=js_buttons, js_cta=js_cta, text_sample=text[:300],
                    home_other_brand_mentions=sorted({n for n, rx in lb.BRAND_RES if rx.search(text)})[:20],
                    html_file=save_html(self.html_dir, domain, self.html_src, body, final, st))
        prot = aff.protection(st, {k.lower(): v for k, v in hdr.items()}, body or "")
        if prot in ("cloudflare_challenge", "ddos_guard", "captcha", "sucuri"):
            home["protection"] = prot
            rec["result"] = {"group": "needs_browser", "reason": f"protection:{prot}"}
            return rec
        if lb.PARKED.search(title + " " + text[:3000]) or lb.PARKED_HTML.search((body or "")[:300_000]):
            rec["result"] = {"group": "5_dead", "reason": "parked"}
            return rec
        if st >= 400:
            geo = bool(lb.GEO_BLOCK.search(title + " " + text[:3000])) or st == 451
            rec["result"] = {"group": "5_not_shown", "reason": "geo_block" if geo else
                             (f"{prot}" if prot else f"http_{st}")}
            return rec
        if "html" not in (home_raw.get("ctype") or "").lower():
            rec["result"] = {"group": "5_not_shown", "reason": "not_html"}
            return rec
        if len(text) < 200 and len(links) < 5:
            has_js = "<script" in (body or "").lower()
            if has_js:
                rec["result"] = {"group": "needs_browser", "reason": "js_shell"}
                return rec
            if len(text) < 30:
                rec["result"] = {"group": "5_dead", "reason": "empty_page"}
                return rec

        site = urlsplit(final).hostname or domain
        destinations = []
        if not aff.same_site(site, domain):
            landing = lb.classify_destination(f"https://{domain}/", final, title, body, text, True)
            if landing["evidence"] == "mostbet_assets" or \
                    (landing["kind"] == "other_gambling" and landing["evidence"].startswith("fields:")):
                destinations.append({"url": f"https://{domain}/", "via": "home_redirect", "final_url": final,
                                     **landing})
                rec.update(destinations=destinations,
                           result={**lb.site_group(destinations, mentions), "method": "home_redirect"})
                return rec
            home["moved_to"] = site
        cands, skipped = pick(links, site)
        home["external_skipped"] = skipped
        rec_cands, dests, not_followed = await self.follow_all(cands, site, follow)
        destinations += dests
        result = self.conclude(destinations, mentions, text, links, not_followed)
        ads = result["group"] != "2_no_ads"
        pending = [d for d in destinations if d.get("kind") == "needs_browser" and
                   (AD_SHAPED.search(d.get("via", "")) or aff.classify_ref(d.get("url", ""), site)
                    or tracker_shaped(d.get("url", "")))]
        if pending:
            result = {**result, "group": "needs_browser", "reason": "destination_needs_browser",
                      "http_group": result["group"]}
        elif not ads and js_cta and mentions >= 3:
            result = {**result, "group": "needs_browser", "reason": "js_buttons", "http_group": result["group"]}
        rec.update(candidates=rec_cands, destinations=destinations, result=result,
                   our_refs_skipped=state["our_refs"])
        return rec

    async def follow_rest(self, rec):
        """Rest pass over a browser record: follow by plain HTTP the candidates it left unfollowed
        and the destinations that ran out of time, then regroup. Candidates include the URLs
        captured from clicked buttons, so the browser is not needed again; what HTTP cannot decide
        stays needs_browser (unresolved)."""
        h = rec.get("home") or {}
        site = urlsplit(h.get("final_url") or "").hostname or rec["domain"]
        state = {"our_refs": []}
        keep = [d for d in rec.get("destinations") or [] if d.get("evidence") not in REST_RETRY]
        seen = {d["url"] for d in keep}
        queue = [{"url": c["url"], "reason": c["reason"], "rank": 0}
                 for c in rec.get("candidates") or [] if c["url"] not in seen]
        _, new, not_followed = await self.follow_all(queue, site, lambda u: self.follow_http_only(u, site, state))
        for d in new:
            d.pop("_html", None)
        destinations = keep + new
        live = [d for d in destinations if d.get("kind") != "internal"]
        result = lb.site_group(live, h.get("mostbet_mentions") or 0)
        result["unresolved"] = sum(d.get("kind") in ("dead", "unknown", "needs_browser") for d in live)
        result["not_followed"] = not_followed
        return {**rec, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network, "mode": "browser+rest",
                "destinations": destinations, "result": result, "rest_followed": len(new),
                "our_refs_skipped": (rec.get("our_refs_skipped") or []) + state["our_refs"]}

    async def follow_deep(self, item):
        """Deep pass: pages beyond the home page. Input rows carry `pages` (inner pages of the site: posts that
        name Mostbet, registration / app / bonus pages) and `scripts` (the site's own JS files, where button
        addresses hide when the page has none). Links found there are followed by HTTP like home-page links;
        our refs are skipped as everywhere."""
        domain = item["domain"]
        site = item.get("site") or domain
        state = {"our_refs": []}
        links, pages, seen, kept = [], [], set(), []
        for u in (item.get("pages") or "").split()[:4]:
            try:
                url, body = u, ""
                for _ in range(4):  # same-site redirects only
                    st, loc, _, body, _ = await aff.hop(self.session, url, aff.HOME_BODY_CAP,
                                                         aiohttp.ClientTimeout(total=20, sock_connect=8))
                    if 300 <= st < 400 and loc and aff.same_site(urlsplit(urljoin(url, loc)).hostname or "", site):
                        url = urljoin(url, loc)
                        continue
                    break
            except Exception as e:  # noqa: BLE001
                pages.append({"url": u, "error": type(e).__name__})
                continue
            found, _, _, text = links_of(body or "", url)
            kept.append({"url": url, "type": "page", "status": st, "body": (body or "")[:aff.HOME_BODY_CAP]})
            pages.append({"url": u, "status": st, "links": len(found), "text_len": len(text),
                          "mostbet_mentions": len(re.findall(r"mostbet|мостбет", body or "", re.I))})
            links += [x for x in found if x[0] not in seen]
            seen |= {x[0] for x in found}
        for u in (item.get("scripts") or "").split()[:6]:
            try:
                async with self.session.get(u, timeout=aiohttp.ClientTimeout(total=20, sock_connect=8), ssl=False) as r:
                    code = (await r.content.read(aff.JS_BODY_CAP)).decode("utf-8", "replace")
                    kept.append({"url": u, "type": "script", "status": r.status, "body": code})
            except Exception as e:  # noqa: BLE001
                pages.append({"url": u, "error": type(e).__name__})
                continue
            found = [(aff.clean(m), "script_file") for m in aff.ABS_URL.findall(code)] + \
                [(urljoin(f"https://{site}/", aff.clean(m)), "script_file_nav") for m in aff.JS_NAV.findall(code)]
            for m in aff.B64_HTTP.findall(code):
                found += [(x, "script_file:b64") for x in aff.b64_urls(m)]
            pages.append({"url": u, "script_bytes": len(code), "urls": len(found)})
            links += [x for x in found if x[0] not in seen]
            seen |= {x[0] for x in found}
        res_file = ""
        if self.html_dir and kept:  # inner pages and scripts as fetched: <domain>.deep-res.json.gz
            res_file = f"{domain}.deep-res.json.gz"
            with gzip.open(self.html_dir / res_file, "wt", encoding="utf-8") as f:
                json.dump(kept, f, ensure_ascii=False)
        cands, skipped = pick(links, site)
        _, new, not_followed = await self.follow_all(cands, site, lambda u: self.follow_http_only(u, site, state))
        for d in new:
            d.pop("_html", None)
        return {"domain": domain, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network, "mode": "deep",
                "resources_file": res_file,
                "pages": pages, "destinations": new, "not_followed": not_followed, "external_skipped": skipped,
                "our_refs_skipped": state["our_refs"],
                "result": {"group": "deep", "reason": f"pages={len(pages)} followed={len(new)}"}}

    async def follow_gates(self, item):
        """Gates pass: follow by plain HTTP the button addresses read from a saved home page (own
        gates like /go/, external trackers) that no earlier pass took to the end. Input rows carry
        `urls` (space-separated). Our refs are skipped as everywhere."""
        domain = item["domain"]
        site = item.get("site") or domain
        state = {"our_refs": []}
        queue = [{"url": u, "reason": "gate", "rank": 0} for u in (item.get("urls") or "").split() if u]
        _, new, not_followed = await self.follow_all(queue, site, lambda u: self.follow_http_only(u, site, state))
        for d in new:
            d.pop("_html", None)
        return {"domain": domain, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network, "mode": "gates",
                "destinations": new, "not_followed": not_followed, "our_refs_skipped": state["our_refs"],
                "result": {"group": "gates", "reason": f"followed={len(new)}"}}

    async def home_dump(self, item):
        """Home-only pass: fetch the home page by plain HTTP and keep it; nothing is followed, so
        groups do not change. A home that redirects straight to a ref is recorded, not requested."""
        domain = item["domain"]
        rec = {"domain": domain, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": self.network, "mode": "home"}
        raw = await aff.fetch_home(self.session, domain, is_ours=lambda u: ref_key(u) in OUR_REFS)
        home = {"hops": [[h.get("status"), h.get("url")] for h in (raw.get("chain") or [])]}
        rec["home"] = home
        if raw.get("home_ref"):
            home["home_ref"] = raw["home_ref"][:300]
            rec["result"] = {"group": "home_redirect", "reason": raw.get("home_ref_kind") or ""}
            return rec
        if not raw["ok"]:
            home["error"] = raw.get("error") or "unknown"
            rec["result"] = {"group": "no_answer", "reason": home["error"]}
            return rec
        st, body, final = raw["status"], raw["body"] or "", raw["final_url"]
        tree = aff.HTMLParser(body)
        title = (tree.css_first("title").text().strip() if tree.css_first("title") else "")[:200]
        links, js_buttons, js_cta, text = links_of(body, final)
        home.update(final_url=final, status=st, title=title, bytes=len(body), text_len=len(text),
                    mostbet_mentions=len(re.findall(r"mostbet|мостбет", body, re.I)), links=len(links),
                    js_buttons=js_buttons, js_cta=js_cta,
                    html_file=save_html(self.html_dir, domain, self.html_src, body, final, st))
        rec["result"] = {"group": "saved" if home["html_file"] else "not_html", "reason": f"http_{st}"}
        return rec

    async def follow_http_only(self, url, site, state):
        key = cache_key(url, site)
        if key and key in self.cache:
            return {**self.cache[key], "cached": True}
        if ref_key(url) in OUR_REFS:
            state["our_refs"].append(url)
            return {"kind": "our_ref_skipped", "brand": "Mostbet", "evidence": "registry"}
        res = await self.http_follow(url, site, state)
        if res is None:
            return {"kind": "needs_browser", "brand": "", "evidence": "http_undecided"}
        if key and res.get("kind") not in ("dead", "internal", "our_ref_skipped"):
            self.cache[key] = {k: v for k, v in res.items() if not k.startswith("_")}
        return res


# Visitors a cloaking site treats differently from a plain desktop browser (--as).
VISITORS = {
    "google-mobile": {"User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) "
                                    "Chrome/124.0 Mobile Safari/537.36", "Referer": "https://www.google.com/"},
    "googlebot": {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"},
    "mobile": {"User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-A536B) AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/124.0 Mobile Safari/537.36"},
}


def repair_log(path: Path) -> int:
    """Rewrite a jsonl.gz log whose last gzip member was cut off by a hard stop.

    Readers stop at the broken member, so records appended after it would be lost; rewriting keeps
    every complete line. Returns the number of lines kept, or -1 when the file was intact.
    """
    if not path.exists():
        return -1
    lines = []
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            for line in f:
                lines.append(line)
        return -1
    except (EOFError, OSError, gzip.BadGzipFile):
        pass
    good = []
    for line in lines:
        try:
            json.loads(line)
            good.append(line if line.endswith("\n") else line + "\n")
        except json.JSONDecodeError:
            pass
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        f.writelines(good)
    tmp.replace(path)
    return len(good)


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
        pass  # the last gzip member is cut off after a hard stop — keep what was read
    return done


def _consume(task):
    if not task.cancelled():
        task.exception()  # retrieved, so an abandoned task does not log "never retrieved"


async def bounded(coro, timeout):
    """Await coro for at most timeout seconds.

    Unlike asyncio.wait_for, a timed-out task is cancelled without waiting for it to finish: the
    cleanup of a page on a crashed browser (ctx.close() in a finally) can wait forever, and
    wait_for would hang the worker with it.
    """
    task = asyncio.ensure_future(coro)
    task.add_done_callback(_consume)
    done, _ = await asyncio.wait({task}, timeout=timeout)
    if not done:
        task.cancel()
        raise TimeoutError(f"no answer in {timeout}s")
    return task.result()


def kill_driver(cm):
    """SIGKILL the Playwright driver of an AsyncCamoufox and everything below it (browser, content
    processes), so a hung browser leaves no orphans behind. No-op when it has already exited."""
    proc = getattr(getattr(getattr(cm, "_connection", None), "_transport", None), "_proc", None)
    if proc is None or proc.returncode is not None:
        return
    pids, todo = [], [proc.pid]
    while todo:
        pid = todo.pop()
        pids.append(pid)
        out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout
        todo += [int(x) for x in out.split()]
    for pid in reversed(pids):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


async def proxy_alive(server: str) -> bool:
    """One cheap request through the proxy. A dropped Mac tunnel would otherwise turn the rest of
    the queue into connection errors within minutes."""
    p = await asyncio.create_subprocess_exec(
        "curl", "-sS", "-m", "10", "-o", "/dev/null", "-w", "%{http_code}",
        "-x", server.replace("socks5://", "socks5h://", 1), "https://www.gstatic.com/generate_204",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await p.communicate()
    return out.strip() == b"204"


async def detect_network(proxy: dict | None = None) -> str:
    """Exit IP as seen by the scan. With --proxy, probe through SOCKS (Mac tunnel), not the host."""
    try:
        if proxy:
            # curl speaks socks5h; aiohttp would need aiohttp-socks.
            server = proxy["server"]
            r = subprocess.run(
                ["curl", "-sS", "-m", "12", "-x", server.replace("socks5://", "socks5h://", 1),
                 "https://ipinfo.io/json"],
                capture_output=True, text=True, check=False,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return f"proxy_fail {server}"
            j = json.loads(r.stdout)
        else:
            async with aiohttp.ClientSession() as s:
                async with s.get("https://ipinfo.io/json", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    j = await resp.json(content_type=None)
        return f"{j.get('country')} {j.get('org')} {j.get('ip')}"
    except Exception:  # noqa: BLE001
        return "unknown"


async def main():
    global MAX_FOLLOW
    ap = argparse.ArgumentParser()
    ap.add_argument("queue_csv")
    ap.add_argument("out_dir")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--priority", help="comma-separated queue priorities to take, e.g. 1,2")
    ap.add_argument("--redo", help="file with domains to rescan")
    ap.add_argument("--domains", help="file with domains to take from the queue (others are ignored)")
    ap.add_argument("--as", dest="as_", choices=sorted(VISITORS),
                    help="HTTP scan as another visitor (cloaking check): google-mobile = mobile browser coming from a "
                         "Google search, googlebot = Google's crawler. Logs to http-scan-<as>.jsonl.gz, pages to "
                         "<domain>.http-<as>.html.gz")
    ap.add_argument("--mode", choices=("http", "destinations", "browser", "home", "rest", "gates", "deep"), default="http",
                    help="http: sites by plain HTTP; destinations: unique destinations HTTP could not decide, "
                         "in the browser; browser: whole sites whose home page needs a browser; "
                         "home: only fetch and keep home pages by plain HTTP (implies --save-html); "
                         "rest: follow by HTTP what browser records left unfollowed (writes rest-scan.jsonl.gz)")
    ap.add_argument("--max-follow", type=int, default=MAX_FOLLOW,
                    help=f"destinations followed per site (default {MAX_FOLLOW}); the rest count as not_followed")
    ap.add_argument("--save-html", nargs="?", const="", default=None, metavar="DIR",
                    help="keep home pages as <domain>.<http|browser>.html.gz (default DIR: <out_dir>/html)")
    ap.add_argument("--from-http", action="store_true",
                    help="browser mode: take only domains still needs_browser after the destination pass")
    ap.add_argument("--proxy",
                    help="exit proxy for Camoufox and HTTP follows, e.g. socks5://127.0.0.1:1080 (SSH -R tunnel "
                         "from the Mac). Does not change the host default route. Needs aiohttp-socks; "
                         "the destination cache from other networks is not loaded")
    a = ap.parse_args()
    if a.as_:
        if a.mode != "http":
            raise SystemExit("--as works with --mode http only")
        aff.HEADERS.update(VISITORS[a.as_])
    MAX_FOLLOW = a.max_follow
    proxy = parse_proxy(a.proxy)
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scan = out / {"http": "http-scan.jsonl.gz", "destinations": "dest-browser.jsonl.gz",
                  "browser": "browser-scan.jsonl.gz", "home": "home-dump.jsonl.gz",
                  "rest": "rest-scan.jsonl.gz", "gates": "gates-scan.jsonl.gz", "deep": "deep-scan.jsonl.gz"}[a.mode]
    if a.as_:
        scan = out / f"http-scan-{a.as_}.jsonl.gz"
    html_dir = None
    if a.save_html is not None or a.mode == "home":
        html_dir = Path(a.save_html) if a.save_html else out / "html"
        html_dir.mkdir(parents=True, exist_ok=True)
    for log in (scan, out / "dest-browser.jsonl.gz"):
        kept = repair_log(log)
        if kept >= 0:
            print(f"repaired truncated {log.name}: {kept} records kept", flush=True)
    dcache = load_dest_cache(out / "dest-browser.jsonl.gz")
    items = list(csv.DictReader(open(a.queue_csv, encoding="utf-8")))
    for x in items:
        x["domain"] = x.get("domain_ascii") or x.get("domain") or x.get("domain_name")
    if a.priority:
        keep = set(a.priority.split(","))
        items = [x for x in items if x.get("priority") in keep]
    if a.domains:
        only = {l.strip() for l in open(a.domains, encoding="utf-8") if l.strip()}
        items = [x for x in items if x["domain"] in only]
    if a.mode == "destinations":
        wanted = {x["domain"] for x in items}
        http_recs = {d: r for d, r in read_last(out / "http-scan.jsonl.gz").items() if d in wanted}
        items = pending_destinations(http_recs)
    elif a.mode == "rest":
        browser_recs = read_last(out / "browser-scan.jsonl.gz")
        items = [{**x, "rec": browser_recs[x["domain"]]} for x in items if x["domain"] in browser_recs]
    elif a.from_http:
        http_recs = read_last(out / "http-scan.jsonl.gz")
        still = {d for d, r in http_recs.items() if resolve_record(r, dcache)["result"]["group"] == "needs_browser"}
        items = [x for x in items if x["domain"] in still]
    done = done_domains(scan)
    if a.redo:
        redo = {l.strip() for l in open(a.redo, encoding="utf-8") if l.strip()}
        done -= redo
        items = [x for x in items if x["domain"] in redo]
    todo = [x for x in items if x["domain"] not in done]
    if a.limit:
        todo = todo[:a.limit]
    network = await detect_network(proxy)
    print(f"queue {len(items)}, done {len(done)}, todo {len(todo)}, network {network}, "
          f"our refs guarded {len(OUR_REFS)}"
          + (f", proxy {proxy['server']}" if proxy else ""), flush=True)
    if proxy and "proxy_fail" in network:
        raise SystemExit("proxy is set but exit IP probe failed — is the Mac SOCKS tunnel up?")

    if proxy:
        from aiohttp_socks import ProxyConnector  # only proxied runs need it
        # rdns: names resolve on the proxy side, like socks5h in curl
        conn = ProxyConnector.from_url(a.proxy, rdns=True, limit=64, limit_per_host=4,
                                       enable_cleanup_closed=True)
    else:
        conn = aiohttp.TCPConnector(limit=64, limit_per_host=4, ttl_dns_cache=600, enable_cleanup_closed=True)
    session = aiohttp.ClientSession(connector=conn, headers=aff.HEADERS, cookie_jar=aiohttp.DummyCookieJar())
    scanner = Scanner(network, session, proxy=proxy, html_dir=html_dir)
    if a.as_:
        scanner.html_src = f"http-{a.as_}"
    if not proxy and not a.as_:  # a cloaking site answers another visitor differently: no shared cache
        scanner.cache.update(dcache)
    fh = gzip.open(scan, "at", encoding="utf-8")
    stats, t0, n = {}, time.time(), 0
    q = asyncio.Queue()
    for x in todo:
        q.put_nowait(x)

    def write(rec):
        nonlocal n
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        n += 1
        g = rec["result"]["group"]
        stats[g] = stats.get(g, 0) + 1
        if n % 25 == 0 or n == len(todo):
            rate = n / (time.time() - t0) * 60
            print(f"{n}/{len(todo)} {rate:.1f}/min {dict(sorted(stats.items()))}", flush=True)

    http_one = {"home": scanner.home_dump, "rest": lambda x: scanner.follow_rest(x["rec"]),
                "gates": scanner.follow_gates, "deep": scanner.follow_deep}.get(
        a.mode, scanner.http_scan_site)

    async def http_worker():
        while not q.empty():
            item = q.get_nowait()
            t = time.time()
            try:
                rec = await asyncio.wait_for(http_one(item), timeout=SITE_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                rec = {"domain": item["domain"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "network": network,
                       "mode": a.mode, "queue_reason": item.get("reason"),
                       "result": {"group": "needs_browser" if a.mode == "http" else "no_answer",
                                  "reason": "scan_error:" + type(e).__name__, "detail": str(e)[:200]}}
            rec["elapsed_s"] = round(time.time() - t, 1)
            write(rec)

    # One browser per worker, sites sequential inside it: Camoufox keeps all tabs of a browser in one
    # content process, so a single heavy page stalls every other tab of the same browser.
    run_one = scanner.resolve_destination if a.mode == "destinations" else scanner.scan_site

    async def worker(wid):
        """One browser, relaunched after every batch, crash or hang; exits only when the queue is empty."""
        from camoufox import DefaultAddons
        from camoufox.async_api import AsyncCamoufox
        fails = 0
        while not q.empty():
            # Camoufox bundles uBlock Origin by default; it aborts ad, tracker and parking scripts,
            # which are exactly what this scan has to see (parked shells rendered as empty pages).
            launch = dict(headless=True, geoip=True, block_images=True, humanize=False,
                          i_know_what_im_doing=True, exclude_addons=[DefaultAddons.UBO])
            if proxy:
                launch["proxy"] = proxy
            cm = AsyncCamoufox(**launch)
            try:
                browser = await bounded(cm.__aenter__(), LAUNCH_TIMEOUT)
            except Exception as e:  # noqa: BLE001
                fails += 1
                kill_driver(cm)
                delay = min(300, 10 * 2 ** min(fails, 5))
                print(f"worker {wid}: browser launch failed ({type(e).__name__}: {str(e)[:120]}), "
                      f"retry in {delay}s", flush=True)
                await asyncio.sleep(delay)
                continue
            fails = 0
            try:
                for _ in range(BATCH):
                    while proxy and not await proxy_alive(proxy["server"]):
                        print(f"{time.strftime('%H:%M:%S')} worker {wid}: proxy down, waiting", flush=True)
                        await asyncio.sleep(60)
                    if q.empty():
                        break
                    item = q.get_nowait()
                    t = time.time()
                    restart = False
                    try:
                        rec = await bounded(run_one(browser, item), SITE_TIMEOUT)
                    except Exception as e:  # noqa: BLE001 — a stuck or crashed browser is replaced
                        restart = True
                        rec = {"domain": item["domain"], "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                               "network": network, "queue_reason": item.get("reason"),
                               "result": {"group": "5_not_shown", "reason": "scan_error:" + type(e).__name__,
                                          "detail": str(e)[:200]}}
                    rec["elapsed_s"] = round(time.time() - t, 1)
                    if proxy:
                        rec["proxy"] = proxy["server"]
                    write(rec)
                    if restart:
                        break
            finally:
                try:
                    await bounded(cm.__aexit__(None, None, None), CLOSE_TIMEOUT)
                except Exception:  # noqa: BLE001 — a dead browser may never answer close()
                    pass
                kill_driver(cm)

    await asyncio.gather(*((http_worker() if a.mode in ("http", "home", "rest", "gates", "deep") else worker(i))
                           for i in range(a.concurrency)))
    await session.close()
    fh.close()
    print("done", dict(sorted(stats.items())), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
