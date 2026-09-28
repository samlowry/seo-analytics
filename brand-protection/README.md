# Brand protection: домены Mostbet из Corsearch

Выгрузки отчёта Websites из Corsearch (zeal.corsearch.com), переведённые в CSV и проверенные
по DNS. Актуальная — `2026-09-28/`.

В каждой папке три файла:

- `all.csv` — все строки, все колонки выгрузки плюс `domain_ascii` (punycode для IDN),
  `dns_status`, `dns_ips`, `dns_note`;
- `resolves.csv` — есть A или AAAA;
- `not-resolving.csv` — всё остальное, причина в `dns_status`.

`dns_status`: `resolves` — есть адрес; `nxdomain` — имени нет; `no_address` — имя есть,
адресов A/AAAA нет; `error` — почти всегда SERVFAIL: домен зарегистрирован, но его NS не
отвечают (битая делегация), изредка таймаут. Выборочная перепроверка ошибок даёт тот же ответ.

«Ресолвится» не значит «сайт работает» — HTTP не проверялся.

## 2026-09-28 — вся база, 50 895 сайтов

- `resolves` — 34 328;
- `nxdomain` — 12 458;
- `error` — 3 215;
- `no_address` — 894.

Corsearch отдаёт в экспорт не больше 10 000 строк, поэтому база выгружена кусками по дате
обхода (Crawling Date → Exact dates, границы включаются, куски не пересекаются):

- 01.01.2000 – 19.01.2026 — 8 561;
- 20.01.2026 – 22.01.2026 — 8 563;
- 23.01.2026 — 12 051, одним днём не помещается, разбит по статусу сайта
  (Takedown Status → Website): Online 3 463, Offline 8 446, Parked 125, Unknown 17;
- 24.01.2026 – 31.05.2026 — 8 027;
- 01.06.2026 – 31.07.2026 — 4 967;
- 01.08.2026 – 28.09.2026 — 8 726.

Склейка по `website_id`: 50 895 уникальных, дублей нет — совпадает с полным счётчиком.
Колонки `phone_number` и `whatsapp` Corsearch не кладёт в кусок, где они пустые у всех, —
склейка идёт по именам колонок.

### Минус наши домены

`resolves-minus-ours.csv` — `resolves.csv` без наших доменов из
[`our-domains.txt`](our-domains.txt) (469 шт., список от владельца 28.09.2026). Сравнение по
punycode в нижнем регистре, без `www.`: `resolves` 34 328 − 455 наших строк = **33 873**.

Из 469 наших: 453 ресолвятся, среди нересолвящихся нет ни одного, 16 в базе Corsearch нет
вовсе — они в `our-domains-not-in-base.txt` (девять из них на `.co.com`).

Сайты не открывались: часть из них может клоачить, на этом этапе ходим только в DNS.

Фильтры в адресе страницы: `interval=exact_dates&start_date=…&end_date=…`, статус —
`taken_down_websites=ONLINE|OFFLINE|PARKED|UNKNOWN`.

## 2026-09-23 — выгрузка за месяц, 6 568 сайтов

Файл `Mostbet_2026-09-23 17_31_33.800553.xlsx`. `resolves` 5 932, `error` 290,
`nxdomain` 178, `no_address` 168.

## Пересобрать

```
uv run --with openpyxl python tools/corsearch-merge-exports.py <out.csv> <папка с xlsx>
uv run --with openpyxl --with dnspython python tools/brand-protection-dns.py <out.csv|file.xlsx> brand-protection/<дата>
python3 tools/brand-protection-minus-ours.py brand-protection/<дата>
```
