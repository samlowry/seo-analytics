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
