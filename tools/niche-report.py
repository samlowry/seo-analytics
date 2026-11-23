#!/usr/bin/env python3
"""Шаг 4 niche-scan: таблицы ниш по странам из niche-scan/data/niches.csv → niche-scan/data/report-tables.md.
Порог объёма: доля THRESHOLD_SHARE от суммарной частотности всех ниш страны (доля выставлена по распределению UZ).
Сортировка — по оценке достижимых визитов в месяц, по убыванию."""
import csv, sys, os, collections
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHARE = float(sys.argv[1]) if len(sys.argv) > 1 else 0.01
rows = list(csv.DictReader(open(f'{ROOT}/niche-scan/data/niches.csv')))
for r in rows:
    for k in ('niche_volume', 'est_visits', 'sample_visits', 'sample_keys', 'weak_keys'): r[k] = int(float(r[k]))
BET = {'high': 'высокая', 'medium': 'средняя', 'low': 'низкая'}
LANG = {'ru': 'рус', 'uz': 'узб', 'az': 'азерб', 'tr': 'тур'}
def f(n): return f'{n:,}'.replace(',', ' ')
out = []
for cc in ['UZ', 'KZ', 'AZ', 'TR', 'KG']:
    rr = [r for r in rows if r['cc'] == cc]; total = sum(r['niche_volume'] for r in rr); thr = SHARE * total
    ok = sorted([r for r in rr if r['culled'] == 'False' and r['niche_volume'] >= thr], key=lambda r: -r['est_visits'])
    culled = [r for r in rr if r['culled'] == 'True']; small = [r for r in rr if r['culled'] == 'False' and r['niche_volume'] < thr]
    out.append(f'\n## {cc}\n\nСуммарная частотность 37 ниш: {f(total)} в месяц. Порог ниши: {f(round(thr))} ({SHARE:.1%}).\n')
    out.append('| # | ниша | язык | частотность ниши | достижимо визитов/мес (оценка) | из них по выборке | слабых ключей | медианная целевая позиция | медианный DR топа | близость к беттингу |')
    out.append('|---|---|---|---|---|---|---|---|---|---|')
    for i, r in enumerate(ok, 1):
        out.append(f"| {i} | {r['name']} | {LANG[r['lang']]} | {f(r['niche_volume'])} | **{f(r['est_visits'])}** | {f(r['sample_visits'])} | {r['weak_keys']}/{r['sample_keys']} | "
                   f"{r['best_pos_median'] or '—'} | {r['dr_median'] or '—'} | {BET[r['bet']]} |")
    if culled: out.append('\nОтбракованы как закрытые (2 и больше из 3 головных ключей с обрезанной выдачей без слабых мест): ' + ', '.join(f"{r['name']} ({r['closed_head']})" for r in culled) + '.')
    if small: out.append('\nНиже порога объёма: ' + ', '.join(f"{r['name']} ({f(r['niche_volume'])})" for r in sorted(small, key=lambda r: -r['niche_volume'])) + '.')
open(f'{ROOT}/niche-scan/data/report-tables.md', 'w').write('\n'.join(out) + '\n')
print('\n'.join(out))
