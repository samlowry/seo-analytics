#!/usr/bin/env python3
"""Шаг 3 niche-scan: оценка ниш по снимкам выдачи.
Вход: niche-scan/seeds.json, data/keywords.jsonl, data/sample.jsonl, data/serp.jsonl, data/dr.json (домен → DR Ahrefs).
Выход: niche-scan/data/keys-scored.jsonl (по ключу), niche-scan/data/niches.csv (по нише × стране).

Слабый результат в топ-10 — любое из:
  ugc     форум, вопросы-ответы, блог-платформа (список UGC ниже); соцсети не считаются — там официальные аккаунты;
  low_dr  DR домена < LOW_DR по Ahrefs (домены без DR не считаются слабыми по этому признаку);
  lang    страница не на языке запроса: локальный запрос (uz/az с местными буквами) — заголовок кириллицей;
          русский запрос — заголовок без кириллицы; не считается у доменов с DR >= HIGH_DR (Google Translate, Википедия).
Тонкие и старые страницы не мерились.
Целевая позиция ключа — лучшая позиция слабого результата в топ-10. Визиты = частотность × min(cps, 1) × доля кликов позиции.
cps (clicks per search, Ahrefs) учитывает поиски без клика; если его нет — cps ниши в стране, взвешенный по частотности, иначе тот же по всем странам, иначе 0,8.
Закрытый ключ: в топ-20 не больше CLOSED_N результатов (для ключей со снятой второй страницей) и слабых в топ-10 нет.
Закрытая ниша: закрыты 2 и больше из 3 головных ключей.
Оценка ниши = визиты выборки × (частотность ниши / частотность выборки) — экстраполяция на неснятые ключи."""
import json, re, os, csv, statistics, collections, itertools, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = f'{ROOT}/niche-scan/data'
LOW_DR, HIGH_DR, CLOSED_N = 30, 70, 12
SHARE = [0.39, 0.18, 0.11, 0.08, 0.06, 0.05, 0.04, 0.035, 0.03, 0.025]
# Соцсети (instagram, facebook, x, tiktok, t.me, vk, ok) сюда не входят: в головных запросах там официальные аккаунты сущности.
UGC = re.compile(r'(^|\.)(reddit\.com|quora\.com|pinterest\.[a-z.]+|'
                 r'otvet\.mail\.ru|answers\.mail\.ru|blogspot\.com|wordpress\.com|livejournal\.com|pikabu\.ru|dzen\.ru|sites\.google\.com|medium\.com|tgstat\.[a-z]+|'
                 r'znanija\.com|brainly\.[a-z.]+|eksisozluk\.com|uludagsozluk\.com|onedio\.com|teletype\.in|vc\.ru|habr\.com|tumblr\.com|fandom\.com|ask\.fm|'
                 r'threads\.net|linkedin\.com|wattpad\.com|ficbook\.net|scribd\.com|studfile\.net|studopedia\.[a-z]+|myshared\.ru|infourok\.ru|nsportal\.ru|multiurok\.ru)$')
FORUM = re.compile(r'(^forum\.|\.forum\.|/forum|/threads?/|/topic|/questions?/|/viewtopic)')
OWNER = re.compile(r'(\.gov\.[a-z]{2}$|^gov\.[a-z]{2}$|\.gov$|egov\.kz$|e-gov\.az$|turkiye\.gov\.tr$|play\.google\.com$|apps\.apple\.com$|\.edu\.[a-z]{2}$|\.k12\.tr$|\.bel\.tr$|\.mil\.)')
SUF2 = {'com.tr', 'gov.tr', 'org.tr', 'net.tr', 'edu.tr', 'k12.tr', 'gen.tr', 'bel.tr', 'av.tr', 'gov.uz', 'co.uz', 'com.uz', 'org.uz', 'edu.uz', 'gov.kz', 'com.kz', 'edu.kz', 'org.kz',
        'gov.az', 'com.az', 'edu.az', 'org.az', 'net.az', 'gov.kg', 'com.kg', 'org.kg', 'edu.kg', 'co.uk', 'com.ua', 'org.ua', 'com.ru', 'msk.ru', 'spb.ru', 'com.br', 'co.in', 'com.au', 'org.ru'}
def host(u): return urllib.parse.urlsplit(u).netloc.lower().split(':')[0].removeprefix('www.')
def regdom(h):
    p = h.split('.')
    return '.'.join(p[-3:]) if len(p) >= 3 and '.'.join(p[-2:]) in SUF2 else '.'.join(p[-2:])
def cyr(s): return len(re.findall('[а-яё]', s.lower()))
def lat(s): return len(re.findall('[a-z]', s.lower()))
LOCAL = {'uz': re.compile(r"[ʻ'‘’]|\b(va|uchun|bilan|qanday|yangi|kun|yil|haqida|olish|narxi|bugun|ertangi|sinf|ish|qo|o'z|ozbek|o'zbek|tilida|kino|ob-havo|namoz|vaqti)\b|sh|ch|q"),
         'az': re.compile(r'[əğışçöü]|\b(və|üçün|ilə|necə|yeni|gün|il|haqqında|qiyməti|bu gün|sabah|sinif)\b'), 'tr': re.compile(r'.'), 'ru': re.compile(r'[а-яё]')}
def mismatch(q, qlang, title):
    if not title or title.startswith('http') or '/' in title.split()[0]: return False  # вместо заголовка URL — язык не определить
    if qlang == 'ru': return cyr(q) > 0 and cyr(title) == 0 and lat(title) > 5
    if qlang in ('uz', 'az') and LOCAL[qlang].search(q.lower()) and cyr(q) == 0: return cyr(title) > lat(title)
    return False
