# Задача: разобрать механику регионального редиректа на https://mostbet.com/

> ⚠️ **Исторический документ: исходное ТЗ на замеры, задача выполнена.**
> Оставлен как след того, что и зачем заказывали. Актуальная фактура — в
> [`mostbet-redirect-scheme.md`](mostbet-redirect-scheme.md), план — в
> [`BRAINSTORM-result.md`](BRAINSTORM-result.md).
>
> Что здесь устарело: замеры делались с двух точек выхода, сейчас их 19; вывод
> об отсутствии подмены по User-Agent опровергнут (она есть в US, GR, CY, UZ);
> апекс с тех пор оказался не одним сайтом, а пятью состояниями по странам.
> Оговорка самого ТЗ — «UA-подмена не доказывает клоакинг сама по себе» —
> наоборот, устояла и вошла в итоговые документы.

## Контекст и что уже известно (проверено, но перепроверь)

Запрос из окружения с US-IP:

    curl -sS -I https://mostbet.com/
    HTTP/2 204
    server: nginx
    server-timing: country;desc="US"
    strict-transport-security: max-age=31536000; includeSubDomains; preload

Ключевое:
1. Сервер отдаёт **204 No Content с пустым телом**, а НЕ 301/302. Обычный GET с
   браузерным User-Agent — тоже 204, тело 0 байт.
2. Заголовок `server-timing: country;desc="US"` — гео определяется на эдже
   (nginx/CDN) и прокидывается в ответ.
3. В DevTools у заказчика редирект не виден как 30X, и исходная страница НЕ
   остаётся в истории (кнопка «Назад» не возвращает на mostbet.com).

Рабочая гипотеза (НЕ подтверждена, твоя задача — подтвердить или опровергнуть):
разводка по регионам делается не HTTP-редиректом, а клиентски — `location.replace()`
или аналог, — либо отдачей разного контента на один URL. `location.replace()` как
раз не оставляет записи в истории, что совпадает с симптомом.

Отдельный подозрительный момент: если безбраузерный запрос получает 204, то
краулер, который не исполняет JS, не получает контента вообще.

## Что сделать

Открой https://mostbet.com/ в реальном браузере (Playwright/Puppeteer с headless=false
либо руками в Chrome с открытым DevTools до навигации, галка Preserve log).

### 1. Зафиксируй цепочку навигации
- Все navigation-запросы и ответы: URL, метод, статус, заголовки `location`,
  `refresh`, `set-cookie`, `content-type`, `server-timing`.
- Итоговый URL, `document.referrer`, `history.length` после приземления.
- Есть ли вообще 30X. Если да — какой код (301/302/303/307/308).

### 2. Определи ТИП перехода — это главный вопрос
Различи между:
- HTTP 30X на эдже;
- `<meta http-equiv="refresh">` или заголовок `Refresh:`;
- JS: `location.replace()` / `location.href=` / `location.assign()` /
  `window.open` / `history.replaceState`;
- отсутствие перехода вообще — тот же URL, но разный контент (server-side
  подмена по гео);
- переход внутри SPA-роутера.

Практичный способ поймать JS-редирект: до навигации поставь перехват —

    await page.addInitScript(() => {
      const log = (kind, url) => (window.__redir ??= []).push({kind, url, stack: new Error().stack});
      const nativeReplace = location.replace.bind(location);
      location.replace = u => { log('location.replace', u); return nativeReplace(u); };
      const nativeAssign = location.assign.bind(location);
      location.assign = u => { log('location.assign', u); return nativeAssign(u); };
      const nativeRS = history.replaceState.bind(history);
      history.replaceState = (...a) => { log('history.replaceState', a[2]); return nativeRS(...a); };
      const nativePS = history.pushState.bind(history);
      history.pushState = (...a) => { log('history.pushState', a[2]); return nativePS(...a); };
    });

Потом прочитай `window.__redir` — там будет и стек вызова, то есть какой именно
скрипт инициировал переход. Стек критичен: он покажет, свой это код или сторонний
антифрод/аффилиатный скрипт.

### 3. Найди источник гео-сигнала
- Есть ли XHR/fetch к какому-нибудь `/api/geo`, `/api/config`, `ip-api`,
  `cloudflare/cdn-cgi/trace` и т.п. — что он возвращает.
- Ставятся ли куки со страной/регионом (имя и значение).
- Используется ли `navigator.language`, `Intl.DateTimeFormat().resolvedOptions().timeZone`,
  Geolocation API.
- Совпадает ли выбранный регион со страной из `server-timing`.

### 4. Проверь разницу по клиентам (это про регламенты Google)
Сравни ответ на один и тот же URL при разных условиях. Сравнивай СТАТУС, ДЛИНУ
ТЕЛА и итоговый URL:
- обычный Chrome UA;
- Googlebot UA:
  `Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/W.X.Y.Z Mobile Safari/537.36 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)`;
- curl без UA;
- с JS и с отключённым JS (`javaScriptEnabled: false`) — что видит краулер без исполнения JS;
- если есть возможность — с IP разных стран (VPN/прокси), минимум 2 региона,
  чтобы увидеть, меняется ли целевой домен.

Важно: UA-подмена НЕ доказывает клоакинг сама по себе (Google верифицирует
Googlebot по обратному DNS). Но если по Googlebot-UA отдаётся заметно другой
контент/статус, чем обычному браузеру, — это надо зафиксировать как факт и
описать, не навешивая ярлыков.

### 5. SEO-разметка
- `<link rel="canonical">` на исходной и на конечной странице.
- `hreflang` / `x-default` — есть ли вообще, и согласованы ли они с фактическим
  редиректом.
- `robots.txt` и `X-Robots-Tag` для mostbet.com и для регионального домена.
- Есть ли noindex.

### 6. Сохрани артефакты
- HAR всей сессии (`recordHar` в Playwright).
- HTML исходного ответа (если непустой) и финальной страницы.
- Скриншот.
- Дамп `window.__redir` со стеками.

## Что ответить

Отчёт по пунктам, коротко и фактами, без общих слов:

1. **Тип механики** — одним предложением: чем именно делается переход
   (30X / meta refresh / JS-метод / подмена контента). Со ссылкой на
   доказательство (номер запроса в HAR, строка стека, кусок кода).
2. **Полная цепочка** URL → URL со статусами.
3. **Почему не остаётся в истории** — конкретная причина, а не догадка.
4. **Почему curl получает 204** — что именно триггерит пустой ответ
   (UA, TLS-фингерпринт, отсутствие куки, гео).
5. **Источник гео** — где принимается решение: эдж или клиент.
6. **Таблица различий** по клиентам из п.4: клиент → статус → размер тела →
   финальный URL.
7. **Оценка по требованиям Google** — со ссылками на актуальную документацию
   (spam policies: cloaking, sneaky redirects; JS-redirect guidance;
   localized versions / hreflang). Отдельно: индексируем ли контент вообще,
   если краулер не исполняет JS и получает 204.
   Формулируй как «соответствует / не соответствует / требует уточнения» с
   обоснованием. Не утверждай нарушение там, где данных не хватает.
8. **Чего не удалось проверить** и почему (например, не было IP нужной страны).

Если какой-то пункт проверить не вышло — так и напиши, не выдумывай.
