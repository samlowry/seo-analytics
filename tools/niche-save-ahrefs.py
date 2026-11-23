#!/usr/bin/env python3
"""Сохраняет выгрузку Ahrefs MCP (файл tool-results) в niche-scan/data/kw-<CC>-<lang>-<group>.json и печатает строки и юниты.
Запуск: python3 tools/niche-save-ahrefs.py <tool-result.txt> <CC> <lang> <group>"""
import sys, json, os
src, cc, lang, grp = sys.argv[1:5]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parts = json.load(open(src)); data = None; cost = None
for p in parts:
    t = json.loads(p['text'])
    if 'keywords' in t: data = t
    if 'apiUsageCosts' in t: cost = t['apiUsageCosts']
out = f'{ROOT}/niche-scan/data/kw-{cc}-{lang}-{grp}.json'
json.dump(dict(cc=cc, lang=lang, group=grp, keywords=data['keywords']), open(out, 'w'), ensure_ascii=False)
k = data['keywords']
print(f"{out.split('/')[-1]}: rows={len(k)} min_vol={min(x['volume'] for x in k) if k else 0} units={cost and cost.get('units-cost-total-actual')}")
