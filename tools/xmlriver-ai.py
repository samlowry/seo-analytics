#!/usr/bin/env python3
"""Массовый съём AI-блока Google через XMLRiver (ai=1).
Вход: список запросов (JSONL: {"cc","query","tag"}), выход: results/ai/xmlriver/<CC>/<sha>.xml (сырое)
и results/ai/xmlriver/answers.jsonl (разобранное). Повторный запуск не перекачивает то, что уже лежит.
Запуск: python3 tools/xmlriver-ai.py queries.jsonl [--threads 3] [--device desktop]
"""
import sys, os, re, json, time, hashlib, base64, html, argparse, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f'{ROOT}/results/ai/xmlriver'
COUNTRY = {'KZ': 2398, 'AZ': 2031, 'UZ': 2860, 'RU': 2643}

def load_env():
    env = {}
    for line in open(f'{ROOT}/.env'):
        line = line.split('#')[0].strip()
        if '=' in line:
            k, v = line.split('=', 1); env[k.strip()] = v.strip()
    return env

class Visible(HTMLParser):
    """Текст без script/style/svg. Скрытые (display:none) поддеревья НЕ выбрасываются:
    свёрнутая часть AI-ответа тоже скрыта, а заглушки «обзор недоступен» режутся отдельно."""
    def __init__(self):
        super().__init__(); self.out = []; self.skip = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'noscript', 'svg'): self.skip += 1
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'br', 'tr'): self.out.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg') and self.skip: self.skip -= 1
    def handle_data(self, d):
        if not self.skip: self.out.append(d)
    def text(self):
        t = html.unescape(''.join(self.out)); t = re.sub(r'[ \t\u00a0\u202f]+', ' ', t); t = re.sub(r'\s*\n\s*', '\n', t)
        return t.strip()

PLACEHOLDERS = [r'Для этого запроса обзор от ИИ недоступен\.?', r'Не удалось сгенерировать обзор с помощью искусственного интеллекта\.?',
                r'Повторите попытку позже\.?', r'^Обзор от ИИ\n', r'^Ответ режима ИИ:\s*']
END_MARKERS = [r'\nОбщее\n0 файлов', r'\nИИ может ошибаться', r'\nСохранить на Google Диске']
def visible_text(h):
    p = Visible(); p.feed(h); t = p.text()
    for rx in PLACEHOLDERS: t = re.sub(rx, '', t).strip()
    m = re.search(r'Ответ в режиме ИИ, исходный запрос: "[^"]*"\s*', t)
    if m: t = t[m.end():]
    cut = min([m.start() for rx in END_MARKERS for m in [re.search(rx, t)] if m] or [len(t)])
    return t[:cut].strip()

def parse(raw, cc, query, tag):
    r = dict(cc=cc, query=query, tag=tag)
    try: root = ET.fromstring(raw)
    except ET.ParseError as e: r['error'] = f'xml: {e}'; return r
    err = root.find('.//error')
    if err is not None: r['error'] = f"{err.get('code')}: {(err.text or '').strip()[:200]}"; return r
    resp = root.find('response'); r['date'] = resp.get('date') if resp is not None else None
    r['related_questions'] = [q.text for q in root.findall('.//relatedQuestions/item/question') if q.text]
    r['organic'] = [dict(pos=i + 1, url=d.findtext('url'), title=re.sub(r'<[^>]+>', '', d.findtext('title') or ''))
                    for i, d in enumerate(root.findall('.//doc')[:10])]
    ai = root.find('.//ai')
    r['ai_present'] = ai is not None
    if ai is None: return r
    ans = ai.findtext('answer')
    if ans:
        try: h = base64.b64decode(ans.strip()).decode('utf-8', 'replace')
        except Exception as e: h = ''; r['error'] = f'b64: {e}'
        r['answer_mode'] = 'ai_mode' if re.search(r'Ответ (в режиме|режима) ИИ', h) else 'ai_overview'
        t = visible_text(h)
        r['answer'] = t
        r['mostbet_mentions'] = len(re.findall(r'mostbet|мостбет', t, re.I))
    r['sources'] = [dict(url=i.findtext('url'), title=(i.findtext('title') or '').replace('. Страница откроется в новой вкладке', '').strip(),
                         snippet=i.findtext('snippet')) for i in ai.findall('item')]
    return r

def fetch(env, cc, query, device, tries=4):
    params = dict(user=env['XMLRIVER_USER'], key=env['XMLRIVER_KEY'], query=query, country=COUNTRY[cc], lr='ru', device=device, ai=1)
    url = env.get('XMLRIVER_ENDPOINT', 'https://xmlriver.com/search/xml') + '?' + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as f: raw = f.read().decode('utf-8', 'replace')
        except Exception as e:
            time.sleep(15 * (i + 1)); last = f'http: {e}'; continue
        m = re.search(r'<error code="(\d+)"', raw)
        if m and m.group(1) in ('110', '115', '201', '500'): time.sleep(20 if m.group(1) == '500' else 60); last = raw[:200]; continue
        return raw
    return f'<yandexsearch><response><error code="999">retries exhausted: {last}</error></response></yandexsearch>'

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('queries'); ap.add_argument('--threads', type=int, default=3); ap.add_argument('--device', default='desktop')
    a = ap.parse_args(); env = load_env()
    items = [json.loads(l) for l in open(a.queries) if l.strip()]
    seen = set(); todo = []
    for it in items:
        key = (it['cc'], it['query'].strip().lower(), a.device)
        if key in seen: continue
        seen.add(key); todo.append(it)
    def path(it):
        h = hashlib.sha1(f"{it['cc']}|{it['query'].strip().lower()}|{a.device}".encode()).hexdigest()[:12]
        os.makedirs(f"{OUT}/{it['cc']}", exist_ok=True); return f"{OUT}/{it['cc']}/{h}.xml"
    pending = [it for it in todo if not os.path.exists(path(it))]
    print(f'queries: {len(todo)} unique, {len(pending)} to fetch, {len(todo) - len(pending)} cached', flush=True)
    def work(it):
        raw = fetch(env, it['cc'], it['query'], a.device); open(path(it), 'w').write(raw); return it
    done = 0; t0 = time.time()
    with ThreadPoolExecutor(a.threads) as ex:
        for fut in as_completed([ex.submit(work, it) for it in pending]):
            it = fut.result(); done += 1
            if done % 10 == 0 or done == len(pending): print(f'  {done}/{len(pending)}  {time.time() - t0:.0f}s', flush=True)
    rows = []
    for it in todo:
        raw = open(path(it), encoding='utf-8', errors='replace').read()
        rows.append(parse(raw, it['cc'], it['query'], it.get('tag', '')))
    with open(f'{OUT}/answers-{a.device}.jsonl', 'w') as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    n_ai = sum(1 for r in rows if r.get('ai_present')); n_err = sum(1 for r in rows if r.get('error'))
    n_mb = sum(1 for r in rows if r.get('mostbet_mentions'))
    print(f'parsed {len(rows)}: ai_present={n_ai} errors={n_err} with_mostbet={n_mb}')
    for cc in sorted({r['cc'] for r in rows}):
        rr = [r for r in rows if r['cc'] == cc]
        print(f"  {cc}: {len(rr)} queries, ai={sum(1 for r in rr if r.get('ai_present'))}, mostbet={sum(1 for r in rr if r.get('mostbet_mentions'))}, errors={sum(1 for r in rr if r.get('error'))}")

if __name__ == '__main__': main()
