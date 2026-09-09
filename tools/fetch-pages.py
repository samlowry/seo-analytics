#!/usr/bin/env python3
"""Задача 2: скачать страницы пула и вытащить, как на них подан Mostbet.
Вход: results/ai/pool.json (+ site-результаты, если есть). Выход: results/ai/pages/<sha>.html и results/ai/pages.jsonl."""
import json, os, re, sys, hashlib, html, time, urllib.request, urllib.parse, ssl
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f'{ROOT}/results/ai/pages'; os.makedirs(OUT, exist_ok=True)
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
BRANDS = ['Mostbet', '1xBet', 'Olimpbet', 'Parimatch', 'Fonbet', 'Winline', 'Pin-Up', 'Melbet', 'Betandyou', 'Misli', 'Topaz', 'BetBoom', 'Marathon', 'Leon', 'Tennisi', 'Bettery', 'Ubet', 'Zenit', 'Betcity', '1win', 'Betwinner', 'Linebet', 'Bet365', '22Bet', 'Pinnacle', 'GGBet']
RUS = {'Mostbet': 'мостбет|мосбет', '1xBet': '1хбет|иксбет', 'Olimpbet': 'олимпбет|олимп', 'Parimatch': 'париматч', 'Fonbet': 'фонбет', 'Winline': 'винлайн', 'Pin-Up': 'пин-?ап', 'Melbet': 'мелбет', 'Leon': 'леон', 'Tennisi': 'теннисси', 'Zenit': 'зенит', 'Betcity': 'бетсити', 'Marathon': 'марафон', 'BetBoom': 'бетбум', '1win': '1вин'}
RX = {b: re.compile('(?<![a-zа-я])(' + re.escape(b).replace(r'\-', '-?') + ('|' + RUS[b] if b in RUS else '') + ')(?![a-zа-я])', re.I) for b in BRANDS}
NEG = re.compile(r'нелегал|незакон|офшор|оффшор|без лицензи|мошенн|обман|развод|скам|scam|лохотрон|не выводит|не платит|задерж|блокир|заблокир|запрещ|риск|жалоб|кидал|кинул|вне правового|предупрежд', re.I)

class T(HTMLParser):
    def __init__(self):
        super().__init__(); self.o = []; self.skip = 0; self.title = ''; self.h1 = ''; self.in_title = self.in_h1 = False; self.lang = ''; self.canonical = ''; self.h2 = []; self.in_h2 = False; self.dates = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header'): self.skip += 1
        if tag == 'html': self.lang = a.get('lang') or ''
        if tag == 'link' and (a.get('rel') or '').lower() == 'canonical': self.canonical = a.get('href') or ''
        if tag == 'meta' and (a.get('property') or a.get('name') or '').lower() in ('article:modified_time', 'article:published_time', 'og:updated_time', 'date', 'last-modified'): self.dates.append(a.get('content') or '')
        if tag == 'time' and a.get('datetime'): self.dates.append(a['datetime'])
        if tag == 'title': self.in_title = True
        if tag == 'h1': self.in_h1 = True
        if tag == 'h2': self.in_h2 = True
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'br', 'tr', 'td', 'th', 'section', 'article'): self.o.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header') and self.skip: self.skip -= 1
        if tag == 'title': self.in_title = False
        if tag == 'h1': self.in_h1 = False
        if tag == 'h2': self.in_h2 = False
    def handle_data(self, d):
        if self.in_title: self.title += d
        if self.in_h1: self.h1 += d
        if self.in_h2: self.h2.append(d.strip())
        if not self.skip: self.o.append(d)
    def text(self):
        t = html.unescape(''.join(self.o)); t = re.sub(r'[ \t ]+', ' ', t); return re.sub(r'\s*\n\s*', '\n', t).strip()

