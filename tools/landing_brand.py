"""Identify the gambling brand behind a landing page and assign a site to a brand-protection group.

Shared by the browser scan (tools/brand-scan-browser.py) and any later HTTP pass, so that both
classify destinations the same way.

A destination is judged by its final page content, not by the tracker domain: Mostbet refs land on
throwaway mirrors (mzkybumb.com, ihlishmb.com, ...), and other operators hide behind *.top/*.buzz
trackers. Mostbet mirrors share one frontend, only the language pack differs, so its assets are
the strongest marker.
"""
import re
from urllib.parse import parse_qs, urlsplit

from selectolax.parser import HTMLParser

# Rendered mirrors load assets from cdn-global-mst.com; the raw HTML of the old shell carries the
# partner hreflang block with x-default on mostbett.bet and the x011bt.com beacon.
MOSTBET_STRONG = re.compile(
    r"cdn-global-mst\.com|mostbet-head-web-upload|x011bt\.com/gif|"
    r"href=\"https://mostbett\.bet/\"\s+hreflang=\"x-default\"", re.I)
MOSTBET_NAME = re.compile(r"most\s?bet|мостбет", re.I)
# Tracker and affiliate parameters: a link carrying them is an ad, not a plain cross-link.
AFF_PARAMS = re.compile(
    r"(^|&)(tag|btag|stag|qtag|pid|p|promo|promocode|ref|aff|affid|aff_id|affiliate|sub1|subid|sub_id|"
    r"click_id|clickid|clid|partner|serial|creative_id|anid|cid|s1|lp|offer|bonus_code)=", re.I)

