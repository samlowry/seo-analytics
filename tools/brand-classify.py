"""One category per site plus tags, over the whole brand-protection list.

Run: uv run --with selectolax --with aiohttp python tools/brand-classify.py brand-protection/2026-09-28
Reads brand-scan/groups.csv (the 22k sites affiliate-scan could not settle, with followed ads),
affiliate-scan/{affiliate,not-affiliate}.csv (the 11.7k it settled), brand-scan/site-features.jsonl.gz
(features of the saved home pages, tools/brand-site-features.py) and the ref registry.
Writes brand-scan/classified.csv and prints the counts. No network.

Categories (one per site):
  mirror         official Mostbet frontend (its assets or its "MostBet.com …" title)
  mono_other     Mostbet monobrand advertising only other brands by affiliate links   — main target
  mono_mixed     Mostbet monobrand advertising Mostbet and other brands                — main target
  mono_xlink     Mostbet monobrand, no foreign affiliate links, plain links to other-brand sites
  mono_mostbet   Mostbet monobrand advertising Mostbet only
  mono_unresolved Mostbet monobrand whose buttons lead to a gate or tracker nobody followed to the end
  mono_no_ads    Mostbet monobrand with no affiliate links found
  bait           Mostbet in the domain or title, the page is about another brand or casino (a violator)
  discredit      Mostbet in the domain, the page is not about gambling at all (shop, drugs, anything)
  multibrand     gambling affiliate not about Mostbet: rating of several brands, games, slots
  mb_page_other  not a monobrand, but its page about Mostbet advertises other brands (owner, 01.10) — a violator
  article        article site or link seller: a feed of posts, Mostbet not its subject
  hacked         unrelated site with Mostbet only in links, often hidden
  other_gambling another operator or its doorway, Mostbet not mentioned
  unrelated      no Mostbet and no gambling
  unclear        Mostbet mentioned, the rules above do not decide
  stub           answers with an empty page: coming soon, suspended, hosting placeholder, bare JS shell
  redirect_ref   the home page itself redirects to a Mostbet ref, no content
  redirect_other the home page itself redirects to another brand's ref
  parked         parking or registrar placeholder
  dead           does not answer
  not_shown      answers, but a bot wall, HTTP error or geo block hides the page
Tags (any number): cloaked:<visitor> (hidden from a plain visitor, shown to one coming from Google search or to
  Googlebot; judged by what that visitor gets), platform, rotating_ads, search_referrer_js, apk, our_ref, brand_in_domain,
  pwa (fake store lander installing an app; its offer is followed in gates-scan), moved (home redirects to another host), ads_unverified (affiliate links not followed to the end),
  no_html, ads_mobile_only / ads_search_only (foreign ads seen only by a mobile visitor / one coming from Google).
"""
import csv
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import landing_brand as lb  # noqa: E402

csv.field_size_limit(sys.maxsize)

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location("brand_site_features", HERE / "brand-site-features.py")
_feat = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_feat)
MB = _feat.MB  # folds accents and look-alike letters: "Μοѕtbеt", "Móstbet"
NOT_AD_HOST = re.compile(r"(^|\.)(wordpress\.(com|org)|wp\.com|gravatar\.com|blogger\.com|tumblr\.com|medium\.com|"
                         r"yahoo\.com|consent\.[a-z.]+|legal\.[a-z.]+|google\.[a-z.]+|facebook\.com|"
                         r"apple\.com|microsoft\.com|cookiebot\.com|onetrust\.com|gannett\.com)$", re.I)
BARE_GATES = {"/go/", "/goto/", "/out/", "/link/", "/visit/", "/redirect/", "/click/", "/go", "/goto", "/out"}
NOT_CASINO_HOST = re.compile(r"(^|\.)(bet\.com|chatgpt\.com|openai\.com|nolimitcity\.com|pragmaticplay\.(com|net)|"
                             r"evolution\.com|playngo\.com|netent\.com|spribe\.co|gpwa\.org|iclg\.com|seo\.casino|promopult\.ru|begambleaware\.org|gamcare\.org\.uk|"
                             r"casino\.guru|askgamblers\.com|trustpilot\.com|curacao-egaming\.com|mga\.org\.mt)$", re.I)
SETTLED_STRIKES = ("mono_other", "mono_mixed", "bait", "redirect_other", "discredit")
VISITORS = ("google-mobile", "googlebot")  # used for sites hidden from a plain visitor
EXTRA_VISITORS = {"mobile": "ads_mobile_only", "google-mobile": "ads_search_only"}  # extra snapshots of live sites
HIDDEN_GROUPS = ("5_not_shown", "6_cf_check", "5_dead")
OPEN_RANK = {"4_mixed": 6, "3_other_only": 5, "1_mostbet_only": 4, "0_mostbet_frontend": 3, "2_no_ads": 2,
             "7_unresolved": 2, "8_no_mention": 2, "needs_browser": 1}
REGISTRY = Path.home() / "Developer/skaner-bitykh-ssylok/registry/entries.json"

# Thresholds, tuned on the review sample.
MONO_DENSITY = 1.0      # Mostbet mentions per 1k chars of visible text for a monobrand without the name in its domain
MONO_DOMINANCE = 2.0    # Mostbet mentions vs the most-mentioned other brand
MULTI_BRANDS = 3        # other brands named at least MULTI_MIN times each for a multibrand review
MULTI_MIN = 2
GAMBLING_DENSITY = 2.0  # gambling words per 1k chars for a gambling page
ARTICLE_LINKS = 15      # internal post links (slug or dated paths) for an article feed
HACKED_MAX_TEXT = 3     # Mostbet mentions in visible text outside links, at most
MIRROR_TEXT = 6000      # visible chars of a rendered mirror; affiliate copies with Mostbet CDN images are longer
HACKED_GAMBLING = 5.0   # a hacked site's own topic is not gambling: gambling words per 1k chars below this
STUB_TEXT = 300         # visible chars below which a page with no ads is a stub
PARKED_MORE = re.compile(r"domain registration has expired|website\.ws/wc_landing|forsale\.godaddy\.com|is for sale|future home of|"
                         r"is this domain name yours|forsale\.dynadot\.com|on auction|^\s*parking page|"
                         r"domain is for sale|buy this domain|domain parking", re.I)
