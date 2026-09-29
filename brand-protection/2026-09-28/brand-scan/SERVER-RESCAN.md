# Рескан uBlock-эпохи с genhost через SOCKS на Mac

Первые ~5 652 записи `browser-scan.jsonl.gz` (до 2026-09-29 11:42) шли со
встроенным uBlock Origin. Перегон — **только браузерный трафик** скана через
твой резидентский IP. Default route сервера не трогаем: прод остаётся на
Serverel (Amsterdam).

## Схема

```
Camoufox на genhost  →  socks5://127.0.0.1:1080  →  SSH -R  →  pproxy на Mac  →  Yettel
```

Никакого Tailscale exit node и никакого системного `HTTP_PROXY` на сервере.

## Списки доменов

| файл | сколько | когда брать |
|---|---|---|
| `redo-ublock-all.txt` | 5 652 | полный рескан uBlock-эпохи |
| `redo-ublock-suspect.txt` | 4 138 | только текущие `1_mostbet_only` и `2_no_ads` — там недосчёт рекламы реален |

Перед стартом после локального финиша пересобери списки (локальный проход мог
перекрыть часть доменов):

```bash
# в worktree на Mac
python3 - <<'PY'
# see tools/brand-scan-genhost-prep.sh — or re-run the generator from NOTES
PY
```

Практично: по умолчанию гони `redo-ublock-suspect.txt` (~4 ч при 10 браузерах).
Полный `all` — если хочешь перепроверить и мёртвых/чужих.

## Один раз: подготовка сервера (можно до финиша локального скана)

На Mac, локальный скан **не останавливать**:

```bash
cd ~/Developer/seo-analytics@brand-scan-2026-09-28
chmod +x tools/brand-scan-socks-tunnel.sh tools/brand-scan-genhost-prep.sh
./tools/brand-scan-genhost-prep.sh
```

SSH: `root@genhost.host` (в DNS короткого `genhost` нет).

## Старт (после финиша локального скана + передёргивания IP)

### 1. Mac — туннель (отдельный терминал, не закрывать)

```bash
cd ~/Developer/seo-analytics@brand-scan-2026-09-28
./tools/brand-scan-socks-tunnel.sh
```

Проверка с Mac:

```bash
ssh root@genhost.host 'curl -sS -m 12 -x socks5h://127.0.0.1:1080 https://ipinfo.io/json'
```

Должен быть **твой новый Yettel IP**, не `109.206.164.218`.

### 2. Mac — докинуть свежие данные на сервер

```bash
REMOTE=root@genhost.host
RDIR=/root/seo-analytics-brand-scan
WT=~/Developer/seo-analytics@brand-scan-2026-09-28

# свежий код, списки, http-scan (для --from-http не нужен при --redo, но полезен отчёту)
rsync -az "$WT/tools/brand-scan.py" "$WT/tools/landing_brand.py" "$WT/tools/affiliate-scan.py" \
  "$REMOTE:$RDIR/tools/"
rsync -az "$WT/brand-protection/2026-09-28/brand-scan/"redo-ublock-*.txt \
  "$REMOTE:$RDIR/brand-protection/2026-09-28/brand-scan/"
# пустой/свежий out для серверного прогона — не смешивать с ещё пишущимся локальным файлом
ssh "$REMOTE" "mkdir -p $RDIR/brand-protection/2026-09-28/brand-scan-server"
rsync -az "$WT/brand-protection/2026-09-28/affiliate-scan/camoufox-queue.csv" \
  "$REMOTE:$RDIR/brand-protection/2026-09-28/affiliate-scan/"
# dest cache ускоряет follow на уже известных переходах
rsync -az "$WT/brand-protection/2026-09-28/brand-scan/dest-browser.jsonl.gz" \
  "$REMOTE:$RDIR/brand-protection/2026-09-28/brand-scan-server/" 2>/dev/null || true
```

### 3. genhost — прогон

```bash
ssh root@genhost.host
cd /root/seo-analytics-brand-scan
export PATH="$HOME/.local/bin:$PATH"
export BRAND_SCAN_REGISTRY=/root/seo-analytics-brand-scan/registry/entries.json

# smoke: 5 доменов, убедиться что network=RS … и proxy в логе
nice -n 10 uv run --with 'camoufox[geoip]' --with aiohttp --with aiohttp-socks --with selectolax \
  python tools/brand-scan.py \
  brand-protection/2026-09-28/affiliate-scan/camoufox-queue.csv \
  brand-protection/2026-09-28/brand-scan-server \
  --mode browser --redo brand-protection/2026-09-28/brand-scan/redo-ublock-suspect.txt \
  --proxy socks5://127.0.0.1:1080 --concurrency 2 --limit 5

# полный рескан (подозрительные группы 1+2)
nice -n 10 uv run --with 'camoufox[geoip]' --with aiohttp --with aiohttp-socks --with selectolax \
  python tools/brand-scan.py \
  brand-protection/2026-09-28/affiliate-scan/camoufox-queue.csv \
  brand-protection/2026-09-28/brand-scan-server \
  --mode browser --redo brand-protection/2026-09-28/brand-scan/redo-ublock-suspect.txt \
  --proxy socks5://127.0.0.1:1080 --concurrency 10 \
  2>&1 | tee -a brand-protection/2026-09-28/brand-scan-server/run-browser.log
```

