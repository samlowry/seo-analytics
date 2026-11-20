# Панель доказательств нарушений

Список на снос (`brand-scan/report/takedown-send.csv`, 3 424 домена) с поиском. У каждого домена:
- текст нарушения;
- ролик, если есть: из пакета (1 814) или из отказа (723, помечен «не доказательство»);
- сохранённая главная: просмотр без скриптов и скачивание исходника;
- метка Corsearch и строка страйка.

Поиск находит домен и там, где он стоит в середине цепочки. Пример: у `mostbet-kg.kg` своего ролика
нет, но через него проходят 120 роликов редиректоров.

Данные лежат на ветке `brand-scan-2026-09-28` (`brand-protection/2026-09-28/`), сюда не копируются.

```bash
D=~/Developer/seo-analytics@brand-scan-2026-09-28/brand-protection/2026-09-28
python3 tools/evidence-panel/build_index.py $D tools/evidence-panel/data/data.json
python3 tools/evidence-panel/server.py $D --port 8790   # http://127.0.0.1:8790/
```

Только stdlib Python. Сервер отдаёт ролики с перемоткой (Range) и HTML из `.html.gz`. При просмотре
вырезаны `<script>` и `meta refresh`, стоит `CSP: sandbox`. Скачивание (`?dl=1`) отдаёт файл как есть.

## На VPS

Адрес — https://reports.apex-gravity.com/evidence/ (только из VPN, без входа через GitLab; остальной
сайт отчётов по-прежнему за входом). Ответы с `X-Robots-Tag: noindex, nofollow`.

- VPS `162.248.160.64`, пользователь `seoapps`, вход `ssh vps-seoapps`.
- Код: `~/apps/evidence-panel/` (`server.py`, `index.html`, `build_index.py`), список — `~/apps/evidence-panel/data/data.json`.
- Данные: `~/evidence-data/2026-09-28/` — `evidence/` целиком (ролики пакета и отказа) и из
  `brand-scan/html/` только варианты страниц, которые есть в `data.json` (`page.all`).
- Сервис: user-юнит `evidence-panel.service`, `127.0.0.1:8085`, поднимается сам после перезагрузки.
- Маршрут: Caddy `~/caddy/Caddyfile`, блок `reports_app`: `/evidence` → 301 на `/evidence/`,
  `/evidence/*` → `127.0.0.1:8085` со снятием префикса, мимо `require_login`. Конфиг и юнит лежат
  в fair-pages-kit, `infra/vps/files/` (ветка `infra/vps-evidence-panel`).

Обновить данные (с мака):

```bash
D=~/Developer/seo-analytics@brand-scan-2026-09-28/brand-protection/2026-09-28
P=tools/evidence-panel
python3 $P/build_index.py $D $P/data/data.json
python3 -c "import json;d=json.load(open('$P/data/data.json'));print('\n'.join(sorted({f'{r[\"domain\"]}.{k}.html.gz' for r in d['rows'] if r['page'] for k in r['page']['all']})))" > /tmp/html-list.txt
rsync -a --files-from=/tmp/html-list.txt $D/brand-scan/html/ vps-seoapps:evidence-data/2026-09-28/brand-scan/html/
rsync -a $D/evidence vps-seoapps:evidence-data/2026-09-28/
rsync -a $P/server.py $P/index.html $P/build_index.py vps-seoapps:apps/evidence-panel/
rsync -a $P/data/data.json vps-seoapps:apps/evidence-panel/data/
ssh vps-seoapps systemctl --user restart evidence-panel   # нужен только после правки server.py
```

`index.html` и `data.json` сервер читает с диска на каждый запрос, поэтому после их замены перезапуск не нужен.
