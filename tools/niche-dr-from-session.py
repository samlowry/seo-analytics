#!/usr/bin/env python3
"""Добавляет в niche-scan/data/dr.json DR из ответов batch-analysis, найденных в транскрипте сессии Claude Code
(основной или субагента) — и пришедших в ответ целиком, и сохранённых в tool-results.
Запуск: python3 tools/niche-dr-from-session.py <transcript.jsonl>..."""
import sys, json, os, re
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = f'{ROOT}/niche-scan/data/dr.json'
dr = json.load(open(out)) if os.path.exists(out) else {}
before, calls, units, n = len(dr), set(), 0, 0
def take(t):
    global units
    for m in re.finditer(r'\{\s*"targets":\s*\[.*?\]\s*\}', t, re.S):
        for x in json.loads(m.group(0))['targets']:
            dom = x['url'].replace('https://', '').replace('http://', '').strip('/').removeprefix('www.')
            dr[dom] = x.get('domain_rating')
    for m in re.finditer(r'"units-cost-total-actual":\s*(\d+)', t): units += int(m.group(1))
for src in sys.argv[1:]:
    for l in open(src):
        try: msg = json.loads(l)
        except Exception: continue
        c = msg.get('message', {}).get('content')
        if not isinstance(c, list): continue
        for b in c:
            if b.get('type') == 'tool_use' and b.get('name', '').endswith('batch-analysis'): calls.add(b['id'])
            if b.get('type') == 'tool_result' and b.get('tool_use_id') in calls:
                cont = b['content']; t = cont if isinstance(cont, str) else ''.join(x.get('text', '') for x in cont)
                p = re.search(r'saved to (\S+\.txt)', t)
                if p: t = ''.join(x['text'] for x in json.load(open(p.group(1))))
                take(t); n += 1
json.dump(dr, open(out, 'w'), ensure_ascii=False, indent=0)
print(f'batch results: {n}, units: {units}, domains with DR: {before} -> {len(dr)}')
