#!/usr/bin/env python3
"""Выбирает домены из топ-10 снимков (niche-scan/data/serp.jsonl), для которых брать DR в Ahrefs:
по частоте появления, пока не покрыто COVER позиций или не набрано MAX доменов. Пишет батчи по 100 в data/dr-batches.json
и печатает покрытие. Домены из UGC-списка и магазинов приложений пропускаются — они и так классифицированы."""
import json, os, sys, collections, importlib.util
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('sc', f'{ROOT}/tools/niche-score.py')
src = open(f'{ROOT}/tools/niche-score.py').read().split('seeds = ')[0]  # только функции и константы, без расчёта
ns = {'__file__': f'{ROOT}/tools/niche-score.py'}; exec(src, ns)
MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
done = set(json.load(open(f'{ROOT}/niche-scan/data/dr.json'))) if os.path.exists(f'{ROOT}/niche-scan/data/dr.json') else set()
c = collections.Counter(); total = 0
for l in open(f'{ROOT}/niche-scan/data/serp.jsonl'):
    r = json.loads(l)
    if r['page'] != 1 or r['cc'] == 'TR': continue  # TR снята 25.11.2026
    for d in r.get('docs', [])[:10]:
        h = ns['host'](d['url']); total += 1
        if ns['UGC'].search(h) or ns['OWNER'].search(h): continue
        c[ns['regdom'](h)] += 1
todo = [d for d, _ in c.most_common() if d not in done][:MAX]
cov = sum(c[d] for d in todo) + sum(c[d] for d in done if d in c)
print(f'positions {total}, classifiable domains {len(c)}, picked {len(todo)} new (+{len(done)} known), cover {cov}/{sum(c.values())} = {cov/max(1,sum(c.values())):.0%}')
json.dump([todo[i:i + 100] for i in range(0, len(todo), 100)], open(f'{ROOT}/niche-scan/data/dr-batches.json', 'w'))
