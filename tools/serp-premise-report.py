#!/usr/bin/env python3
"""Сводка шага 0 по niche-scan/premise-serp.jsonl: размер выдачи (топ-20) и чьи в ней сайты."""
import json, collections, urllib.parse, re
STORE = re.compile(r'(play\.google|apps\.apple|uptodown|apkpure|softonic|malavida|aptoide|an1\.com|softportal|androidp1|divxland|appstor|cafebazaar|rustore|playstore\.com|ldplayer|gameloop|trashbox|phoneky)')
SOCIAL = re.compile(r'(youtube|facebook|instagram|^x\.com|t\.me|vk\.ru|tiktok|wikipedia|wikiwand|t\.co$|wa\.me|eksisozluk|fandom)')
TOKENS = {'mostbet': 'mostbet', '1xbet': '1x', 'melbet': 'mel', '1win': '1win', 'pin up casino': 'pin', 'betwinner': 'betwinner', 'betandyou': 'betandyou',
          'linebet': 'linebet', 'olimpbet': 'olimp', 'fonbet kz': 'fon', 'topaz': 'topaz', 'betandreas': 'andreas', 'bets10': 'bets10', 'nesine': 'nesine',
          '1xbet kg': '1x', 'melbet kg': 'mel', 'netflix': 'netflix', 'aliexpress': 'aliexpress', 'telegram': 'telegram', 'whatsapp': 'whatsapp', 'temu': 'temu',
          'spotify': 'spotify', 'pubg mobile': 'pubg', 'free fire': 'garena|freefire', 'click uz': 'click', 'uzum market': 'uzum', 'kaspi': 'kaspi',
          'kolesa kz': 'kolesa', 'kapital bank': 'kapital|birbank', 'tap az': 'tap.az', 'trendyol': 'trendyol', 'hepsiburada': 'hepsiburada', 'mbank': 'mbank', 'lalafo': 'lalafo'}
def cls(host, q):
    tok = TOKENS.get(q, TOKENS.get(q.split()[0], '^$'))
    if re.search(tok, host.replace('-', '')) and not STORE.search(host): return 'brand'
    if STORE.search(host): return 'store'
    if SOCIAL.search(host): return 'social'
    return 'third'
R = collections.defaultdict(dict)
for l in open('niche-scan/premise-serp.jsonl'):
    r = json.loads(l); R[(r['cc'], r['kind'], r['query'])][r['page']] = r
def group(cc, kind, q):
    if kind in ('control', 'bet-generic', 'control-generic'): return kind
    return 'bet-mod' if q.startswith('mostbet ') else 'bet-brand'
S = collections.defaultdict(lambda: dict(n=0, res=0, p2empty=0, c=collections.Counter()))
for (cc, kind, q), pp in R.items():
    docs = pp[1].get('docs', []) + pp.get(2, {}).get('docs', [])
    g = S[(cc, group(cc, kind, q))]; g['n'] += 1; g['res'] += len(docs); g['p2empty'] += not pp.get(2, {}).get('docs')
    for d in docs: g['c'][cls(urllib.parse.urlsplit(d['url']).netloc.lower().removeprefix('www.'), q)] += 1
print('cc  group      queries  avg_results_top20  page2_empty  brand store social third')
for cc in ['UZ', 'KZ', 'AZ', 'TR', 'KG']:
    for gname in ['bet-brand', 'bet-mod', 'control', 'bet-generic', 'control-generic']:
        g = S[(cc, gname)]; t = sum(g['c'].values()) or 1
        print(f"{cc}  {gname:15} {g['n']:3}  {g['res']/g['n']:6.1f}  {g['p2empty']:3}/{g['n']:<3}  " + '  '.join(f"{100*g['c'][k]/t:4.0f}%" for k in ['brand', 'store', 'social', 'third']))