seeds = {n['id']: n for n in json.load(open(f'{ROOT}/niche-scan/seeds.json'))['niches']}
DR = json.load(open(f'{D}/dr.json')) if os.path.exists(f'{D}/dr.json') else {}
KW = [json.loads(l) for l in open(f'{D}/keywords.jsonl')]
SAMPLE = [json.loads(l) for l in open(f'{D}/sample.jsonl')]
SERP = collections.defaultdict(dict)
for l in open(f'{D}/serp.jsonl'):
    r = json.loads(l); SERP[(r['cc'], r['keyword'])][r['page']] = r
def wcps(rs):
    v = [(r['cps'], r['volume']) for r in rs if r['cps'] is not None]
    return sum(c * w for c, w in v) / sum(w for _, w in v) if v else None
cps_niche = {nid: wcps(list(g)) for nid, g in itertools.groupby(sorted(KW, key=lambda r: r['niche']), key=lambda r: r['niche'])}
cps_med = {}
for (cc, nid), g in itertools.groupby(sorted(KW, key=lambda r: (r['cc'], r['niche'])), key=lambda r: (r['cc'], r['niche'])):
    c = wcps(list(g)); cps_med[(cc, nid)] = c if c is not None else cps_niche.get(nid) or 0.8
keys = []
for s in SAMPLE:
    pp = SERP.get((s['cc'], s['keyword']), {}); p1 = pp.get(1, {})
    if 'docs' not in p1 and not p1.get('empty'): keys.append(dict(s, status='error')); continue
    docs = p1.get('docs', [])[:10]
    n20 = len(docs) + len(pp.get(2, {}).get('docs', [])) if s['pages'] == 2 else None
    pos = []
    for i, d in enumerate(docs):
        h = host(d['url']); rd = regdom(h); dr = DR.get(rd, DR.get(h))
        why = []
        if UGC.search(h) or FORUM.search(h + urllib.parse.urlsplit(d['url']).path.lower()): why.append('ugc')
        if dr is not None and dr < LOW_DR: why.append('low_dr')
        if mismatch(s['keyword'], s['lang'], d['title']) and (dr is None or dr < HIGH_DR): why.append('lang')
        pos.append(dict(p=i + 1, host=h, dom=rd, dr=dr, owner=bool(OWNER.search(h)), weak=why))
    weak = [x for x in pos if x['weak']]
    best = weak[0]['p'] if weak else None
    cps = s['cps'] if s['cps'] is not None else cps_med[(s['cc'], s['niche'])]
    visits = s['volume'] * min(cps, 1.0) * SHARE[best - 1] if best else 0
    drs = [x['dr'] for x in pos if x['dr'] is not None]
    keys.append(dict(s, status='ok', n_top10=len(docs), n_top20=n20, best_pos=best, visits=round(visits), cps_used=cps,
                     closed=bool(n20 is not None and n20 <= CLOSED_N and not weak), weak_n=len(weak),
                     why=collections.Counter(w for x in weak for w in x['weak']), owner_n=sum(x['owner'] for x in pos),
                     dr_median=statistics.median(drs) if drs else None, dr_known=len(drs), top=[f"{x['p']}:{x['host']}:{x['dr']}:{'+'.join(x['weak'])}" for x in pos]))
with open(f'{D}/keys-scored.jsonl', 'w') as fh:
    for k in keys: fh.write(json.dumps(k, ensure_ascii=False, default=dict) + '\n')
vol = collections.defaultdict(int)
for r in KW: vol[(r['cc'], r['niche'], r['lang'])] += r['volume']
out = []
for (cc, nid), g in itertools.groupby(sorted(keys, key=lambda k: (k['cc'], k['niche'])), key=lambda k: (k['cc'], k['niche'])):
    g = [k for k in g if k['status'] == 'ok']
    if not g: continue
    lang = g[0]['lang']; nv = vol[(cc, nid, lang)]; sv = sum(k['volume'] for k in g); sv_vis = sum(k['visits'] for k in g)
    head = [k for k in g if k['n_top20'] is not None]
    closed_head = sum(k['closed'] for k in head)
    drs = [k['dr_median'] for k in g if k['dr_median'] is not None]
    pos_total = sum(k['n_top10'] for k in g)
    why = sum((k['why'] for k in g), collections.Counter())
    out.append(dict(cc=cc, niche=nid, name=seeds[nid]['name'], bet=seeds[nid]['bet'], lang=lang, niche_volume=nv, sample_keys=len(g), sample_volume=sv,
                    sample_visits=sv_vis, est_visits=round(sv_vis * nv / sv) if sv else 0, weak_keys=sum(1 for k in g if k['best_pos']),
                    best_pos_median=statistics.median([k['best_pos'] for k in g if k['best_pos']]) if any(k['best_pos'] for k in g) else None,
                    closed_head=f'{closed_head}/{len(head)}', culled=closed_head >= 2, dr_median=statistics.median(drs) if drs else None,
                    owner_share=round(sum(k['owner_n'] for k in g) / pos_total, 2) if pos_total else None,
                    weak_ugc=why['ugc'], weak_low_dr=why['low_dr'], weak_lang=why['lang'],
                    top20_head=statistics.mean([k['n_top20'] for k in head]) if head else None))
with open(f'{D}/niches.csv', 'w') as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print(f'keys scored: {sum(k["status"]=="ok" for k in keys)}, errors: {sum(k["status"]=="error" for k in keys)}; niches: {len(out)}')
