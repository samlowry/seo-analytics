#!/usr/bin/env python3
"""Собирает ai-answers/01-corpus-and-sources.md и corpus-informational.csv
из сырых JSON в results/ai/ (corpus/, serp/). Ничего не запрашивает — только сводит.
Запуск: python3 tools/ai-answers-report.py
"""
import json, glob, re, csv, collections, urllib.parse, datetime, os
from collections import defaultdict, Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORPUS = f'{ROOT}/results/ai/corpus'
SERP = f'{ROOT}/results/ai/serp'
OUT_DIR = f'{ROOT}/ai-answers'
os.makedirs(OUT_DIR, exist_ok=True)
CC = ['KZ', 'AZ', 'UZ']
CNAME = {'KZ': 'Казахстан', 'AZ': 'Азербайджан', 'UZ': 'Узбекистан'}
cyr = re.compile('[а-яё]', re.I)
fmt = lambda n: f'{n:,}'.replace(',', ' ')

# ───────── корпус ─────────
rows = {}
units_corpus = 0
for cc in CC:
    for f in sorted(glob.glob(f'{CORPUS}/{cc}/*.json')):
        d = json.load(open(f)); units_corpus += d.get('units', 0)
        for k in d['keywords']:
            key = (cc, k['keyword'])
            if key in rows: rows[key]['seeds'].add(d['seed']); continue
            rows[key] = dict(cc=cc, keyword=k['keyword'], volume=k.get('volume') or 0,
                             parent_topic=k.get('parent_topic'), serp_features=k.get('serp_features') or [],
                             intents=k.get('intents') or {}, seeds={d['seed']})

HARD_EXCL = re.compile(r'скачат|вход|войти|зеркал|apk|\bios\b|андроид|android|приложени|официальн|промокод|регистрац|партнер|партнёр|affiliate|казино|casino|слот|авиатор|aviator|самолет|взлом|мобильн|рабоч|актуальн|сегодня', re.I)
SOFT_NAV = re.compile(r'бонус|фриспин|фрибет|бесплатн|лайв|\blive\b|линия|результат|прогноз|коэффициент|телефон|играть', re.I)
BARE_BRAND = re.compile(r'^(бк |букмекер(ская контора)? |казино )?(мостбет|mostbet)( (бк|kz|uz|az|кз|уз|аз|com|казахстан|узбекистан|азербайджан))?$', re.I)
THEMES = [  # порядок важен: первое совпадение побеждает
    ('отзывы',       r'отзыв|обзор'),
    ('вывод денег',  r'вывод|вывест|выплат|не платит|задерж|kaspi|каспи|комисси|минимальн|лимит'),
    ('верификация',  r'верификац|провер|документ|паспорт|идентификац|kyc'),
    ('легальность',  r'легал|лицен|закон|запрещ|заблок|блокир|разреш|налог'),
    ('надёжность',   r'надежн|надёжн|честн|обман|мошен|развод|кида|лохотрон|скам|scam|жалоб|доверять'),
    ('выбор БК',     r'какой|какую|какие|лучш|рейтинг|топ\b|сравн|стоит ли|самые|популярн|букмекерские конторы|букмекеры|список|все бк|\bбк\b'),
    ('возраст',      r'со скольки|\bлет\b|\b18\b|возраст'),
    ('поддержка',    r'поддержк|служба|\bчат\b|связаться|горячая линия|номер телефона'),
    ('как ставить',  r'как ставить|как делать|как сделать|стратеги|где ставить|где поставить|где можно ставить'),
    ('что это',      r'\bэто$|что такое|кто так'),
]
def theme_of(k):
    for name, rx in THEMES:
        if re.search(rx, k, re.I): return name
    return None

info = defaultdict(list)
for r in rows.values():
    k = r['keyword']
    if not cyr.search(k): continue
    if HARD_EXCL.search(k) or BARE_BRAND.match(k.strip()): continue
    th = theme_of(k)
    it = r['intents']
    if th is None:
        if SOFT_NAV.search(k): continue
        if not (it.get('informational') or it.get('commercial')): continue
        if it.get('navigational'): continue
        th = 'прочее'
    r['theme'] = th
    info[r['cc']].append(r)
for cc in CC: info[cc].sort(key=lambda r: -r['volume'])

