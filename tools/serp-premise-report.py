#!/usr/bin/env python3
"""Сводка шага 0 по niche-scan/premise-serp.jsonl: длина выдачи (топ-20) и чьи в ней сайты.
Классы: main — главный домен оператора/бренда (список MAIN); lookalike — имя бренда в домене, но не главный
(зеркало или аффилиат, снаружи не различить); store — магазины приложений; social — соцсети и вики; third — прочие."""
import json, collections, urllib.parse, re
STORE = re.compile(r'(play\.google|apps\.apple|uptodown|apkpure|softonic|malavida|aptoide|an1\.com|softportal|androidp1|divxland|appstor|cafebazaar|rustore|playstore\.com|ldplayer|gameloop|trashbox|phoneky)')
SOCIAL = re.compile(r'(youtube|facebook|instagram|^x\.com|t\.me|vk\.ru|tiktok|wikipedia|wikiwand|^t\.co$|wa\.me|eksisozluk|fandom|pinterest)')
# главный домен: хост равен ему или является его поддоменом
MAIN = {'mostbet': ['mostbet.com'], '1xbet': ['1xbet.com'], 'melbet': ['melbet.com'], '1win': ['1win.com'], 'pin up casino': ['pin-up.world'],
        'betwinner': ['betwinner.com'], 'betandyou': ['betandyou.com'], 'linebet': ['linebet.com'], 'olimpbet': ['olimpbet.kz'],
        'fonbet kz': ['fon.bet', 'fonbet.kz'], 'topaz': ['topaz.az', 'etopaz.az'], 'betandreas': [], 'bets10': [], 'nesine': ['nesine.com'],
        '1xbet kg': ['1xbet.com'], 'melbet kg': ['melbet.com'], 'netflix': ['netflix.com'], 'aliexpress': ['aliexpress.com', 'aliexpress.ru'],
        'telegram': ['telegram.org'], 'whatsapp': ['whatsapp.com'], 'temu': ['temu.com'], 'spotify': ['spotify.com'], 'pubg mobile': ['pubgmobile.com', 'pubg.com'],
        'free fire': ['garena.com'], 'click uz': ['click.uz'], 'uzum market': ['uzum.uz'], 'kaspi': ['kaspi.kz'], 'kolesa kz': ['kolesa.kz'],
        'kapital bank': ['kapitalbank.az', 'birbank.az', 'kapital.bank'], 'tap az': ['tap.az'], 'trendyol': ['trendyol.com'], 'hepsiburada': ['hepsiburada.com'],
        'mbank': ['mbank.kg'], 'lalafo': ['lalafo.kg']}
TOKEN = {'1xbet': '1x', '1xbet kg': '1x', 'melbet': 'mel', 'melbet kg': 'mel', 'pin up casino': 'pin', 'fonbet kz': 'fon', 'betandreas': 'andreas', 'olimpbet': 'olimp'}
def key(q):
    return q if q in MAIN else q.split()[0]
def cls(host, q):
    k = key(q)
    if k in MAIN:
        if any(host == d or host.endswith('.' + d) for d in MAIN[k]): return 'main'
        if STORE.search(host): return 'store'
        if re.search(TOKEN.get(k, k.split()[0]), host.replace('-', '')): return 'lookalike'
    if STORE.search(host): return 'store'
    if SOCIAL.search(host): return 'social'
    return 'third'
R = collections.defaultdict(dict)
for l in open('niche-scan/premise-serp.jsonl'):
    r = json.loads(l); R[(r['cc'], r['kind'], r['query'])][r['page']] = r
def group(kind, q):
    if kind == 'bet': return 'bet-mod' if q.startswith('mostbet ') else 'bet-brand'
    return kind
CC = ['UZ', 'KZ', 'AZ', 'TR', 'KG']; K = ['main', 'lookalike', 'store', 'social', 'third']
rows = {}
for (cc, kind, q), pp in R.items():
    docs = pp[1].get('docs', []) + pp.get(2, {}).get('docs', [])
    c = collections.Counter(cls(urllib.parse.urlsplit(d['url']).netloc.lower().removeprefix('www.'), q) for d in docs)
    rows[(cc, kind, q)] = dict(n=len(docs), p2=bool(pp.get(2, {}).get('docs')), c=c)
print('## по группам: среднее результатов в топ-20 | пустых 2-х страниц | доли классов ' + ' '.join(K))
for cc in CC:
    for g in ['bet-brand', 'bet-mod', 'control', 'bet-generic', 'control-generic']:
        rr = [v for (c, k, q), v in rows.items() if c == cc and group(k, q) == g]
        tot = sum(sum(v['c'].values()) for v in rr) or 1; cs = sum((v['c'] for v in rr), collections.Counter())
        print(f"{cc} {g:15} {sum(v['n'] for v in rr)/len(rr):5.1f}  {sum(not v['p2'] for v in rr)}/{len(rr):<3} " + ' '.join(f"{100*cs[k]/tot:4.0f}%" for k in K))
print('\n## брендовые запросы беттинга: результатов в топ-20 по странам (* = 2-я страница пустая); main/lookalike/third — сумма по 5 странам')
for kind in ['bet', 'control']:
    qs = sorted({q for (c, k, q) in rows if k == kind}, key=lambda q: (q.startswith('mostbet '), q))
    for q in qs:
        cells = []; cs = collections.Counter()
        for cc in CC:
            v = rows.get((cc, kind, q))
            cells.append(f"{v['n']:2}{'*' if not v['p2'] else ' '}" if v else '  - '); cs += v['c'] if v else collections.Counter()
        t = sum(cs.values()) or 1
        print(f"{kind:7} {q:18} " + ' '.join(cells) + f"   main {100*cs['main']/t:3.0f}%  look {100*cs['lookalike']/t:3.0f}%  third {100*cs['third']/t:3.0f}%")
