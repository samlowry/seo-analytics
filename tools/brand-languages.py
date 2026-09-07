#!/usr/bin/env python3
"""Сайдквест: пропорции языков брендовых запросов Mostbet по странам (из results/ai/corpus, seeds mostbet/мостбет)."""
import json, re, collections
CC = ['KZ', 'AZ', 'UZ']
BRAND = re.compile(r'mostbet|мостбет|mosbet|мосбет|most bet|мост бет', re.I)
NOISE = re.compile(r'^(kz|uz|az|com|net|org|ru|apk|ios|android|app|aviator|casino|bet|online|www|official|2024|2025|2026|\d+|[.\-_/]+)$', re.I)
KK = re.compile(r'[әғқңөұүһі]', re.I)
UZC = re.compile(r'[ўғқҳ]', re.I)
CYR = re.compile(r'[а-яё]', re.I)
AZ_L = re.compile(r'ə', re.I)
AZW = re.compile(r'\b(yukle|yükle|yüklə|yukl[eə]|giri[sş]|qeydiyyat|r[eə]smi|proqram|idman|m[eə]rc|oyun|pulsuz|endir|azerbaycan|az[eə]rbaycan|c[iı]xar\w*|ç[iı]xar\w*|hesab|d[eə]st[eə]k|qazan\w*|saytı)\b', re.I)
TRW = re.compile(r'\b(indir|giriş|güncel|kayıt|canlı|adresi|bahis|mobil|uygulama|üyelik|para|çekme|yatırma|tv|türkiye)\b', re.I)
UZW = re.compile(r'\b(yuklab|yuklash|skachat|kirish|olish|o.?ynash|ro.?yxat\w*|bepul|uchun|rasmiy|sayti|ilova|onlayn|yechish|to.?ldirish|bukmeker|tikish|stavka|uzbekcha|o.?zbek\w*)\b', re.I)
ENW = re.compile(r'\b(download|login|log in|sign ?up|register|registration|app|review|reviews|official|site|website|promo ?code|withdraw|withdrawal|deposit|sports|betting|mobile|version|free|play|games|slots|live|support|india|bangladesh|pakistan|nepal|english|kazakhstan|uzbekistan|azerbaijan|partners?|affiliate|agent|cash|demo|promo|code|bookmaker)\b', re.I)
RUT = re.compile(r'\b(skachat|zerkalo|vhod|vkhod|oficialn\w*|otzyvy|kazino|registraciya|prilozhenie|besplatno|segodnya|rabochee|sayt|stavki|bukmeker\w*)\b', re.I)
PTW = re.compile(r'\b(baixar|aplicativo|entrar|apostas|cadastro|login|bônus|bonus|oficial|site|jogo|jogos|brasil|cassino|saque|depósito)\b', re.I)
ESW = re.compile(r'\b(descargar|aplicaci[oó]n|entrar|apuestas|registro|bono|oficial|casino|juego|iniciar|sesi[oó]n|retiro|dep[oó]sito|m[eé]xico|per[uú]|chile)\b', re.I)
def lang(k, cc=None):
    words = [w for w in re.split(r'\s+', BRAND.sub(' ', k).strip()) if w and not NOISE.match(w)]
    if not words: return 'только бренд'
    rest = ' '.join(words)
    if CYR.search(rest):
        if KK.search(rest): return 'kk'
        if UZC.search(rest): return 'uz (кириллица)'
        return 'ru'
    cand = []
    if AZ_L.search(rest) or AZW.search(rest): cand.append('az')
    if TRW.search(rest): cand.append('tr')
    if UZW.search(rest): cand.append('uz (латиница)')
    if re.search(r'\b(bonus|sayt|pul|mobil|tv)\b', rest, re.I) and not cand: cand = ['az', 'uz (латиница)']  # общие слова — по стране
    if cand:
        local = {'AZ': 'az', 'UZ': 'uz (латиница)'}.get(cc)
        if local in cand: return local
        if 'az' in cand and 'tr' in cand: return 'az/tr'
        return cand[0]
    if RUT.search(rest): return 'ru (транслит)'
    if PTW.search(rest) and not ENW.search(rest): return 'pt'
    if ESW.search(rest) and not ENW.search(rest): return 'es'
    if ENW.search(rest): return 'en'
    return 'латиница, не определён'
rows = {}
for cc in CC:
    for idx in ('01', '02'):
        for k in json.load(open(f'results/ai/corpus/{cc}/{idx}.json'))['keywords']:
            rows.setdefault((cc, k['keyword']), k.get('volume') or 0)
out = {}
for cc in CC:
    by = collections.defaultdict(lambda: dict(n=0, vol=0, ex=[]))
    for (c, k), v in rows.items():
        if c != cc: continue
        l = lang(k, cc); by[l]['n'] += 1; by[l]['vol'] += v
        if len(by[l]['ex']) < 4 and v >= 50: by[l]['ex'].append(f'{k} ({v})')
    tot = sum(d['vol'] for d in by.values()); out[cc] = dict(total=tot, langs=by)
    print(f'\n=== {cc}: {len([1 for (c, _) in rows if c == cc])} запросов, объём {tot:,} ==='.replace(',', ' '))
    for l, d in sorted(by.items(), key=lambda kv: -kv[1]['vol']):
        print(f"  {l:24} {d['vol']:>8,}  {100 * d['vol'] / max(tot, 1):5.1f} %   {d['n']:>4} запр.   {'; '.join(d['ex'])}".replace(',', ' '))
json.dump({cc: dict(total=o['total'], langs={l: dict(n=d['n'], vol=d['vol'], ex=d['ex']) for l, d in o['langs'].items()}) for cc, o in out.items()},
          open('results/ai/brand-languages.json', 'w'), ensure_ascii=False, indent=1)