with open(f'{OUT_DIR}/corpus-informational.csv', 'w', newline='') as fh:
    w = csv.writer(fh); w.writerow(['country', 'theme', 'volume', 'keyword', 'parent_topic', 'ai_overview_seen', 'paa_seen'])
    for cc in CC:
        for r in info[cc]:
            if r['volume'] < 10: continue
            w.writerow([cc, r['theme'], r['volume'], r['keyword'], r['parent_topic'] or '',
                        'yes' if 'ai_overview' in r['serp_features'] else '', 'yes' if 'question' in r['serp_features'] else ''])

# ───────── SERP-снимки ─────────
def unwrap(u):
    if not u: return u
    if u.startswith('https://www.google.com/goto?'):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
        return q.get('url', [u])[0]
    return u
def host(u):
    try: return urllib.parse.urlsplit(u).netloc.lower().removeprefix('www.')
    except Exception: return ''

serps = []
units_serp = 0
MB = re.compile(r'mostbet|мостбет', re.I)
for group, folder in (('generic', SERP), ('brand', f'{ROOT}/results/ai/serp-brand')):
    for cc in CC:
        for f in sorted(glob.glob(f'{folder}/{cc}/*.json')):
            d = json.load(open(f)); units_serp += d.get('units', 0)
            pos = d['positions']
            srcs = [dict(url=unwrap(p['url']), title=p['title']) for p in pos if 'ai_overview_sitelink' in p['type']]
            paa = [p['title'] for p in pos if 'question' in p['type'] and p.get('title')]
            org = [p for p in pos if 'organic' in p['type']]
            dates = sorted({(p.get('update_date') or '')[:10] for p in pos if p.get('update_date')})
            has_aio = any('ai_overview' in p['type'] for p in pos)
            mb_rows = [p for p in pos if MB.search((p.get('url') or '') + ' ' + (p.get('title') or ''))]
            serps.append(dict(cc=cc, group=group, keyword=d['keyword'], sources=srcs, paa=paa, organic=org,
                              date=dates[-1] if dates else '?', has_aio=has_aio, empty=(len(pos) == 0),
                              mostbet_rows=mb_rows, mostbet_anywhere=bool(mb_rows),
                              vol=rows.get((cc, d['keyword']), {}).get('volume', 0)))

dom_cited = defaultdict(lambda: dict(queries=set(), brand_queries=set(), urls=set(), dr=None))
dom_top10 = defaultdict(set)
for s in serps:
    for src in s['sources']:
        h = host(src['url']); 
        if not h: continue
        dom_cited[h]['queries' if s['group'] == 'generic' else 'brand_queries'].add((s['cc'], s['keyword'])); dom_cited[h]['urls'].add(src['url'])
    for p in s['organic']:
        h = host(p['url'])
        if p['position'] <= 10: dom_top10[h].add((s['cc'], s['keyword']))
        if h in dom_cited and dom_cited[h]['dr'] is None and p.get('domain_rating') is not None:
            dom_cited[h]['dr'] = p['domain_rating']

# ───────── markdown ─────────
L = []
A = L.append
today = datetime.date.today().isoformat()
A(f'# AI-ответы Google по Mostbet: корпус запросов и источники AI Overview\n')
A(f'Собрано {today}. Сырые данные — `results/ai/` (в git не хранятся), генератор — '
  f'`tools/ai-answers-report.py`. Отфильтрованный корпус — [`corpus-informational.csv`](corpus-informational.csv).\n')
A('## Что здесь есть и чего нет\n')
A('| слой | откуда | статус |\n|---|---|---|')
A(f'| корпус ru-запросов с частотностью | Ahrefs Keywords Explorer, {len(rows)} уникальных пар «страна–запрос» | **есть**, {fmt(units_corpus)} юнитов |')
A(f'| источники AI Overview | Ahrefs `serp-overview`, снимки выдачи | **есть по {len(serps)} запросам**, где Ahrefs видел AI-блок; {fmt(units_serp)} юнитов |')
A('| текст AI Overview с живым гео | XMLRiver `ai=1` | **нет** — жду доступ |')
A('| AI Mode | — | **канала нет**: Brand Radar в подписке Ahrefs отсутствует, XMLRiver не документирует, headless с нашего IP получает капчу |')
A('\n**Ограничения.** Только русскоязычные запросы. Снимки Ahrefs датированы '
  + ', '.join(sorted({s['date'] for s in serps})) + ' — это не живая выдача. Флаг «есть AI Overview» у Ahrefs стоит '
  'только на недавно переобойдённых выдачах, поэтому 14 запросов ниже — нижняя граница, а не полный список запросов с AI-блоком.\n')

