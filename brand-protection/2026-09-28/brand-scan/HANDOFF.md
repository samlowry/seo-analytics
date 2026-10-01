# Handoff: brand-scan Mostbet (продолжение в Claude Code)

Срез: 2026-09-30. Ветка / worktree: `brand-scan-2026-09-28` →
`~/Developer/seo-analytics@brand-scan-2026-09-28`.

**Карта файлов Mac + genhost:** [SERVER-LAYOUT.md](SERVER-LAYOUT.md).  
**Как поднимать SOCKS и гонять на сервере:** [SERVER-RESCAN.md](SERVER-RESCAN.md).

Задача: по списку доменов понять, кто **юзает бренд Mostbet** и куда уходит
трафик (наша партнёрка / чужое казино / никуда), без запросов **наших** рефок
из реестра.

---

## 1. SOCKS: genhost через ноутбук

Цель: браузер и HTTP-follow с genhost выходят с **резидентского Yettel RS IP**
(серия `109.245.…`), а прод на Serverel (Amsterdam) не трогается.

Схема:

```
Camoufox / aiohttp на genhost
  → socks5://127.0.0.1:1080
  → SSH -R (reverse)
  → pproxy / socks5 на Mac
  → Yettel
```

На Mac (терминал не закрывать, ноут не усыплять, `caffeinate` уже использовали):

```bash
cd ~/Developer/seo-analytics@brand-scan-2026-09-28
./tools/brand-scan-socks-tunnel.sh
```

Скан на сервере: `--proxy socks5://127.0.0.1:1080` и в `uv run` обязательно
`--with aiohttp-socks`. Без прокси follow с Amsterdam даёт `451` на лендингах
Mostbet → ложное «рекламы нет».

Жёстко: **не** Tailscale exit node на genhost, **не** `ALL_PROXY`. Реестр:
`BRAND_SCAN_REGISTRY=…/registry/entries.json` — наши рефки abort / skip.

Подробности команд, smoke, concurrency — в [SERVER-RESCAN.md](SERVER-RESCAN.md).

---

## 2. Какие прогоны уже сделаны

Порядок по смыслу (даты 28–30.09.2026):

1. **HTTP-скан** (`--mode http`) — главная + follow ссылок без браузера. Лог:
   `http-scan.jsonl.gz`. Часть сайтов осталась `needs_browser`.
2. **Destination pass** (`--mode destinations`) — в браузере только URL, которые
   HTTP не решил. `dest-browser.jsonl.gz`.
3. **Browser pass** (`--mode browser`, в т.ч. `--from-http`) — целые сайты. Ранние
   записи шли с **включённым uBlock** в Camoufox → недосчёт рекламы; дальше uBlock
   выключен (`exclude_addons=[UBO]`).
4. **Серверный рескан через SOCKS** → `brand-scan-server/`. Первый заход: HTTP-follow
   шёл из Amsterdam → много `451` (файл `browser-scan.jsonl.gz.bad-http451`;
   ~1.7k записей без перекрытия доменом из нового лога — валидны). Второй:
   follow через SOCKS (`redo-proxy-follow.txt` / `redo-proxy-http.txt`).
5. **Пересчёт отчёта без рескана** — правки в `landing_brand.py` /
   `brand-scan-report.py`: Azino≠kazino, `7_unresolved`, `8_no_mention`,
   `0_mostbet_frontend`, «неопознанный title без трекера ≠ реклама».
6. **HTTP-дамп главных** (`--mode home`) с Mac, IP Yettel: сырой HTML всех живых
   (~19k) → `brand-scan/html/<d>.http.html.gz`, лог `home-dump.jsonl.gz`.
   30.09 дозалиты 11 728 доменов, которые `affiliate-scan` решил сам (`affiliate.csv` +
   `not-affiliate.csv`, в `groups.csv` их нет): очередь `home-dump-affiliate-queue.csv`,
   сохранено 11 557.
