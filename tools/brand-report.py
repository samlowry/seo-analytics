"""Report on the whole brand scan: classes, numbers, 10 examples per class. One HTML file, printed to PDF.

Run: uv run --with selectolax python tools/brand-report.py brand-protection/2026-09-28/brand-scan
Reads classified.csv, site-features.jsonl.gz, corsearch-false-positives.csv. Writes report/brand-report.html, self-contained:
the donut of groups and the share meters are inline SVG/CSS, no external resources. Examples: per class, the domains sorted by name and cut into ten equal
parts, one random domain from each part (fixed seed), so the sample spreads over the whole class.
"""
import collections
import csv
import gzip
import html
import json
import random
import re
import sys
from pathlib import Path

csv.field_size_limit(sys.maxsize)
SEED = 20261001

GROUPS = [
    ("Нарушители: бренд Mostbet используется для рекламы чужих", [
        ("mono_other", "Монобренд → реклама только чужих",
         "Сайт целиком про Mostbet (домен, заголовки, текст), а партнёрские ссылки и кнопки ведут только на другие бренды."),
        ("mono_mixed", "Монобренд → Mostbet и чужие",
         "Сайт про Mostbet рекламирует и Mostbet, и другие бренды; часто одна ссылка ротирует между ними."),
        ("mb_page_other", "Статья про Mostbet → реклама чужих",
         "Сайт не монобренд (статейник, мультибренд), но его страница про Mostbet рекламирует другие бренды. "
         "Адрес страницы — в поле «почему»."),
        ("bait", "Приманка",
         "Mostbet в домене или заголовке, а внутри чужое казино, чужое PWA-приложение или слоты."),
        ("redirect_other", "Редирект на чужую рефку",
         "Главная сразу уводит посетителя на партнёрскую ссылку другого бренда."),
        ("discredit", "Дискредитация бренда",
         "Mostbet в домене, а на сайте содержимое не про ставки вообще (магазин, наркошоп и т. п.)."),
    ]),
    ("Монобренд Mostbet без чужой рекламы", [
        ("mono_mostbet", "Монобренд → только Mostbet", "Реклама только Mostbet (партнёрские ссылки с pid)."),
        ("redirect_ref", "Редирект на рефку Mostbet", "Главная сразу уводит на партнёрскую ссылку Mostbet; "
         "большая часть — скрытая сеть одного партнёра, видимая только посетителю из Google."),
        ("mono_xlink", "Монобренд, простые ссылки на чужих", "Чужой рекламы нет, но есть простые ссылки на дорвеи "
         "и обзорники других брендов."),
        ("mono_unresolved", "Монобренд, получатель неизвестен", "Кнопки ведут на трекер или шлюз, до получателя "
         "не дошли ни HTTP, ни браузер (мёртвый трекер, кнопка без адреса)."),
        ("mono_no_ads", "Монобренд без рекламы", "Партнёрских ссылок нет: браузер прокликал кнопки — никуда."),
        ("mirror", "Зеркало Mostbet", "Официальный сайт Mostbet (старый шаблон) на стороннем домене."),
    ]),
    ("Сайты другого типа", [
        ("multibrand", "Гэмблинг-аффилиат не про Mostbet", "Рейтинги нескольких брендов, игры (Aviator, Chicken Road), "
         "слоты; Mostbet — один из многих."),
        ("article", "Статейник", "Лента статей на разные темы, Mostbet — в отдельных постах."),
        ("hacked", "Взломанный сайт", "Своя тема (магазин, клиника, блог), Mostbet только во вставленных ссылках, "
         "часто скрытых."),
        ("other_gambling", "Чужое казино или БК", "Mostbet на странице не упоминается."),
        ("unrelated", "Не про гэмблинг", "Ни Mostbet, ни ставок."),
        ("unclear", "Не определено", "Правила не решили."),
    ]),
    ("Не работают", [
        ("not_shown", "Не показались", "Сервер отвечает, но отдаёт 403/503 или блок Cloudflare любому посетителю, "
         "включая заход из Google и Googlebot."),
        ("stub", "Пустышка", "Пустая страница: coming soon, заглушка хостинга, отключённый аккаунт."),
        ("parked", "Парковка", "Парковка или страница регистратора, домен продаётся."),
        ("dead", "Мёртвые", "Не отвечают: DNS, таймаут, отказ соединения."),
    ]),
]
TAG_RU = {
    "cloaked:google-mobile": "скрыт, виден посетителю из Google", "cloaked:googlebot": "скрыт, виден Googlebot",
    "ads_search_only": "чужая реклама только при заходе из Google", "ads_mobile_only": "чужая реклама только в мобильной версии",
    "rotating_ads": "реклама меняется между снимками", "search_referrer_js": "скрипт реагирует на заход из поиска",
    "pwa": "PWA-лендинг", "apk": "раздаёт APK", "brand_in_domain": "Mostbet в домене", "moved": "главная переезжает",
    "ads_unverified": "не все ссылки пройдены", "platform": "на платформе (blogspot и т. п.)", "no_html": "HTML нет",
    "our_ref": "наша рефка",
}


