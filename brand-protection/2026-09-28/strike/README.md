# Страйк: 1 814 нарушителей с видеодоказательством

Все сайты, у которых в `../evidence/results.jsonl` стоит `accepted: true`. Label во всех классах —
Trademark Infringement: везде нарушение — бренд Mostbet в домене или на странице, через который
посетителя уводят к чужим. Copyright, Design, Counterfeit не подходят — копирование контента,
дизайна или поддельный товар мы не доказывали.

| файл | класс | сайтов | тег |
|---|---|---:|---|
| `00-pilot-5.xlsx` | по одному из классов 01–05 | 5 | тег своего класса |
| `01-mono_other` | монобренд → только чужие | 1 583 | `strike-01-mono-other` + часть `…-p1`…`-p8` |
| `02-mono_mixed` | монобренд → Mostbet и чужие | 18 | `strike-02-mono-mixed` |
| `03-mb_page_other` | страница про Mostbet → чужие | 9 | `strike-03-mb-page-other` |
| `04-bait` | приманка | 61 | `strike-04-bait` |
| `05-redirect_other` | редирект на чужую рефку | 4 | `strike-05-redirect-other` |
| `06-discredit` | дискредитация | 19 | `strike-06-discredit` |
| `07-mono_hidden` | скрытые ссылки на чужие | 120 | `strike-07-mono-hidden` |

`.xlsx` — по шаблону Corsearch `accounts_manual_upload_sample`: 13 колонок, заполнены `url`, `label`, `tags`, `geo`, `name` (обязательны `url` и `name`), для Uploads → Accounts & Websites. `.csv` — то же плюс `website_id`,
бренд на выходе, конечный URL, путь к видео, текущий Label и `taken_down`. `strike-list.csv` — все классы.

Пилот: загрузить `00-pilot-5.xlsx` → в Websites фильтр по тегу → тег и Label встали на старую запись, а не на
новую-дубль → грузить классы, Batch Update пачками по 500 (в `01` — 4 пачки).

Перед Batch Update: 6 сайтов в Corsearch сейчас с Label Official Store (5 в `04-bait`, 1 в `01`),
25 уже сняты (`taken_down=True`).

`01-mono_other` для загрузки разбит на `01-mono_other-p1…p8.xlsx` по 200 (последняя — 183): у каждой
части второй тег `strike-01-mono-other-pN`, фильтр по нему даёт ровно пачку для Batch Update.

`mostbetfrance.com` выкинут из `01-mono_other-p6.xlsx` (199 сайтов): загрузка отвечает «account already
exists» — в Corsearch у него, видимо, есть вторая запись, которой нет в выгрузке 28.09. Label ставить руками.
