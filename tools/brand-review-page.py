"""Review page for the sites the automatic check was not sure about.

Run: python3 tools/brand-review-page.py brand-protection/2026-09-28/brand-scan/review [--max-confidence 0.7]
Reads sample.json and verdicts-*.json from the review folder, keeps sites judged "wrong" or "unsure" or with
confidence below the threshold, writes review.html next to them: one card per site with the category given
by the classifier, the checker's opinion, the evidence, and "right / wrong / note" controls. Marks stay in the
browser (localStorage); "Copy all" puts them on the clipboard as JSON.
"""
import html
import json
import sys
from pathlib import Path

CATEGORY_RU = {
    "mono_other": "Монобренд → только чужие", "mono_mixed": "Монобренд → Mostbet и чужие",
    "mono_xlink": "Монобренд, простые ссылки на чужих", "mono_mostbet": "Монобренд → только Mostbet",
    "mono_unresolved": "Монобренд, получатель рекламы неизвестен", "mono_no_ads": "Монобренд без рекламы",
    "mirror": "Зеркало Mostbet", "bait": "Приманка: Mostbet в имени, внутри чужой",
    "multibrand": "Гэмблинг-аффилиат не про Mostbet", "article": "Статейник", "hacked": "Взломанный",
    "other_gambling": "Чужой гэмблинг", "unrelated": "Не про гэмблинг", "unclear": "Неясно", "stub": "Пустышка",
    "parked": "Парковка", "dead": "Мёртвый", "not_shown": "Не показался", "redirect_ref": "Редирект на рефку Mostbet",
    "redirect_other": "Редирект на чужую рефку",
}


def e(x) -> str:
    return html.escape(str(x or ""))


def main(folder: str, max_conf: float = 0.7):
    folder = Path(folder)
    sample = {x["domain"]: x for x in json.loads((folder / "sample.json").read_text())}
    verdicts = []
    for p in sorted(folder.glob("verdicts-*.json")):
        verdicts += json.loads(p.read_text())
    import csv
    csv.field_size_limit(10**9)
    cur = {}
    cls = folder.parent / "classified.csv"
    if cls.exists():
        with open(cls, newline="", encoding="utf-8") as f:
            cur = {r["domain"]: r for r in csv.DictReader(f)}
    for v in verdicts:  # judge against the current classification, not the one the checker saw
        expected = v.get("should_be") if v.get("verdict") == "wrong" else v.get("given")
        now = (cur.get(v["domain"]) or {}).get("category") or v.get("given")
        v["now"], v["agrees"] = now, v.get("verdict") != "unsure" and now == expected
        if v["domain"] in cur:
            sample[v["domain"]] = {**sample.get(v["domain"], {}), **{k: cur[v["domain"]][k] for k in
                                   ("why", "tags", "mostbet_ads", "other_ads", "plain_gambling_links", "mb_text", "mb_per_1k", "other_brands_text")}}
    keep = [v for v in verdicts if not v["agrees"] or float(v.get("confidence") or 0) < max_conf]
    keep.sort(key=lambda v: (v.get("now") or "", v["domain"]))
    cards = []
    for v in keep:
        s = sample.get(v["domain"], {})
        links = "".join(f'<li><a href="{e(x.get("url"))}" rel="noreferrer">{e(x.get("url"))[:90]}</a> '
                        f'<span class="t">{e(x.get("text"))} {e(x.get("brand"))}</span></li>'
                        for x in (s.get("aff_links") or [])[:8])
        facts = [("почему", s.get("why")), ("теги", s.get("tags")), ("реклама Mostbet", s.get("mostbet_ads")),
                 ("реклама чужих", s.get("other_ads")), ("простые ссылки", s.get("plain_gambling_links")),
                 ("Mostbet в тексте", f'{s.get("mb_text")} ({s.get("mb_per_1k")}/1k)'),
                 ("чужие бренды в тексте", s.get("other_brands_text")), ("title", s.get("title")), ("h1", s.get("h1"))]
        grid = "".join(f'<div class="kv"><span>{k}</span><b>{e(val)}</b></div>' for k, val in facts if val not in ("", None))
        given, should = v.get("now"), (v.get("should_be") if v.get("verdict") == "wrong" else v.get("given"))
        cards.append(f'''<article class="card" data-domain="{e(v["domain"])}" data-given="{e(given)}">
<header><a class="dom" href="https://{e(v["domain"])}/" target="_blank" rel="noreferrer">{e(v["domain"])}</a>
<span class="badge">{e(CATEGORY_RU.get(given, given))}</span>
<span class="op">проверяющий: <b>{e(CATEGORY_RU.get(should, should)) if v.get("verdict") != "unsure" else "не уверен"}</b>
· уверенность {e(v.get("confidence"))}</span></header>
<p class="comment">{e(v.get("comment"))}</p>
<div class="grid">{grid}</div>
<div class="sample">{e((s.get("text_sample") or "")[:400])}</div>
{f'<ul class="links">{links}</ul>' if links else ''}
<footer><label><input type="radio" name="v-{e(v["domain"])}" value="ok"> категория верна</label>
<label><input type="radio" name="v-{e(v["domain"])}" value="bad"> неверна</label>
<input class="note" placeholder="какая должна быть / комментарий"></footer></article>''')
    page = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Проверка классов brand scan</title><style>