# Matched only against "brand fields" of the landing (title, og/app names, icon URLs, host),
# never against the whole body: casino lobbies list game providers and rival names in text.
BRANDS = [
    ("1xBet", r"1\s?x\s?bet|1хбет|1xbet"), ("1win", r"\b1\s?win\b|1вин|1wzpdo|one-vv\d"),
    ("Melbet", r"melbet|мелбет"), ("Pin-Up", r"pin[\s-]?up|пин[\s-]?ап"), ("Vavada", r"vavada|вавада"),
    ("Betwinner", r"betwinner"), ("22Bet", r"\b22\s?bet"), ("Parimatch", r"pari\s?match|париматч"),
    ("Linebet", r"linebet"), ("Megapari", r"megapari"), ("BetAndYou", r"betandyou"),
    ("888Starz", r"888\s?starz"), ("Leon", r"leon\s?bet|leon\.(ru|bet)"), ("Fonbet", r"fonbet|фонбет"),
    ("Winline", r"winline|винлайн"), ("GGBet", r"gg\.?bet"), ("Stake", r"\bstake\.(com|bet|us)|\bstake casino"),
    ("BC.Game", r"bc\.game"), ("20Bet", r"\b20\s?bet"), ("4rabet", r"4ra\s?bet"), ("Dafabet", r"dafabet"),
    ("Betway", r"betway"), ("bet365", r"bet\s?365"), ("Pokerdom", r"pokerdom|покердом"),
    ("Joycasino", r"joy\s?casino|джойказино"), ("Vulkan", r"vulkan|вулкан"), ("Azino777", r"azino|азино"),
    ("Selector", r"selector|селектор"), ("Gama", r"gama\s?casino|гама\s?казино"), ("Riobet", r"riobet"),
    ("Kometa", r"kometa|комета\s?казино"), ("Irwin", r"irwin"), ("R7", r"\br7\s?(casino|казино)"),
    ("Daddy", r"daddy\s?casino"), ("Monro", r"monro"), ("Kent", r"kent\s?casino"), ("Starda", r"starda"),
    ("Legzo", r"legzo"), ("Jet", r"jet\s?casino|джет\s?казино"), ("Fresh", r"fresh\s?casino"),
    ("Sol", r"sol\s?casino"), ("Izzi", r"izzi\s?casino"), ("Drip", r"drip\s?casino"), ("Volna", r"volna"),
    ("Rox", r"rox\s?casino"), ("Lex", r"lex\s?casino"), ("Casino-X", r"casino[\s-]x\b|казино[\s-]икс"),
    ("NormCasino", r"norm\s?casino"), ("ON-X", r"\bon-x\b|on-x\d*\.casino|казино on-x"),
    ("Spinbetter", r"spinbetter"), ("Mr Bit", r"mr\.?\s?bit"), ("Play Fortuna", r"play\s?fortuna"),
    ("Eldorado", r"eldorado"), ("Bizzo", r"bizzo"), ("Glory", r"glory\s?casino"), ("Crickex", r"crickex"),
    ("Baji", r"\bbaji"), ("Jeetbuzz", r"jeetbuzz"), ("Krikya", r"krikya"), ("Marvelbet", r"marvelbet"),
    ("Betvisa", r"betvisa"), ("Six6s", r"six6s"), ("Betano", r"betano"), ("Blaze", r"\bblaze\.(com|bet)"),
    ("Betfury", r"betfury"), ("Rollbit", r"rollbit"), ("Roobet", r"roobet"), ("Pinnacle", r"pinnacle"),
    ("Olimpbet", r"olimp\s?bet|олимпбет"), ("Betboom", r"betboom|бетбум"),
    ("Liga Stavok", r"liga\s?stavok|лига\s?ставок"), ("Marathonbet", r"marathon\s?bet|марафонбет"),
    ("Betcity", r"betcity|бетсити"), ("Superbet", r"superbet"), ("Fortuna", r"efortuna|ifortuna"),
    ("Tipsport", r"tipsport"), ("Unibet", r"unibet"), ("Bwin", r"\bbwin"), ("Betsson", r"betsson"),
    ("Sportybet", r"sportybet"), ("Bet9ja", r"bet9ja"), ("Betika", r"betika"), ("1Go", r"1go\s?casino"),
    ("Gizbo", r"gizbo"), ("Flagman", r"flagman"), ("Cat Casino", r"cat\s?casino|кэт\s?казино"),
    ("Dragon Money", r"dragon\s?money|драгон\s?мани"), ("Up-X", r"\bup-?x\b"), ("Lev", r"\blev\s?casino"),
    ("Banda", r"banda\s?casino"), ("Pinco", r"pinco"), ("Vodka", r"vodka\s?(casino|bet)|водка\s?казино"),
    ("Beef", r"beef\s?casino"), ("Mellstroy", r"mellstroy"), ("Arkada", r"arkada"), ("Booi", r"\bbooi"),
    ("7K", r"\b7k\s?casino|7k\.casino"), ("Brillx", r"brillx"), ("Betandreas", r"betandreas"),
    ("Mostplay", r"mostplay"), ("Jugabet", r"jugabet"), ("Betsul", r"betsul"), ("Estrela", r"estrela\s?bet"),
    ("Galera", r"galera\.?bet"), ("KTO", r"\bkto\.(com|bet)"), ("Bet7k", r"bet7k"), ("Betnacional", r"betnacional"),
    ("Sportingbet", r"sportingbet"), ("Rivalo", r"rivalo"), ("Codere", r"codere"), ("Caliente", r"caliente"),
    ("Admiral", r"admiral"), ("Mozzart", r"mozzart"), ("Meridian", r"meridian\s?bet|meridianbet"),
    ("Maxbet", r"maxbet"), ("Soccerbet", r"soccer\s?bet"), ("Balkan Bet", r"balkan\s?bet"),
    ("Betsafe", r"betsafe"), ("LeoVegas", r"leovegas"), ("Casumo", r"casumo"), ("Wazamba", r"wazamba"),
    ("Nine Casino", r"nine\s?casino"), ("Rabona", r"rabona"), ("Vulkan Vegas", r"vulkan\s?vegas"),
    ("Ice Casino", r"ice\s?casino"), ("Hellspin", r"hell\s?spin"), ("Nomini", r"nomini"),
    ("Slottica", r"slottica"), ("Betmaster", r"betmaster"), ("Sultanbet", r"sultanbet"),
    ("Tempobet", r"tempobet"), ("Bets10", r"bets10"), ("Jojobet", r"jojobet"), ("Marsbahis", r"marsbahis"),
    ("Casibom", r"casibom"), ("Matbet", r"matbet"), ("Grandpashabet", r"grandpasha"),
    ("Olimp KZ", r"olimp\.(kz|bet)"), ("Parik24", r"parik24"), ("Favbet", r"favbet"), ("Betera", r"betera"),
    ("Topbet", r"topbet"), ("Gizbo", r"gizbo"), ("Cactus", r"kaktuz|cactus\s?casino"),
    ("Lucky Bird", r"lucky\s?bird"), ("Joker", r"joker\s?(casino|win)"), ("Riobet", r"riobet"),
    ("Aurora", r"aurora\s?casino"), ("Bollywood", r"bollywood\s?casino"), ("Fairspin", r"fairspin"),
    ("Mostwin", r"mostwin"), ("Megaslot", r"megaslot"), ("Melbet", r"mel-?bet"),
]
BRAND_RES = [(name, re.compile(rx, re.I)) for name, rx in BRANDS]