def analyze(url, raw):
    p = T()
    try: p.feed(raw)
    except Exception: pass
    t = p.text(); words = len(re.findall(r'\w+', t))
    pos = {b: [m.start() for m in RX[b].finditer(t)] for b in BRANDS}
    order = sorted([(v[0], b) for b, v in pos.items() if v]); order = [b for _, b in order]
    mb = pos['Mostbet']; ctx = []
    for i in mb[:3]:
        a, z = max(0, i - 220), min(len(t), i + 260); seg = re.sub(r'\s+', ' ', t[a:z]).strip(); ctx.append(seg)
    neg_near = sum(1 for i in mb if NEG.search(t[max(0, i - 300):i + 300]))
    # позиция Mostbet в списке брендов страницы (по первому упоминанию)
    rank = order.index('Mostbet') + 1 if 'Mostbet' in order else None
    # заголовки h2, где есть Mostbet
    h2m = [h for h in p.h2 if RX['Mostbet'].search(h)]
    return dict(url=url, title=re.sub(r'\s+', ' ', p.title).strip()[:200], h1=re.sub(r'\s+', ' ', p.h1).strip()[:200], lang=p.lang, canonical=p.canonical,
                words=words, brands_order=order[:15], n_brands=len(order), mostbet_count=len(mb), mostbet_rank=rank, mostbet_neg_near=neg_near,
                mostbet_h2=h2m[:5], mostbet_ctx=ctx, dates=p.dates[:3], text_sha=hashlib.sha1(t.encode()).hexdigest()[:10])

def fetch(url):
    h = hashlib.sha1(url.encode()).hexdigest()[:12]; f = f'{OUT}/{h}.html'
    if os.path.exists(f):
        raw = open(f, encoding='utf-8', errors='replace').read(); status = 'cached'
    else:
        sp = urllib.parse.urlsplit(url)
        safe = urllib.parse.urlunsplit((sp.scheme, sp.netloc.encode('idna').decode(), urllib.parse.quote(sp.path, safe='/%:@'), urllib.parse.quote(sp.query, safe='=&%+'), ''))
        req = urllib.request.Request(safe, headers={'User-Agent': UA, 'Accept-Language': 'ru,en;q=0.8', 'Accept': 'text/html,*/*'})
        try:
            with urllib.request.urlopen(req, timeout=25, context=CTX) as r:
                raw = r.read(3_000_000).decode(r.headers.get_content_charset() or 'utf-8', 'replace'); status = str(r.status)
        except urllib.error.HTTPError as e: raw = ''; status = f'http {e.code}'
        except Exception as e: raw = ''; status = f'err {type(e).__name__}'
        open(f, 'w').write(raw)
    d = analyze(url, raw) if raw else dict(url=url, words=0, mostbet_count=0)
    d['status'] = status; d['bytes'] = len(raw); return d

if __name__ == '__main__':
    pool = json.load(open(f'{ROOT}/results/ai/pool.json'))
    urls = [d['url'] for d in pool]
    extra = f'{ROOT}/results/ai/site/results.jsonl'
    if os.path.exists(extra):
        seen = set(urls)
        for l in open(extra):
            r = json.loads(l)
            if r.get('url') and r['url'] not in seen: seen.add(r['url']); urls.append(r['url'])
    print(f'urls: {len(urls)}', flush=True)
    out = []; t0 = time.time()
    with ThreadPoolExecutor(10) as ex:
        for i, fut in enumerate(as_completed([ex.submit(fetch, u) for u in urls]), 1):
            out.append(fut.result())
            if i % 100 == 0: print(f'  {i}/{len(urls)} {time.time() - t0:.0f}s', flush=True)
    with open(f'{ROOT}/results/ai/pages.jsonl', 'w') as fh:
        for d in out: fh.write(json.dumps(d, ensure_ascii=False) + '\n')
    ok = [d for d in out if d['status'] in ('200', 'cached') and d.get('words', 0) > 50]
    print(f'done: {len(out)} pages, ok {len(ok)}, with Mostbet {sum(1 for d in ok if d.get("mostbet_count"))}, statuses: {dict(__import__("collections").Counter(d["status"] for d in out).most_common(8))}')