7. **Rest pass** (`--mode rest`) с Mac: непройденные кандидаты из браузерных записей
   (в т.ч. с кликов) догоняются HTTP → `rest-scan.jsonl.gz`.
8. **Ночной browser** на genhost (`brand-scan-night.sh`, очередь `night-queue.csv`,
   ~10k): `--save-html`, клики CTA, `--max-follow 20`, concurrency 8. Закончился
   ~05:07 30.09. Отрисованный HTML: `<d>.browser.html.gz`, перенесён в общий `brand-scan/html/`.
   Слито в основной `browser-scan.jsonl.gz`.

Отчёт сейчас: **последняя запись по домену + реклама из любого прошлого прогона**
(`with_history` в `brand-scan-report.py`). Поля: `latest_group`, `ever_*`,
`ads_differ`, `group_history`. Рекламные dest из старых прогонов — в
`destinations.csv` с колонкой `scan`.

Группы на срезе (после истории):

| группа | ~N | смысл |
|---|---|---|
| `0_mostbet_frontend` | 134 | официальный фронт (зеркало): title вида `MostBet.com …` |
| `1_mostbet_only` | 2125 | реклама только Mostbet (когда-либо) |
| `2_no_ads` | 2899 | открылся, рекламы нет |
| `3_other_only` | 1589 | только чужие казино |
| `4_mixed` | 166 | и Mostbet, и чужие |
| `7_unresolved` | 1287 | «нет рекламы» не доказано (ссылки/кнопки не дожаты) |
| `8_no_mention` | 605 | на главной нет Mostbet и нет Mostbet-рекламы |
| `5_dead` / `5_not_shown` | 3048 / 10223 | мёртвые / не показались |
| `6_cf_check` | 55 | challenge не прошёл пассивным ожиданием |

~4.8k «cloudflare_*» в `5_not_shown`: браузер с RS IP часто даёт те же 403/503/404 —
это чаще мёртвый/закрытый origin, не «надо кликнуть Turnstile». Живых среди них мало.

---

## 3. Ручной review (HTML-выборка)

Сделана страница `/tmp/brand-review/review.html`: по 5 сайтов из каждой группы,
равномерно по списку, со ссылками и классами; вердикты в localStorage + export JSON.

Главные выводы владельца по review (не терять):

- **Не сохранили контент страниц** — большая ошибка первого прохода; исправлено
  дампами `home` + night `--save-html`.
- **Рефки на кнопках** браузер иногда не ловил: старый проход брал только
  `needs_browser` после dest-pass; сайты с «уже решёнными» dest выпадали.
- **Статейники и линк-селлеры ≠ affiliate abuse бренда.** Смотреть:
  - плотность упоминаний Mostbet на главной (даже по `mostbet_mentions` /
    `text_len` из лога, без HTML);
  - тип ссылок: партнёрские параметры / коды / цепочки трекеров vs простые ссылки;
  - цепочки на другие бренды.
- **Наши зеркала** (старый дизайн, язык по гео) попали в данные → группа
  `0_mostbet_frontend` по шаблону title `MostBet.com …` (не путать с дорвеями
  «Mostbet Official Website…»).
- Cloudflare **не пропускать** «насовсем» — отрабатывать отдельно; многие могут
  открыться в Camoufox (на практике большая часть 403/503 оказались мёртвыми).

Примеры из review: `mostbet.de.com` — типичный abuser (чужой бренд + трекер);
`1xbet.com` — чужой оператор, 0 упоминаний Mostbet → `8_no_mention`;
`51m0s8b.com` — наше зеркало; `mostbet-casino-azerbaycan.com` /
`mostbetkz-mobile.kz` — рефка на кнопках, HTTP видел «пусто».

---

## 4. Как качали контент

**Сырой HTML (Mac, `--mode home`):** один GET главной через aiohttp (тот же
стек, что HTTP-скан), редиректы руками, тело до cap из affiliate-scan. Файл:
комментарий-шапка `<!-- brand-scan http … status=… final_url=… -->` + HTML,
gzip. Follow ссылок **нет**, группы не меняет. Список: `home-dump-domains.txt`
(все не-`5_dead` из отчёта на тот момент).