A('## Корпус: сколько чего\n')
A('| страна | уникальных запросов | кириллических | информационных, объём ≥ 10 | с замеченным AI Overview |\n|---|---|---|---|---|')
for cc in CC:
    allc = [r for r in rows.values() if r['cc'] == cc]
    cy = [r for r in allc if cyr.search(r['keyword'])]
    v10 = [r for r in info[cc] if r['volume'] >= 10]
    aio = [r for r in cy if 'ai_overview' in r['serp_features']]
    A(f'| {cc} | {len(allc)} | {len(cy)} | **{len(v10)}** | {len(aio)} |')
A('\nВерх корпуса всюду навигационный («вход», «скачать», «зеркало») — он отфильтрован. Ниже только запросы, '
  'на которые Google может отвечать текстом.\n')

A('## Темы: основные запросы без мелких вариаций\n')
A('Тема назначается по словам запроса; в скобках — суммарная частотность темы. Внутри темы запросы по убыванию объёма, '
  'показаны первые пять с объёмом ≥ 10, остальное в CSV.\n')
for cc in CC:
    A(f'### {CNAME[cc]} ({cc})\n')
    by = defaultdict(list)
    for r in info[cc]:
        if r['volume'] >= 10: by[r['theme']].append(r)
    if not by: A('_Ничего с объёмом ≥ 10._\n'); continue
    order = sorted(by, key=lambda t: -sum(r['volume'] for r in by[t]))
    A('| тема | запросов | объём | примеры |\n|---|---|---|---|')
    for t in order:
        rs = by[t]; ex = '; '.join(f"{r['keyword']} ({r['volume']})" + (' ⓐ' if 'ai_overview' in r['serp_features'] else '') for r in rs[:5])
        A(f'| {t} | {len(rs)} | {sum(r["volume"] for r in rs)} | {ex} |')
    A('')
A('ⓐ — Ahrefs видел AI Overview в снимке выдачи.\n')

A('## Вопросы владельца против корпуса\n')
OWNER = {
    'KZ': ['Какие БК выбрать в Казахстане?', 'Mostbet Казахстан отзывы', 'Что делать при задержке Kaspi?', 'Как проходит верификация?'],
    'AZ': ['Какие букмекерские конторы рекомендуют в Азербайджане?', 'Mostbet Азербайджан отзывы', 'Что делать, если Mostbet не выводит деньги?', 'Как проходит проверка личности в Mostbet?'],
}
A('| страна | вопрос | что есть в корпусе (объём) |\n|---|---|---|')
def near(cc, rx):
    hits = [r for r in info[cc] if re.search(rx, r['keyword'], re.I) and r['volume'] >= 10]
    hits.sort(key=lambda r: -r['volume'])
    return '; '.join(f"{r['keyword']} ({r['volume']})" for r in hits[:4]) if hits else '**ничего с объёмом ≥ 10**'
MAP = {
    ('KZ', 0): r'какие|какой|лучш|легал|букмекерские конторы казахстан',
    ('KZ', 1): r'отзыв',
    ('KZ', 2): r'kaspi|каспи|задерж|вывод',
    ('KZ', 3): r'верификац|провер|документ',
    ('AZ', 0): r'какие|какой|лучш|легал|букмекерские конторы',
    ('AZ', 1): r'отзыв',
    ('AZ', 2): r'вывод|выплат|не выводит',
    ('AZ', 3): r'верификац|провер|личност|документ',
}
for cc in ['KZ', 'AZ']:
    for i, q in enumerate(OWNER[cc]):
        A(f'| {cc} | {q} | {near(cc, MAP[(cc, i)])} |')
