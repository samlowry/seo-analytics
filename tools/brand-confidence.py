"""Confidence 0-100 for the class of every site in the brand scan.

Run: python3 tools/brand-confidence.py brand-protection/2026-09-28/brand-scan [--sample-round4]

1. Raw score 0..1 per site: how strong the evidence of its class is (the rule that fired, the links that decided),
   minus penalties for missing data (no HTML, links not followed to the end, site moved, visible only to some visitors)
   and for a page near the border of the neighbouring class.
2. Calibration: the raw score is turned into a probability that a checker agrees with the class, fitted per group of
   classes on every checked site (review rounds 1-4, the owner's marks). Platt scaling with a pull towards the raw
   score, plus a shift per class pulled to zero, so a class with few checks keeps the scale of its group.
3. Writes confidence.csv (domain, category, raw, confidence, minus) and calibration.md (bins: claimed vs observed).

--sample-round4 instead writes review/round4/sample.json: 20 sites per class not checked before, spread over the raw
score of the class (sorted by score, cut into 20 parts, one random site from each part).
"""
import collections
import csv
import glob
import gzip
import json
import math
import random
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)
SEED = 20261013
MONO_DENSITY = 1.0  # as in brand-classify.py

FAMILY = {
    **{c: "viol" for c in ("mono_other", "mono_mixed", "mb_page_other", "bait", "redirect_other", "discredit", "mono_hidden")},
    **{c: "mono" for c in ("mono_mostbet", "redirect_ref", "mono_xlink", "mono_unresolved", "mono_no_ads", "mirror")},
    **{c: "other" for c in ("multibrand", "article", "hacked", "other_gambling", "unrelated", "unclear")},
    **{c: "dead" for c in ("not_shown", "stub", "parked", "dead")},
}
VIOL = {c for c, f in FAMILY.items() if f == "viol"}
CONTENT = {c for c, f in FAMILY.items() if f in ("viol", "mono", "other")} - {"redirect_ref", "redirect_other"}

# The owner's marks of round 2 that name a class (review/owner-marks-r2.json): "ok" keeps the class shown then,
# "bad" with a note naming the class. Marks whose note names no class are left out.
OWNER_BAD = {
    "freepressreleasedb.com": {"article"}, "kmostb-top.com": {"mono_mostbet"}, "museumteensummit.org": {"mono_no_ads"},
    "mostbet-casino-play9le.top": {"stub"}, "mostbet-vipapp.com": {"mono_other", "mono_mixed"},
    "mostbett.pe": {"mono_other", "mono_mixed"}, "ramblers.pl": {"mono_other", "mono_mixed"},
    "mostbet.forum": {"bait"}, "mostbet.living": {"bait"}, "mostbet.rest": {"bait"}, "mostbetgame.store": {"bait"},
    "pawabetfixed.com": {"article"},
}


BLOCK_TITLE = re.compile(r"Attention Required|Just a moment|you have been blocked|Access denied", re.I)
MB_TRACKERS, OTHER_TRACKERS = set(), set()  # link hosts seen leading to a Mostbet ref / to another brand


def load_trackers(d: Path):
    """Hosts of links that some site's chain followed to a Mostbet ref (pid, …mb.com) or to another brand (round 4:
    a "via host" counted as a foreign ad is often Mostbet's own tracker)."""
    from urllib.parse import urlsplit
    for name in ("destinations.csv", "destinations-google-mobile.csv", "destinations-mobile.csv", "destinations-googlebot.csv"):
        if not (d / name).exists():
            continue
        with open(d / name, newline="", encoding="utf-8") as f:
            for x in csv.DictReader(f):
                h = (urlsplit(x["url"]).hostname or "").lower()
                if x["kind"] == "mostbet" and (x["pid"] or re.search(r"mb\.com|pid=", x["final_url"])):
                    MB_TRACKERS.add(h)
                elif x["kind"] == "other_gambling":
                    OTHER_TRACKERS.add(h)