:root{{--bg:#f1f5f9;--card:#fff;--fg:#0f172a;--mut:#64748b;--line:#e2e8f0;--acc:#2563eb;--ok:#16a34a;--bad:#dc2626}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0b1120;--card:#111827;--fg:#e5e7eb;--mut:#94a3b8;--line:#1f2937;--acc:#60a5fa}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:16px}} h1{{font-size:20px;margin:4px 0}} .sub{{color:var(--mut);margin-bottom:12px}}
nav{{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;gap:8px;align-items:center;z-index:2}}
button{{border:0;background:var(--acc);color:#fff;padding:7px 12px;border-radius:8px;cursor:pointer}}
.card{{background:var(--card);border-radius:10px;padding:12px 14px;margin-bottom:10px;border:2px solid transparent}}
.card.ok{{border-color:var(--ok)}} .card.bad{{border-color:var(--bad)}}
header{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}} .dom{{font-weight:700;font-size:16px;color:var(--fg)}}
.badge{{background:var(--acc);color:#fff;border-radius:6px;padding:2px 8px;font-size:12px}} .op{{color:var(--mut);font-size:12.5px}}
.comment{{margin:6px 0}} .grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:2px 14px;font-size:12.5px}}
.kv{{display:flex;gap:6px;min-width:0}} .kv span{{color:var(--mut);white-space:nowrap}} .kv b{{font-weight:500;overflow-wrap:anywhere}}
.sample{{color:var(--mut);font-size:12px;margin:6px 0}} .links{{font-size:12px;margin:4px 0;padding-left:18px;overflow-wrap:anywhere}} .t{{color:var(--mut)}}
footer{{display:flex;flex-wrap:wrap;gap:12px;align-items:center;border-top:1px dashed var(--line);padding-top:8px;margin-top:6px}}
.note{{flex:1;min-width:200px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--fg);font:inherit}}
</style></head><body><main>
<h1>Проверка классов brand scan</h1>
<div class="sub">Сайты второго круга проверки, где проверяющий не уверен (ниже {max_conf}) или не согласен с текущей категорией: {len(keep)} из {len(verdicts)}.
Синяя плашка — категория классификатора сейчас; «проверяющий» — что считает агент, читавший HTML.
Ссылки открывают живой сайт. Отметки хранятся в этом браузере; «Скопировать всё» кладёт их в буфер JSON-ом.</div>
<nav><button id="exp">Скопировать всё</button><span id="cnt" class="sub"></span></nav>
{''.join(cards)}
<script>
const KEY='brand-classes-review-r2';let st={{}};try{{st=JSON.parse(localStorage.getItem(KEY)||'{{}}')}}catch(e){{}}
const save=()=>{{try{{localStorage.setItem(KEY,JSON.stringify(st))}}catch(e){{}};document.getElementById('cnt').textContent=Object.values(st).filter(x=>x.v).length+' отмечено'}};
document.querySelectorAll('.card').forEach(c=>{{const d=c.dataset.domain,s=st[d]||{{}};
 c.querySelectorAll('input[type=radio]').forEach(r=>{{if(r.value===s.v){{r.checked=true;c.classList.add(s.v)}}
  r.onchange=()=>{{c.classList.remove('ok','bad');c.classList.add(r.value);st[d]={{...st[d],v:r.value,given:c.dataset.given}};save()}}}});
 const n=c.querySelector('.note');n.value=s.note||'';n.oninput=()=>{{st[d]={{...st[d],note:n.value,given:c.dataset.given}};save()}}}});
document.getElementById('exp').onclick=()=>{{const t=JSON.stringify(st,null,1);navigator.clipboard.writeText(t).then(()=>document.getElementById('exp').textContent='Скопировано')}};
save();
</script></main></body></html>'''
    (folder / "review.html").write_text(page, encoding="utf-8")
    print(f"{len(keep)} of {len(verdicts)} sites -> {folder / 'review.html'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    mc = float(args[args.index("--max-confidence") + 1]) if "--max-confidence" in args else 0.7
    main(args[0], mc)