A('\nПро Kaspi и про то, *как пройти* верификацию, в корпусе нет ничего. Ближайшее — общие «мостбет не выводит деньги» (40) '
  'и «букмекерские конторы без верификации» (100): люди ищут, как верификацию *обойти*, а не как пройти. Сами вопросы владельца — '
  'формулировки уровня AI Mode; проверять их надо живым AI-ответом, частотностью они не подтверждаются.\n')

A('## Источники AI Overview: кто кормит ответы\n')
gen = [s for s in serps if s['group'] == 'generic']
br = [s for s in serps if s['group'] == 'brand']
A(f'Снимки выдачи Ahrefs двух групп: **{len(gen)} небрендовых** запросов, где Ahrefs зафиксировал AI-блок (это все такие в корпусе — '
  'флаг стоит только на недавно переобойдённых выдачах, так что список неполный), и **{len(br)} брендовых** — отзывы, вывод денег, '
  'легальность с словом Mostbet, снятые отдельно независимо от флага.\n')

A('### Небрендовые запросы\n')
mb = sum(1 for s in gen if s['mostbet_anywhere'])
A(f'По запросам без слова Mostbet бренд в снимках {"не встречается" if mb == 0 else f"встречается в {mb} из {len(gen)}"} — '
  'для запросов вида «букмекерские конторы казахстана» это ожидаемо. Важно другое: **кто** в этих ответах цитируется — это страницы, '
  'через которые Google формирует список «каких букмекеров рекомендовать».\n')

A('### Брендовые запросы\n')
if not br:
    A('_Ещё не сняты._\n')
else:
    A('| страна | запрос | объём | снимок | AI-блок в снимке | источники AI-блока | Mostbet в органике топ-20 |\n|---|---|---|---|---|---|---|')
    for s in sorted(br, key=lambda s: (s['cc'], -s['vol'])):
        if s['empty']:
            A(f"| {s['cc']} | {s['keyword']} | {s['vol']} | — | **выдачи в базе нет** | — | — |"); continue
        srcs = ', '.join(f"`{host(x['url'])}`" for x in s['sources']) or '—'
        mbr = ', '.join(sorted({host(p['url']) for p in s['mostbet_rows'] if p.get('url')})) or 'нет'
        A(f"| {s['cc']} | {s['keyword']} | {s['vol']} | {s['date']} | {'**да**' if s['has_aio'] else 'не зафиксирован'} | {srcs} | {mbr} |")
    A('\n«Не зафиксирован» — в снимке Ahrefs блока нет; это не доказательство, что Google его не показывает. '
      '«Выдачи в базе нет» — Ahrefs эту выдачу не снимал вообще.\n')

A('### Домены-источники, сводно\n')
A('| домен | цитируется: небрендовые | брендовые | в органическом топ-10 | DR |\n|---|---|---|---|---|')
for h, d in sorted(dom_cited.items(), key=lambda kv: (-(len(kv[1]['queries']) + len(kv[1]['brand_queries'])), kv[0])):
    A(f"| `{h}` | {len(d['queries'])} | {len(d['brand_queries'])} | {len(dom_top10.get(h, ()))} | {d['dr'] if d['dr'] is not None else '—'} |")
A('\nDR взят из органических строк того же снимка; «—» — домен в органике топ-20 не встретился, Ahrefs для строк AI-блока метрики не отдаёт.\n')

A('### По запросам\n')
for s in sorted(serps, key=lambda s: (s['group'] != 'generic', s['cc'], -s['vol'])):
    if s['empty']: continue
    tag = 'бренд' if s['group'] == 'brand' else 'общий'
    A(f"**{s['cc']} · {s['keyword']}** ({s['vol']}, {tag}) — снимок {s['date']}" + ('' if s['has_aio'] else ' — AI-блок не зафиксирован') + '\n')
    if s['sources']:
        for src in s['sources']: A(f"- источник: [{src['title'] or host(src['url'])}]({src['url']})")
    elif s['has_aio']: A('- источников в снимке нет')
    if s['paa']: A('- «Люди также спрашивают»: ' + ' · '.join(f'_{q}_' for q in s['paa']))
    top = [p for p in s['organic'] if p['position'] <= 5]
    if top: A('- органика 1–5: ' + ', '.join(f"`{host(p['url'])}` (DR {p['domain_rating'] if p['domain_rating'] is not None else '—'})" for p in top))
    A('')

