# Цепочки переходов, 20.11.2026

Сняты curl с подменой браузера (Chrome 131, referer — главная сайта). Чешский выход — Протон,
146.70.129.28 (CZ, Прага-Либуш, AS9009 M247). Прямой выход мака в тот день — Латвия (81.94.235.186).

## mostbet-czechia.cz

С чешского IP, `/go/registration` и `/go/download`, по 2 раза — все 4 на Kingmaker:

    302 https://mostbet-czechia.cz/go/registration
    302 https://gotosimn.com/TFmQ9P?sub_id_1=mostbet-czechia.cz&sub_id_2=4dc9a51f
    302 https://famecpa.trk2afse.com/click?pid=2218&offer_id=3538&l=1790601474&sub2=4dc9a51f&sub1=…
    302 https://mysaga.trk2afse.com/click?pid=23&offer_id=216&sub1=…&sub2=2218&sub3=4dc9a51f
    302 https://kngm.kngpulse.com/?mid=346168_2254620&clickid=…
    302 https://k1ngmkr100.com/cs/registration?mid=346168_2254620&…
    200 https://kingmaker-9364.com/cs/registration?mid=346168_2254620&…

С сербского IP (до переключения на Протон) — на Mostbet, обе кнопки:

    302 https://mostbet-czechia.cz/go/registration
    302 https://gotosimn.com/TFmQ9P?sub_id_1=mostbet-czechia.cz&sub_id_2=4dc9a51f
    302 https://oxkhpu.com/tlcs?sub1=4dc9a51f&sub2=…
    302 https://a3n8w6mb.com/registration?cid=8445311231&pid=80872&sip=0
    200 https://a3n8w6mb.com/?registration=1&cid=8445311231&pid=80872&sip=0

## dobirkazdarma.cz

Кнопки — `<a data-v-…>` без href, клик открывает `/to/` новой вкладкой (`window.open`).

С сербского IP:

    302 https://www.dobirkazdarma.cz/to/
    302 https://winshark.link/dwhaxgdel?source=rezerv&visit_id=…
    200 https://winshark13.com/en?stag=109401_…&source=rezerv&tracking_link=http://winshark.link/dwhaxgdel#signup

С чешского IP (2 раза одинаково; конечная страница отвечает curl 403, браузеру — проверкой Cloudflare):

    302 https://www.dobirkazdarma.cz/to/
    302 https://go.gambleon.com/visit/?bta=75223&nci=5393&afp2=rezerv&afp1=…
    403 https://r32snk7b2e9.com/registration?cxd=75223_391224_|afp1:…|afp2:rezerv