Concurrency: на 31 ГБ стартуй с **8–10**. Если сыплются таймауты — упираешься в аплинк
Yettel, снижай до 6.

### 4. После финиша — забрать результат на Mac и слить

```bash
rsync -az root@genhost.host:/root/seo-analytics-brand-scan/brand-protection/2026-09-28/brand-scan-server/ \
  ~/Developer/seo-analytics@brand-scan-2026-09-28/brand-protection/2026-09-28/brand-scan-server/

# дописать серверные записи в основной лог (report берёт последнюю по домену)
cd ~/Developer/seo-analytics@brand-scan-2026-09-28
python3 - <<'PY'
import gzip, shutil
from pathlib import Path
main = Path('brand-protection/2026-09-28/brand-scan/browser-scan.jsonl.gz')
srv = Path('brand-protection/2026-09-28/brand-scan-server/browser-scan.jsonl.gz')
with gzip.open(main, 'ab') as out, gzip.open(srv, 'rb') as inn:
    shutil.copyfileobj(inn, out)
print('merged')
PY
uv run --with aiohttp --with selectolax python tools/brand-scan-report.py \
  brand-protection/2026-09-28/brand-scan
```

## Жёсткие правила

- На genhost **не** включать Tailscale exit node и **не** ставить `ALL_PROXY`.
- Туннель держать на Mac, пока идёт скан; ноут не усыплять.
- Локальный скан и серверный не писать в один `browser-scan.jsonl.gz` одновременно.
- Наши рефки по-прежнему не запрашиваются (`BRAND_SCAN_REGISTRY`).
- При `--proxy` HTTP-переходы идут через тот же SOCKS, что и браузер (`aiohttp-socks`, в
  `uv run` нужен `--with aiohttp-socks`). Голый HTTP с genhost — Amsterdam: рефки Mostbet
  отвечают `451`, и сайт ложно уходит в `2_no_ads`. Кэш переходов с других сетей при
  `--proxy` не подгружается, кэш внутри прогона работает.
- `--redo` сканирует список заново целиком, даже уже снятые домены: для дозапуска
  собирать остаток, а не перезапускать старый список.

## Что лежит в `brand-scan-server/` (2026-09-29)

- `browser-scan.jsonl.gz.bad-http451` — первый прогон, где HTTP-переходы шли из
  Амстердама. Жертвы `451` перескан перекрывает. **Остальные ~1 850 записей верные**
  (в том числе ~100 переходов «рекламы нет» → чужой бренд) — при сливе брать их оттуда,
  кроме доменов, которые есть в новом логе.
- `browser-scan.jsonl.gz` — перескан с проксированными переходами: `redo-proxy-follow.txt`
  (сначала переходы браузером, ~670 доменов), затем остаток плюс 76 доменов с `451` без
  смены группы — `redo-proxy-http.txt` (HTTP через SOCKS).

## Ночной проход `brand-scan-night/` (с 2026-09-29 ~22:20)

`tools/brand-scan-night.sh` на genhost ждёт окончания рескана и затем снимает
`night-queue.csv` (13 039 сайтов) браузером через SOCKS: `--save-html` (отрисованная
главная в `brand-scan-night/html/<домен>.browser.html.gz`), JS-кнопки жмутся,
`--max-follow 20`, параллельность 8 (машина упирается в CPU уже на ней, ~22 сайта в минуту,
~10 часов). Очередь идёт по приоритету, так что недоделанный хвост — наименее важный:

1. 3 489 — сайты с рекламой или «не определено», которые видел только HTTP (кнопки не жались);
2. 4 873 — Cloudflare, ни разу не открытые браузером (`cloudflare_403/503/401/404…`, без `52x`);
3. 1 323 — `7_unresolved`, снятые браузером, но с непройденными ссылками;
4. 3 354 — уже снятые браузером группы 1–4: нужен только отрисованный HTML.

Если туннель падает, воркеры ждут (`proxy down, waiting` в логе), а не сжигают очередь.
Лог: `brand-scan-night/run-browser.log`. Сливать так же, как `brand-scan-server/`: отчёт
берёт последнюю запись по домену.

Сырой HTML главных для всех ~19 тыс. живых сайтов снимается с Mac режимом `--mode home`
в `brand-scan/html/<домен>.http.html.gz` (лог `home-dump.jsonl.gz`). Папки `html/` в git не
кладутся.
