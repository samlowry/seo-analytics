#!/usr/bin/env python3
"""Задача 2: обычная выдача Google через XMLRiver (без AI) с оператором site:<tld>, страницы 1–10.
Выход: results/ai/site/<CC>/<sha>-p<N>.xml и results/ai/site/results.jsonl (url, title, snippet, query, page, pos)."""
import sys, os, re, json, time, hashlib, urllib.request, urllib.parse, xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f'{ROOT}/results/ai/site'
COUNTRY = {'KZ': 2398, 'AZ': 2031, 'UZ': 2860}
TLD = {'KZ': 'kz', 'AZ': 'az', 'UZ': 'uz'}
env = {k.strip(): v.split('#')[0].strip() for k, v in (l.split('=', 1) for l in open(f'{ROOT}/.env') if '=' in l and not l.startswith('#'))}
QUERIES = ['mostbet', 'мостбет', 'mostbet отзывы', 'мостбет отзывы', 'букмекерские конторы', 'лучшие букмекерские конторы']
PAGES = int(sys.argv[1]) if len(sys.argv) > 1 else 10
def fetch(cc, q, page):
    p = dict(user=env['XMLRIVER_USER'], key=env['XMLRIVER_KEY'], query=f'{q} site:{TLD[cc]}', country=COUNTRY[cc], lr='ru', device='desktop', page=page)
    url = env.get('XMLRIVER_ENDPOINT', 'https://xmlriver.com/search/xml') + '?' + urllib.parse.urlencode(p)
    for i in range(4):
        try:
            with urllib.request.urlopen(url, timeout=90) as f: raw = f.read().decode('utf-8', 'replace')
        except Exception as e: time.sleep(15 * (i + 1)); continue
        m = re.search(r'<error code="(\d+)"', raw)
        if m and m.group(1) in ('110', '115', '201', '500'): time.sleep(20 if m.group(1) == '500' else 60); continue
        return raw
    return '<yandexsearch><response><error code="999">retries</error></response></yandexsearch>'
jobs = [(cc, q, pg) for cc in COUNTRY for q in QUERIES for pg in range(1, PAGES + 1)]
def path(cc, q, pg):
    os.makedirs(f'{OUT}/{cc}', exist_ok=True); return f"{OUT}/{cc}/{hashlib.sha1(q.encode()).hexdigest()[:10]}-p{pg}.xml"
pending = [j for j in jobs if not os.path.exists(path(*j))]
print(f'jobs {len(jobs)}, to fetch {len(pending)}', flush=True)
def work(j): open(path(*j), 'w').write(fetch(*j)); return j
done = 0
with ThreadPoolExecutor(3) as ex:
    for fut in as_completed([ex.submit(work, j) for j in pending]):
        done += 1
        if done % 20 == 0 or done == len(pending): print(f'  {done}/{len(pending)}', flush=True)
rows = []
for cc, q, pg in jobs:
    raw = open(path(cc, q, pg), encoding='utf-8', errors='replace').read()
    try: root = ET.fromstring(raw)
    except ET.ParseError: continue
    if root.find('.//error') is not None: rows.append(dict(cc=cc, query=q, page=pg, error=(root.find('.//error').text or '')[:100])); continue
    for i, d in enumerate(root.findall('.//doc')):
        rows.append(dict(cc=cc, query=q, page=pg, pos=(pg - 1) * 10 + i + 1, url=d.findtext('url'), title=re.sub(r'<[^>]+>', '', d.findtext('title') or ''),
                         snippet=re.sub(r'<[^>]+>', '', (d.findtext('.//passage') or d.findtext('snippet') or ''))[:300]))
with open(f'{OUT}/results.jsonl', 'w') as fh:
    for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + '\n')
ok = [r for r in rows if 'url' in r]; errs = [r for r in rows if 'error' in r]
print(f'rows {len(ok)}, errors {len(errs)}, unique urls {len({r["url"] for r in ok})}, unique hosts {len({urllib.parse.urlsplit(r["url"]).netloc for r in ok})}')
for cc in COUNTRY: print(f"  {cc}: {len({r['url'] for r in ok if r['cc'] == cc})} urls, {len({urllib.parse.urlsplit(r['url']).netloc for r in ok if r['cc'] == cc})} hosts")
