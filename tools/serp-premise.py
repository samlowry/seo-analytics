#!/usr/bin/env python3
"""Шаг 0 niche-scan: проверка посылки «брендовая выдача в igaming = только официальные сайты».
Снимает Google через XMLRiver, страницы 1 и 2 (топ-20), по брендам беттинга и по контрольным брендам других ниш.
Выход: results/niche-premise/<CC>/<sha>-p<N>.xml (сырое), niche-scan/premise-serp.jsonl (разобранное).
Запуск: python3 tools/serp-premise.py [--threads 4]"""
import os, re, json, time, hashlib, argparse, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = f'{ROOT}/results/niche-premise'
# страна: (geo id Google, язык интерфейса = доминирующий язык поиска)
COUNTRY = {'UZ': (2860, 'ru'), 'KZ': (2398, 'ru'), 'AZ': (2031, 'az'), 'TR': (2792, 'tr'), 'KG': (2417, 'ru')}
BET = ['mostbet', '1xbet', 'melbet', '1win', 'pin up casino', 'betwinner', 'mostbet скачать', 'mostbet giriş', 'mostbet apk', 'mostbet promokod']
LOCAL_BET = {'KZ': ['olimpbet', 'fonbet kz'], 'UZ': ['betandyou', 'linebet'], 'AZ': ['topaz', 'betandreas'], 'TR': ['bets10', 'nesine'], 'KG': ['1xbet kg', 'melbet kg']}
CONTROL = ['netflix', 'aliexpress', 'telegram', 'whatsapp', 'temu', 'spotify', 'pubg mobile', 'free fire']
# общие запросы без бренда, на доминирующем языке страны (язык = COUNTRY[cc][1])
GEN = {'ru': (['ставки на спорт', 'онлайн казино', 'букмекерская контора', 'лучшие букмекеры', 'приложение для ставок', 'прогнозы на футбол'],
              ['смотреть фильмы онлайн', 'скачать музыку', 'курс доллара', 'футбол онлайн', 'гороскоп на сегодня', 'рецепт плова']),
       'az': (['idman mərcləri', 'onlayn kazino', 'mərc saytları', 'bukmeker', 'futbol proqnozları', 'mərc tətbiqi'],
              ['filmlər onlayn', 'musiqi yüklə', 'dollar məzənnəsi', 'futbol canlı', 'bürc', 'plov resepti']),
       'tr': (['bahis siteleri', 'canlı bahis', 'casino siteleri', 'deneme bonusu', 'iddaa tahminleri', 'bahis uygulaması'],
              ['film izle', 'müzik indir', 'dolar kuru', 'canlı maç izle', 'günlük burç', 'pilav tarifi'])}
LOCAL_CONTROL = {'KZ': ['kaspi', 'kolesa kz'], 'UZ': ['click uz', 'uzum market'], 'AZ': ['kapital bank', 'tap az'], 'TR': ['trendyol', 'hepsiburada'], 'KG': ['mbank', 'lalafo']}

def env():
    e = {}
    for l in open(f'{ROOT}/.env'):
        l = l.split('#')[0].strip()
        if '=' in l: k, v = l.split('=', 1); e[k.strip()] = v.strip()
    return e
E = env()

def fetch(cc, q, page, tries=4):
    gid, lr = COUNTRY[cc]
    p = dict(user=E['XMLRIVER_USER'], key=E['XMLRIVER_KEY'], query=q, country=gid, lr=lr, device='desktop', page=page)
    url = E.get('XMLRIVER_ENDPOINT', 'https://xmlriver.com/search/xml') + '?' + urllib.parse.urlencode(p)
    last = ''
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=90) as f: raw = f.read().decode('utf-8', 'replace')
        except Exception as ex: last = str(ex); time.sleep(10 * (i + 1)); continue
        m = re.search(r'<error code="(\d+)"', raw)
        if m and m.group(1) in ('110', '115', '201', '500'): last = raw[:200]; time.sleep(30); continue
        return raw
    return f'<r><response><error code="999">{last}</error></response></r>'

def jobs():
    for cc in COUNTRY:
        gb, gc = GEN[COUNTRY[cc][1]]
        for kind, qs in (('bet', BET + LOCAL_BET[cc]), ('control', CONTROL + LOCAL_CONTROL[cc]), ('bet-generic', gb), ('control-generic', gc)):
            for q in qs:
                for pg in (1, 2): yield cc, kind, q, pg

def path(cc, q, pg):
    os.makedirs(f'{RAW}/{cc}', exist_ok=True)
    return f"{RAW}/{cc}/{hashlib.sha1(f'{cc}|{q}'.encode()).hexdigest()[:12]}-p{pg}.xml"

ap = argparse.ArgumentParser(); ap.add_argument('--threads', type=int, default=4); a = ap.parse_args()
J = list(jobs()); todo = [j for j in J if not os.path.exists(path(j[0], j[2], j[3]))]
print(f'jobs {len(J)}, to fetch {len(todo)}', flush=True)
def work(j):
    cc, kind, q, pg = j; open(path(cc, q, pg), 'w').write(fetch(cc, q, pg))
with ThreadPoolExecutor(a.threads) as ex: list(ex.map(work, todo))
out = open(f'{ROOT}/niche-scan/premise-serp.jsonl', 'w')
for cc, kind, q, pg in J:
    raw = open(path(cc, q, pg), encoding='utf-8', errors='replace').read()
    try: root = ET.fromstring(raw)
    except ET.ParseError as ex: out.write(json.dumps(dict(cc=cc, kind=kind, query=q, page=pg, error=str(ex))) + '\n'); continue
    err = root.find('.//error')
    if err is not None:
        out.write(json.dumps(dict(cc=cc, kind=kind, query=q, page=pg, error=f"{err.get('code')} {(err.text or '')[:150]}"), ensure_ascii=False) + '\n'); continue
    found = root.findtext('.//found')
    docs = [dict(pos=(pg - 1) * 10 + i + 1, url=d.findtext('url'), title=re.sub(r'<[^>]+>', '', d.findtext('title') or ''))
            for i, d in enumerate(root.findall('.//doc'))]
    out.write(json.dumps(dict(cc=cc, kind=kind, query=q, page=pg, found=found, docs=docs), ensure_ascii=False) + '\n')
out.close(); print('done')