def load_rows(d: Path) -> list:
    with open(d / "classified.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(x, default=0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def raw_score(r: dict) -> tuple:
    """(score 0..1, [what lowered it]) for the class the site got."""
    c, w, tags = r["category"], r["why"], set(r["tags"].split())
    links = json.loads(r.get("ad_links") or "[]")
    other_l = [x for x in links if x[0] == "other"]
    mb_l = [x for x in links if x[0] == "mb"]
    dens, mb_n, text_len = num(r["mb_per_1k"]), num(r["mb_text"]), num(r["text_len"])
    minus = []

    def pen(delta, why):
        minus.append(why)
        return delta

    s = 0.7
    if c in ("mono_other", "mono_mixed"):
        named = [x for x in other_l if not x[1].startswith("via ") and "." not in x[1]]
        if named and any(x[3] for x in named):
            s = 0.92
        elif named:
            s = 0.85
        elif other_l:
            s = 0.68
            pen(0, "чужая реклама только через трекер, который не открылся")
        else:
            s = 0.78
        if len({x[1] for x in other_l}) >= 2:
            s += 0.03
        if "name_in_title" in w:
            s -= 0.03
        elif "heads=" in w:
            s += pen(-0.08, "Mostbet нет ни в домене, ни в title")
        if dens < MONO_DENSITY:
            s += pen(-0.08, "мало упоминаний Mostbet для монобренда")
        if c == "mono_mixed" and not mb_l and r["mostbet_ads"] != "True":
            s += pen(-0.1, "реклама Mostbet не подтверждена ссылкой")
        if tags & {"ads_search_only", "ads_mobile_only"}:
            s += pen(-0.05, "чужая реклама видна не всем")
    elif c == "mb_page_other":
        brands = w.rsplit("(", 1)[-1]
        s = 0.8 if re.search(r"[A-Za-z]{3}", brands) and "." not in brands else 0.68
    elif c == "bait":
        m = re.search(r"content=([^:]*):(\d+) mostbet=(\d+)", w)
        if "moves to" in w:
            s = 0.85
        elif "never names" in w:
            s = 0.8
        elif "PWA" in w:
            s = 0.7
        elif m:
            s = 0.88 if int(m[2]) >= 3 * (int(m[3]) + 1) else 0.72
            if int(m[2]) < 3 * (int(m[3]) + 1):
                minus.append("Mostbet упоминается почти так же часто, как чужой бренд")
        if "in_title" in w:
            s += pen(-0.1, "Mostbet только в title, не в домене")
    elif c == "redirect_ref":
        s = 0.95 if "pid" in w else 0.85
    elif c == "redirect_other":
        t = w.rsplit("(", 1)[-1] if "(" in w else ""
        if re.search(r"припаркован|Congratulations|Gratulálunk|не найдена", t):
            s = pen(0.4, "редирект похож на парковку или ошибку, а не на рефку")
        elif t.strip(") ?") == "":
            s = 0.62
            minus.append("получатель редиректа не назван")
        elif "script" in w:
            s = 0.7
        else:
            s = 0.85
    elif c == "discredit":
        s = 0.78 + (0.05 if text_len >= 5000 else 0)
        if num(r["gambling_per_1k"]) > 1:
            s += pen(-0.15, "на странице есть слова про ставки")
    elif c == "mono_mostbet":
        s = 0.86
        if not mb_l:
            s += pen(-0.08, "рефка Mostbet не в списке решивших ссылок")
        if "ads_unverified" in tags:
            s += pen(-0.12, "не все кнопки пройдены до конца")
    elif c == "mono_unresolved":
        s = 0.75
        if text_len < 1500:
            s += pen(-0.15, "текста мало — может быть неподнятый сайт")
    elif c == "mono_no_ads":
        s = 0.72
        if text_len < 1500:
            s += pen(-0.15, "текста мало — может быть неподнятый сайт")
        if "ads_unverified" in tags:
            s += pen(-0.1, "не все кнопки пройдены до конца")
    elif c == "mono_xlink":
        s = 0.65
    elif c == "mono_hidden":
        s = 0.85  # the hidden link is read from the saved HTML itself
    elif c == "mirror":
        s = 0.95 if w == "mostbet_shell" else 0.8
    elif c == "multibrand":
        m = re.search(r"top_other=([^:]*):(\d+) mostbet=(\d+)", w)
        if not m or not m[1]:
            s = pen(0.6, "чужие бренды в тексте не названы")
        else:
            ratio = int(m[2]) / (int(m[3]) + 1)
            s = 0.85 if ratio >= 3 else 0.75 if ratio >= 1.5 else pen(0.6, "Mostbet упоминается почти так же часто, как чужой бренд")
        if "brand_in_domain" in tags:
            s += pen(-0.3, "Mostbet в домене — по правилу владельца это нарушитель")
    elif c == "article":
        fl = num(r["feed_links"])
        s = 0.85 if fl >= 30 else 0.75 if fl >= 15 else pen(0.62, "лента короткая")
        if dens >= MONO_DENSITY:
            s += pen(-0.1, "Mostbet упоминается часто, как у монобренда")
    elif c == "hacked":
        if re.search(r"hidden(_mostbet_links)?=([3-9]|\d\d)", w):
            s = 0.85
        elif re.search(r"hidden=[1-9]", w):
            s = 0.8
        elif "in_title" in w:
            s = pen(0.55, "Mostbet в title, на странице нет ссылок")
        else:
            s = pen(0.65, "ссылки на Mostbet не скрыты")
    elif c in ("other_gambling", "unrelated"):
        s = 0.88
    elif c == "unclear":
        s = pen(0.3, "правила не решили")
    elif c == "stub":
        s = {"placeholder text": 0.85}.get(w, 0.85 if w.startswith("hosting") else 0.7 if w.startswith("text_len") else 0.6)
        if w.startswith("mostbet_only"):
            minus.append("Mostbet в домене при пустой странице")
    elif c == "parked":
        s = 0.9 if w == "parked" else 0.85
    elif c == "dead":
        k = w.removeprefix("home dump: ")
        s = {"dns_fail": 0.95, "connection_refused": 0.9, "tls_error": 0.85, "too_many_redirects": 0.85,
             "timeout": 0.75, "ServerDisconnectedError": 0.75, "connect_error": 0.8}.get(k, 0.7)
        if k == "timeout":
            minus.append("один таймаут — может ожить")
    elif c == "not_shown":
        m = re.match(r"(http|cloudflare)_(\d+)", w)
        if m:
            s = 0.8 if m[2] in ("403", "401", "429") else 0.72
        elif w.startswith("answered in an earlier scan"):
            s = pen(0.55, "в первых проходах сайт отвечал")
        else:
            s = {"cloudflare_challenge": 0.85, "cloudflare_turnstile": 0.85, "geo_block": 0.9}.get(w, 0.62)

    if c in ("mono_other", "mono_mixed"):
        o = [b for b in r["other_ads"].split(" | ") if b]
        if o and all(b.startswith("via ") and b[4:] in MB_TRACKERS and b[4:] not in OTHER_TRACKERS for b in o):
            s += pen(-0.35, "«чужой» трекер в других местах ведёт на Mostbet")
        if other_l and all("1win.global" in x[2] for x in other_l):
            s += pen(-0.35, "чужая ссылка 1win.global может быть из закомментированного кода темы")
    if c not in ("not_shown", "dead", "parked") and BLOCK_TITLE.search(r["title"]):
        s += pen(-0.4, "вместо страницы — блокировка Cloudflare")
    if c in CONTENT and "no_html" in tags:
        s += pen(-0.2, "HTML страницы не сохранён")
    if any(t.startswith("cloaked:") for t in tags):
        s += pen(-0.04, "сайт виден только посетителю из Google или Googlebot")
    if c in ("mono_other", "mono_mixed", "mono_xlink") and "ads_unverified" in tags:
        s += pen(-0.03, "не все кнопки пройдены до конца")
    return min(0.98, max(0.05, s)), minus


def labels(d: Path, now: dict) -> dict:
    """domain -> (agrees, source, expected classes) from every checked site; later rounds win, the owner wins over agents."""
    out = {}
    paths = sorted(glob.glob(str(d / "review" / "round1" / "verdicts-*.json"))) + \
        sorted(glob.glob(str(d / "review" / "round2" / "verdicts-*.json"))) + \
        sorted(glob.glob(str(d / "review" / "verdicts-*.json"))) + \
        sorted(glob.glob(str(d / "review" / "round4" / "verdicts-*.json")))
    for p in paths:
        for v in json.loads(Path(p).read_text()):
            if v.get("verdict") == "unsure" or v["domain"] not in now:
                continue
            if "given" not in v:  # verdicts on the Mostbet-page evidence: "correct" means the evidence holds
                ok = v["verdict"] == "correct"
                out[v["domain"]] = (ok, Path(p).stem, {now[v["domain"]]} if ok else {"not_a_violator"})
                continue
            expected = {v.get("should_be")} if v.get("verdict") == "wrong" else {v.get("given")}
            out[v["domain"]] = (now[v["domain"]] in expected, Path(p).parent.name + "/" + Path(p).stem, expected)
    om = d / "review" / "owner-marks-r2.json"
    if om.exists():
        for dom, m in json.loads(om.read_text()).items():
            if dom not in now:
                continue
            if m.get("v") == "ok":
                out[dom] = (now[dom] == m.get("given"), "owner", {m.get("given")})
            elif dom in OWNER_BAD:
                out[dom] = (now[dom] in OWNER_BAD[dom], "owner", OWNER_BAD[dom])
    om4 = d / "review" / "owner-marks-r4.json"  # the owner's classes after round 4: {domain: class}
    if om4.exists():
        for dom, c in json.loads(om4.read_text()).items():
            if dom in now:
                out[dom] = (now[dom] == c, "owner", {c})
    return out


def logit(p):
    p = min(1 - 1e-6, max(1e-6, p))
    return math.log(p / (1 - p))


def fit(xs, ys, prior=4.0):
    """Platt scaling p = σ(a + b·logit(raw)) with a Gaussian pull to a=0, b=1 (the raw score as it is)."""
    a, b = 0.0, 1.0
    for _ in range(200):
        ga, gb = a * prior, (b - 1) * prior
        haa, hab, hbb = prior, 0.0, prior
        for x, y in zip(xs, ys):
            p = 1 / (1 + math.exp(-(a + b * x)))
            ga += p - y
            gb += (p - y) * x
            wgt = p * (1 - p)
            haa += wgt
            hab += wgt * x
            hbb += wgt * x * x
        det = haa * hbb - hab * hab
        da, db = (hbb * ga - hab * gb) / det, (haa * gb - hab * ga) / det
        a, b = a - da, b - db
        if abs(da) + abs(db) < 1e-9:
            break
    return a, b


def class_offset(pts, prior=3.0):
    """Shift o on the logit scale maximising Σ log σ(z+o) for the class's checks, with a Gaussian pull to 0."""
    o = 0.0
    for _ in range(100):
        g, h = o * prior, prior
        for z, y in pts:
            p = 1 / (1 + math.exp(-(z + o)))
            g += p - y
            h += p * (1 - p)
        o -= g / h
    return o


def main(d: str, sample_round4=False):
    d = Path(d)
    rows = load_rows(d)
    load_trackers(d)
    scored = {}
    for r in rows:
        scored[r["domain"]] = raw_score(r)
    now = {r["domain"]: r["category"] for r in rows}
    lab = labels(d, now)

    if sample_round4:
        write_sample(d, rows, scored, lab)
        return

    params, report = {}, []
    for fam in ("viol", "mono", "other", "dead"):
        pts = [(logit(scored[dom][0]), 1.0 if ok else 0.0) for dom, (ok, *_) in lab.items() if FAMILY.get(now[dom]) == fam]
        params[fam] = fit([x for x, _ in pts], [y for _, y in pts]) if pts else (0.0, 1.0)
        report.append((fam, len(pts), sum(y for _, y in pts), params[fam]))

    # Each class gets its own shift on top of its group, pulled to zero: a class with few checks keeps the group scale.
    offs = {}
    for c in FAMILY:
        a, b = params[FAMILY[c]]
        pts = [(a + b * logit(scored[dom][0]), 1.0 if ok else 0.0) for dom, (ok, *_) in lab.items() if now[dom] == c]
        offs[c] = class_offset(pts)

    def conf(dom):
        a, b = params[FAMILY[now[dom]]]
        return 1 / (1 + math.exp(-(a + offs[now[dom]] + b * logit(scored[dom][0]))))

    # Leave-one-out check of the calibration: claimed vs observed, by bins.
    bins = collections.defaultdict(lambda: [0, 0, 0.0])
    for dom, (ok, *_) in lab.items():
        fam = FAMILY[now[dom]]
        rest = [(logit(scored[x][0]), 1.0 if o else 0.0) for x, (o, *_) in lab.items() if x != dom and FAMILY[now[x]] == fam]
        a, b = fit([x for x, _ in rest], [y for _, y in rest]) if rest else (0.0, 1.0)
        o = class_offset([(a + b * logit(scored[x][0]), 1.0 if ok2 else 0.0) for x, (ok2, *_) in lab.items()
                          if x != dom and now[x] == now[dom]])
        p = 1 / (1 + math.exp(-(a + o + b * logit(scored[dom][0]))))
        k = min(4, int(p * 5))
        bins[k][0] += 1
        bins[k][1] += ok
        bins[k][2] += p

    # The second scale: is the site a violator at all, whatever its class. Trained on the same checks turned into
    # violator / not; a mix-up inside the violators (mono_other vs mono_mixed) is no error here. For a violator class
    # a stronger class evidence means a likelier violation, for the others a less likely one.
    def vx(dom):
        x = logit(scored[dom][0])
        return x if now[dom] in VIOL else -x
    vlab = {dom: bool(exp & VIOL) for dom, (_, _, exp) in lab.items()}
    vparams = {}
    for fam in ("viol", "mono", "other", "dead"):
        pts = [(vx(dom), 1.0 if (y if fam == "viol" else not y) else 0.0) for dom, y in vlab.items() if FAMILY[now[dom]] == fam]
        vparams[fam] = fit([x for x, _ in pts], [y for _, y in pts]) if pts else (0.0, 1.0)
    voffs = {}
    for c in FAMILY:
        a, b = vparams[FAMILY[c]]
        voffs[c] = class_offset([(a + b * vx(dom), 1.0 if (y if c in VIOL else not y) else 0.0)
                                 for dom, y in vlab.items() if now[dom] == c])

    def viol(dom):
        c = now[dom]
        a, b = vparams[FAMILY[c]]
        p = 1 / (1 + math.exp(-(a + voffs[c] + b * vx(dom))))
        return p if c in VIOL else 1 - p

    vbins = collections.defaultdict(lambda: [0, 0, 0.0])
    for dom, y in vlab.items():
        k = min(4, int(viol(dom) * 5))
        vbins[k][0] += 1
        vbins[k][1] += y
        vbins[k][2] += viol(dom)

    with open(d / "confidence.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["domain", "category", "raw", "confidence", "violation", "minus", "checked"])
        for r in rows:
            dom = r["domain"]
            ck = lab.get(dom)
            w.writerow([dom, r["category"], f"{scored[dom][0]:.2f}", round(conf(dom) * 100), round(viol(dom) * 100),
                        "; ".join(scored[dom][1]),
                        "" if not ck else ("agrees" if ck[0] else "disagrees")])

    per_class = collections.defaultdict(list)
    for r in rows:
        per_class[r["category"]].append(conf(r["domain"]) * 100)
    checked = collections.Counter((now[x], ok) for x, (ok, *_) in lab.items())
    md = ["# Калибровка уверенности", "",
          f"Проверенных сайтов с вердиктом: {len(lab)}. Подгонка по группам классов, Platt с притяжением к сырому баллу.", "",
          "## Группы", ""]
    for fam, n, pos, (a, b) in report:
        md.append(f"- {fam}: проверено {n}, класс подтверждён {int(pos)}; a={a:.2f}, b={b:.2f}")
    md += ["", "Сдвиг по классам (логит): " + ", ".join(f"{c} {o:+.2f}" for c, o in offs.items() if abs(o) >= 0.05)]
    md += ["", "## Заявленная уверенность против подтверждённой (каждый сайт оценён без себя)", ""]
    for k in sorted(bins):
        n, ok, ps = bins[k]
        md.append(f"- {k * 20}–{k * 20 + 20}: сайтов {n}, заявлено {ps / n * 100:.0f} %, подтверждено {ok / n * 100:.0f} %")
    md += ["", "## По классам: средняя уверенность, проверено (подтверждено)", ""]
    for c in sorted(per_class, key=lambda c: (list(FAMILY).index(c))):
        v = per_class[c]
        md.append(f"- {c}: {sum(v) / len(v):.0f}, ниже 60 — {sum(1 for x in v if x < 60)} из {len(v)}; "
                  f"проверено {checked[(c, True)] + checked[(c, False)]} ({checked[(c, True)]})")
    md += ["", "## Уверенность в нарушении: заявлено против подтверждённого (на тех же сайтах, без исключения себя)", ""]
    for k in sorted(vbins):
        n, ok, ps = vbins[k]
        md.append(f"- {k * 20}–{k * 20 + 20}: сайтов {n}, заявлено {ps / n * 100:.0f} %, нарушителей {ok / n * 100:.0f} %")
    md += ["", "## Уверенность в нарушении по классам: средняя, сайтов от 50", ""]
    vpc = collections.defaultdict(list)
    for r in rows:
        vpc[r["category"]].append(viol(r["domain"]) * 100)
    for c in sorted(vpc, key=lambda c: list(FAMILY).index(c)):
        v = vpc[c]
        md.append(f"- {c}: {sum(v) / len(v):.0f}, от 50 — {sum(1 for x in v if x >= 50)} из {len(v)}")
    (d / "review" / "calibration.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


def write_sample(d: Path, rows, scored, lab):
    feats = {}
    want_rows = []
    rnd = random.Random(SEED)
    by = collections.defaultdict(list)
    for r in rows:
        if r["domain"] not in lab:
            by[r["category"]].append(r)
    for c, rs in by.items():
        rs.sort(key=lambda r: (scored[r["domain"]][0], r["domain"]))
        n = min(20, len(rs))
        want_rows += [rnd.choice(rs[i * len(rs) // n:(i + 1) * len(rs) // n]) for i in range(n)]
    want = {r["domain"] for r in want_rows}
    with gzip.open(d / "site-features.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            if x["domain"] in want:
                feats[x["domain"]] = next((x[k] for k in ("browser", "http", "http-google-mobile", "http-googlebot") if x.get(k)), {})
    out = []
    keep = ("domain", "category", "tags", "why", "mostbet_ads", "other_ads", "plain_gambling_links", "ad_links", "mb_text",
            "mb_per_1k", "mb_anchor", "mb_hidden_links", "text_len", "gambling_per_1k", "other_brands_text", "feed_links",
            "title", "h1", "lang", "final_url", "scan_group")
    for r in sorted(want_rows, key=lambda r: (r["category"], r["domain"])):
        pg = feats.get(r["domain"], {})
        files = sorted(str(p.relative_to(d.parents[2])) for p in (d / "html").glob(f'{r["domain"]}.*')
                       if re.match(r"(http|browser|deep|mbpages)", p.name[len(r["domain"]) + 1:]))
        out.append({**{k: r[k] for k in keep}, "text_sample": (pg.get("text_sample") or "")[:600],
                    "aff_links": (pg.get("aff_links") or [])[:10], "gates": (pg.get("gates") or [])[:10],
                    "trackers": (pg.get("trackers") or [])[:10], "html_files": files})
    (d / "review" / "round4").mkdir(exist_ok=True)
    (d / "review" / "round4" / "sample.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), collections.Counter(x["category"] for x in out))


if __name__ == "__main__":
    main(sys.argv[1], "--sample-round4" in sys.argv)
