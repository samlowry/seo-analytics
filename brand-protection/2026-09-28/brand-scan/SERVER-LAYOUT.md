# Где что лежит: Mac и genhost

Дата среза: 2026-09-30. Worktree: `~/Developer/seo-analytics@brand-scan-2026-09-28`,
ветка `brand-scan-2026-09-28`. Как поднимать SOCKS и запускать прогоны —
[SERVER-RESCAN.md](SERVER-RESCAN.md). Смысл задачи и выводы — [HANDOFF.md](HANDOFF.md).

## Mac (источник правды для Claude Code)

Всё для продолжения работы — локально. На genhost копии остались, но ими можно
не пользоваться.

| путь | что |
|---|---|
| `brand-protection/2026-09-28/brand-scan/` | основной каталог: логи скана, отчёт, списки redo, HTML-дамп (сырой) |
| `…/brand-scan/http-scan.jsonl.gz` | HTTP-проход по сайтам (главная + follow ссылок без браузера) |
| `…/brand-scan/browser-scan.jsonl.gz` | все браузерные записи, **уже слитые** (локальные + server + night) |
| `…/brand-scan/dest-browser.jsonl.gz` | кэш follow, которые HTTP не решил |
| `…/brand-scan/rest-scan.jsonl.gz` | HTTP-догон непройденных ссылок из браузерных записей (`--mode rest`) |
| `…/brand-scan/home-dump.jsonl.gz` | лог `--mode home` (только скачивание главных) |
| `…/brand-scan/groups.csv`, `destinations.csv` | свежий отчёт (`brand-scan-report.py`, с историей прогонов) |
| `…/brand-scan/html/` | **весь HTML в одном месте**, 40 472 файла на 30 459 доменов, 681 МБ. `<domain>.http.html.gz` — сырой HTML главной (30 266, все живые из `groups.csv` + `affiliate-scan`); `<domain>.browser.html.gz` — отрисованный из ночного прохода (10 206). **В git не лежит** (`.gitignore`) |
| `…/brand-scan-server/` | сырые логи серверного рескана до слияния; `.bad-http451` — первый прогон без SOCKS на HTTP-follow |
| `…/brand-scan-night/` | сырой ночной прогон: `browser-scan.jsonl.gz`, `run-browser.log` |
| `tools/brand-scan.py` | сканер: режимы `http` / `destinations` / `browser` / `home` / `rest` |
| `tools/landing_brand.py` | бренды, refine, `_tracked`, зеркала, группы 1–4 |
| `tools/brand-scan-report.py` | отчёт; `post_group` (0/7/8), `with_history` (реклама из любого прогона) |
| `tools/brand-scan-socks-tunnel.sh` | Mac: локальный SOCKS + SSH `-R` на genhost |
| `tools/brand-scan-night.sh` | genhost: ночной browser-проход (ждёт предыдущий скан) |
| `tools/socks5-local.py` | запасной локальный SOCKS (в туннеле сейчас `uvx pproxy`) |

Отчёт пересобрать:

```bash
cd ~/Developer/seo-analytics@brand-scan-2026-09-28
uv run --with aiohttp --with selectolax python tools/brand-scan-report.py \
  brand-protection/2026-09-28/brand-scan
```

## genhost (`root@genhost.host`)

Корень: `/root/seo-analytics-brand-scan` — **не git-репозиторий**, копия файлов
(rsync / scp). Реестр наших рефок: `BRAND_SCAN_REGISTRY=/root/seo-analytics-brand-scan/registry/entries.json`
(сканер их не запрашивает).

| путь на сервере | что |
|---|---|
| `/root/seo-analytics-brand-scan/tools/` | `brand-scan.py`, `landing_brand.py`, `affiliate-scan.py`, `brand-scan-night.sh` |
| `…/brand-protection/2026-09-28/brand-scan/` | списки `redo-*.txt`, `night-queue.csv` (без полного зеркала Mac) |
| `…/brand-protection/2026-09-28/brand-scan-server/` | рескан через SOCKS (29.09); после слияния на Mac можно не трогать |
| `…/brand-protection/2026-09-28/brand-scan-night/` | ночной прогон 29–30.09; HTML в `html/` (~10k файлов) |
| `…/brand-protection/2026-09-28/affiliate-scan/camoufox-queue.csv` | очередь доменов |

SOCKS на сервере: `127.0.0.1:1080` — reverse-tunnel с Mac. Default route genhost
(Amsterdam / Serverel) **не меняем**. Не включать Tailscale exit node и не ставить
`ALL_PROXY` / системный `HTTP_PROXY`.

Проверка туннеля с genhost:

```bash
curl -sS -m 12 -x socks5h://127.0.0.1:1080 https://ipinfo.io/json
# нужен RS / Yettel (109.245.…), не NL / Serverel
```

SSH с Mac удобно через ControlMaster (иначе 1Password ломает ssh из tmux):

```bash
ssh -o ControlPath=~/.ssh/cm-genhost-brandscan root@genhost.host
```

## Что в git, чего нет

В git: код, jsonl.gz логов, csv отчёта, списки доменов, `run-*.log`,
`SERVER-RESCAN.md`, этот файл, `HANDOFF.md`.

Не в git: `brand-protection/*/brand-scan*/html/` — только на диске Mac (и копия
night-html ещё на genhost). Без локального worktree HTML для Claude Code недоступен.
