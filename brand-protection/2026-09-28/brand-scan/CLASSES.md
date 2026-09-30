# Классы сайтов brand scan (срез 30.09.2026)

Файл: `classified.csv` — все 33 859 доменов базы Corsearch минус наши, одна категория на сайт и теги.
Пересобрать (без сети):

```
uv run --with selectolax --with aiohttp python tools/brand-site-features.py brand-protection/2026-09-28/brand-scan
uv run --with selectolax --with aiohttp python tools/brand-classify.py brand-protection/2026-09-28
python3 tools/brand-review-page.py brand-protection/2026-09-28/brand-scan/review
```

Источники: `groups.csv` и `destinations.csv` (brand-scan, 22 тыс. сайтов с пройденными ссылками),
`affiliate-scan/` (11,7 тыс., с цепочками шлюзов), признаки из сохранённого HTML (`site-features.jsonl.gz`).

## Категории

Нарушители, главная цель:
- `mono_other` — монобренд Mostbet, аффилиатские ссылки только на чужие бренды;
- `mono_mixed` — монобренд Mostbet, ссылки и на Mostbet, и на чужих (часто ротация одной ссылки).

Монобренд Mostbet, остальное:
- `mono_xlink` — чужой рекламы нет, простые ссылки на сайты других брендов;
- `mono_unresolved` — кнопки ведут на свой шлюз или трекер, до получателя никто не дошёл; здесь могут
  прятаться `mono_other`, нужен сетевой догон с RS-IP;
- `mono_mostbet` — реклама только Mostbet;
- `mono_no_ads` — аффилиатских ссылок нет.

Прочие типы: `mirror` (официальное зеркало), `bait` (Mostbet в домене/title, внутри чужой бренд),
`redirect_ref` / `redirect_other` (главная сразу уводит на рефку Mostbet / чужую), `multibrand`
(гэмблинг-аффилиат не про Mostbet), `article` (статейник, Mostbet в постах), `hacked` (чужая тема,
Mostbet в ссылках, часто скрытых), `other_gambling`, `unrelated`, `unclear`.

Статусы: `stub` (пустая страница), `parked`, `dead`, `not_shown` (защита, ошибка, гео-блок).

Теги: `brand_in_domain`, `moved` (главная переехала на другой хост), `ads_unverified` (есть ссылки,
не пройденные до конца), `rotating_ads` (разные прогоны дали разную рекламу), `search_referrer_js`
(скрипт реагирует на заход из поиска), `apk`, `platform` (blogspot, wix и т. п.), `our_ref`, `no_html`.

Реклама = ссылка с кодом партнёра (параметры `pid`, `tag`, `affiliateCode`, `sub1`…) или проход через
трекер (промежуточный хост). Переезд домена, APK, простая ссылка на сайт — не реклама.

## Проверка

Два круга по 10 сайтов на категорию, равномерно по списку; каждый сайт читали по сохранённому HTML
(`review/round1/`, `review/verdicts-r2-*.json`). После правок по второму кругу классификация сходится с
проверяющим на 171 из 200. Спорные и неуверенные — `review/review.html` для ручной отметки.
