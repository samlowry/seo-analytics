#!/usr/bin/env python3
"""Задача 2: ai-answers/04-candidates.md из results/ai/{pool.json, pages.jsonl, tone/assessment.json, ahrefs/domains-*.json, site/results.jsonl, site-check/*.xml, xmlriver/answers-desktop.jsonl, xmlriver/classification.json}."""
import json, os, re, glob, datetime, urllib.parse, xml.etree.ElementTree as ET
from collections import Counter, defaultdict
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = f'{ROOT}/results/ai'; OUT = f'{ROOT}/ai-answers/04-candidates.md'
host = lambda u: urllib.parse.urlsplit(u).netloc.lower().removeprefix('www.') if u else ''
fmt = lambda n: '—' if n is None else f'{int(n):,}'.replace(',', ' ')
load = lambda p, d: json.load(open(p)) if os.path.exists(p) else d

pool = {d['url']: d for d in load(f'{R}/pool.json', [])}
pages = {p['url']: p for p in (json.loads(l) for l in open(f'{R}/pages.jsonl') if l.strip())} if os.path.exists(f'{R}/pages.jsonl') else {}
tone = {t['url']: t for t in load(f'{R}/tone/assessment.json', [])}
ans = [json.loads(l) for l in open(f'{R}/xmlriver/answers-desktop.jsonl') if l.strip()] if os.path.exists(f'{R}/xmlriver/answers-desktop.jsonl') else []
cls = {(c['cc'], c['query'].strip().lower()): c for c in load(f'{R}/xmlriver/classification.json', [])}
# метрики доменов
dom = {}
for f in sorted(glob.glob(f'{R}/ahrefs/domains-*.json')):
    for r in load(f, {}).get('targets_result', []):
        h = host('https://' + r['url'].strip('/')) if '://' not in r['url'] else host(r['url'])
        dom[h.rstrip('/')] = r
# site:-выдача
site_rows = [json.loads(l) for l in open(f'{R}/site/results.jsonl') if l.strip()] if os.path.exists(f'{R}/site/results.jsonl') else []
site_rows = [r for r in site_rows if r.get('url')]
# site-check: сколько страниц про Mostbet на ключевых площадках
site_check = {}
for f in glob.glob(f'{R}/site-check/*.xml'):
    try: site_check[os.path.basename(f)[:-4]] = int(ET.parse(f).getroot().findtext('.//found') or 0)
    except Exception: pass

# проблемные ответы: absent/negative — с какими запросами связана каждая страница
problem_q = {}
for a in ans:
    if not a.get('ai_present'): continue
    c = cls.get((a['cc'], a['query'].strip().lower()))
    if not c: continue
    if c['mostbet_mentioned'] and c['mostbet_sentiment'] != 'negative': continue
    problem_q[(a['cc'], a['query'])] = a
okp = lambda p: p and p.get('status') in ('200', 'cached') and p.get('words', 0) > 50

# ── агрегаты по хостам ──
H = defaultdict(lambda: dict(urls=set(), cited=0, cited_urls=set(), top10=0, mb_pages=0, usable=0, site_urls=set(), cc=Counter()))
for u, d in pool.items():
    h = d['host']; H[h]['urls'].add(u); H[h]['cited'] += len(d['cited']); H[h]['top10'] += len(d['top10'])
    if d['cited']: H[h]['cited_urls'].add(u)
    for c in d['cc']: H[h]['cc'][c] += 1
    p = pages.get(u)
    if okp(p) and p.get('mostbet_count'): H[h]['mb_pages'] += 1
    if tone.get(u, {}).get('usable_paragraph'): H[h]['usable'] += 1
for r in site_rows: H[host(r['url'])]['site_urls'].add(r['url'])

today = datetime.date.today().isoformat()
L = []; A = L.append
A('# Кандидаты на прокачку: кто кормит AI-ответы и где Mostbet уже подан нормально\n')
A(f'Собрано {today}. Входы: {len(pool)} URL из источников AI-ответов и органического топ-10 по {len(problem_q)} проблемным запросам, '
  f'{len(site_rows)} строк `site:kz/uz/az`, {len(pages)} скачанных страниц, метрики Ahrefs по {len(dom)} доменам, оценка абзацев на {len(tone)} страницах с Mostbet. '
  'Генератор — `tools/candidates-report.py`; предыдущие слои — [01](01-corpus-and-sources.md), [02](02-ai-answers.md), [03](03-brand-languages.md).\n')
