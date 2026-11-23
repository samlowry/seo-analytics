#!/usr/bin/env python3
"""Шаг 2 niche-scan: снимки Google через XMLRiver по niche-scan/data/sample.jsonl.
Десктоп, страна ключа, язык интерфейса = язык ключа. Страница 2 — для первых трёх ключей ниши (поле pages).
Сырьё: results/niche-serp/<CC>/<sha>-p<N>.xml (повторный запуск не перекачивает; ошибка 15 «нет результатов» —
это данные, но такие файлы перекачиваются один раз повторно, см. --retry-empty).
Выход: niche-scan/data/serp.jsonl. Запуск: python3 tools/niche-serp.py [--threads 6] [--retry-empty]"""
import os, re, json, time, hashlib, argparse, urllib.request, urllib.parse, glob
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = f'{ROOT}/results/niche-serp'
GEO = {'UZ': 2860, 'KZ': 2398, 'AZ': 2031, 'TR': 2792, 'KG': 2417}
E = {}
for l in open(f'{ROOT}/.env'):
    l = l.split('#')[0].strip()
    if '=' in l: k, v = l.split('=', 1); E[k.strip()] = v.strip()
def path(cc, q, pg):
    os.makedirs(f'{RAW}/{cc}', exist_ok=True)
    return f"{RAW}/{cc}/{hashlib.sha1(f'{cc}|{q.lower()}'.encode()).hexdigest()[:12]}-p{pg}.xml"
def fetch(cc, q, lang, pg, tries=4):
    p = dict(user=E['XMLRIVER_USER'], key=E['XMLRIVER_KEY'], query=q, country=GEO[cc], lr=lang, device='desktop', page=pg)
    url = E.get('XMLRIVER_ENDPOINT', 'https://xmlriver.com/search/xml') + '?' + urllib.parse.urlencode(p); last = ''
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as f: raw = f.read().decode('utf-8', 'replace')
        except Exception as ex: last = str(ex); time.sleep(10 * (i + 1)); continue
        m = re.search(r'<error code="(\d+)"', raw)
        if m and m.group(1) in ('110', '115', '201', '500'): last = raw[:200]; time.sleep(30); continue
        return raw
    return f'<r><response><error code="999">{last}</error></response></r>'
def parse(raw):
    try: root = ET.fromstring(raw.strip())  # XMLRiver иногда отдаёт пробел перед <?xml
    except ET.ParseError as ex: return dict(error=f'xml {ex}')
    err = root.find('.//error')
    if err is not None: return dict(error=f"{err.get('code')} {(err.text or '')[:120]}", empty=err.get('code') == '15')
    return dict(docs=[dict(url=d.findtext('url'), title=re.sub(r'<[^>]+>', '', d.findtext('title') or ''),
                           passage=re.sub(r'<[^>]+>', '', ' '.join(p.text or '' for p in d.findall('.//passage')))[:300]) for d in root.findall('.//doc')])
if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--threads', type=int, default=6); ap.add_argument('--retry-empty', action='store_true'); ap.add_argument('--parse-only', action='store_true'); a = ap.parse_args()
    S = [json.loads(l) for l in open(f'{ROOT}/niche-scan/data/sample.jsonl')]
    jobs = [(r['cc'], r['keyword'], r['lang'], pg) for r in S for pg in range(1, r['pages'] + 1)]
    def need(j):
        f = path(j[0], j[1], j[3])
        if not os.path.exists(f) or os.path.getsize(f) == 0: return True  # 0 байт — запрос прерван
        if 'error code="999"' in open(f, errors='replace').read(): return True  # повторы исчерпаны — переснять
        if a.retry_empty and 'error code="15"' in open(f).read() and not os.path.exists(f + '.first'): os.rename(f, f + '.first'); return True
        return False
    todo = [] if a.parse_only else [j for j in jobs if need(j)]
    print(f'jobs {len(jobs)}, to fetch {len(todo)}', flush=True)
    done = [0]; t0 = time.time()
    def work(j):
        raw = fetch(*j); open(path(j[0], j[1], j[3]), 'w').write(raw); done[0] += 1
        if done[0] % 100 == 0: print(f'  {done[0]}/{len(todo)} {time.time()-t0:.0f}s', flush=True)
    with ThreadPoolExecutor(a.threads) as ex: list(ex.map(work, todo))
    with open(f'{ROOT}/niche-scan/data/serp.jsonl', 'w') as out:
        for r in S:
            for pg in range(1, r['pages'] + 1):
                f = path(r['cc'], r['keyword'], pg)
                if not os.path.exists(f) or os.path.getsize(f) == 0: continue  # ещё не снят (режим --parse-only)
                out.write(json.dumps(dict(cc=r['cc'], niche=r['niche'], keyword=r['keyword'], lang=r['lang'], page=pg, **parse(open(f, encoding='utf-8', errors='replace').read())), ensure_ascii=False) + '\n')
    print('done', flush=True)