GAMBLING = re.compile(
    r"casino|kazino|казино|kasyno|kasino|cassino|bet\b|betting|ставк|stavk|bahis|apuesta|aposta|slot|слот|"
    r"poker|покер|jackpot|джекпот|bukmeker|букмекер|sportsbook|freespin|фриспин|depozit|депозит|deposit|"
    r"bonus|бонус|рулетк|roulette|aviator|lucky\s?jet", re.I)
PARKED = re.compile(
    r"domain (name )?(is |may be )?for sale|buy this domain|this domain is parked|parkingcrew|sedoparking|"
    r"bodis\.com|dan\.com|afternic|hugedomains|domain has expired|домен продается|домен припаркован|"
    r"продажа домена|registrar-servers|this domain has been registered", re.I)
GEO_BLOCK = re.compile(
    r"not available in your (country|region|location)|unavailable in your (country|region)|"
    r"restricted (country|region|territory|jurisdiction)|access (is )?(denied|restricted) (from|in) your|"
    r"недоступ\w* в вашей (стране|регионе)|your country|your region|\b451\b", re.I)


def brand_fields(title: str, html: str, final_url: str) -> str:
    """Concatenate the parts of a page that name the operator: title, og/app names, icon URLs, host."""
    parts = [title or "", urlsplit(final_url).hostname or ""]
    try:
        tree = HTMLParser(html or "")
    except Exception:  # noqa: BLE001 — broken markup still has a title and a host
        tree = None
    if tree is not None:
        for n in tree.css("meta[property],meta[name]"):
            key = (n.attributes.get("property") or n.attributes.get("name") or "").lower()
            if key in ("og:site_name", "og:title", "application-name", "apple-mobile-web-app-title",
                       "twitter:site", "twitter:title"):
                parts.append(n.attributes.get("content") or "")
        for n in tree.css("link[rel]"):
            if "icon" in (n.attributes.get("rel") or "").lower() or \
                    (n.attributes.get("rel") or "").lower() == "manifest":
                parts.append(n.attributes.get("href") or "")
    return " | ".join(p for p in parts if p)


def raw_brand_name(title: str, html: str) -> str:
    """Best-effort operator name for pages no dictionary entry matched."""
    try:
        tree = HTMLParser(html or "")
        for key in ("og:site_name", "application-name", "apple-mobile-web-app-title"):
            n = tree.css_first(f'meta[property="{key}"]') or tree.css_first(f'meta[name="{key}"]')
            if n and (n.attributes.get("content") or "").strip():
                return n.attributes["content"].strip()[:60]
    except Exception:  # noqa: BLE001
        pass
    t = re.split(r"\s[|\-–—:]\s", title or "")
    return (t[0] if t else "").strip()[:60]


def partner_id(final_url: str) -> str:
    """Mostbet mirrors carry the affiliate account in ?pid= of the landing URL."""
    try:
        q = parse_qs(urlsplit(final_url).query)
    except ValueError:
        return ""
    return (q.get("pid") or [""])[0]


def brand_of_host(host: str) -> str:
    """Brand named directly in a link host (1xbet.com, mostbet-xx.com); empty if none."""
    host = (host or "").lower()
    if MOSTBET_NAME.search(host):
        return "Mostbet"
    for name, rx in BRAND_RES:
        if rx.search(host):
            return name
    return ""


