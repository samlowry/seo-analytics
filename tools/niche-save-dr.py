#!/usr/bin/env python3
"""Добавляет DR из выгрузки Ahrefs batch-analysis (файл tool-results) в niche-scan/data/dr.json. Запуск: niche-save-dr.py <file>..."""
import sys, json, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = f'{ROOT}/niche-scan/data/dr.json'
dr = json.load(open(out)) if os.path.exists(out) else {}
for src in sys.argv[1:]:
    for p in json.load(open(src)):
        t = json.loads(p['text'])
        if 'targets' in t:
            for x in t['targets']:
                dom = x['url'].replace('https://', '').replace('http://', '').strip('/').removeprefix('www.')
                dr[dom] = x.get('domain_rating')
        if 'apiUsageCosts' in t: print('units', t['apiUsageCosts'].get('units-cost-total-actual'))
json.dump(dr, open(out, 'w'), ensure_ascii=False, indent=0)
print('domains with DR:', len(dr), ' e.g.', list(dr.items())[:5])