A('## Главное\n')
A('**[Sports.ru, 18.08.2026](https://www.sports.ru/betting/industry/1117338157-mostbet-v-sentyabre-planiruet-nachat-legalnuyu-rabotu-v-kazaxstane-i-u.html): '
  '«Mostbet в сентябре планирует начать легальную работу в Казахстане и Узбекистане»** (источник — телеграм-канал «Азартный Казахстан», деталей нет, '
  'независимого подтверждения нет). Если это так, рейтинговые страницы ниже добавят Mostbet сами, по своим правилам, и AI-ответы подтянутся следом; '
  'задача сводится к подготовке площадок к дню Х и мониторингу. Если нет — работаем со страницами, где Mostbet уже подан как международный вариант. '
  '**Статус лицензии — вопрос владельцу.**\n')

# ── A. рейтинговые страницы ──
A('## A. Куда AI-ответы ходят за списком букмекеров\n')
A('Страницы, которые чаще всего цитируются в проблемных ответах (Mostbet отсутствует или подан с негативом). «Брендов» — сколько БК названо на странице, '
  '«Mostbet» — упоминаний на ней, «страниц про Mostbet на сайте» — по `site:host mostbet`.\n')
A('| цитирований | страница | DR | брендов на стр. | Mostbet на стр. | страниц про Mostbet на сайте |\n|---|---|---|---|---|---|')
top_cited = sorted([(len(d['cited']), u) for u, d in pool.items() if d['cited']], reverse=True)[:25]
for n, u in top_cited:
    p = pages.get(u, {}); h = host(u); m = dom.get(h, {})
    A(f"| {n} | [{u[:75]}]({u}) | {fmt(m.get('domain_rating'))} | {p.get('n_brands', '—') if okp(p) else 'не скачана'} | {p.get('mostbet_count', 0) if okp(p) else '—'} | {fmt(site_check.get(h)) if h in site_check else '—'} |")
A('')

# ── B. домены ──
A('## B. Шорт-лист доменов\n')
A('Сортировка: число цитирований в проблемных ответах, затем DR. «Трафик» — органический, по Ahrefs; «топ страны» — откуда трафик.\n')
A('| домен | DR | доноров | трафик | топ страны | URL в пуле | цитируется | в топ-10 | стр. с Mostbet | пригодных абзацев | в `site:` |\n|---|---|---|---|---|---|---|---|---|---|---|')
rows = []
for h, d in H.items():
    m = dom.get(h, {}); rows.append((d['cited'], m.get('domain_rating') or 0, h, d, m))
for cited, dr, h, d, m in sorted(rows, key=lambda x: (-x[0], -x[1]))[:60]:
    tc = ', '.join(f'{c} {fmt(v)}' for c, v in (m.get('org_traffic_top_by_country') or [])[:3])
    A(f"| `{h}` | {fmt(m.get('domain_rating'))} | {fmt(m.get('refdomains'))} | {fmt(m.get('org_traffic'))} | {tc} | {len(d['urls'])} | {cited} | {d['top10']} | {d['mb_pages']} | {d['usable']} | {len(d['site_urls'])} |")
A('')

# ── C. страницы с пригодным абзацем ──
A('## C. Страницы, где Mostbet уже подан нормально\n')
A('Оценка агентами по фрагментам вокруг упоминаний: «пригодный абзац» — описание Mostbet как обычного варианта без предупреждений. '
  'Сортировка: цитирования + попадания в топ-10, затем DR домена.\n')
A('| страница | DR | тип | тон | цит. | топ-10 | ранг Mostbet среди брендов | цитата |\n|---|---|---|---|---|---|---|---|')
SPAM = re.compile(r'спам|аффилиат|клон|мусор|дорвей|сателлит', re.I)
cand = []; spammy = []
for u, t in tone.items():
    if not t.get('usable_paragraph'): continue
    if SPAM.search(t.get('issues', '')) or re.search(r'mostbet|мостбет', host(u)): spammy.append((u, t)); continue
    d = pool.get(u, {}); p = pages.get(u, {}); m = dom.get(host(u), {})
    cand.append((len(d.get('cited', [])) + len(d.get('top10', [])), m.get('domain_rating') or 0, u, t, p, d, m))
for sc, dr, u, t, p, d, m in sorted(cand, key=lambda x: (-x[0], -x[1])):
    A(f"| [{u[:70]}]({u}) | {fmt(m.get('domain_rating'))} | {t['page_type']} | {t['tone']} | {len(d.get('cited', []))} | {len(d.get('top10', []))} | {p.get('mostbet_rank') or '—'}/{p.get('n_brands', '—')} | {t['paragraph_quote'].replace('|', '¦')[:300]} |")