def brand_name(b: str) -> str:
    """Brand as people know it: a host that names a brand becomes the brand, a bare host is a tracker."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import landing_brand as lb
    host = b.removeprefix("via ")
    if "." in host and " " not in host:
        named = lb.brand_of_host(host)
        return named if named and named != "Mostbet" else f"трекер {host}"
    return b


def why_ru(r) -> str:
    """The rule that decided, in words — only where it is the evidence itself."""
    w, c = r["why"], r["category"]
    if "Mostbet page advertises others:" in w:
        url, brands = w.split("Mostbet page advertises others: ", 1)[1].rsplit(" (", 1)
        return f"страница про Mostbet {url} рекламирует {brands.rstrip(')')}"
    if c in ("redirect_ref", "redirect_other"):
        w = re.sub(r"home redirects to( a Mostbet ref,)?", "главная уводит на", w)
        return w.replace("script sends the home page to", "скрипт уводит главную на").replace("pid", "pid")
    if c == "discredit":
        return "Mostbet в домене, страница не про ставки"
    if c == "bait":
        return "Mostbet в домене или заголовке, страница про другой бренд" + \
            (" (страница не называет Mostbet)" if "never names" in w else "")
    if c == "hacked":
        return "Mostbet только в ссылках" + (", скрытых" if re.search(r"hidden=[1-9]|hidden_mostbet", w) else "")
    return ""


GROUP_KEYS = ["viol", "mono", "other", "dead"]  # CSS colour slots, in GROUPS order


def donut(parts, total) -> str:
    """Donut of the groups: inline SVG, 2px surface gaps between slices, native tooltip per slice."""
    import math
    cx = cy = 90
    r_out, r_in = 84, 52
    a0, out = -math.pi / 2, []
    for key, name, n in parts:
        a1 = a0 + 2 * math.pi * n / total
        large = 1 if a1 - a0 > math.pi else 0
        p = lambda a, r: (cx + r * math.cos(a), cy + r * math.sin(a))  # noqa: E731
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = p(a0, r_out), p(a1, r_out), p(a1, r_in), p(a0, r_in)
        d_ = (f"M{x0:.2f},{y0:.2f} A{r_out},{r_out} 0 {large} 1 {x1:.2f},{y1:.2f} L{x2:.2f},{y2:.2f} "
              f"A{r_in},{r_in} 0 {large} 0 {x3:.2f},{y3:.2f}Z")
        out.append(f'<path d="{d_}" style="fill:var(--g-{key})" stroke="var(--card)" stroke-width="2">'
                   f'<title>{e(name)}: {fmt(n)} ({pc(n * 100 / total)} %)</title></path>')
        a0 = a1
    return (f'<svg viewBox="0 0 180 180" width="180" height="180" role="img" aria-label="Доли групп">{"".join(out)}'
            f'<text x="90" y="86" text-anchor="middle" class="dn-n">{fmt(total)}</text>'
            f'<text x="90" y="104" text-anchor="middle" class="dn-l">доменов</text></svg>')


def meter(key, share, label) -> str:
    """Horizontal share bar across the full text width: a same-hue track with the share filled from the left;
    the number above it in text ink."""
    w = max(0.4, share * 100)
    return (f'<div class="meter"><div class="meter-t">{label}</div><div class="bar" role="img" aria-label="{w:.1f} %">'
            f'<div class="bar-track" style="background:var(--g-{key})"></div>'
            f'<div class="bar-fill" style="width:{w:.2f}%;background:var(--g-{key})"></div></div></div>')


def e(x) -> str:
    return html.escape(str(x or ""))


def pc(x) -> str:
    return f"{x:.1f}".replace(".", ",")


def fmt(n) -> str:
    return f"{n:,}".replace(",", " ")


def sample(rows, n=10):
    rows = sorted(rows, key=lambda r: r["domain"])
    if len(rows) <= n:
        return rows
    rnd = random.Random(SEED)
    return [rnd.choice(rows[i * len(rows) // n:(i + 1) * len(rows) // n]) for i in range(n)]


def main(d: str):
    d = Path(d)
    with open(d / "classified.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by = collections.defaultdict(list)
    for r in rows:
        by[r["category"]].append(r)
    picks = {c: sample(by[c]) for g in GROUPS for c, _, _ in g[1]}
    want = {r["domain"] for v in picks.values() for r in v}
    text = {}
    with gzip.open(d / "site-features.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            x = json.loads(line)
            if x["domain"] in want:
                pg = next((x[k] for k in ("browser", "http", "http-google-mobile", "http-googlebot") if x.get(k)), {})
                text[x["domain"]] = (pg.get("text_sample") or "")[:260]
    with open(d / "corsearch-false-positives.csv", newline="", encoding="utf-8") as f:
        false_pos = sum(1 for _ in csv.DictReader(f))

    total = len(rows)
    cnt = collections.Counter(r["category"] for r in rows)
    strikes = [r for r in rows if r["category"] in ("mono_other", "mono_mixed", "mb_page_other")]
    brands = collections.Counter(brand_name(b) for r in strikes for b in set(r["other_ads"].split(" | ")) if b)
    top = brands.most_common(12)
    cloaked = sum(1 for r in rows if "cloaked:" in r["tags"])
    pid_net = sum(1 for r in rows if r["category"] == "redirect_ref" and "229671" in r["why"])
    viol = sum(cnt[c] for c, _, _ in GROUPS[0][1])

    toc, sections = [], []
    gsum = {g[0]: sum(cnt[c] for c, _, _ in g[1]) for g in GROUPS}
    for gi, (gname, cats) in enumerate(GROUPS):
        key = GROUP_KEYS[gi]
        toc.append(f'<tr class="grp"><td colspan="3"><span class="sw" style="background:var(--g-{key})"></span>{e(gname)}'
                   f' — {fmt(gsum[gname])}'
                   + meter(key, gsum[gname] / total, f"<b>{pc(gsum[gname] * 100 / total)} %</b> всех доменов")
                   + '</td></tr>')
        sections.append(f'<div class="ghead" id="g-{key}"><h1>{e(gname)}</h1>'
                        + meter(key, gsum[gname] / total, f"<b>{pc(gsum[gname] * 100 / total)} %</b> всех доменов · "
                                f"{fmt(gsum[gname])} из {fmt(total)}") + '</div>')
        for c, ru, desc in cats:
            gs = cnt[c] / gsum[gname] if gsum[gname] else 0
            toc.append(f'<tr><td><a href="#{c}">{e(ru)}</a></td><td class="n">{fmt(cnt[c])}</td><td>{e(desc)}'
                       + meter(key, gs, f"<b>{pc(gs * 100)} %</b> группы · {pc(cnt[c] * 100 / total)} % всех")
                       + '</td></tr>')
            cards = []
            for r in picks[c]:
                tags = ", ".join(TAG_RU.get(t, t) for t in r["tags"].split() if t in TAG_RU and t != "brand_in_domain")
                facts = [("почему", why_ru(r)), ("реклама чужих", ", ".join(dict.fromkeys(brand_name(b) for b in r["other_ads"].split(" | ") if b))),
                         ("реклама Mostbet", "да" if r["mostbet_ads"] == "True" else ""),
                         ("простые ссылки", r["plain_gambling_links"]), ("метки", tags), ("title", r["title"]),
                         ("конечный адрес", r["final_url"] if r["final_url"] and r["domain"] not in r["final_url"] else "")]
                grid = "".join(f'<div class="kv"><span>{k}</span> <b>{e(v)}</b></div>' for k, v in facts if v)
                cards.append(f'''<article class="card"><header><a class="dom" href="https://{e(r["domain"])}/">{e(r["domain"])}</a></header>
{grid}{f'<div class="sample">{e(text.get(r["domain"]))}</div>' if text.get(r["domain"]) else ''}</article>''')
            shown = f"{len(picks[c])} из {fmt(cnt[c])}" if cnt[c] > 10 else f"все {cnt[c]}"
            gshare = cnt[c] / gsum[gname] if gsum[gname] else 0
            sections.append(f'''<section id="{c}" class="g-{key}"><h2>{e(ru)} <small>{fmt(cnt[c])} · примеры: {shown}</small></h2>
{meter(key, gshare, f"<b>{pc(gshare * 100)} %</b> группы «{e(gname.split(':')[0])}» · {pc(cnt[c] * 100 / total)} % всех доменов")}
<p class="desc">{e(desc)}</p>{''.join(cards)}</section>''')

    brand_rows = "".join(f"<li><b>{e(b)}</b> — {fmt(n)}</li>" for b, n in top)
    page = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Использование бренда Mostbet</title><style>
:root{{--bg:#f1f5f9;--card:#fff;--fg:#0f172a;--mut:#64748b;--line:#e2e8f0;--acc:#2563eb;
 --g-viol:#eb6834;--g-mono:#2a78d6;--g-other:#1baf7a;--g-dead:#4a3aa7}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#0b1120;--card:#111827;--fg:#e5e7eb;--mut:#94a3b8;
 --line:#1f2937;--acc:#60a5fa;--g-viol:#d95926;--g-mono:#256abf;--g-other:#199e70;--g-dead:#9085e9}}}}
:root[data-theme="dark"]{{--bg:#0b1120;--card:#111827;--fg:#e5e7eb;--mut:#94a3b8;--line:#1f2937;--acc:#60a5fa;
 --g-viol:#d95926;--g-mono:#256abf;--g-other:#199e70;--g-dead:#9085e9}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:1040px;margin:0 auto;padding:16px}} h1{{font-size:24px;margin:8px 0 4px}} .sub{{color:var(--mut)}}
h2{{font-size:18px;margin:28px 0 4px;border-left:5px solid var(--acc);padding-left:10px}} h2 small{{color:var(--mut);font-weight:400;font-size:13px}}
section.g-viol h2{{border-color:var(--g-viol)}} section.g-mono h2{{border-color:var(--g-mono)}}
section.g-other h2{{border-color:var(--g-other)}} section.g-dead h2{{border-color:var(--g-dead)}}
.chart{{display:flex;gap:24px;align-items:center;flex-wrap:wrap}} .legend{{list-style:none;padding:0;margin:0;flex:1;min-width:240px}}
.legend li{{display:flex;gap:8px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line)}} .legend a{{flex:1;color:var(--fg)}}
.legend b{{font-variant-numeric:tabular-nums}} .pct{{color:var(--mut);width:52px;text-align:right;font-variant-numeric:tabular-nums}}
.sw{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px;flex:none}}
.dn-n{{font-size:20px;font-weight:700;fill:var(--fg)}} .dn-l{{font-size:11px;fill:var(--mut)}}
.meter{{margin:6px 0 10px}} .meter-t{{font-size:12.5px;color:var(--mut);line-height:1.35;margin-bottom:4px}}
.bar{{position:relative;height:10px;width:100%}} .bar-track{{position:absolute;inset:0;border-radius:4px;opacity:.16}}
.bar-fill{{position:absolute;left:0;top:0;bottom:0;border-radius:4px}}
.meter-t b{{color:var(--fg);font-size:15px}} .ghead{{margin-top:36px;padding-top:8px;border-top:2px solid var(--line)}} .ghead h1{{margin:0 0 4px}}
.desc{{color:var(--mut);margin:2px 0 10px}} .lead{{background:var(--card);border-radius:10px;padding:12px 16px;margin:12px 0;break-inside:avoid}}
.lead li{{margin:3px 0}} table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden;font-size:13px}}
td{{padding:5px 10px;border-bottom:1px solid var(--line);vertical-align:top}} td.n{{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}}
tr.grp td{{font-weight:700;background:var(--bg)}} tr.grp .meter-t{{font-weight:400}} td .meter{{margin:6px 0 2px}} a{{color:var(--acc)}}
.card{{background:var(--card);border-radius:10px;padding:9px 14px;margin-bottom:8px;break-inside:avoid}}
.dom{{font-weight:700;font-size:15px;color:var(--fg);text-decoration:none}}
.kv{{font-size:12.5px;overflow-wrap:anywhere}} .kv span{{color:var(--mut)}} .kv b{{font-weight:500}}
.sample{{color:var(--mut);font-size:12px;margin-top:4px;overflow-wrap:anywhere}} .cols{{columns:2;column-gap:28px}}
@media (max-width:640px){{.cols{{columns:1}}}}
@media print{{body{{background:#fff}} .card,.lead,table{{border:1px solid #e2e8f0}} h2{{break-after:avoid}}}}
</style></head><body><main>
<h1>Использование бренда Mostbet: кто и как</h1>
<div class="sub">Срез 01.10.2026 · база Corsearch от 28.09.2026 без наших доменов · {fmt(total)} доменов</div>

<div class="lead chart"><div>{donut([(GROUP_KEYS[i], g[0], gsum[g[0]]) for i, g in enumerate(GROUPS)], total)}</div>
<ul class="legend">{"".join(f'<li><span class="sw" style="background:var(--g-{GROUP_KEYS[i]})"></span><a href="#g-{GROUP_KEYS[i]}">{e(g[0])}</a>'
f'<b>{fmt(gsum[g[0]])}</b><span class="pct">{pc(gsum[g[0]] * 100 / total)} %</span></li>' for i, g in enumerate(GROUPS))}</ul></div>

<div class="lead"><b>Главное</b><ul>
<li><b>{fmt(viol)} нарушителей</b> используют бренд Mostbet, чтобы рекламировать других или дискредитировать бренд.
Из них {fmt(cnt["mono_other"] + cnt["mono_mixed"])} — сайты целиком про Mostbet с рекламой чужих брендов,
{fmt(cnt["mb_page_other"])} — статьи про Mostbet на других сайтах с рекламой чужих,
{fmt(cnt["bait"] + cnt["redirect_other"])} — приманки и редиректы на чужое, {fmt(cnt["discredit"])} — дискредитация.</li>
<li>Кого рекламируют чаще всего:</li></ul><ul class="cols">{brand_rows}</ul><ul>
<li><b>{fmt(cloaked)} сайтов скрыты от обычного посетителя</b> и показываются только пришедшему из Google или Googlebot.
Из них {fmt(pid_net)} — одна сеть одного партнёра Mostbet (pid 229671): посетителя из Google сразу уводит на его рефку.</li>
<li>{fmt(false_pos)} доменов не имеют никакого отношения к бренду (ни в имени, ни на странице) — Corsearch собрал их
по ошибке, список для вайтлиста: <code>corsearch-false-positives.csv</code>.</li>
<li>{fmt(cnt["not_shown"] + cnt["stub"] + cnt["parked"] + cnt["dead"])} доменов не работают: не показываются, пустые,
припаркованы или мертвы.</li></ul></div>

<h2>Классы</h2><p class="desc">Один класс на сайт. Реклама — партнёрская ссылка (с кодом, через трекер) или прямая ссылка
на сайт другого оператора; простой текст без ссылки рекламой не считается.</p>
<table>{''.join(toc)}</table>

<div class="lead"><b>Как проверяли</b><ul>
<li>Каждый сайт открыт по HTTP и браузером с резидентского IP в Сербии; пройдены все ссылки и кнопки главной,
до 4 внутренних страниц, собственные скрипты сайта и до 8 страниц про Mostbet (из sitemap и меню).</li>
<li>Каждый сайт дополнительно открыт как мобильный посетитель, как посетитель из Google и как Googlebot —
так видна реклама, которую показывают не всем.</li>
<li>Наши партнёрские ссылки из реестра не открывались ни разу.</li>
<li>Классы проверены вручную и агентами: по 10 случайных сайтов на класс, три круга; с проверяющим совпадает
77–82 %, класс «монобренд → реклама только чужих» — 10 из 10 во всех кругах; страницы-доказательства статей про
Mostbet — 15 из 20 подтверждены (ошибки исправлены).</li>
<li>Не видно: реклама, которую показывают только в других странах; {fmt(cnt["mono_unresolved"])} монобрендов,
чьи трекеры не открылись.</li></ul></div>

<h1 style="margin-top:28px">Примеры по классам</h1>
<div class="sub">По 10 на класс: домены класса упорядочены по имени и разбиты на 10 равных частей, из каждой взят
один случайный.</div>
{''.join(sections)}
</main></body></html>'''
    out = d / "report"
    out.mkdir(exist_ok=True)
    (out / "brand-report.html").write_text(page, encoding="utf-8")
    print(out / "brand-report.html")


if __name__ == "__main__":
    main(sys.argv[1])
