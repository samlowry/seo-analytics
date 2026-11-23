# Ручная проверка 20.11.2026: mostbet-czechia.cz, dobirkazdarma.cz

Два домена от владельца («там вроде прямой кросс»). Прогнан тот же конвейер, что у среза 2026-09-28,
в отдельной папке, чтобы не переписать общие `groups.csv` / `classified.csv` / `confidence.csv`.

| шаг | mostbet-czechia.cz | dobirkazdarma.cz |
|---|---|---|
| наш ли | нет: нет в `our-domains.txt`, реестре рефок, jamstack-sites, fair-pages-kit, cf-panel | нет, там же |
| Corsearch | в базе, website_id 18144933, без метки; отправлен на снос (23.11) | не было в базе; отправлен на снос (23.11) |
| `brand-scan.py` http + browser | `3_other_only`, Kingmaker (чешский IP) | `3_other_only`, WinShark (прямой выход, LV) |
| `brand-classify.py` | `mono_other`, brand_in_domain | `mono_other`, rotating_ads |
| `brand-confidence.py` | не запускался: калибровка по раундам проверки, на двух доменах не имеет смысла; класс проверен вручную по скану, цепочкам и ролику |
| видео | в пакете: клик «Přihlášení» → Kingmaker, чешский IP | в пакете: клик «Registrujte se a získejte bonus» → WinShark |

- `queue.csv` — вход сканера; `brand-scan/` — логи, отчёт, классификация, HTML главных.
- `takedown-send.csv` — оба домена на снос, те же колонки, что в срезе 2026-09-28.
- `evidence/` — ролики и `results.jsonl`, как у среза 2026-09-28.
- **Оба домена отправлены владельцем в Corsearch на снос** (отмечено 23.11.2026; колонка `sent_to_corsearch`
  в `takedown-send.csv`). В страйк-лист среза 2026-09-28 (`../2026-09-28/strike/`) не входят: отправлены отдельно.
- `chains.md` — цепочки переходов с чешского и сербского IP.

Как запускали (из корня репо; чешский выход — Протон через mihomo, `proton-sv geo cz`, порт 7892):

```bash
R=brand-protection/2026-11-20
uv run --with aiohttp --with aiohttp-socks --with 'selectolax<1' python tools/brand-scan.py $R/queue.csv $R/brand-scan --mode http --save-html --proxy socks5://127.0.0.1:7892
uv run --with 'camoufox[geoip]' --with aiohttp --with aiohttp-socks --with 'selectolax<1' python tools/brand-scan.py $R/queue.csv $R/brand-scan --mode browser --from-http --save-html --proxy socks5://127.0.0.1:7892
uv run --with 'camoufox[geoip]' --with aiohttp --with aiohttp-socks --with 'selectolax<1' python tools/brand-scan.py $R/queue.csv $R/brand-scan --mode browser --redo $R/redo-rs.txt --save-html   # dobirkazdarma без прокси
uv run --with aiohttp --with aiohttp-socks --with 'selectolax<1' python tools/brand-scan-report.py $R/brand-scan
uv run --with aiohttp --with 'selectolax<1' python tools/brand-site-features.py $R/brand-scan
uv run --with aiohttp --with 'selectolax<1' python tools/brand-classify.py $R    # affiliate-scan/ — пустые заглушки
uv run --with 'camoufox[geoip]' --with 'selectolax<1' --with aiohttp --with aiohttp-socks python tools/brand-evidence-video.py $R/brand-scan $R/evidence/domains-cz.txt $R/evidence --proxy socks5://127.0.0.1:7892
uv run --with 'camoufox[geoip]' --with 'selectolax<1' --with aiohttp --with aiohttp-socks python tools/brand-evidence-video.py $R/brand-scan $R/evidence/domains-direct.txt $R/evidence
```

Рекордер поправлен в тот же день: Camoufox исполняет подмену `window.open` в изолированном мире, и сайт,
открывающий рефку новой вкладкой, давал отказ «клик не уводит с сайта». Теперь адрес новой вкладки
открывается в записываемой странице.