**Отрисованный HTML (genhost night, `--save-html`):** после settle +
пассивного ожидания challenge (кликать Turnstile / Cloudflare **запрещено** —
safety) пишется DOM: `<domain>.browser.html.gz`. Параллельно кликаются CTA
без href (capture navigation abort), follow до `--max-follow 20`.

Флаг `--save-html` работает и в `http`/`browser` режиме обычного скана.

---

## 5. Классификация: куда идём дальше

Текущие группы 1–4 — про **куда уходит трафик по follow**, не про **тип сайта**.
Договорились: две оси после HTML.

**Ось A — тип сайта** (по контенту главной):

- плотность Mostbet (mentions / text_len, домен/title);
- статейник / линк-селлер / дорвей на бренде / наше зеркало / чужой оператор /
  сайт без отношения к бренду.

**Ось B — слив трафика:**

- есть ли **реф-подобные** ссылки (params `pid`/`p`/`tag`/`cxd`/`affiliateCode`/…
  из `AFF_PARAMS`/`TRACK_PARAMS`, трекер-хосты, `/go/` → чужой хост);
- Mostbet vs чужой бренд vs mixed;
- ротация: `mostbet2.click` / `mosttbet.ink` в разные прогоны вели то на Mostbet
  (`pid=444325`), то на чужое → сейчас `4_mixed` через историю. Такие —
  «юзают бренд», ребаланс групп отдельно.

**Не называть «взломанным» сайт только потому, что реклама то появляется, то нет.**
Пример `detailsquad.pt`: в HTML есть скрипт, который при реферере из поиска
открывает popunder на трекер → чужое казино. По плотности Mostbet и смыслу
страницы это скорее **аффилиатский / дорвейный** паттерн, а не «скомпрометированный
чужой сайт». **Взломанный** в нашей рамке — когда сайт **не про Mostbet** (магазин,
блог без бренда), а в него воткнули рефку. Тип сайта — сначала по плотности
и тематике текста, потом по ссылкам.

Слив = именно реф-подобные уходы, не любая внешняя ссылка (Springer, Telegraph,
sister-domain без params — не ads; см. `_tracked` / `unrecognized_no_tracker`).

---

## 6. Известные грабли

- Отчёт без истории брал **только последний** прогон → ротация `/go/` и
  search-popunder «исчезали». Исправлено `with_history`.
- Azino regex ловил «kazino/казино» — починен lookbehind; stale `fields:Azino777`
  перепроверяются в `refine`.
- Page title как «бренд» без трекера → не ad.
- `--redo` = весь список заново; для дозапуска собирать remainder.
- Кэш dest с других сетей при `--proxy` не грузится.
- HTML в git не коммитить; без worktree на Mac Claude Code HTML не увидит.
- Не писать код автоклика Cloudflare/Turnstile.

---

## 7. Что делать в Claude Code дальше

1. Читать этот файл + [SERVER-LAYOUT.md](SERVER-LAYOUT.md); код —
   `tools/brand-scan-report.py`, `landing_brand.py`.
2. По сохранённому HTML (предпочитать `*.browser.html.gz`, иначе `*.http.html.gz`)
   разметить **тип сайта** и уточнить **слив**; пороги плотности + правила ссылок —
   согласовать с владельцем, не выдумывать в вакууме.
3. Детализировать группы / колонки отчёта под две оси; ротирующих (ads_differ)
   не терять.
4. Cloudflare/`5_not_shown` — отдельно и точечно, не второй ночной прогон на все 10k.

Команды отчёта и пути — в SERVER-LAYOUT. Новый код/доки — в том же worktree
ветки `brand-scan-2026-09-28` (или новая ветка от ствола
`claude/mostbet-regional-redirect-lf5lyh` по branch-per-task, если это уже другая
задача).