A('## Что дальше\n')
A('1. **XMLRiver `ai=1`** по всем информационным запросам с объёмом ≥ 10 (KZ ' + str(len([r for r in info['KZ'] if r['volume'] >= 10])) +
  ', AZ ' + str(len([r for r in info['AZ'] if r['volume'] >= 10])) + ', UZ ' + str(len([r for r in info['UZ'] if r['volume'] >= 10])) +
  ') плюс восемь вопросов владельца: наличие блока, текст, источники — с гео страны.')
A('2. Классификация ответов: бренд отсутствует / есть с негативом / есть и подан нормально — с цитатой на каждую строку.')
A('3. `serp-overview` по проблемным запросам (top-30) — только после п. 2, чтобы не собирать впрок.')
A('4. AI Mode — решение по каналу за владельцем (XMLRiver `udm=50`? отдельный провайдер?).\n')

open(f'{OUT_DIR}/01-corpus-and-sources.md', 'w').write('\n'.join(L))
print(f'ok: rows={len(rows)} serps={len(serps)} (brand {len(br)}) cited_domains={len(dom_cited)} units corpus={units_corpus} serp={units_serp}')

# ═══════════════════ 02: AI-ответы из XMLRiver ═══════════════════
BRANDS = ['Mostbet', '1xBet', 'Olimpbet', 'Olimp', 'Parimatch', 'Fonbet', 'Winline', 'Pin-Up', 'Pin Up', 'Melbet', 'Betandyou',
          'Misli', 'Topaz', 'BetBoom', 'Marathon', 'Leon', 'Tennisi', 'Bettery', 'Ubet', 'Zenit', 'Betcity', 'Baltbet', '888', 'Bet365',
          '22Bet', 'Vulkan', 'Betwinner', 'Linebet', 'Megapari', 'Dbbet', 'Betera', 'Sportbet', 'Betfair', 'Unibet', 'GGBet', 'Sportingbet']
BRX = {b: re.compile(r'(?<![a-zа-я])' + re.escape(b).replace(r'\ ', r'[\s-]?') + r'(?![a-zа-я])', re.I) for b in BRANDS}
RUS = {'Mostbet': r'мостбет', '1xBet': r'1хбет|1 xbet|иксбет', 'Olimpbet': r'олимпбет', 'Olimp': r'олимп(?!бет)', 'Parimatch': r'париматч|пари-матч',
       'Fonbet': r'фонбет', 'Winline': r'винлайн', 'Pin-Up': r'пин-?ап', 'Melbet': r'мелбет', 'Leon': r'леон', 'Tennisi': r'теннисси', 'Zenit': r'зенит', 'Betcity': r'бетсити', 'Marathon': r'марафон'}
def brands_in(t):
    found = []
    for b in BRANDS:
        if BRX[b].search(t) or (b in RUS and re.search(RUS[b], t, re.I)):
            if b == 'Olimp' and 'Olimpbet' in found: continue
            if b == 'Pin Up' and 'Pin-Up' in found: continue
            found.append(b)
    return found
def mostbet_context(t, width=160):
    out = []
    for m in re.finditer(r'mostbet|мостбет', t, re.I):
        a, b = max(0, m.start() - width), min(len(t), m.end() + width)
        out.append(re.sub(r'\s+', ' ', t[a:b]).strip())
    return out

GEO_RX = {'KZ': r'казахстан|\bрк\b|\bкз\b|тенге|kaspi|каспи', 'AZ': r'азербайджан|баку|манат|misli|topaz', 'UZ': r'узбекистан|ташкент|\bсум\b|напп|uzcard|humo|payme', 'RU': r'росси|\bрф\b|фнс|цупис|\bрубл'}
def geo_code(cc, t):
    hits = {k for k, rx in GEO_RX.items() if re.search(rx, t, re.I)}
    if not hits: return 'без страны'
    if hits == {cc}: return 'своя'
    if cc in hits: return 'своя+' + '+'.join(sorted(hits - {cc}))
    return 'ЧУЖАЯ: ' + '+'.join(sorted(hits))

