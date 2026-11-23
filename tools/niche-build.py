#!/usr/bin/env python3
"""Шаг 1 niche-scan: ключи Ahrefs → ниши, доминирующий язык ниши в стране, выборка ключей под снимки выдачи.
Вход: niche-scan/seeds.json, niche-scan/data/kw-<CC>-<lang>-<group>.json.
Выход: niche-scan/data/keywords.jsonl (все ключи с нишей), niche-scan/data/sample.jsonl (что снимать в XMLRiver),
niche-scan/data/niche-volumes.csv (объём ниши по языкам и выбранный язык).
Ключ относится к нише, если в нём есть все слова одного из её исходных слов (см. word_hit); при нескольких нишах — к той,
чьё совпавшее исходное слово длиннее. Выборка: на нишу × страну до 15 ключей доминирующего языка — самый частотный ключ
каждого parent_topic Ahrefs, по убыванию частотности; первые 3 снимаются с двумя страницами."""
import json, glob, os, re, collections, csv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
N = json.load(open(f'{ROOT}/niche-scan/seeds.json'))['niches']
LANGS = {'UZ': ['ru', 'uz'], 'KZ': ['ru'], 'AZ': ['az', 'ru'], 'TR': ['tr'], 'KG': ['ru']}
SAMPLE, PAGE2 = 15, 3
# Адалт-запросы выбрасываются из всех ниш: это отдельный рынок, в нишу «кино» или «аниме» он не входит.
ADULT = re.compile(r'(porn|порн|секс|sex|xxx|ххх|hentai|хентай|эрот|erot|18\+|голые|seks|jinsiy|onlyfans|sikiş|minet|минет|голая|голый)', re.I)
def norm(s): return s.lower().replace('ı', 'i').replace('’', "'").replace('ʻ', "'").replace('‘', "'")
def word_hit(sw, words):
    """Слово исходника встречается в ключе: короткое (до 3 букв) — целым словом, длинное — как начало слова;
    от 5 букв допускается окончание (основа без последней буквы)."""
    if len(sw) <= 3: return sw in words
    stem = sw[:-1] if len(sw) >= 5 else sw
    return any(w.startswith(stem) for w in words)
def niche_of(kw, lang):
    words = re.findall(r"[\w'.-]+", norm(kw)); best = None
    for n in N:
        for s in n[lang]:
            if all(word_hit(w, words) for w in norm(s).split()):
                if best is None or len(s) > best[1]: best = (n['id'], len(s))
    return best and best[0]
def lang_of(kw, cc):
    """Язык ключа — по алфавиту, а не по выгрузке: в узбекской выгрузке встречаются русские ключи.
    Кириллица → ru (узбекская кириллица и казахский/кыргызский здесь тоже считаются ru-слоем), латиница → местный язык."""
    if cc in ('KZ', 'KG'): return 'ru'
    if cc == 'TR': return 'tr'
    cyr = len(re.findall('[а-яёўқғҳ]', kw.lower())); lat = len(re.findall('[a-zəğıöüşç]', kw.lower()))
    return 'ru' if cyr > lat else LANGS[cc][1] if cc == 'UZ' else 'az'
rows = {}
for f in sorted(glob.glob(f'{ROOT}/niche-scan/data/kw-*.json')):
    d = json.load(open(f))
    for k in d['keywords']:
        key = (d['cc'], k['keyword'])
        if key in rows: continue
        lang = lang_of(k['keyword'], d['cc'])
        if ADULT.search(k['keyword']): continue
        nid = niche_of(k['keyword'], lang) or niche_of(k['keyword'], d['lang'])
        if nid: rows[key] = dict(cc=d['cc'], lang=lang, niche=nid, keyword=k['keyword'], volume=k['volume'], cps=k.get('cps'), parent=k.get('parent_topic') or k['keyword'])
with open(f'{ROOT}/niche-scan/data/keywords.jsonl', 'w') as fh:
    for r in rows.values(): fh.write(json.dumps(r, ensure_ascii=False) + '\n')
vol = collections.defaultdict(int)
for r in rows.values(): vol[(r['cc'], r['niche'], r['lang'])] += r['volume']
dom = {}
with open(f'{ROOT}/niche-scan/data/niche-volumes.csv', 'w') as fh:
    w = csv.writer(fh); w.writerow(['cc', 'niche', 'lang', 'volume', 'dominant'])
    for cc, langs in LANGS.items():
        for n in N:
            v = {l: vol[(cc, n['id'], l)] for l in langs}; best = max(v, key=v.get); dom[(cc, n['id'])] = best
            for l in langs: w.writerow([cc, n['id'], l, v[l], int(l == best)])
sample = []
for (cc, nid), lang in dom.items():
    kws = sorted([r for r in rows.values() if r['cc'] == cc and r['niche'] == nid and r['lang'] == lang], key=lambda r: -r['volume'])
    seen = set(); picked = []
    for r in kws:
        if r['parent'] in seen: continue
        seen.add(r['parent']); picked.append(r)
        if len(picked) == SAMPLE: break
    for i, r in enumerate(picked): sample.append(dict(r, pages=2 if i < PAGE2 else 1))
with open(f'{ROOT}/niche-scan/data/sample.jsonl', 'w') as fh:
    for r in sample: fh.write(json.dumps(r, ensure_ascii=False) + '\n')
print(f'keywords with niche: {len(rows)}; sample: {len(sample)} keys, {sum(r["pages"] for r in sample)} SERP requests')
un = collections.Counter(r['cc'] for r in rows.values())
print('per country:', dict(un))
