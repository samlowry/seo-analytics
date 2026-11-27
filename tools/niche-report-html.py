#!/usr/bin/env python3
"""Шаг 5 niche-scan: HTML-отчёт для команды → niche-scan/report.html (один файл, данные внутри).
Вход: data/niches.csv (строго, DR < 20), data/niches-dr30.csv (потолок), data/keys-scored.jsonl, data/keywords.jsonl,
tools/niche-report-template.html (вёрстка и графики), tools/niche-report-text.html (тексты разделов, размечены <!-- NAME -->).
Числа в текстах подставляются из данных: {{N_KEYS}}, {{N_SERP}}, {{DR_COVER}}, {{N_THEMES}}, {{THRESHOLDS}}, {{N_CC_WORD}}, {{CC_LIST}}.
Порог объёма — та же доля, что в niche-report.py (THRESHOLD_SHARE).
«Один запрос» (ONE, CONC) считается сам: открытая ниша с оценкой от CONC_MIN, где один ключ даёт от CONC_SHARE визитов выборки.
Юридический риск (RISK) — ручная пометка, правится здесь."""
import csv, json, os, re, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from niche_brand import brand
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = f'{ROOT}/niche-scan/data'
THRESHOLD_SHARE, CONC_MIN, CONC_SHARE = 0.005, 15000, 0.7
CC = [['UZ', 'Узбекистан'], ['KZ', 'Казахстан'], ['AZ', 'Азербайджан'], ['KG', 'Кыргызстан'], ['MD', 'Молдова'], ['PK', 'Пакистан']]
CC_GEN = {'UZ': 'Узбекистане', 'KZ': 'Казахстане', 'AZ': 'Азербайджане', 'KG': 'Кыргызстане', 'MD': 'Молдове', 'PK': 'Пакистане'}
WORD = {4: 'четырёх', 5: 'пяти', 6: 'шести'}
# Слабые места в топе держат пираты, взлом или ответы на контрольные — см. раздел «Юридический риск» в niche-report-text.html.
RISK = {'UZ:movies', 'KZ:series', 'KG:series', 'KZ:anime', 'KG:anime', 'KZ:apk', 'KG:apk', 'UZ:exams', 'PK:movies', 'PK:apk', 'PK:anime'}
SEEDS = {n['id']: n for n in json.load(open(f'{ROOT}/niche-scan/seeds.json'))['niches']}

def fnum(n): return f'{round(n):,}'.replace(',', ' ')
def k(n): return f"{n / 1e6:.1f}".replace('.', ',') + ' млн' if n >= 1e6 else f'{round(n / 1e3)} тыс.' if n >= 1e3 else str(round(n))

strict = list(csv.DictReader(open(f'{D}/niches.csv')))
ceil = {(r['cc'], r['niche']): int(float(r['est_visits'])) for r in csv.DictReader(open(f'{D}/niches-dr30.csv'))}
keys = [json.loads(l) for l in open(f'{D}/keys-scored.jsonl')]
kw = [json.loads(l) for l in open(f'{D}/keywords.jsonl')]
ccs = [c for c, _ in CC]
data, thr = {}, {}
for cc in ccs:
    rr = [r for r in strict if r['cc'] == cc]
    tot = sum(int(r['niche_volume']) for r in rr); thr[cc] = tot * THRESHOLD_SHARE
    data[cc] = []
    for r in rr:
        st = 'closed' if r['culled'] == 'True' else 'open' if int(r['niche_volume']) >= thr[cc] else 'low'
        data[cc].append([r['niche'], r['name'], r['lang'], int(r['niche_volume']), int(float(r['est_visits'])), ceil[(cc, r['niche'])], st,
                         f"{r['weak_keys']}/{r['sample_keys']}", r['bet'], r['dr_median'] if r['dr_median'] not in ('', 'nan') else ''])
# «Оценка держится на одном запросе»
ok = [x for x in keys if x['status'] == 'ok' and x['cc'] in ccs]
by = collections.defaultdict(list)
for x in ok: by[(x['cc'], x['niche'])].append(x)
one, conc = [], []
for cc in ccs:
    for row in data[cc]:
        nid, name, est, st = row[0], row[1], row[4], row[6]
        g = by[(cc, nid)]; sv = sum(x['visits'] for x in g)
        if st != 'open' or est < CONC_MIN or not sv: continue
        top = max(g, key=lambda x: x['visits'])
        if top['visits'] / sv < CONC_SHARE: continue
        one.append(f'{cc}:{nid}')
        p = top['best_pos']; t = next((s for s in top['top'] if s.startswith(f'{p}:')), '')
        host, dr = (t.split(':')[1], t.split(':')[2]) if t else ('?', '')
        dr = f", DR {float(dr):.0f}" if dr not in ('', 'None') else ''
        conc.append([f'{name}, {dict(CC)[cc]}', f'«{top["keyword"]}», слабое место — {p}-е, {host}{dr}', round(est * top['visits'] / sv), est])
conc.sort(key=lambda c: -c[3])
# числа для текстов
kw_ok = [r for r in kw if r['cc'] in ccs and not brand(r)]
pos = sum(x['n_top10'] for x in ok); known = sum(x['dr_known'] for x in ok)
used_niches = {r[0] for cc in ccs for r in data[cc]}
nums = {
    'N_KEYS': fnum(len(kw_ok)), 'N_SERP': fnum(len(ok)), 'DR_COVER': f'{round(known / pos * 100)} %', 'N_THEMES': str(len(used_niches)),
    'THRESHOLDS': ', '.join(f'{dict(CC)[cc]} {k(thr[cc])}' for cc in ccs), 'N_CC_WORD': WORD[len(ccs)],
    'CC_LIST': ' · '.join(n for _, n in CC),
}
text = open(f'{ROOT}/tools/niche-report-text.html').read()
parts = dict(re.findall(r'<!-- ([A-Z_]+) -->\n(.*?)(?=\n<!-- [A-Z_]+ -->|\Z)', text, re.S))
def fill(s): return re.sub(r'\{\{([A-Z_]+)\}\}', lambda m: nums[m.group(1)], s)
t = open(f'{ROOT}/tools/niche-report-template.html').read()
for name in ('HEADER', 'KPI_NOTE', 'AVOID', 'METHOD'): t = t.replace('{{' + name + '}}', fill(parts[name]).rstrip())
t = (t.replace('{{CC}}', json.dumps(CC, ensure_ascii=False)).replace('{{ONE}}', json.dumps({x: 1 for x in one}))
      .replace('{{RISK}}', json.dumps({x: 1 for x in sorted(RISK)})).replace('{{CONC}}', json.dumps(conc, ensure_ascii=False))
      .replace('{{KPI_COLS}}', str(3 if len(ccs) == 6 else len(ccs))).replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':'))))
assert '{{' not in t, re.findall(r'\{\{[A-Z_]+\}\}', t)
open(f'{ROOT}/niche-scan/report.html', 'w').write(t)
print('report.html:', len(t) // 1024, 'KB;', nums, '\nONE:', one)