A('')
if spammy:
    A(f'Ещё {len(spammy)} страниц с формально пригодным абзацем отсечены как спам-размещения, аффилиатные клоны или домены с «mostbet» в имени — '
      'прокачивать их не имеет смысла: ' + ', '.join(f'`{host(u)}`' for u, _ in spammy[:25]) + ('…' if len(spammy) > 25 else '') + '\n')

# ── D. страницы с Mostbet, но непригодные ──
A('## D. Страницы с Mostbet, которые надо править\n')
A('| страница | DR | тип | тон | цит. | что не так |\n|---|---|---|---|---|---|')
bad = []
for u, t in tone.items():
    if t.get('usable_paragraph'): continue
    d = pool.get(u, {}); m = dom.get(host(u), {})
    bad.append((len(d.get('cited', [])) + len(d.get('top10', [])), m.get('domain_rating') or 0, u, t, d, m))
for sc, dr, u, t, d, m in sorted(bad, key=lambda x: (-x[0], -x[1]))[:60]:
    A(f"| [{u[:70]}]({u}) | {fmt(m.get('domain_rating'))} | {t['page_type']} | {t['tone']} | {len(d.get('cited', []))} | {t['issues'].replace('|', '¦')} |")
A('')

# ── E. site: ──
A('## E. `site:kz` / `site:uz` / `site:az` — кто вообще пишет про Mostbet и БК на местных доменах\n')
for cc in ('KZ', 'UZ', 'AZ'):
    rr = [r for r in site_rows if r['cc'] == cc]
    if not rr: A(f'**{cc}** — данных нет.\n'); continue
    hc = Counter(host(r['url']) for r in rr)
    A(f"**{cc}** — {len({r['url'] for r in rr})} URL на {len(hc)} хостах. Топ хостов: " + ', '.join(f"`{h}` ({n})" for h, n in hc.most_common(15)) + '\n')
A('')
A('## Выводы по странам\n')
A('**Казахстан.** AI-ответы про выбор БК строятся на четырёх рейтингах легальных букмекеров (`legalbet.kz/rating/`, `meta-ratings.kz/bookmakersrating/`, '
  '`bookmaker-ratings.kz`, `stavka.tv/bookmakers`) — Mostbet ни в одном, при том что те же площадки держат сотни и тысячи страниц про Mostbet. '
  'Ссылочная прокачка тут не работает: на целевых страницах бренда нет. Единственный вход — попадание в сами рейтинги, а это вопрос лицензии '
  '(см. «Главное»). До лицензии Mostbet живёт в KZ-ответах только в рамке «офшорные / без паспорта»; страницы из раздела C для KZ — '
  '«зарубежные БК» на `strategya.com`, `pribalt.info`, `rgo-rb.ru` (DR 25–36) — это второй эшелон и он не выведет бренд в ответ про «какую БК выбрать».\n')
A('**Узбекистан.** Здесь Mostbet уже в ответах, и есть страницы с нормальной подачей на сильных доменах: `sportreytingi.uz` (местный рейтинг, Mostbet первый), '
  '`futureby.info` (цитируется в 8 ответах), `metaratings.ru/bukmekerskie-kontory-uzbekistana/` (DR 69), `ua.tribuna.com` (DR 76), `sport.ua` (DR 66), '
  '`vseprosport.ru` (DR 59). Это и есть шорт-лист на прокачку. Что снимать — оговорку про лицензию НАПП, которая идёт следом за Mostbet в 6 из 7 ответов.\n')
A('**Азербайджан.** Русскоязычной поверхности почти нет (см. [03](03-brand-languages.md)); единственная пригодная страница — `fc-arsenal.com` (DR 22). '
  'AI-ответ опирается на МВД и `demokrat.az`; менять его русскоязычными страницами не получится — нужна az/tr-работа, это отдельная задача.\n')
A('## Метод и ограничения\n')
A('- Пул страниц — только из проблемных AI-ответов и `site:`-выдачи; страницы, которых нет ни там, ни там, не рассматривались.')
A('- `bookmaker-ratings.kz`, `stavkinasport.com`, `parimatch.kz` не отдают HTML ни обычному клиенту, ни headless — их страницы оценены только по метрикам и `site:`.')
A('- Оценка абзацев сделана по фрагментам ±250 символов вокруг упоминаний, а не по полной странице.')
A('- Метрики доменов — Ahrefs batch-analysis (~53 юнита на домен); метрики отдельных страниц не снимались.')
open(OUT, 'w').write('\n'.join(L))
print(f'04-candidates.md: pool {len(pool)}, pages {len(pages)}, tone {len(tone)}, domains {len(dom)}, site rows {len(site_rows)}, usable {len(cand)}')