def identify(final_url: str, title: str, html: str, text: str = "") -> dict:
    """Classify a landing page.

    Returns {"kind": mostbet | other_gambling | non_gambling | unknown, "brand", "evidence", "pid"}.
    Mostbet is "strong" when its CDN assets are present and "weak" when only the name matches,
    which also happens on intermediate review pages that are not the operator itself.
    """
    html = html or ""
    fields = brand_fields(title, html, final_url)
    if MOSTBET_STRONG.search(html):
        return {"kind": "mostbet", "brand": "Mostbet", "evidence": "mostbet_assets",
                "pid": partner_id(final_url)}
    sample = f"{title} {text[:3000]}"
    gambling = bool(GAMBLING.search(sample))
    host = urlsplit(final_url).hostname or ""
    for name, rx in BRAND_RES:
        m = rx.search(fields)
        # Several brand names are ordinary words (Admiral, Aurora, Joker): require gambling
        # context or the name in the host itself.
        if m and (gambling or rx.search(host)):
            return {"kind": "other_gambling", "brand": name, "evidence": f"fields:{m.group(0)}", "pid": ""}
    if MOSTBET_NAME.search(fields):
        return {"kind": "mostbet", "brand": "Mostbet", "evidence": "name_only_weak",
                "pid": partner_id(final_url)}
    if gambling:
        return {"kind": "other_gambling", "brand": raw_brand_name(title, html) or "?",
                "evidence": "gambling_words_unrecognized", "pid": ""}
    if len(text) < 100 and len(html) < 5000:
        return {"kind": "unknown", "brand": "", "evidence": "empty_page", "pid": ""}
    return {"kind": "non_gambling", "brand": raw_brand_name(title, html), "evidence": "no_gambling_words", "pid": ""}


def is_ad_route(start_url: str, final_url: str, redirected: bool) -> bool:
    """A destination reached through a tracker redirect or with affiliate parameters is an ad."""
    try:
        return redirected or bool(AFF_PARAMS.search(urlsplit(start_url).query or "")) or \
            bool(AFF_PARAMS.search(urlsplit(final_url).query or ""))
    except ValueError:
        return redirected


def classify_destination(start_url: str, final_url: str, title: str, html: str, text: str,
                         redirected: bool) -> dict:
    """identify() plus the ad-or-link decision.

    kind: mostbet | other_gambling — counted as advertising;
          brand_site — another site using the Mostbet name (link networks cross-link each other);
          gambling_site — unrecognized gambling page reached by a plain link;
          non_gambling | unknown.
    """
    ident = identify(final_url, title, html, text)
    ad = is_ad_route(start_url, final_url, redirected)
    ident["ad_route"] = ad
    fields = brand_fields(title, html, final_url)
    kind, ev = ident["kind"], ident["evidence"]
    if kind == "mostbet" and ev == "name_only_weak" and not ad:
        return {**ident, "kind": "brand_site"}
    if kind == "other_gambling":
        if MOSTBET_NAME.search(fields) and not ad:
            return {**ident, "kind": "brand_site"}
        if ev == "gambling_words_unrecognized" and not ad:
            return {**ident, "kind": "gambling_site"}
    return ident


def site_group(destinations: list, mostbet_mentions: int) -> dict:
    """Assign an opened site to a group from the brands of its advertised destinations.

    Groups: mostbet_only (1), no_ads (2), other_only (3), mixed (4). Group 5 (dead) is decided
    before this, when the site does not open at all. Links to other Mostbet-named sites and to
    unrecognized gambling pages do not count as ads; they are listed for review.
    """
    mb = [d for d in destinations if d.get("kind") == "mostbet"]
    other = [d for d in destinations if d.get("kind") == "other_gambling"]
    brands = sorted({d["brand"] for d in other if d.get("brand")})
    pids = sorted({d["pid"] for d in mb if d.get("pid")})
    weak = bool(mb) and all(d.get("evidence") == "name_only_weak" for d in mb)
    base = {"other_brands": brands, "mostbet_pids": pids, "mostbet_weak_only": weak,
            "no_brand_mention": mostbet_mentions == 0,
            "brand_site_links": sorted({urlsplit(d.get("final_url") or "").hostname or ""
                                        for d in destinations if d.get("kind") == "brand_site"})[:30],
            "gambling_site_links": sorted({urlsplit(d.get("final_url") or "").hostname or ""
                                           for d in destinations if d.get("kind") == "gambling_site"})[:30]}
    if mb and other:
        return {"group": "4_mixed", **base}
    if mb:
        return {"group": "1_mostbet_only", **base}
    if other:
        return {"group": "3_other_only", **base}
    return {"group": "2_no_ads", **base}