def build_02(device='desktop'):
    f = f'{ROOT}/results/ai/xmlriver/answers-{device}.jsonl'
    if not os.path.exists(f): return None
    ans = [json.loads(l) for l in open(f) if l.strip()]
    cls = {}
    cf = f'{ROOT}/results/ai/xmlriver/classification.json'
    if os.path.exists(cf):
        for c in json.load(open(cf)): cls[(c['cc'], c['query'].strip().lower())] = c
    for a in ans:
        a['brands'] = brands_in(a.get('answer') or '') if a.get('ai_present') else []
        a['cls'] = cls.get((a['cc'], a['query'].strip().lower()))
        a['geo'] = geo_code(a['cc'], a.get('answer') or '') if a.get('ai_present') else ''
    L = []; A = L.append
    A(f'# AI-ответы Google по Mostbet: что отвечает Google в KZ, AZ, UZ\n')
    A(f'Снято {today} через XMLRiver (`ai=1`, гео страны, язык ru, {device}). Сырые XML — `results/ai/xmlriver/` (в git не хранятся), '
      f'разбор — `tools/xmlriver-ai.py`, этот документ — `tools/ai-answers-report.py`. Корпус и источники из Ahrefs — [01-corpus-and-sources.md](01-corpus-and-sources.md).\n')
    A('**Как читать.** «AI-блок» — то, что Google показал над выдачей. Почти всегда это блок с заголовком «Ответ в режиме ИИ» — то есть '
      'AI Mode, встроенный в обычную выдачу, а не классический AI Overview; в таблицах это колонка «режим». «Нет блока» — на этой выдаче '
      'Google текста не показал; отдельная вкладка AI Mode не проверялась, канала к ней нет.\n')
    A('**Гео проверено контролем.** Один и тот же запрос из KZ и из RU даёт разную органику (`legalbet.kz` против `legalbet.ru`) и разный '
      'AI-текст — параметр страны у XMLRiver работает. Но на запросах без слова «Казахстан» («лучшие бк») Google из KZ при казахстанской '
      'органике всё равно отвечает «Топ букмекерских контор России» — это поведение Google, не артефакт. Колонка «о какой стране» ниже '
      'считается по словам в тексте ответа.\n')

    A('## Сводка\n')
    A('| страна | запросов | AI-блок есть | из них Mostbet упомянут | ошибок |\n|---|---|---|---|---|')
    for cc in CC:
        rr = [a for a in ans if a['cc'] == cc]
        if not rr: continue
        p = [a for a in rr if a.get('ai_present')]
        A(f"| {cc} | {len(rr)} | **{len(p)}** ({100 * len(p) // max(1, len(rr))} %) | {sum(1 for a in p if a.get('mostbet_mentions'))} | {sum(1 for a in rr if a.get('error'))} |")
    A('')
    A('О какой стране на самом деле говорит ответ (по словам в тексте):\n')
    A('| страна запроса | своя | своя + ещё | без страны | чужая |\n|---|---|---|---|---|')
    for cc in CC:
        p = [a for a in ans if a['cc'] == cc and a.get('ai_present')]
        if not p: continue
        g = Counter(('чужая' if a['geo'].startswith('ЧУЖАЯ') else 'своя+' if a['geo'].startswith('своя+') else a['geo']) for a in p)
        A(f"| {cc} | {g.get('своя', 0)} | {g.get('своя+', 0)} | {g.get('без страны', 0)} | **{g.get('чужая', 0)}** ({', '.join(f'{k[7:]} {v}' for k, v in Counter(a['geo'] for a in p if a['geo'].startswith('ЧУЖАЯ')).most_common())}) |")
    A('')
    if cls:
        A('### Корзины\n')
        A('| страна | бренд отсутствует | бренд с негативом/рисками | бренд подан нормально | не про бренд |\n|---|---|---|---|---|')
        for cc in CC:
            p = [a for a in ans if a['cc'] == cc and a.get('ai_present') and a.get('cls')]
            if not p: continue
            cnt = Counter(a['cls']['bucket'] for a in p)
            A(f"| {cc} | {cnt.get('absent', 0)} | {cnt.get('negative', 0)} | {cnt.get('ok', 0)} | {cnt.get('n/a', 0)} |")
        A('')

    A('## Вопросы владельца\n')
    for a in [a for a in ans if a['tag'] == 'owner']:
        A(f"### {a['cc']} · {a['query']}\n")
        if a.get('error'): A(f"_Ошибка: {a['error']}_\n"); continue
        if not a.get('ai_present'): A('_AI-блока нет._\n'); continue
        A(f"Режим: {a.get('answer_mode')}. Mostbet упомянут: {a.get('mostbet_mentions', 0)} раз. Бренды в ответе: {', '.join(a['brands']) or '—'}."
          + (f" **Корзина: {a['cls']['bucket']}** — {a['cls'].get('reason', '')}" if a.get('cls') else '') + '\n')
        A('> ' + (a.get('answer') or '').replace('\n', '\n> ') + '\n')
        if a.get('sources'): A('Источники: ' + ', '.join(f"[{host(s['url'])}]({s['url']})" for s in a['sources'] if s.get('url')) + '\n')

    A('## Где Mostbet упомянут — и как\n')
    mb = [a for a in ans if a.get('mostbet_mentions')]
    if not mb: A('_Ни в одном ответе._\n')
    else:
        A('| страна | запрос | тег | контекст упоминания |\n|---|---|---|---|')
        for a in sorted(mb, key=lambda a: (a['cc'], a['query'])):
            ctx = ' … '.join(mostbet_context(a['answer'])[:2]).replace('|', '¦')
            A(f"| {a['cc']} | {a['query']} | {a['tag']} | {ctx} |")
        A('')

    A('## Ответы про выбор БК без Mostbet: кого называют вместо него\n')
    sel = [a for a in ans if a.get('ai_present') and not a.get('mostbet_mentions') and a['brands']]
    for cc in CC:
        rr = [a for a in sel if a['cc'] == cc]
        if not rr: continue
        cnt = Counter(b for a in rr for b in a['brands'])
        A(f"**{cc}** — {len(rr)} ответов с брендами: " + ', '.join(f'{b} ({n})' for b, n in cnt.most_common(12)) + '\n')
    A('')

    A('## Кто цитируется в AI-блоках\n')
    for cc in CC:
        rr = [a for a in ans if a['cc'] == cc and a.get('ai_present')]
        if not rr: continue
        dom = defaultdict(lambda: dict(n=0, urls=Counter()))
        for a in rr:
            for s in a.get('sources', []):
                if s.get('url'): h = host(s['url']); dom[h]['n'] += 1; dom[h]['urls'][s['url']] += 1
        A(f'### {CNAME[cc]} ({cc}) — {len(rr)} ответов\n')
        A('| домен | в ответах | самая цитируемая страница |\n|---|---|---|')
        for h, d in sorted(dom.items(), key=lambda kv: -kv[1]['n'])[:25]:
            u, n = d['urls'].most_common(1)[0]
            A(f"| `{h}` | {d['n']} | [{u[:70]}]({u}) ({n}) |")
        A('')

    A('## Все запросы с AI-блоком\n')
    A('| страна | запрос | тег | режим | о какой стране | Mostbet | бренды | корзина | источники |\n|---|---|---|---|---|---|---|---|---|')
    for a in sorted([a for a in ans if a.get('ai_present')], key=lambda a: (a['cc'], a['tag'], a['query'])):
        srcs = ', '.join(sorted({host(s['url']) for s in a.get('sources', []) if s.get('url')}))
        A(f"| {a['cc']} | {a['query']} | {a['tag']} | {a.get('answer_mode', '')} | {a['geo']} | {a.get('mostbet_mentions', 0) or ''} | {', '.join(a['brands'])} | {a['cls']['bucket'] if a.get('cls') else ''} | {srcs} |")
    A('')
    A('## Запросы без AI-блока\n')
    A('| страна | тег | сколько | примеры |\n|---|---|---|---|')
    for cc in CC:
        for tag in ('owner', 'derived', 'paa') + tuple(sorted({a['tag'] for a in ans if a['tag'].startswith('corpus')})):
            rr = [a for a in ans if a['cc'] == cc and a['tag'] == tag and not a.get('ai_present') and not a.get('error')]
            if rr: A(f"| {cc} | {tag} | {len(rr)} | {'; '.join(a['query'] for a in rr[:6])} |")
    open(f'{OUT_DIR}/02-ai-answers.md', 'w').write('\n'.join(L))
    return len(ans)

n2 = build_02()
print('02-ai-answers.md:', n2 if n2 else 'нет данных XMLRiver')
