# Trustpilot: выдача по «mostbet» и pid вебмастеров — 03.11.2026

Выдача `trustpilot.com/search?query=mostbet&experiment=semantic_search_enabled`: 11 страниц,
101 компания (`trustpilot-search-urls.txt`). 48 из них к Mostbet не относятся (поиск нечёткий:
`hostnet.nl`, `rustbet.com`). Остальные 53 открыты браузером с сербского IP; живую рефку каждого
сайта прошли один раз, чтобы увидеть `pid` после редиректа трекера.

`pids.csv` — 53 сайта: `pid` найден у 20, причина отсутствия — у остальных 33 (`status`).
Наших `pid=414669` и сетки апекса `pid=35818` среди них нет. Самый частый — `37776`, 7 сайтов.

## Загрузка в Corsearch

10 сайтов с Mostbet в домене или контенте, кнопки которых ведут на чужие бренды: 5 напрямую
(20Bet, Kaasino, Slotornado, казино winstrazuz) и 5 через TDS (Verde Casino, Vivatbet; так из RS,
из других стран TDS может вести иначе).

| файл | что | тег |
|---|---|---|
| `upload-sites.csv` / `.xlsx` | 10 сайтов | `tp-2611-sites` |
| `upload-trustpilot.csv` / `.xlsx` | их 10 страниц на Trustpilot | `tp-2611-trustpilot` |

Формат — шаблон Corsearch `accounts_manual_upload_sample`, как в `strike/` ветки
`brand-scan-2026-09-28`: Label — Trademark Infringement, geo — GLOBAL.

В выгрузке Corsearch 28.09.2026 есть 9 сайтов из 10, кроме `mostbet-zaklady.pl`. Три уже стоят
в страйк-листе: `mostbet-site.org`, `mostbetslots.com.de` (`strike-01-mono-other`),
`mostbet-cz.co` (`strike-01` и `strike-05`); у них новый тег станет вторым.
