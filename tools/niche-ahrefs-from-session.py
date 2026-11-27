#!/usr/bin/env python3
"""Находит в транскрипте сессии Claude Code вызовы keywords-explorer-matching-terms и путь к файлу ответа (tool-results),
печатает country, первые слова keywords и путь — чтобы разложить выгрузки по kw-<CC>-<lang>-<group>.json через niche-save-ahrefs.py.
Запуск: python3 tools/niche-ahrefs-from-session.py <session.jsonl>"""
import sys, json, re
calls = {}
for l in open(sys.argv[1]):
    try: m = json.loads(l)
    except Exception: continue
    c = m.get('message', {}).get('content')
    if not isinstance(c, list): continue
    for b in c:
        if b.get('type') == 'tool_use' and b.get('name', '').endswith('keywords-explorer-matching-terms'): calls[b['id']] = b['input']
        if b.get('type') == 'tool_result' and b.get('tool_use_id') in calls:
            cont = b['content']; txt = cont if isinstance(cont, str) else ''.join(x.get('text', '') for x in cont)
            p = re.search(r'saved to (\S+\.txt)', txt); i = calls[b['tool_use_id']]
            print(i['country'], i['limit'], i['keywords'][:40], p.group(1) if p else 'INLINE')