STUB_MORE = re.compile(r"why am i seeing this page|fastpanel|account (disabled|suspended)|web server is ready|"
                       r"website is ready|coming soon|under construction|default (web )?page|it works!|"
                       r"домен не прилинкован|сайт заблокирован|hosting account|техническая пауза|сайт обновляется|"
                       r"under-construction|site not found|served by the hosting platform|сайт в разработке|"
                       r"website \S+ is ready|content is to be added|только что создан|welcome to nginx|сайт недоступен|"
                       r"parked domain|registered at|hostinger|this site can.t be reached|default site", re.I)
CHALLENGE = re.compile(r"just a moment|attention required|ddos-guard|checking your browser|verify you are human|"
                       r"access denied|cookie consent|before you continue", re.I)
MIRROR_TITLE = re.compile(r"\bmost\s?bet\.com\s*[-–—]", re.I)  # localized "Betting company MostBet.com – …"


def ref_key(url: str) -> str:
    s = urlsplit(url)
    return (s.hostname or "").lower() + (s.path.rstrip("/") or "/")


def load_csv(p: Path) -> dict:
    if not p.exists():
        return {}
    with open(p, newline="", encoding="utf-8") as f:
        return {r["domain"]: r for r in csv.DictReader(f)}


def load_features(p: Path) -> dict:
    out = {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            out[r["domain"]] = r
    return out


def merged_page(fr: dict) -> dict:
    """The rendered page for text, links from both pages."""
    b, h = fr.get("browser") or {}, fr.get("http") or {}
    if b.get("error"):
        b = {}
    if h.get("error"):
        h = {}
    base = dict(b if b and b.get("text_len", 0) >= h.get("text_len", 0) else h or b)
    if not base:
        return {}
    seen, links = set(), []
    for x in (b.get("aff_links") or []) + (h.get("aff_links") or []):
        if x["url"] not in seen:
            seen.add(x["url"])
            links.append(x)
    base["aff_links"] = links
    for k in ("gates", "trackers"):
        base[k] = (b.get(k) or []) + [x for x in (h.get(k) or []) if x not in (b.get(k) or [])]
    base["mostbet_shell"] = bool(b.get("mostbet_shell") or h.get("mostbet_shell"))
    base["pwa"] = bool(b.get("pwa") or h.get("pwa"))
    base["pwa_offer"] = b.get("pwa_offer") or h.get("pwa_offer") or ""
    base["apk"] = sorted(set((b.get("apk") or []) + (h.get("apk") or [])))
    base["referrer_js"] = bool(b.get("referrer_js") or h.get("referrer_js"))
    base["mostbet_assets"] = bool(b.get("mostbet_assets") or h.get("mostbet_assets"))
    base["mirror_title"] = bool(b.get("mirror_title") or h.get("mirror_title"))
    base["parked"] = bool((b or h).get("parked")) and not (b.get("text_len", 0) > 2000)
    return base


def from_scan(page: dict, g: dict, a: dict, na: dict) -> dict:
    """A page whose saved HTML has no text (JS shell, bot wall) takes what the scan saw rendered."""
    src = g or a or na
    if not src:
        return page
    tl = int(src.get("text_len") or 0)
    challenge = bool(page) and bool(CHALLENGE.search(page.get("title") or ""))
    if page and not challenge and page.get("text_len", 0) >= max(tl, 1) * 0.5:
        return page
    if challenge:
        page = {k: v for k, v in page.items() if k not in ("aff_links", "gambling_per_1k", "gambling_words", "slug_links", "date_links")}
    mb = int(src.get("mostbet_mentions") or 0)
    if not tl and not mb and not src.get("title"):
        return page
    title = src.get("title") or ""
    others = {}
    for x in (g.get("home_other_brand_mentions") or "").split(" | "):
        if x:
            others[x] = 2
    return {**(page or {}), "title": title or (page or {}).get("title", ""), "text_len": tl, "mb_text": mb,
            "mb_per_1k": round(mb * 1000 / tl, 2) if tl else 0.0, "mb_title": bool(MB.search(title)),
            "mb_h1": (page or {}).get("mb_h1", False), "other_brands": others or (page or {}).get("other_brands", {}),
            "from_scan": True}


def hop_urls(x: dict) -> list:
    return [h.split(" ", 1)[-1] for h in (x.get("hops") or "").split(" → ") if h]


def is_coded(x: dict) -> bool:
    """A partner code anywhere on the way: affiliate parameters in the link, a hop or the landing."""
    for u in [x.get("url") or "", x.get("final_url") or ""] + hop_urls(x):
        try:
            q = urlsplit(u).query or ""
        except ValueError:
            continue
        if lb.AFF_PARAMS.search(q) or lb.TRACK_PARAMS.search(q) or CODE_Q.search(q):
            return True
    return False


def via_tracker(x: dict) -> bool:
    """The chain passes a host that is neither the linked host nor the landing: a tracker, not a domain move."""
    ends = {lb_base(x.get("url") or ""), lb_base(x.get("final_url") or "")}
    return any(lb_base(u) not in ends for u in hop_urls(x) if lb_base(u))


def lb_base(u: str) -> str:
    try:
        return (urlsplit(u).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def with_meta(page: dict) -> dict:
    """A page with no visible text (PWA store landers) is read from its meta and og tags."""
    if not page or page.get("text_len", 0) >= 100 or not page.get("meta_text"):
        return page
    mt = page["meta_text"]
    return {**page, "mb_text": max(page.get("mb_text", 0), page.get("mb_meta", 0)), "mb_title": bool(page.get("mb_title") or MB.search(mt)),
            "title": page.get("title") or mt[:120], "from_meta": True}


def ads(domain: str, g: dict, a: dict, na: dict, page: dict, our: set, dests: list, trackers_to_other: set,
        checks: list = (), mostbet_titled: set = frozenset()) -> dict:
    """Affiliate traffic of a site: to Mostbet, to other brands (with names), plain links to other
    gambling sites, links not followed to the end, our own refs."""
    mb, other, plain, unverified, ours = False, set(), set(), 0, False
    links = []  # (kind, name, url, final) of every link that decided: the evidence shown in the report

    def add_other(name, u, f):
        other.add(name)
        links.append(("other", name, u, f))

    def add_mb(u, f, kind="mb"):
        nonlocal mb
        mb = True
        links.append((kind, "Mostbet", u, f))

    def add_plain(host, u, f):
        plain.add(host)
        links.append(("plain", host, u, f))
    if g.get("incomplete"):
        unverified += 1
    for x in dests:
        url, final = x.get("url") or "", x.get("final_url") or ""
        su = urlsplit(url)
        if x.get("via") == "home_redirect":
            continue  # the site's own move
        if su.path.lower() in BARE_GATES and str(x.get("via", "")).startswith("js:"):
            continue  # a gate prefix glued in a script without its id
        if url.lower().split("?")[0].endswith(".apk") or x.get("kind") == "download" or \
                str(x.get("evidence", "")).startswith("download"):
            continue  # an app download is not an ad of the brand it names
        coded, tracked = is_coded(x), via_tracker(x)
        kind, brand = x.get("kind"), x.get("brand") or ""
        if kind in ("unknown", "dead", "needs_browser", "non_gambling") and MB.search(lb_base(url)) and not su.query:
            continue  # a plain link to a sister Mostbet-named site; where that site now goes is not this site's ad
        if x.get("via", "").startswith("js:data-modal"):
            continue  # game demo windows of providers, not links
        if mostbet_ref(url, domain):
            add_mb(url, final, "mb")  # Mostbet ref by its shape and host, even when the ref host no longer answers
        elif kind == "mostbet":
            # Named only by its title (another Mostbet-branded site, not the operator): an ad only with a code.
            weak = x.get("evidence") == "name_only_weak"
            if x.get("pid") or coded or mostbet_ref(url, domain) or (tracked and not weak):
                add_mb(url, final, "mb")
        elif kind in ("other_gambling", "gambling_site") and (coded or tracked):
            add_other(brand if brand and brand != "?" else (urlsplit(final).hostname or "?"), url, final)
        elif kind == "other_gambling" and brand and brand != "?" and lb.brand_of_host(lb_base(final)) not in ("", "Mostbet") \
                and not NOT_CASINO_HOST.search(lb_base(final)):
            add_other(brand, url, final)  # a link to an operator (its brand in the host) is an ad even without a code (owner, 30.09)
        elif kind in ("other_gambling", "gambling_site") and MB.search(lb_base(url)):
            continue  # a sister Mostbet-named site of a network moving elsewhere: not this site's ad
        elif kind == "other_gambling" and not NOT_CASINO_HOST.search(lb_base(final)):
            add_plain(lb_base(final), url, final)  # a review or doorway naming a brand in its title, not the operator
        elif kind == "gambling_site":
            host = (urlsplit(final).hostname or "").lower()
            named = lb.brand_of_host(host) or next((n for n, rx in lb.BRAND_RES if rx.search(x.get("title") or "")), "")
            if lb.brand_of_host(host) not in ("", "Mostbet") and not NOT_CASINO_HOST.search(host):
                add_other(lb.brand_of_host(host), url, final)
            elif not NOT_CASINO_HOST.search(host):
                add_plain(host, url, final)  # another gambling site with no known brand: a doorway, the weak case
        elif kind in ("unknown", "needs_browser", "dead") and coded and mostbet_ref_host(lb_base(final) or lb_base(url)):
            add_mb(url, final, "mb")
        elif kind in ("unknown", "needs_browser", "dead") and coded and not MB.search(lb_base(final) or lb_base(url)):
            add_other(lb_base(final) or lb_base(url), url, final)  # partner code on a host that is not Mostbet
        elif kind in ("unknown", "needs_browser", "dead") and (tracked or x.get("ad_route") == "True"):
            unverified += 1
    if a:
        ref = a.get("ref_url") or ""
        if ref_key(ref) in our:
            ours = True
            add_mb(ref, "", "ours")
        elif mostbet_ref(ref, domain) or MB.search(lb_base(ref)):
            add_mb(ref, "", "mb")
        elif looks_tracker(ref):
            add_other(lb.brand_of_host(lb_base(ref)) or f"via {lb_base(ref)}", ref, "")
    for chk in checks:
        chain = [c.get("url") or "" for c in chk.get("chain") or []]
        if chk.get("found") or len(chain) < 2:
            continue
        hosts = [lb_base(u) for u in chain[1:] if lb_base(u) and not lb_same(lb_base(u), domain)]
        if not hosts or any(NOT_AD_HOST.search(h) for h in hosts):
            continue
        named = next((lb.brand_of_host(h) for h in hosts if lb.brand_of_host(h)), "") or \
            ("Mostbet" if any(h in mostbet_titled for h in hosts) else "")
        coded = any(lb.AFF_PARAMS.search(urlsplit(u).query or "") or lb.TRACK_PARAMS.search(urlsplit(u).query or "") for u in chain)
        last_ok = (chk.get("chain") or [{}])[-1].get("status") == 200
        if named == "Mostbet":
            # A chain of Mostbet-named doorways is not an ad; a ref host or a partner code is.
            if coded or any(mostbet_ref_host(h) for h in hosts):
                add_mb(chain[1], chain[-1], "mb")
        elif named:
            add_other(named, chain[1], chain[-1])
        elif coded and last_ok:
            add_other(hosts[-1], chain[1], chain[-1])
        elif not mostbet_ref_host(hosts[0]) and not MB.search(hosts[0]) and looks_tracker(chain[1] if len(chain) > 1 else ""):
            add_other(f"via {hosts[0]}", chain[1], chain[-1])  # a foreign tracker counts even when it no longer opens (owner, 30.09)
        else:
            unverified += 1
    for x in page.get("aff_links") or []:
        if ref_key(x["url"]) in our:
            ours = True
            add_mb(x["url"], "", "ours")
        elif x.get("brand") == "Mostbet" or (x.get("ref_kind") and mostbet_ref(x["url"], domain)):
            add_mb(x["url"], "", "mb")
        elif x.get("ref_kind"):
            add_other(f"via {x.get('host')}", x["url"], "")
        elif x.get("brand"):
            add_other(x["brand"], x["url"], "")
        elif lb.AFF_PARAMS.search(urlsplit(x["url"]).query or "") or lb.TRACK_PARAMS.search(urlsplit(x["url"]).query or "") \
                or re.search(r"(^|&)(affiliatecode|affiliate_code|sub\d|buyer)=", urlsplit(x["url"]).query or "", re.I):
            if not MB.search(x.get("host") or "") and not mostbet_ref_host(x.get("host") or ""):
                add_other(x.get("host") or "?", x["url"], "")
        elif not g:
            unverified += 1  # tracker link of an unknown brand, not followed for this site
    return {"mb": mb, "other": sorted(other), "plain": sorted(p for p in plain if p), "unverified": unverified,
            "ours": ours, "links": links}


_aff = None


TRACKER_PATH = re.compile(r"^/[A-Za-z0-9_-]{4,12}/?$")
CODE_Q = re.compile(r"(^|&)(code|invite|invitecode|affiliatecode|affiliate_code|sub\d|buyer|refcode)=", re.I)


def mostbet_ref(url: str, site: str) -> bool:
    """A Mostbet ref: ref-shaped AND on a Mostbet ref host (…mb.com, …mst.com, registry). Other programs use the
    same /XXXX shape (bwredir.com/2Sgv is Betwinner)."""
    aff_ref("https://x/", "x")
    kind = _aff.classify_ref(url, site)
    host = lb_base(url)
    return kind in ("known_ref_host", "mostbet_host") or (kind == "ref" and mostbet_ref_host(host))


def looks_tracker(url: str) -> bool:
    """A tracker link: a random-looking host, a short code for a path, or partner parameters."""
    try:
        s = urlsplit(url)
    except ValueError:
        return False
    aff_ref("https://x/", "x")
    rooted = (s.path or "/") == "/" and not s.query
    return bool((_aff.random_host((s.hostname or "").lower()) and not rooted) or
                (TRACKER_PATH.search(s.path or "") and any(c.isupper() or c.isdigit() for c in s.path)) or
                lb.AFF_PARAMS.search(s.query or "") or lb.TRACK_PARAMS.search(s.query or ""))


def mostbet_ref_host(host: str) -> bool:
    """Mostbet ref hosts end in mb/mst/most before the TLD (weg96sbmb.com) or are in the registry."""
    aff_ref("https://x/", "x")  # load the module
    return bool(host) and (bool(_aff.REF_HOST.search(host)) or host in _aff.KNOWN_REF_HOSTS)


def aff_ref(url: str, site: str) -> bool:
    global _aff
    if _aff is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("affiliate_scan", HERE / "affiliate-scan.py")
        _aff = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_aff)
    return bool(_aff.classify_ref(url, site))


def top_other(page: dict):
    ob = page.get("other_brands") or {}
    if not ob:
        return "", 0
    name = max(ob, key=ob.get)
    return name, ob[name]


GAME_WORDS = re.compile(r"aviator|chicken\s?road|plinko|tappy\s?bird|crash game|mines game|jetx|lucky\s?jet|"
                        r"spaceman|penalty shoot|slot|مراهن|كازينو|رهان|fogad|kaszin|bukmach|kasyn|zakład|apuest|cassino|"
                        r"aposta|bahis|kumar|pariuri|sázk|tikish|mərc|kazino|বেটিং|ক্যাসিনো|सट्टा|कैसीनो|bookmaker|betting|"
                        r"nhà cái|cá cược|kèo|tài xỉu|nổ hũ|game bài|bắn cá|พนัน|คาสิโน|judi|taruhan", re.I)


def site_type(domain: str, page: dict, ad: dict) -> tuple:
    """(category, why) from the page and its ads; statuses are decided before."""
    # A domain that moved to another site is judged by that site: its own name no longer shows.
    in_domain = bool(MB.search(page.get("host") or domain)) if page.get("moved") else bool(MB.search(domain))
    brand_domain = bool(MB.search(domain))  # the name the visitor typed, before any move
    in_head = bool(page.get("mb_title") or page.get("mb_h1"))
    mb_text, dens = page.get("mb_text", 0), page.get("mb_per_1k", 0.0)
    other_name, other_n = top_other(page)
    n_brands = sum(1 for v in (page.get("other_brands") or {}).values() if v >= 1)
    gpk = page.get("gambling_per_1k", 0.0)
    head = f'{page.get("title", "")} {page.get("h1", "")}'
    gambling_head = bool(_feat.GAMBLING.search(head) or GAME_WORDS.search(head)) or \
        any(rx.search(head) for _, rx in lb.BRAND_RES[:40])
    gambling = gpk >= GAMBLING_DENSITY or page.get("gambling_words", 0) >= 15 or gambling_head or \
        len(GAME_WORDS.findall(page.get("text_sample") or "")) >= 2 or bool(ad["other"]) or bool(ad["plain"])
    posts = page.get("articles", 0) > 0 or page.get("date_links", 0) >= 5
    ext_mb, int_mb = page.get("mb_anchor_ext", 0), page.get("mb_anchor_int", 0)
    hidden_mb, in_posts = page.get("mb_hidden_links", 0), page.get("mb_in_posts", 0)
    dominant = mb_text >= MONO_DOMINANCE * max(other_n, 1) or (mb_text and not other_n)
    other_dominant = other_n >= MONO_DOMINANCE * max(mb_text, 1) and other_n >= 5
    topic_gambling = gambling_head or gpk >= HACKED_GAMBLING or n_brands > 5
    subject = (in_head or page.get("mb_meta", 0) > 0) and dens >= MONO_DENSITY  # Mostbet in title/meta and all over the text

    if in_domain and page.get("from_meta") and not ad["mb"]:
        return "bait", "mostbet_in_domain, store-style PWA lander without a Mostbet ref"  # owner, 30.09
    if brand_domain and page.get("moved") and not mb_text and not ad["mb"] and (gambling or ad["other"]):
        return "bait", f"brand domain moves to {page.get('host', '')} with other gambling"
    if not (mb_text or ext_mb or int_mb or in_domain or in_head or ad["mb"]):
        known_other = [x for x in ad["other"] if not x.startswith("via ")]
        return ("other_gambling" if gambling or known_other else "unrelated"), "no_mostbet"
    if hidden_mb >= 3 and not gambling_head and not in_domain and not subject:
        return "hacked", f"hidden_mostbet_links={hidden_mb}"
    # Own topic is not gambling and Mostbet sits in links to other domains or in hidden blocks: injected.
    if not topic_gambling and not in_domain and not subject and (hidden_mb or (ext_mb and mb_text <= max(ext_mb, HACKED_MAX_TEXT) + 2)):
        return "hacked", f"mostbet_in_links ext={ext_mb} hidden={hidden_mb} text={mb_text} gambling={gpk}"
    if in_head and not in_domain and not gambling and not subject and page.get("text_len", 0) >= 1000 and not ad["mb"]:
        return "hacked", f"mostbet_in_title_of_non_gambling_page text={mb_text}"
    # Mostbet only in the site's own posts: an article site or a sold post.
    if not topic_gambling and not in_domain and not ad["mb"] and not subject and (in_posts or (int_mb and posts)):
        return "article", f"mostbet_in_posts int={int_mb} in_posts={in_posts} articles={page.get('articles', 0)}"
    foreign = bool(other_n or ad["other"] or ad["plain"])
    title_mb = bool(MB.search(page.get("title") or ""))
    if (in_domain or (title_mb and n_brands < 3)) and foreign and (other_dominant or (gambling and not mb_text and not ad["mb"])):
        return "bait", f"mostbet_in_{'domain' if in_domain else 'title'} content={other_name or 'other'}:{other_n} mostbet={mb_text}"
    if (in_domain or in_head) and dominant and (dens >= MONO_DENSITY / 2 or (in_head and ad["mb"])):
        return "mono", f"name_in_{'domain' if in_domain else 'title'} density={dens}"
    feed_real = page.get("date_links", 0) >= 5 or (page.get("articles", 0) >= 3 and page.get("slug_links", 0) >= ARTICLE_LINKS)
    if not in_domain and not in_head and feed_real and not dominant_site(page) and not ad["mb"] and not subject:
        return "article", f"feed before density: date={page.get('date_links', 0)} slug={page.get('slug_links', 0)}"
    if dominant and dens >= MONO_DENSITY and gambling and page.get("mb_heads", 0) >= 2 and ext_mb <= mb_text / 2:
        return "mono", f"density={dens} heads={page.get('mb_heads', 0)}"
    if not in_domain and not in_head and (page.get("date_links", 0) >= 5 or (page.get("articles", 0) >= 3 and page.get("slug_links", 0) >= ARTICLE_LINKS)) and \
            not dominant_site(page) and not (page.get("mb_meta") and dens >= MONO_DENSITY):
        return "article", f"dated feed date={page.get('date_links', 0)} articles={page.get('articles', 0)}"
    # The brand in the domain name makes the site a brand user whatever it shows (owner, 30.09):
    # gambling content of others -> bait; content with no gambling at all -> brand discredit.
    if in_domain and not page.get("moved") and gambling and foreign:
        return "bait", f"mostbet_in_domain content={other_name or 'gambling'}:{other_n} mostbet={mb_text}"
    if in_domain and not page.get("moved") and not ad["mb"] and (page.get("from_meta") or (gambling and not mb_text)):
        return "bait", "mostbet_in_domain, page never names Mostbet"  # PWA of others, slots apps (owner, 30.09)
    if in_domain and not page.get("moved") and gambling:
        return "mono", f"name_in_domain, no other brand density={dens}"
    if in_domain and not page.get("moved") and not gambling and page.get("text_len", 0) >= 1500:
        return "discredit", f"mostbet_in_domain non_gambling content text={page.get('text_len', 0)}"
    if gambling and not mb_text and not ext_mb and not int_mb and not ad["mb"] and not in_head:
        return "other_gambling", "mostbet_only_in_meta"
    if gambling:
        return "multibrand", f"top_other={other_name}:{other_n} mostbet={mb_text} density={dens}"
    if not in_domain and (int_mb or posts):
        return "article", f"non_gambling int={int_mb} articles={page.get('articles', 0)}"
    if in_domain and not mb_text and page.get("text_len", 0) >= 1500:
        return "discredit", "mostbet_only_in_domain"
    if in_domain and not mb_text:
        return "stub", f"mostbet_only_in_domain, little text={page.get('text_len', 0)}"
    return "unclear", f"density={dens} top_other={other_name}:{other_n} gambling={gpk}"


def redirect_of(domain: str, g: dict, a: dict, hrec: dict):
    """The home page itself sends the visitor to a ref: (category, why) or None."""
    final = g.get("final_url") or a.get("final_url") or ""
    host = (urlsplit(final).hostname or "").lower()
    if hrec.get("group") == "home_redirect" or (a.get("method") or "").startswith("home_redirect"):
        return "redirect_ref", "home redirects to a Mostbet ref"
    if g.get("method") == "home_redirect" and not host:
        # The home page redirected straight into a ref chain; the scan kept only where it landed.
        if g.get("mostbet_pids"):
            return "redirect_ref", f"home redirects to a Mostbet ref, pid {g['mostbet_pids']}"
        if g.get("other_brands"):
            return "redirect_other", f"home redirects to {g['other_brands']}"
    if not host or lb_same(host, domain):
        return None
    query = urlsplit(final).query or ""
    # A plain move to another content site is not a ref: the site is judged by what it shows (tag moved).
    if not (lb.AFF_PARAMS.search(query) or lb.TRACK_PARAMS.search(query) or aff_ref(final, domain)):
        return None
    if g.get("mostbet_pids") or g.get("group") == "1_mostbet_only" or "pid=" in query and MB.search(g.get("title") or ""):
        return "redirect_ref", f"home redirects to {host} (Mostbet)"
    if not (g.get("other_brands") or _feat.GAMBLING.search(g.get("title") or "") or GAME_WORDS.search(g.get("title") or "")
            or looks_tracker(final)):
        return None  # moved to a site that is not about gambling: judged by its content
    return "redirect_other", f"home redirects to {host} ({g.get('other_brands') or (g.get('title') or '')[:40]})"


def js_redirect_of(domain: str, page: dict):
    target = page.get("js_redirect") or ""
    host = lb_base(target)
    if not host or lb_same(host, domain):
        return None
    if aff_ref(target, domain) or MB.search(host):
        return "redirect_ref", f"script sends the home page to {host} (Mostbet)"
    if not (looks_tracker(target) or _feat.GAMBLING.search(host) or GAME_WORDS.search(host)):
        return None
    return "redirect_other", f"script sends the home page to {host}"


def dominant_site(page: dict) -> bool:
    """Mostbet is the site's subject: most of its headings name it."""
    return page.get("heads", 0) > 0 and page.get("mb_heads", 0) >= max(3, page.get("heads", 0) // 2)


def mb_page_evidence(domain: str, html_dir: Path, dests: list) -> list:
    """Pages about Mostbet (Mostbet in their title or h1) that advertise other brands: [(page url, [brands])].

    Pages come from the deep and mbpages passes (<domain>.{deep,mbpages}-res.json.gz); each link on such a page is
    judged by what the pass found behind it — a partner code or tracker to another brand, or a link to an operator."""
    by_url = {}
    for x in dests:
        by_url.setdefault(x.get("url") or "", []).append(x)
    out = []
    for tag in ("mbpages", "deep"):
        p = html_dir / f"{domain}.{tag}-res.json.gz"
        if not p.exists():
            continue
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                res = json.load(f)
        except (OSError, ValueError):
            continue
        for r in res:
            if r.get("type") != "page" or not r.get("body"):
                continue
            tree = lb.HTMLParser(r["body"])
            title = (tree.css_first("title").text() if tree.css_first("title") else "") + " " + \
                " ".join(n.text(deep=True) for n in tree.css("h1")[:2])
            # About Mostbet: named in the title or h1, and no other brand named there (a rating "Mostbet, Pin-Up,
            # 1xbet" is a multibrand page, not an article about Mostbet).
            if not MB.search(title) or any(rx.search(title) for _, rx in lb.BRAND_RES):
                continue
            brands = set()
            for a_ in tree.css("a[href],[data-href],[data-url],[data-link],[data-go]"):
                raw = next((a_.attributes.get(k) for k in ("href", "data-href", "data-url", "data-link", "data-go")
                            if a_.attributes.get(k)), "")
                try:
                    u = urljoin(r["url"], raw.strip())
                except ValueError:
                    continue
                host = lb_base(u)
                own = lb_same(host, lb_base(r["url"])) or lb_same(host, domain)
                if not host or own and not by_url.get(u):
                    continue
                if _feat.hidden(a_) or re.search(r"color\s*:\s*transparent", a_.attributes.get("style") or "", re.I):
                    continue  # hidden SEO links to satellites are not ads on the page
                for x in by_url.get(u, []):
                    final = x.get("final_url") or ""
                    if x.get("kind") in ("other_gambling", "gambling_site") and (is_coded(x) or via_tracker(x)):
                        brands.add(x.get("brand") if x.get("brand") not in ("", "?") else lb_base(final))
                    elif x.get("kind") == "other_gambling" and lb.brand_of_host(lb_base(final)) not in ("", "Mostbet"):
                        brands.add(x.get("brand") or lb.brand_of_host(lb_base(final)))
                q = urlsplit(u).query or ""
                if not own and lb.brand_of_host(host) not in ("", "Mostbet") and not NOT_CASINO_HOST.search(host):
                    brands.add(lb.brand_of_host(host))

            brands.discard("")
            if brands:
                out.append((r["url"], sorted(brands)))
    return out


def mono_sub(ad: dict, page: dict, g: dict = None) -> str:
    if ad["other"]:
        return "mono_mixed" if ad["mb"] else "mono_other"
    g = g or {}
    clicked = g.get("mode") in ("browser", "browser+rest") and g.get("group") in ("2_no_ads", "8_no_mention") \
        and not g.get("incomplete")
    if clicked and not ad["mb"] and not ad["plain"]:
        return "mono_no_ads"  # the browser clicked every button and followed every link: nothing is advertised
    # Buttons lead somewhere (own gate, external tracker, partner link of an unknown brand) and nobody
    # followed them to the end: the advertiser is unknown, not absent.
    if not ad["mb"] and (page.get("gates") or page.get("trackers") or ad["unverified"] or page.get("placeholder_links", 0) >= 2):
        return "mono_unresolved"
    if ad["plain"]:
        return "mono_xlink"
    return "mono_mostbet" if ad["mb"] else "mono_no_ads"


def main(d: str):
    d = Path(d)
    bs_dir, af_dir = d / "brand-scan", d / "affiliate-scan"
    groups = load_csv(bs_dir / "groups.csv")
    aff, notaff = load_csv(af_dir / "affiliate.csv"), load_csv(af_dir / "not-affiliate.csv")
    feats = load_features(bs_dir / "site-features.jsonl.gz")
    aff_checks = {}  # follow chains of the affiliate-scan pass: where a site's gates really lead
    with gzip.open(af_dir / "scan.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("checks"):
                aff_checks[r["domain"]] = r["checks"]
    dest_by, trackers_to_other, mostbet_titled = {}, set(), set()
    with open(bs_dir / "destinations.csv", newline="", encoding="utf-8") as f:
        for x in csv.DictReader(f):
            dest_by.setdefault(x["domain"], []).append(x)
            if MB.search(x.get("title") or ""):
                mostbet_titled.add(lb_base(x.get("final_url") or ""))
            if x.get("kind") == "other_gambling" and x.get("brand") not in ("", "?"):
                trackers_to_other |= {lb_base(u) for u in hop_urls(x) + [x.get("url") or ""] if lb_base(u)}
    not_gates = set()
    for log_name, via in (("gates-scan.jsonl.gz", "gates"), ("deep-scan.jsonl.gz", "deep"), ("mbpages-scan.jsonl.gz", "mbpages")):
      gates_log = bs_dir / log_name  # --mode gates: button addresses; --mode deep: inner pages and own scripts
      if gates_log.exists():
        with gzip.open(gates_log, "rt", encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                for x in r.get("destinations") or []:
                    if x.get("kind") == "internal":
                        not_gates.add(x.get("url") or "")  # the "gate" is an ordinary page of the site
                    row = {k: str(x.get(k, "")) for k in ("url", "final_url", "kind", "brand", "evidence", "pid", "title")}
                    row.update(domain=r["domain"], via=via, ad_route=str(x.get("ad_route", "")),
                               hops=" → ".join(f"{h[0]} {h[1]}" for h in x.get("hops") or [] if len(h) == 2))
                    dest_by.setdefault(r["domain"], []).append(row)
    home = {}
    with gzip.open(bs_dir / "home-dump.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            home[r["domain"]] = r
    our = set()
    if REGISTRY.exists():
        our = {ref_key(e["destination_url"]) for e in json.loads(REGISTRY.read_text())["entries"]}
    ours_domains = {x.strip().lower() for x in (d.parent / "our-domains.txt").read_text().split() if x.strip()}

    # Sites hidden from a plain visitor, scanned again as a visitor from Google search and as Googlebot
    # (brand-scan.py --as, brand-scan-report.py <dir> <as>): judged by what those visitors get.
    variants = {}
    for v in sorted(set(VISITORS) | set(EXTRA_VISITORS)):
        vg = load_csv(bs_dir / f"groups-{v}.csv")
        vd = {}
        if (bs_dir / f"destinations-{v}.csv").exists():
            with open(bs_dir / f"destinations-{v}.csv", newline="", encoding="utf-8") as f:
                for x in csv.DictReader(f):
                    vd.setdefault(x["domain"], []).append(x)
        variants[v] = (vg, vd)

    rows = []
    for domain in sorted(set(groups) | set(aff) | set(notaff)):
        if domain.lower().removeprefix("www.") in ours_domains:
            continue
        g, a, na = groups.get(domain, {}), aff.get(domain, {}), notaff.get(domain, {})
        fr = feats.get(domain, {})
        cloaked, dests_here = "", dest_by.get(domain, [])
        if g.get("group") in HIDDEN_GROUPS:
            best = max(((OPEN_RANK.get(variants[v][0].get(domain, {}).get("group"), 0), v) for v in VISITORS), default=(0, ""))
            if best[0]:
                cloaked = best[1]
                g = variants[cloaked][0][domain]
                dests_here = variants[cloaked][1].get(domain, [])
                fr = {"platform": fr.get("platform"), "sources": fr.get("sources"), "http": fr.get(f"http-{cloaked}") or {}}
        page = with_meta(from_scan(merged_page(fr), g, a, na))
        if page.get("gates"):
            page["gates"] = [x for x in page["gates"] if (x.get("url") if isinstance(x, dict) else x) not in not_gates]
        args = (our,)
        extra = {} if cloaked else {v: variants[v][1].get(domain, []) for v in EXTRA_VISITORS}
        ad = ads(domain, g, a, na, page, our, dests_here + [x for xs in extra.values() for x in xs], trackers_to_other,
                 aff_checks.get(domain, []), mostbet_titled)
        extra_tags = []
        if extra and any(extra.values()):
            base_other = set(ads(domain, g, a, na, page, our, dests_here, trackers_to_other, aff_checks.get(domain, []),
                                 mostbet_titled)["other"])
            for v, tag in EXTRA_VISITORS.items():
                if extra[v] and set(ads(domain, g, a, na, page, our, extra[v], trackers_to_other, (), mostbet_titled)["other"]) - base_other:
                    extra_tags.append(tag)  # foreign ads seen only by this visitor
        tags = []
        tags += extra_tags
        if cloaked:
            tags.append(f"cloaked:{cloaked}")
        if page.get("pwa"):
            tags.append("pwa")
        if fr.get("platform"):
            tags.append("platform")
        if g.get("ads_differ") == "True":
            tags.append("rotating_ads")
        if page.get("referrer_js"):
            tags.append("search_referrer_js")
        if page.get("apk"):
            tags.append("apk")
        if ad["ours"]:
            tags.append("our_ref")
        if MB.search(domain):
            tags.append("brand_in_domain")
        final_host = (page.get("host") or urlsplit(g.get("final_url") or a.get("final_url") or na.get("final_url") or "").hostname or "").lower()
        if final_host and not lb_same(final_host, domain):
            tags.append("moved")
        if ad["unverified"]:
            tags.append("ads_unverified")
        if page:
            page["moved"] = "moved" in tags
        if not page:
            tags.append("no_html")

        grp = g.get("group", "")
        hrec = (home.get(domain) or {}).get("result") or {}
        why = ""
        redirect = redirect_of(domain, g, a, hrec) or js_redirect_of(domain, page)
        if redirect:
            cat, why = redirect
        elif grp == "5_dead" and g.get("reason") != "parked" and \
                any(x in (g.get("group_history") or "") for x in ("5_not_shown", "6_cf_check", "_only", "no_ads", "mixed", "no_mention", "unresolved")):
            cat, why = "not_shown", f"answered in an earlier scan: {g.get('group_history')}"
        elif grp == "5_dead":
            cat, why = ("parked" if g.get("reason") == "parked" else "dead"), g.get("reason", "")
        elif grp in ("5_not_shown", "6_cf_check") and STUB_MORE.search(f'{g.get("title", "")} {g.get("text_sample", "")}'):
            cat, why = "stub", f"hosting placeholder behind {g.get('reason', '')}"
        elif grp in ("5_not_shown", "6_cf_check"):
            cat, why = "not_shown", g.get("reason", "")
        elif page and CHALLENGE.search(page.get("title") or "") and not page.get("from_scan"):
            cat, why = "not_shown", f"bot wall: {page.get('title', '')[:40]}"
        elif not fr and hrec.get("group") == "no_answer":
            cat, why = "dead", f"home dump: {((home.get(domain) or {}).get('home') or {}).get('error', '')}"
        elif not page:
            cat, why = ("dead" if hrec.get("group") == "no_answer" else "stub"), f"no page: {hrec.get('group', '')}"
        elif (page.get("parked") or PARKED_MORE.search(f'{page.get("title", "")} {page.get("text_sample", "")} {page.get("final_url", "")}')) \
                and not ad["other"] and page.get("text_len", 0) < 3000:
            cat, why = "parked", "parking markup"
        elif (page.get("mostbet_shell") or (page.get("mostbet_assets") and MIRROR_TITLE.search(page.get("title") or ""))) and \
                (page.get("mb_text", 0) <= 5 or page.get("text_len", 0) < MIRROR_TEXT):
            cat, why = "mirror", "mostbet_shell" if page.get("mostbet_shell") else "assets_and_title"
        elif STUB_MORE.search(f'{page.get("title", "")} {page.get("text_sample", "")[:300]} {page.get("final_url", "")}') and \
                page.get("text_len", 0) < 1500 and not ad["mb"] and not ad["other"]:
            cat, why = "stub", "placeholder text"  # hosting placeholders print the domain name, Mostbet included
        elif page.get("text_len", 0) < STUB_TEXT and not page.get("mb_text") and not ad["mb"] and not ad["other"]:
            cat, why = "stub", f"text_len={page.get('text_len', 0)}"
        else:
            cat, why = site_type(domain, page, ad)
            if cat == "mono":
                cat = mono_sub(ad, page, g)
        evidence = mb_page_evidence(domain, bs_dir / "html", dests_here) if cat not in SETTLED_STRIKES else []
        if evidence:
            if cat.startswith("mono_"):
                cat = "mono_mixed" if ad["mb"] else "mono_other"
            elif cat not in ("dead", "parked", "not_shown", "stub", "mirror"):
                cat = "mb_page_other"
            why = f"{why} | Mostbet page advertises others: {evidence[0][0]} ({', '.join(evidence[0][1][:4])})"
            ad["other"] = sorted(set(ad["other"]) | {b_ for _, bs in evidence for b_ in bs})
        ob = page.get("other_brands") or {}
        rows.append({
            "domain": domain, "category": cat, "tags": " ".join(tags), "why": why,
            "source": "brand-scan" if g else "affiliate-scan",
            "mostbet_ads": ad["mb"], "other_ads": " | ".join(ad["other"]), "plain_gambling_links": " ".join(ad["plain"][:10]),
            "ad_links": ad_links_json(ad["links"]),
            "mb_text": page.get("mb_text", ""), "mb_per_1k": page.get("mb_per_1k", ""), "mb_anchor": page.get("mb_anchor", ""),
            "mb_hidden_links": page.get("mb_hidden_links", ""), "text_len": page.get("text_len", ""),
            "gambling_per_1k": page.get("gambling_per_1k", ""),
            "other_brands_text": " ".join(f"{k}:{v}" for k, v in sorted(ob.items(), key=lambda x: -x[1])[:6]),
            "feed_links": max(page.get("slug_links", 0), page.get("date_links", 0)) if page else "",
            "title": page.get("title", "") or g.get("title", "") or a.get("title", "") or na.get("title", ""),
            "h1": page.get("h1", ""), "lang": page.get("lang", ""), "final_url": page.get("final_url", "") or g.get("final_url", ""),
            "scan_group": grp or ("affiliate" if a else "not-affiliate"),
            "html": " ".join(fr.get("sources") or []),
        })
    # Sites with no trace of the brand at all (not in the domain, the page, the links or the ads):
    # Corsearch collected them by mistake; the owner sends this list to Corsearch as a whitelist.
    fp = [r for r in rows if r["category"] in ("unrelated", "other_gambling") and "brand_in_domain" not in r["tags"]
          and not int(r["mb_text"] or 0) and not int(r["mb_anchor"] or 0) and r["mostbet_ads"] is False]
    with open(d / "brand-scan" / "corsearch-false-positives.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["domain", "category", "title", "final_url"])
        w.writeheader()
        w.writerows({k: r[k] for k in ("domain", "category", "title", "final_url")} for r in fp)
    print("corsearch false positives", len(fp))
    out = d / "brand-scan" / "classified.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("sites", len(rows))
    for k, v in Counter(r["category"] for r in rows).most_common():
        print(f"  {k:15} {v}")
    print("tags:", Counter(t for r in rows for t in r["tags"].split()).most_common())


def ad_links_json(links: list) -> str:
    """The links that decided, foreign ads first, one per name, at most 6; our own refs never printed."""
    seen, out = set(), []
    for kind in ("other", "mb", "plain"):
        for k, name, u, f in links:
            if k == kind and (k, name) not in seen and u:
                seen.add((k, name))
                out.append([k, name, u, f if f != u else ""])
    return json.dumps(out[:6], ensure_ascii=False) if out else ""


def lb_same(a: str, b: str) -> bool:
    a, b = a.lower().removeprefix("www."), b.lower().removeprefix("www.")
    return a == b or a.endswith("." + b) or b.endswith("." + a)


if __name__ == "__main__":
    main(sys.argv[1])
