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
  mono_no_ads    Mostbet monobrand with no affiliate links found
  bait           Mostbet in the domain or title, the page is about another brand or casino
  multibrand     gambling affiliate not about Mostbet: rating of several brands, games, slots
  article        article site or link seller: a feed of posts, Mostbet not its subject
  hacked         unrelated site with Mostbet only in links, often hidden
  other_gambling another operator or its doorway, Mostbet not mentioned
  unrelated      no Mostbet and no gambling
  unclear        Mostbet mentioned, the rules above do not decide
  stub           answers with an empty page: coming soon, suspended, hosting placeholder, bare JS shell
  redirect_ref   the home page itself redirects to a ref, no content
  parked         parking or registrar placeholder
  dead           does not answer
  not_shown      answers, but a bot wall, HTTP error or geo block hides the page
Tags (any number): platform, rotating_ads, search_referrer_js, apk, our_ref, brand_in_domain,
  moved (home redirects to another host), ads_unverified (affiliate links not followed to the end),
  no_html.
"""
import csv
import gzip
import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import landing_brand as lb  # noqa: E402

csv.field_size_limit(sys.maxsize)

MB = re.compile(r"most\s?bet|мостбет|мостбэт", re.I)
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
MIRROR_TITLE = re.compile(r"\bmost\s?bet\.com\b", re.I)  # localized "Betting company MostBet.com – …"


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
    if page and page.get("text_len", 0) >= max(tl, 1) * 0.5:
        return page
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


def ads(domain: str, g: dict, a: dict, na: dict, page: dict, our: set) -> dict:
    """Affiliate traffic of a site: to Mostbet, to other brands (with names), plain links to other
    gambling sites, links not followed to the end, our own refs."""
    mb, other, plain, unverified, ours = False, set(), set(), 0, False
    if g:
        mb = g["group"] in ("1_mostbet_only", "4_mixed") or bool(g.get("ever_mostbet_pids"))
        other |= {x for x in (g.get("other_brands") or "").split(" | ") + (g.get("ever_other_brands") or "").split(" | ") if x}
        plain |= set((g.get("gambling_site_links") or "").split())
        if g.get("incomplete"):
            unverified += 1
    if a:
        mb = True
        if ref_key(a.get("ref_url") or "") in our:
            ours = True
    if na and na.get("gate_other"):
        other.add(f"via {na['gate_other']}")
    for x in page.get("aff_links") or []:
        if ref_key(x["url"]) in our:
            ours = True
            mb = True
        elif x.get("ref_kind") or x.get("brand") == "Mostbet":
            mb = True
        elif x.get("brand"):
            other.add(x["brand"])
        elif not g:
            unverified += 1  # tracker link of an unknown brand, not followed for this site
    return {"mb": mb, "other": sorted(other), "plain": sorted(p for p in plain if p), "unverified": unverified,
            "ours": ours}


def top_other(page: dict):
    ob = page.get("other_brands") or {}
    if not ob:
        return "", 0
    name = max(ob, key=ob.get)
    return name, ob[name]


def site_type(domain: str, page: dict, ad: dict) -> tuple:
    """(category, why) from the page and its ads; statuses are decided before."""
    in_domain = bool(MB.search(domain))
    in_head = bool(page.get("mb_title") or page.get("mb_h1"))
    mb_text, dens = page.get("mb_text", 0), page.get("mb_per_1k", 0.0)
    other_name, other_n = top_other(page)
    gpk = page.get("gambling_per_1k", 0.0)
    head = f'{page.get("title", "")} {page.get("h1", "")}'
    gambling_head = bool(lb.GAMBLING.search(head)) or any(rx.search(head) for _, rx in lb.BRAND_RES[:40])
    gambling = gpk >= GAMBLING_DENSITY or page.get("gambling_words", 0) >= 15 or gambling_head
    feed = max(page.get("slug_links", 0), page.get("date_links", 0)) >= ARTICLE_LINKS or page.get("articles", 0) >= 5
    anchors, hidden_mb = page.get("mb_anchor", 0), page.get("mb_hidden_links", 0)
    dominant = mb_text >= MONO_DOMINANCE * max(other_n, 1) or (mb_text and not other_n)
    other_dominant = other_n >= MONO_DOMINANCE * max(mb_text, 1) and other_n >= 5

    if not (mb_text or anchors or in_domain or in_head or ad["mb"]):
        return ("other_gambling" if gambling or ad["other"] else "unrelated"), "no_mostbet"
    if (in_domain or in_head) and (other_dominant or (gambling and not mb_text and not ad["mb"])):
        return "bait", f"mostbet_in_{'domain' if in_domain else 'title'} content={other_name or 'other'}:{other_n} mostbet={mb_text}"
    if (in_domain or in_head) and dominant and (dens >= MONO_DENSITY / 2 or in_domain or ad["mb"]):
        return "mono", f"name_in_{'domain' if in_domain else 'title'} density={dens}"
    if dominant and dens >= MONO_DENSITY and gambling:
        return "mono", f"density={dens}"
    if not in_domain and not in_head and gpk < HACKED_GAMBLING and not gambling_head and (
            hidden_mb or (anchors and mb_text <= max(anchors, HACKED_MAX_TEXT))):
        return "hacked", f"mostbet_in_links anchors={anchors} hidden={hidden_mb} text={mb_text} gambling={gpk}"
    if gambling:
        return "multibrand", f"top_other={other_name}:{other_n} mostbet={mb_text} density={dens}"
    if feed and not in_domain:
        return "article", f"feed slug={page.get('slug_links', 0)} date={page.get('date_links', 0)} articles={page.get('articles', 0)}"
    if in_domain and not mb_text:
        return "unrelated", "mostbet_only_in_domain"
    return "unclear", f"density={dens} top_other={other_name}:{other_n} gambling={gpk}"


def mono_sub(ad: dict) -> str:
    if ad["other"]:
        return "mono_mixed" if ad["mb"] else "mono_other"
    if ad["plain"]:
        return "mono_xlink"
    return "mono_mostbet" if ad["mb"] else "mono_no_ads"


def main(d: str):
    d = Path(d)
    bs_dir, af_dir = d / "brand-scan", d / "affiliate-scan"
    groups = load_csv(bs_dir / "groups.csv")
    aff, notaff = load_csv(af_dir / "affiliate.csv"), load_csv(af_dir / "not-affiliate.csv")
    feats = load_features(bs_dir / "site-features.jsonl.gz")
    home = {}
    with gzip.open(bs_dir / "home-dump.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            home[r["domain"]] = r
    our = set()
    if REGISTRY.exists():
        our = {ref_key(e["destination_url"]) for e in json.loads(REGISTRY.read_text())["entries"]}
    ours_domains = {x.strip().lower() for x in (d.parent / "our-domains.txt").read_text().split() if x.strip()}

    rows = []
    for domain in sorted(set(groups) | set(aff) | set(notaff)):
        if domain.lower().removeprefix("www.") in ours_domains:
            continue
        g, a, na = groups.get(domain, {}), aff.get(domain, {}), notaff.get(domain, {})
        fr = feats.get(domain, {})
        page = from_scan(merged_page(fr), g, a, na)
        ad = ads(domain, g, a, na, page, our)
        tags = []
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
        if not page:
            tags.append("no_html")

        grp = g.get("group", "")
        hrec = (home.get(domain) or {}).get("result") or {}
        why = ""
        if hrec.get("group") == "home_redirect" or (a.get("method") or "").startswith("home_redirect"):
            cat, why = "redirect_ref", "home redirects to a ref"
        elif grp == "5_dead":
            cat, why = ("parked" if g.get("reason") == "parked" else "dead"), g.get("reason", "")
        elif grp in ("5_not_shown", "6_cf_check"):
            cat, why = "not_shown", g.get("reason", "")
        elif not page:
            cat, why = ("dead" if hrec.get("group") == "no_answer" else "unclear"), f"no page: {hrec.get('group', '')}"
        elif (page.get("mostbet_assets") or MIRROR_TITLE.search(page.get("title") or "")) and \
                (page.get("mb_text", 0) <= 5 or page.get("text_len", 0) < MIRROR_TEXT):
            cat, why = "mirror", "mostbet_assets" if page.get("mostbet_assets") else "mirror_title"
        elif page.get("parked") and not ad["mb"] and not ad["other"]:
            cat, why = "parked", "parking markup"
        elif page.get("text_len", 0) < STUB_TEXT and not page.get("mb_text") and not ad["mb"] and not ad["other"]:
            cat, why = "stub", f"text_len={page.get('text_len', 0)}"
        else:
            cat, why = site_type(domain, page, ad)
            if cat == "mono":
                cat = mono_sub(ad)
        ob = page.get("other_brands") or {}
        rows.append({
            "domain": domain, "category": cat, "tags": " ".join(tags), "why": why,
            "source": "brand-scan" if g else "affiliate-scan",
            "mostbet_ads": ad["mb"], "other_ads": " | ".join(ad["other"]), "plain_gambling_links": " ".join(ad["plain"][:10]),
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
    out = d / "brand-scan" / "classified.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("sites", len(rows))
    for k, v in Counter(r["category"] for r in rows).most_common():
        print(f"  {k:15} {v}")
    print("tags:", Counter(t for r in rows for t in r["tags"].split()).most_common())


def lb_same(a: str, b: str) -> bool:
    a, b = a.lower().removeprefix("www."), b.lower().removeprefix("www.")
    return a == b or a.endswith("." + b) or b.endswith("." + a)


if __name__ == "__main__":
    main(sys.argv[1])
