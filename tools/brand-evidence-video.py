"""Video evidence of brand violations: the site opens, a cursor moves to the link that decided the class, clicks it,
and the other brand's page opens. One video per domain.

Run (on genhost, through the Mac SOCKS tunnel, as the brand scan):
  uv run --with 'camoufox[geoip]' python tools/brand-evidence-video.py brand-protection/2026-09-28/brand-scan \
      <domains.txt> <out-dir> --proxy socks5://127.0.0.1:1080 --concurrency 8

Reads classified.csv (class, ad_links, tags, why). Scenario by class:
  click     mono_other, mono_mixed, mb_page_other, and bait/discredit/redirect_other with a link to another brand —
            open the page (mb_page_other: the Mostbet article), move the cursor to the link, click, follow;
  hidden    mono_hidden — reveal the hidden block, outline it, move the cursor to its first link and click it;
  redirect  redirect_other — open the home page and let it take the visitor away;
  page      bait/discredit without a link — scroll the page down and back.
Sites with ads only for a visitor from Google open with a Google referer; ads only on mobile — with a phone screen.
An overlay bar shows the current address and the UTC time on every page, a drawn cursor follows the mouse (headless
browsers draw neither). Our registry refs are aborted as in the scan; bot checks are waited out, never clicked.
Attempts run until a recording passes the check (verdict()): the click landed on another brand's page, or a bait
page shows another brand by content. Every link to another brand from the scan is tried (twice: ads rotate), then,
on a monobrand without Mostbet ads, the main calls to action in turn; an https site that does not open is tried over
plain http. Passing: <out-dir>/<class>/<domain>.mp4 + .png (last frame). Failing — the last attempt, never in the
package: <out-dir>/rejected/<class>/. <out-dir>/results.jsonl — one line per domain with every attempt and its log;
<out-dir>/actions.log — the same logs as text.
"""
import argparse
import asyncio
import csv
import fcntl
import importlib.util
import json
import re
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

csv.field_size_limit(sys.maxsize)
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("brand_scan", HERE / "brand-scan.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)
lb = bs.lb

DESKTOP = {"width": 1280, "height": 720}
PHONE = {"width": 412, "height": 820}
PHONE_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Mobile Safari/537.36")
LINK_TRIES = 2     # per link to another brand: rotating ads give Mostbet one time and another brand the next
CTA_TRIES = 3      # main calls to action tried in turn when no link of the scan is on the page
MAX_ATTEMPTS = 9
CTA_CLASSES = {"mono_other", "bait", "mb_page_other"}

OVERLAY = r"""
(() => {
  window.open = (u) => { try { location.href = new URL(u, location.href).href } catch (e) {} return null };
  const pad = n => String(n).padStart(2, '0');
  const stamp = () => { const d = new Date();
    return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
           `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC` };
  let x = -50, y = -50;
  addEventListener('mousemove', e => { x = e.clientX; y = e.clientY; draw() }, true);
  function draw() {
    const root = document.documentElement; if (!root) return;
    let bar = document.getElementById('__ev_bar'), cur = document.getElementById('__ev_cur');
    if (!bar) {
      bar = document.createElement('div'); bar.id = '__ev_bar';
      bar.style.cssText = 'all:initial;position:fixed;left:0;right:0;bottom:0;z-index:2147483647;pointer-events:none;' +
        'background:rgba(15,23,42,.88);color:#fff;font:13px/1.2 monospace;padding:5px 10px;white-space:nowrap;' +
        'overflow:hidden;text-overflow:ellipsis';
      root.appendChild(bar);
    }
    if (!cur) {
      cur = document.createElement('div'); cur.id = '__ev_cur';
      cur.innerHTML = '<svg width="22" height="30" viewBox="0 0 22 30"><path d="M1 1 L1 24 L7 18 L11 28 L15 26 L11 17 ' +
        'L19 17 Z" fill="#fff" stroke="#000" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      cur.style.cssText = 'all:initial;position:fixed;z-index:2147483647;pointer-events:none;width:22px;height:30px';
      root.appendChild(cur);
    }
    bar.textContent = stamp() + '   ' + location.href;
    cur.style.left = x + 'px'; cur.style.top = y + 'px';
  }
  setInterval(draw, 250);
})();
"""

FIND = r"""
([target, site]) => {
  const norm = u => { try { const s = new URL(u.replace(/&amp;/g, '&'), location.href);
    return (s.hostname.replace(/^www\./, '') + s.pathname.replace(/\/+$/, '') + s.search).toLowerCase() } catch (e) { return '' } };
  const pathOnly = u => { try { const s = new URL(u.replace(/&amp;/g, '&'), location.href);
    return (s.pathname.replace(/\/+$/, '') + s.search).toLowerCase() } catch (e) { return '' } };
  const t = norm(target), tp = pathOnly(target);
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 4 && r.height > 4 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.05 };
  const vals = el => [el.href, ...[...el.attributes].map(a => a.value)].filter(v => v && typeof v === 'string' && v.length < 2000);
  const all = [...document.querySelectorAll('a, area, button, form, [onclick], [role=button], div, span, img')]
    .filter(el => el.attributes.length);
  let hits = all.filter(el => vals(el).some(v => norm(v) === t));
  if (!hits.length && tp.length > 1) hits = all.filter(el => el.matches('a, area, form') && vals(el).some(v => pathOnly(v) === tp));
  if (!hits.length) hits = all.filter(el => vals(el).some(v => v.includes(target)));
  hits = hits.map(el => el.closest('a, button, [role=button], [onclick]') || el);
  const best = hits.find(vis) || hits[0];
  if (!best) return null;
  document.querySelectorAll('[data-ev-pick]').forEach(e => e.removeAttribute('data-ev-pick'));
  best.setAttribute('data-ev-pick', '1');
  return { visible: vis(best), n: hits.length, text: (best.innerText || best.value || '').trim().slice(0, 60), how: 'link' };
}
"""

# The decisive link is not on the page as an address (a script builds it on click): take the main call to action.
CTA = r"""
(rank) => {
  const rx = /regist|regisztr|rejestr|registr|sign ?up|join|qeydiyyat|kayıt|daftar|регистр|зарегистр|play|grać|graj|oyna|jugar|jouer|spielen|játsz|играть|bonus|bónusz|бонус|claim|get|start|download|letölt|скачать|pobierz|install|login|войти|вход|belépés|giriş|zaloguj|bet now|ставк|казино|casino|kaszinó|kasyn|app/i;
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 30 && r.height > 14 && cs.visibility !== 'hidden' && cs.display !== 'none' && +cs.opacity > 0.05 };
  const me = location.hostname.replace(/^www\./, '');
  const internalNav = el => { try { const u = new URL(el.href, location.href);
    return el.tagName === 'A' && u.hostname.replace(/^www\./, '') === me && !/\/(go|out|goto|link|redirect|reg|play|click|visit|bonus|app)\b/i.test(u.pathname) &&
      (u.pathname.length > 1 || u.hash) && !/^#?$/.test(u.hash) } catch (e) { return false } };
  const els = [...document.querySelectorAll('a, button, [role=button], [onclick]')].filter(vis)
    .filter(el => rx.test((el.innerText || el.value || el.getAttribute('aria-label') || '').trim()))
    .filter(el => !internalNav(el));
  if (!els.length) return null;
  const score = el => { const r = el.getBoundingClientRect(), t = (el.innerText || '').trim();
    return (/regist|regisztr|rejestr|sign|qeydiyyat|kayıt|регистр|daftar/i.test(t) ? 3 : 0) + (r.top < 900 ? 2 : 0) +
      Math.min(r.width * r.height / 20000, 2) + (el.tagName === 'BUTTON' || /btn|button/i.test(el.className) ? 1 : 0) };
  els.sort((a, b) => score(b) - score(a));
  const seen = new Set(), uniq = [];  // one candidate per distinct target, so rank 2 is not the same button again
  for (const el of els) { const k = (el.href || '') + '|' + (el.innerText || '').trim().toLowerCase();
    if (!seen.has(k)) { seen.add(k); uniq.push(el) } }
  const el = uniq[rank];
  if (!el) return null;
  document.querySelectorAll('[data-ev-pick]').forEach(e => e.removeAttribute('data-ev-pick'));
  el.setAttribute('data-ev-pick', '1');
  return { visible: true, n: uniq.length, text: (el.innerText || '').trim().slice(0, 60), how: 'cta' };
}
"""


HIDDEN = r"""
(site) => {
  const host = h => h.replace(/^www\./, '').toLowerCase();
  const me = host(site), here = host(location.hostname);  // the home page may have moved to another domain
  const tiny = el => { for (let e = el; e && e !== document.body; e = e.parentElement) {
      const cs = getComputedStyle(e), r = e.getBoundingClientRect();
      if (cs.display === 'none' || cs.visibility === 'hidden' || (r.height <= 3 && cs.overflow !== 'visible') ||
          (r.width <= 3 && cs.overflow !== 'visible') || +cs.opacity < 0.05 || r.bottom < -1000 || r.right < -1000)
        return e;
    } return null };
  const links = [...document.querySelectorAll('a[href]')].filter(a => { try { const h = host(new URL(a.href).hostname);
      return h && h !== me && !h.endsWith('.' + me) && h !== here && !h.endsWith('.' + here) } catch (e) { return false } });
  const hid = links.map(a => [a, tiny(a)]).filter(([, box]) => box)
    .sort(([a], [b]) => /mostbet/i.test(a.href) - /mostbet/i.test(b.href));  // another brand's link first
  if (!hid.length) return null;
  const box = hid[0][1];
  const cs0 = getComputedStyle(box), r0 = box.getBoundingClientRect();
  const how = cs0.display === 'none' ? 'display:none' : cs0.visibility === 'hidden' ? 'visibility:hidden' :
    +cs0.opacity < 0.05 ? 'прозрачный' : (r0.bottom < -1000 || r0.right < -1000) ? 'вынесен за край экрана' :
    `высота ${Math.round(r0.height)} px, лишнее обрезано`;
  const inBox = hid.filter(([, b]) => b === box).length;
  box.style.cssText += ';display:block!important;visibility:visible!important;height:auto!important;width:auto!important;' +
    'overflow:visible!important;opacity:1!important;position:relative!important;left:auto!important;top:auto!important;' +
    'outline:4px solid #e11d48!important;background:#fff59d!important;padding:6px!important;margin:12px!important';
  for (let e = box.parentElement; e && e !== document.body; e = e.parentElement) {
    const cs = getComputedStyle(e);
    if (cs.display === 'none' || cs.overflow === 'hidden' || e.getBoundingClientRect().height <= 3)
      e.style.cssText += ';display:block!important;overflow:visible!important;height:auto!important;visibility:visible!important';
  }
  const tag = document.createElement('div');
  tag.textContent = `Скрытый от посетителя блок (${how}), ссылок на другие сайты: ${inBox}`;
  tag.style.cssText = 'all:initial;display:block;font:bold 14px sans-serif;color:#fff;background:#e11d48;padding:4px 8px;margin:4px 0';
  box.prepend(tag);
  hid[0][0].setAttribute('data-ev-pick', '1');
  return { n: hid.length, how, hosts: [...new Set(hid.map(([a]) => host(new URL(a.href).hostname)))].slice(0, 10) };
}
"""


def host(u: str) -> str:
    return (urlsplit(u).hostname or "").lower().removeprefix("www.")


def reg(h: str) -> str:
    p = h.split(".")
    return ".".join(p[-3:]) if len(p) > 2 and len(p[-1]) == 2 and p[-2] in ("com", "co", "net", "org") else ".".join(p[-2:])


def plan(r: dict) -> dict:
    links = json.loads(r.get("ad_links") or "[]")
    c = r["category"]
    tags = set(r["tags"].split())
    targets, seen = [], set()
    for kind, name, url, final in links:  # every link to another brand
        if kind == "other" and url not in seen:
            seen.add(url)
            targets.append({"url": url, "expect": final, "brand": name})
    targets.sort(key=lambda t: not t["expect"])  # links the scan followed to a destination first
    start = f"https://{r['domain']}/"
    if c == "mb_page_other":
        m = re.search(r"https?://\S+", r["why"])
        if m:
            start = m[0].rstrip(".,)")
    if c == "mono_hidden":
        kind = "hidden"
    elif c == "discredit":
        kind = "page"  # the proof is the page itself: the Mostbet name over content that is not betting
    elif targets:
        kind = "click"
    elif c == "redirect_other":
        kind = "redirect"
    else:
        kind = "page"
    return {"domain": r["domain"], "category": c, "kind": kind, "start": start, "targets": targets[:6],
            # the main call to action of a site that also shows Mostbet leads to Mostbet: never a fallback there
            "cta_ok": c in CTA_CLASSES,
            "referer": "https://www.google.com/" if tags & {"ads_search_only", "cloaked:google-mobile"} else None,
            "phone": "ads_mobile_only" in tags}


def attempts(p: dict) -> list:
    """What to try, in order, until one recording passes the check."""
    if p["kind"] == "click":
        out = [("link", i) for i in range(len(p["targets"])) for _ in range(LINK_TRIES)]
        if p["cta_ok"]:
            out += [("cta", k) for k in range(CTA_TRIES)]
        return out[:MAX_ATTEMPTS]
    return [(p["kind"], 0)] * (1 if p["kind"] == "page" else 2)


async def glide(page, state, x, y, ms=1100):
    """Move the mouse in small steps so the drawn cursor visibly travels."""
    x0, y0 = state["xy"]
    steps = 30
    for i in range(1, steps + 1):
        k = i / steps
        k = k * k * (3 - 2 * k)  # ease in-out
        await page.mouse.move(x0 + (x - x0) * k, y0 + (y - y0) * k)
        await page.wait_for_timeout(ms // steps)
    state["xy"] = (x, y)


async def wheel_to(page, el, vp):
    """Scroll to the element with the mouse wheel: the video shows the way down (an instant jump it may not paint)."""
    for _ in range(80):
        y = await el.evaluate("e => { const r = e.getBoundingClientRect(); return r.top + r.height / 2 }")
        dy = y - vp["height"] * 0.45
        if abs(dy) < vp["height"] * 0.2:
            return
        before = await page.evaluate("() => scrollY")
        await page.mouse.wheel(0, max(-1600, min(1600, dy)))
        await page.wait_for_timeout(140)
        if await page.evaluate("() => scrollY") == before:  # inside a scroll box, or the end of the page
            await el.evaluate("e => e.scrollIntoView({block: 'center'})")
            await page.wait_for_timeout(600)
            return


async def settle(page, ms=3000):
    try:
        await page.wait_for_load_state("load", timeout=15_000)
    except Exception:  # noqa: BLE001
        pass
    await page.wait_for_timeout(ms)


async def bot_check(page):
    kind, _, _ = await bs.pass_challenge(page)
    return kind


def own(h: str, sites) -> bool:
    return any(h == x or h.endswith("." + x) for x in sites)


async def left_site(page, sites, ms=20_000):
    waited = 0
    while waited < ms:
        h = host(page.url)
        if h and not own(h, sites):
            return True
        await page.wait_for_timeout(500)
        waited += 500
    return False


FPS = 5
FFMPEG = shutil.which("ffmpeg") or str(Path.home() / "bin" / "ffmpeg")


async def capture(page, d: Path, frames: list, stop: asyncio.Event):
    """Screenshots at FPS with their times. The browser's own screencast misses scrolling on long pages;
    a screenshot is always the page as it is now."""
    t0 = time.monotonic()
    while not stop.is_set():
        t = time.monotonic()
        f = d / f"{len(frames):05d}.jpg"
        try:
            await asyncio.wait_for(page.screenshot(path=str(f), type="jpeg", quality=70, timeout=3000), 4)
            frames.append((f, t - t0))
        except Exception:  # noqa: BLE001  — mid-navigation: no frame this time
            pass
        await asyncio.sleep(max(0.0, 1 / FPS - (time.monotonic() - t)))
    frames.append((None, time.monotonic() - t0))


async def encode(frames: list, d: Path, dst: Path) -> str:
    """H.264 mp4 from the screenshots, each shown until the next one was taken (real timing)."""
    shots = [(f, t) for f, t in frames if f]
    if len(shots) < 2:
        return "no frames"
    end = frames[-1][1]
    lines = []
    for i, (f, t) in enumerate(shots):
        nxt = shots[i + 1][1] if i + 1 < len(shots) else end
        lines += [f"file '{f.name}'", f"duration {max(0.04, nxt - t):.3f}"]
    lines.append(f"file '{shots[-1][0].name}'")
    (d / "list.txt").write_text("\n".join(lines) + "\n")
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(d / "list.txt"),
        "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=10", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, e = await proc.communicate()
    return e.decode()[-200:] if proc.returncode else ""


BRANDMARK = r"""
(name) => {
  const key = s => (s || '').toLowerCase().replace(/[^a-z0-9а-я]/g, '');
  const k = key(name);
  const vis = el => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    return r.width > 8 && r.height > 8 && cs.visibility !== 'hidden' && cs.display !== 'none' };
  let hits = [];
  if (k.length > 2) {
    hits = [...document.querySelectorAll('img, svg, a, h1, h2, h3, span, div, p, b, strong')].filter(vis).filter(el =>
      key(el.getAttribute('alt')).includes(k) || key(el.getAttribute('title')).includes(k) ||
      (el.tagName === 'IMG' && key(el.getAttribute('src')).includes(k)) ||
      (el.children.length === 0 && key(el.textContent).includes(k)));
  }
  if (!hits.length)
    hits = [...document.querySelectorAll('header img, [class*=logo] img, img[class*=logo], [class*=logo], h1')].filter(vis);
  if (!hits.length) return null;
  hits.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
  hits[0].setAttribute('data-ev-pick', '1');
  hits[0].style.outline = '3px solid #e11d48'; hits[0].style.outlineOffset = '3px';
  return { text: (hits[0].getAttribute('alt') || hits[0].textContent || '').trim().slice(0, 60), tag: hits[0].tagName };
}
"""


async def error_page(page) -> str:
    """Firefox error page (certificate, refused connection, DNS) instead of the site, or ''."""
    try:
        uri = await page.evaluate("() => document.documentURI")
        title = await page.title()
    except Exception:  # noqa: BLE001
        return ""
    if uri.startswith(("about:neterror", "about:certerror", "about:blocked")):
        return uri.split("?")[0] + " " + (re.search(r"[?&]e=([^&]+)", uri) or [None, ""])[1]
    if bs.FIREFOX_ERROR_TITLE.search(title or ""):
        return "error title: " + title[:60]
    return ""


CLASS_RU = {
    "mono_other": "монобренд Mostbet рекламирует только чужие бренды",
    "mono_mixed": "монобренд Mostbet рекламирует и Mostbet, и чужие бренды",
    "mb_page_other": "страница про Mostbet рекламирует чужие бренды",
    "bait": "приманка: имя Mostbet, внутри чужое казино",
    "redirect_other": "главная уводит на рефссылку чужого бренда",
    "discredit": "дискредитация: имя Mostbet, содержимое не про ставки",
    "mono_hidden": "монобренд Mostbet со скрытыми ссылками на чужой бренд",
}
PLAN_RU = {
    "click": "Откроем сайт, подведём курсор к рекламной ссылке и кликнем.",
    "hidden": "Откроем сайт, раскроем скрытый от посетителя блок и кликнем ссылку из него.",
    "redirect": "Откроем главную: сайт сам уведёт посетителя на чужой бренд.",
    "bait": "Откроем сайт под именем Mostbet: покажем чужой бренд и кликнем регистрацию.",
    "discredit": "Откроем сайт под именем Mostbet и покажем его содержимое.",
}

CARD = """<html><body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
background:#0f172a;color:#fff;font:22px/1.5 -apple-system,Segoe UI,Arial,sans-serif"><div style="max-width:80%">
<div style="font-size:15px;color:#94a3b8;margin-bottom:8px">Запись доказательства · {ts} UTC</div>
<div style="font-size:30px;font-weight:700;margin-bottom:10px">{domain}</div>
<div style="color:#fca5a5;margin-bottom:14px">{cls}</div><div>{plan}</div></div></body></html>"""

OUTRO = r"""
(text) => { const d = document.createElement('div'); d.id = '__ev_outro'; d.textContent = text;
  d.style.cssText = 'all:initial;position:fixed;left:0;right:0;top:0;z-index:2147483647;pointer-events:none;' +
    'background:rgba(225,29,72,.95);color:#fff;font:bold 18px/1.35 -apple-system,Segoe UI,Arial,sans-serif;padding:12px 16px';
  (document.documentElement || document.body).appendChild(d) }
"""


def scenario(p) -> str:
    return "bait" if p["category"] == "bait" and p["kind"] == "page" else \
        "discredit" if p["kind"] == "page" else p["kind"]


def outro_text(res: dict, p: dict) -> str:
    a = host(res.get("start") or "")
    b = host(res.get("final_url") or "")
    L = res.get("landing") or res.get("page_brand") or {}
    who = L.get("brand") or ""
    if who in ("?", "") and b and b != a:
        who = b  # a casino the dictionary does not know: name it by its domain
    if p["category"] == "discredit":
        return f"Итог: {a} — имя Mostbet, содержимое не про ставки ({who})." if who else f"Итог: {a} — содержимое не про ставки."
    path = f"{a} → {b}" if b and b != a else a
    return f"Итог: {path} — чужой бренд {who}." if who else f"Итог: {path}."


GENERIC_LOGO = {"logo", "site logo", "logotype", "home", "main", "image"}


async def page_now(page) -> str:
    """One line on what the page is now, for the log of a failed attempt."""
    B = await page_brand(page)
    try:
        title = (await page.title())[:60]
    except Exception:  # noqa: BLE001
        title = ""
    return f"page now: {B['kind']} {B['brand']}, title {title!r}"


async def page_brand(page) -> dict:
    """Brand of the page by its content only: the site's own host has Mostbet in it and must not count."""
    try:
        html, title = await page.content(), await page.title()
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:  # noqa: BLE001
        return {"kind": "", "brand": ""}
    d = lb.identify("https://example.invalid/", title, html, text)
    return {"kind": d["kind"], "brand": d.get("brand", ""), "evidence": d.get("evidence", "")}


async def landing(page, sites) -> dict:
    """Brand of the page the click ended on, by the scan's own rules (tools/landing_brand.py)."""
    if own(host(page.url), sites):
        return {"kind": "same_site", "brand": ""}
    for _ in range(8):  # a casino app still drawing itself: give it up to 8 s more to show its name
        try:
            if len(await page.evaluate("() => document.body ? document.body.innerText : ''")) > 300:
                break
        except Exception:  # noqa: BLE001
            pass
        await page.wait_for_timeout(1000)
    try:
        html = await page.content()
        title = await page.title()
        text = await page.evaluate("() => document.body ? document.body.innerText : ''")
    except Exception:  # noqa: BLE001
        return {"kind": "", "brand": ""}
    d = lb.identify(page.url, title, html, text)
    if d["kind"] != "mostbet" and lb.brand_of_host(host(page.url)) == "Mostbet":
        d = {**d, "kind": "mostbet", "brand": "Mostbet"}
    return {"kind": d["kind"], "brand": d.get("brand", ""), "evidence": d.get("evidence", ""), "pid": d.get("pid", "")}


def verdict(res: dict) -> str:
    """'' when the recording proves the violation; otherwise why it does not. A recording that shows Mostbet,
    an error page or nothing goes to rejected/, never to the package."""
    if res.get("error_page"):
        return "error page: " + res["error_page"]
    st = res["status"]
    L = res.get("landing") or {}
    if st in ("landed",):
        if L.get("kind") == "other_gambling" and L.get("brand") != "Mostbet":
            return ""
        return f"landed on {L.get('kind') or 'unknown'} {L.get('brand') or ''}".strip()
    if st == "shown":
        L = res.get("landing") or {}
        if L.get("kind") == "other_gambling" and L.get("brand") != "Mostbet":
            return ""
        B = res.get("page_brand") or {}
        if B.get("kind") == "other_gambling" and B.get("brand") not in ("Mostbet", "", "?"):
            return ""
        if res.get("category") == "discredit" and B.get("kind") == "non_gambling":
            return ""  # discredit is the Mostbet name over content that is not betting at all
        return f"no other brand recognised on the page ({B.get('kind') or 'unknown'} {B.get('brand') or ''})".strip()
    return st + (": " + res["note"] if res.get("note") else "")


class Log:
    """A few lines per attempt: what was opened, what was clicked, what happened."""

    def __init__(self):
        self.t0, self.lines = time.monotonic(), []

    def __call__(self, msg: str):
        self.lines.append(f"{time.monotonic() - self.t0:5.1f}s {msg}")


async def record(browser, p, att, tmp: Path, start: str):
    """One recording. Returns the result with the log and the paths of its video and last frame in tmp."""
    how, idx = att
    t0 = time.time()
    log = Log()
    res = {"domain": p["domain"], "category": p["category"], "attempt": f"{how}{idx}", "start": start, "status": "",
           "note": ""}
    vp = PHONE if p["phone"] else DESKTOP
    opts = dict(ignore_https_errors=True, viewport=vp)
    if p["phone"]:
        opts["user_agent"] = PHONE_UA
    ctx = await browser.new_context(**opts)
    ctx.set_default_timeout(15_000)
    our = []

    async def route(r, req):
        if bs.ref_key(req.url) in bs.OUR_REFS:
            our.append(req.url)
            return await r.abort()
        await r.continue_()

    await ctx.route("**/*", route)
    await ctx.add_init_script(OVERLAY)
    page = await ctx.new_page()
    page.on("dialog", lambda d: asyncio.ensure_future(d.dismiss()))
    frames_dir = tmp / "frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    frames, stop = [], asyncio.Event()
    cam = asyncio.create_task(capture(page, frames_dir, frames, stop))
    st = {"xy": (vp["width"] * 0.5, vp["height"] * 0.3)}
    site = p["domain"].lower().removeprefix("www.")
    sites = [site]
    try:
        await page.set_content(CARD.format(ts=time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), domain=p["domain"],
                                           cls=CLASS_RU.get(p["category"], p["category"]), plan=PLAN_RU[scenario(p)]))
        await page.wait_for_timeout(2500)
        try:
            resp = await page.goto(start, wait_until="domcontentloaded", timeout=45_000, referer=p["referer"])
            log(f"open {start}" + (" (referer Google)" if p["referer"] else "") + (" phone" if p["phone"] else "")
                + f" → HTTP {resp.status if resp else '?'}, {page.url[:100]}")
        except Exception as e:  # noqa: BLE001
            res.update(status="open_failed", note=f"{type(e).__name__}: {str(e).splitlines()[0][:120]}")
            log(f"open {start} → failed: {res['note']}")
            res["error_page"] = await error_page(page)
            return res
        await page.mouse.move(*st["xy"])
        if how != "redirect" and host(page.url) and not own(host(page.url), sites):
            # the home page moved: the new domain is the site too (for a redirect it is the evidence itself)
            sites.append(host(page.url))
        res["error_page"] = await error_page(page)
        if res["error_page"]:
            res["status"] = "error_page"
            log(f"browser error page: {res['error_page']}")
            await page.wait_for_timeout(1500)
            return res
        if await bot_check(page):
            res.update(status="bot_check", note="bot check did not clear by itself; not clicked")
            log("bot check did not clear; stop")
            return res
        await settle(page, 2500)
        if how == "redirect":
            moved = await left_site(page, sites, 20_000)
            await settle(page, 4000)
            log(("left the site by itself → " if moved else "stayed on the site, no redirect: ") + page.url[:120])
            res["status"] = "landed" if moved else "no_redirect"
        elif how == "page":
            res["page_brand"] = await page_brand(page)
            B = res["page_brand"]
            log(f"page brand by content: {B['kind']} {B['brand']}")
            mark = await page.evaluate(BRANDMARK, B["brand"] if B["kind"] == "other_gambling" else "")
            logo = (mark or {}).get("text", "").strip()
            if B["kind"] == "mostbet" and B.get("evidence") == "name_only_weak" and len(logo) >= 3 and \
                    not lb.MOSTBET_NAME.search(logo) and logo.lower() not in GENERIC_LOGO and \
                    lb.GAMBLING.search(await page.evaluate("() => document.body ? document.body.innerText.slice(0, 5000) : ''")):
                # Mostbet only in the title and meta (the bait's SEO), gambling on the page, another name on the logo
                res["page_brand"] = B = {"kind": "other_gambling", "brand": logo[:40], "evidence": "logo"}
                log(f"Mostbet only in title/meta, logo says {logo[:40]!r}: another brand")
            if mark:
                el = page.locator("[data-ev-pick]").first
                await wheel_to(page, el, vp)
                box = await el.bounding_box()
                if box:
                    await glide(page, st, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                log(f"cursor to brand mark <{mark['tag']}> {mark['text']!r}")
                await page.wait_for_timeout(2500)
            res["status"] = "shown"
            if p["category"] == "bait":
                cta = await page.evaluate(CTA, 0)
                if cta:
                    el = page.locator("[data-ev-pick]").first
                    await el.evaluate("e => { e.removeAttribute('target'); e.style.outline = '3px solid #e11d48';"
                                      " e.style.outlineOffset = '2px' }")
                    await wheel_to(page, el, vp)
                    box = await el.bounding_box()
                    if box and box["width"] > 0:
                        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                        await glide(page, st, x, y)
                        await page.wait_for_timeout(700)
                        await page.mouse.click(x, y)
                        log(f"call to action {cta['text']!r}: click at {x:.0f},{y:.0f}")
                        moved = await left_site(page, sites, 8_000)
                        await settle(page, 5000)
                        res["error_page"] = await error_page(page)
                        if moved:
                            res["landing"] = await landing(page, sites)
                            L = res["landing"]
                            log(f"left the site → {page.url[:100]}; landing: {L['kind']} {L['brand']}")
                            if L["kind"] == "mostbet":
                                res["status"] = "landed"  # verdict() rejects a Mostbet landing
                        else:
                            log(f"stayed on the site: {page.url[:100]}")
                else:
                    log("no call to action to click")
                    await page.wait_for_timeout(2000)
            else:
                for dy in (vp["height"] * 0.7,) * 2 + (-vp["height"] * 1.4,):
                    await page.mouse.wheel(0, dy)
                    await page.wait_for_timeout(1200)
                log("scrolled down two screens and back")
                await page.wait_for_timeout(1500)
        else:
            if how == "hidden":
                info = await page.evaluate(HIDDEN, site)  # the page's own host is excluded inside
                if not info:
                    res.update(status="hidden_not_found", note="no hidden external links on the page now")
                    log("no hidden links to other sites on the page now")
                    await page.wait_for_timeout(2000)
                    return res
                res["note"] = f"hidden ({info['how']}) hosts: " + ", ".join(info["hosts"])
                log(f"hidden block revealed ({info['how']}), hosts: {', '.join(info['hosts'])}")
                await page.wait_for_timeout(1500)
            elif how == "link":
                tg = p["targets"][idx]
                res["target"] = tg["url"]
                info = await page.evaluate(FIND, [tg["url"], site])
                if not info:
                    res.update(status="link_not_found", note=f"no element with {tg['url'][:120]}")
                    log(f"link {tg['url'][:100]} (scan: {tg['brand']}) not on the page now; {await page_now(page)}")
                    return res
                log(f"link {tg['url'][:100]} (scan: {tg['brand']}) found: {info['text']!r}"
                    + ("" if info["visible"] else ", not visible"))
            else:
                info = await page.evaluate(CTA, idx)
                if not info:
                    res.update(status="link_not_found", note=f"no call to action #{idx + 1}")
                    log(f"no call to action #{idx + 1} on the page; {await page_now(page)}")
                    return res
                log(f"call to action #{idx + 1}: {info['text']!r}")
            el = page.locator("[data-ev-pick]").first
            await el.evaluate("e => { e.removeAttribute('target'); e.style.outline = '3px solid #e11d48';"
                              " e.style.outlineOffset = '2px' }")
            await wheel_to(page, el, vp)
            await page.wait_for_timeout(1200)
            box = await el.bounding_box()
            if box and box["width"] > 0:
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                await glide(page, st, x, y)
                await page.wait_for_timeout(900)
                await page.mouse.click(x, y)
                log(f"click at {x:.0f},{y:.0f}")
            else:
                await el.evaluate("e => e.click()")
                log("click by script (element has no box)")
            moved = await left_site(page, sites, 20_000)
            if moved:
                await bot_check(page)
            await settle(page, 6000)
            res["error_page"] = await error_page(page)
            res["status"] = "landed" if moved else "clicked_stayed"
            log(("left the site → " if moved else "stayed on the site: ") + page.url[:120])
        res["final_url"] = page.url
        try:
            res["final_title"] = (await page.title())[:120]
        except Exception:  # noqa: BLE001
            pass
        if res["status"] == "landed":
            res["landing"] = await landing(page, sites)
            L = res["landing"]
            log(f"landing: {L['kind']} {L['brand']} ({L.get('evidence', '')})")
        if not verdict(res):
            await page.evaluate(OUTRO, outro_text(res, p))
            await page.wait_for_timeout(3000)
        await page.screenshot(path=str(tmp / "last.png"))
        return res
    except Exception as e:  # noqa: BLE001
        res.update(status="error", note=f"{type(e).__name__}: {str(e).splitlines()[0][:160]}")
        log(f"error: {res['note']}")
        return res
    finally:
        res["our_refs_aborted"] = our
        res["seconds"] = round(time.time() - t0, 1)
        res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))
        stop.set()
        await cam
        shots = [f for f, _ in frames if f]
        if not (tmp / "last.png").exists() and shots:  # stopped early: the last frame is the final picture
            shutil.copy(shots[-1], tmp / "last.jpg")
        try:
            await bs.bounded(ctx.close(), 15)  # on a crashed browser close() never returns
        except Exception:  # noqa: BLE001
            pass
        err = await encode(frames, frames_dir, tmp / "video.mp4")
        shutil.rmtree(frames_dir, ignore_errors=True)
        if err:
            res["note"] += f" | video: {err}"
        res["log"] = log.lines


PROXY = None  # (host, port) of the SOCKS proxy, set in main()
STALL_S = 600
PROGRESS = Path("/tmp/evidence-progress.txt")  # readable without root: sites done, accepted, rejected, requeued


class BrowserGone(RuntimeError):
    pass


async def proxy_alive() -> bool:
    """SOCKS5 CONNECT to example.com:443 through the tunnel answers 'succeeded'."""
    if not PROXY:
        return True
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(*PROXY), 5)
        w.write(b"\x05\x01\x00")
        await w.drain()
        await asyncio.wait_for(r.readexactly(2), 5)
        name = b"example.com"
        w.write(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + (443).to_bytes(2, "big"))
        await w.drain()
        rep = await asyncio.wait_for(r.readexactly(4), 15)
        w.close()
        return rep[1] == 0
    except Exception:  # noqa: BLE001
        return False


async def wait_proxy():
    """The Mac tunnel is down: hold the site (do not reject it) until the tunnel is back."""
    n = 0
    while not await proxy_alive():
        if n % 10 == 0:
            print(f"{time.strftime('%H:%M:%S')} proxy down, waiting", flush=True)
        n += 1
        await asyncio.sleep(30)


async def run_site(browser, p, out: Path) -> dict:
    """Attempts in order until one passes verdict(); the passing video goes to <class>/, the last failing one
    to rejected/<class>/."""
    tmp = out / "_tmp" / p["domain"]
    tries, start, http_tried = [], p["start"], False
    queue = attempts(p)
    i = 0
    res = {}
    while i < len(queue):
        att = queue[i]
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        if not browser.is_connected():
            raise BrowserGone(p["domain"])
        try:
            res = await bs.bounded(record(browser, p, att, tmp, start), 200)
        except TimeoutError:
            res = {"domain": p["domain"], "attempt": f"{att[0]}{att[1]}", "status": "timeout", "note": "", "log": []}
        if res["status"] == "timeout" or (res["status"] == "error" and not browser.is_connected()):
            # a hung or dead browser, not the site: relaunch and record the site again. Counting it as a rejection
            # once turned a frozen driver into 46 false rejections and kept the stall watchdog from firing.
            raise BrowserGone(p["domain"])
        if res["status"] in ("open_failed", "timeout", "error") and not await proxy_alive():
            await wait_proxy()  # the failure is our tunnel, not the site: repeat the attempt
            continue
        res["verdict"] = verdict(res)
        tries.append(res)
        if not res["verdict"]:
            break
        if res["status"] in ("open_failed", "error_page") and start.startswith("https://") and not http_tried:
            start, http_tried = "http://" + start[len("https://"):], True  # self-signed or broken TLS: try plain HTTP
            continue
        if res["status"] in ("open_failed", "error_page", "bot_check", "hidden_not_found"):
            break
        if res["status"] == "link_not_found" and att[0] == "link":  # this link is gone: skip its repeats
            while i + 1 < len(queue) and queue[i + 1] == att:
                i += 1
        i += 1
    ok = not res["verdict"]
    dst = out / p["category"] if ok else out / "rejected" / p["category"]
    dst.mkdir(parents=True, exist_ok=True)
    files = {}
    for src, ext in ((tmp / "video.mp4", "mp4"), (tmp / "last.png", "png"), (tmp / "last.jpg", "jpg")):
        if src.exists():
            shutil.move(str(src), dst / f"{p['domain']}.{ext}")
            files[ext] = str((dst / f"{p['domain']}.{ext}").relative_to(out))
    shutil.rmtree(tmp, ignore_errors=True)
    return {"domain": p["domain"], "category": p["category"], "kind": p["kind"], "accepted": ok,
            "reason": res["verdict"], "status": res["status"], "final_url": res.get("final_url", ""),
            "landing": res.get("landing") or res.get("page_brand") or {}, "files": files,
            "attempts": [{k: t.get(k) for k in ("attempt", "start", "status", "verdict", "target", "final_url",
                                                 "seconds", "our_refs_aborted", "log")} for t in tries]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_dir")
    ap.add_argument("domains")
    ap.add_argument("out")
    ap.add_argument("--proxy")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--shard", default="0/1", help="k/n: this process takes the domains whose index %% n == k")
    a = ap.parse_args()
    shard_k, shard_n = (int(x) for x in a.shard.split("/"))
    d, out = Path(a.scan_dir), Path(a.out)
    want = [x.strip() for x in Path(a.domains).read_text().split() if x.strip()]
    rows = {r["domain"]: r for r in csv.DictReader(open(d / "classified.csv", newline="", encoding="utf-8"))}
    done = set()
    if (out / "results.jsonl").exists():
        done = {json.loads(x)["domain"] for x in open(out / "results.jsonl")}
    todo = [plan(rows[x]) for i, x in enumerate(want) if i % shard_n == shard_k and x in rows and x not in done]
    (out / "_tmp").mkdir(parents=True, exist_ok=True)
    proxy = bs.parse_proxy(a.proxy)
    global PROXY
    if a.proxy:
        u = urlsplit(a.proxy)
        PROXY = (u.hostname, u.port or 1080)
    q = asyncio.Queue()
    for p in todo:
        q.put_nowait(p)
    print(f"{len(todo)} to record, {len(done)} done before", flush=True)
    from camoufox import DefaultAddons
    from camoufox.async_api import AsyncCamoufox
    lock = asyncio.Lock()

    stats = {"done": len(done), "ok": 0, "rej": 0, "requeued": 0, "last_error": ""}
    # geoip=True asks an IP service on every browser launch; hundreds of relaunches got refused and every launch
    # failed (the full run stopped twice). The exit IP is looked up once here and handed to Camoufox as is.
    geo = True
    if a.proxy:
        ip = subprocess.run(["curl", "-s", "-m", "15", "-x", a.proxy.replace("socks5://", "socks5h://"),
                             "https://api.ipify.org"], capture_output=True, text=True).stdout.strip()
        if re.fullmatch(r"[0-9.]+", ip):
            geo = ip
        print(f"exit IP for geoip: {geo}", flush=True)

    last = [time.monotonic()]

    drivers = {}  # worker -> pid of its Playwright driver

    def dead(pid: int) -> bool:
        try:
            return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] in "ZX"
        except (OSError, IndexError):
            return True

    def watchdog():
        """A Playwright driver crash (TypeError … '_getChildFrames' in the driver, every 10–20 min) leaves every
        worker waiting forever. A dead driver: exit at once; no new site for STALL_S seconds: exit too. The wrapper
        loop on the server starts the run again; finished sites are skipped, sites in flight are recorded again."""
        while True:
            time.sleep(10)
            gone = [w for w, pid in list(drivers.items()) if dead(pid)]
            if gone and Path("/proc").exists():
                print(f"{time.strftime('%H:%M:%S')} [shard {a.shard}] driver of worker {gone[0]} died: restart", flush=True)
                kill_tree_and_exit()
            if time.monotonic() - last[0] > STALL_S:
                print(f"{time.strftime('%H:%M:%S')} [shard {a.shard}] no site finished for {STALL_S} s: restart", flush=True)
                kill_tree_and_exit()

    def kill_tree_and_exit():
        """SIGKILL every descendant (drivers, browsers) so a restart leaves no orphans, then exit 75."""
        pids, todo_p = [], [os.getpid()]
        while todo_p:
            pid = todo_p.pop()
            out_p = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout
            kids = [int(x) for x in out_p.split()]
            pids += kids
            todo_p += kids
        for pid in reversed(pids):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        os._exit(75)

    threading.Thread(target=watchdog, daemon=True).start()

    def note_progress():
        """Counts over results.jsonl (every shard writes there), readable without root."""
        last[0] = time.monotonic()
        try:
            n = ok = 0
            with open(out / "results.jsonl", encoding="utf-8") as f:
                for line in f:
                    n += 1
                    ok += '"accepted": true' in line
            tmp = PROGRESS.with_suffix(f".{os.getpid()}")
            tmp.write_text(f"{n} {ok} {n - ok} {stats['requeued']} {len(want)}\n{stats['last_error']}\n")
            tmp.chmod(0o644)
            tmp.replace(PROGRESS)
        except OSError:
            pass

    async def worker(wid):
        """One browser, relaunched every 20 sites and after a crash; a site whose browser died is recorded again."""
        while not q.empty():
            cm = AsyncCamoufox(headless=True, geoip=geo, humanize=False, i_know_what_im_doing=True,
                               exclude_addons=[DefaultAddons.UBO], **({"proxy": proxy} if proxy else {}))
            try:
                browser = await bs.bounded(cm.__aenter__(), bs.LAUNCH_TIMEOUT)
                proc = getattr(getattr(getattr(cm, "_connection", None), "_transport", None), "_proc", None)
                if proc is not None:
                    drivers[wid] = proc.pid
            except Exception as e:  # noqa: BLE001
                print(f"[{wid}] browser launch failed: {type(e).__name__}: {str(e)[:200]}; retry in 30 s", flush=True)
                stats["last_error"] = f"{time.strftime('%H:%M:%S')} launch: {type(e).__name__}: {str(e)[:150]}"
                note_progress()
                bs.kill_driver(cm)
                await asyncio.sleep(30)
                continue
            try:
                for _ in range(20):
                    if q.empty() or not browser.is_connected():
                        break
                    p = q.get_nowait()
                    try:
                        r = await bs.bounded(run_site(browser, p, out), 1200)
                    except (BrowserGone, TimeoutError) as e:
                        p["_requeued"] = p.get("_requeued", 0) + 1
                        stats["requeued"] += 1
                        if p["_requeued"] <= 2:
                            q.put_nowait(p)
                            print(f"[{wid}] browser lost on {p['domain']} ({type(e).__name__}); requeued", flush=True)
                            break
                        r = {"domain": p["domain"], "category": p["category"], "kind": p["kind"], "accepted": False,
                             "reason": "browser crashed three times on this site", "status": "crash",
                             "final_url": "", "landing": {}, "files": {}, "attempts": []}
                    async with lock:
                        with open(out / "results.jsonl", "a", encoding="utf-8") as f:
                            fcntl.flock(f, fcntl.LOCK_EX)  # other shards append to the same file
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        with open(out / "actions.log", "a", encoding="utf-8") as f:
                            fcntl.flock(f, fcntl.LOCK_EX)
                            f.write(f"== {p['domain']} [{p['category']}] → {'ACCEPTED' if r['accepted'] else 'REJECTED: ' + r['reason']}\n")
                            for t in r["attempts"]:
                                f.write(f"  -- attempt {t['attempt']}: {t['status']}\n")
                                f.writelines(f"     {x}\n" for x in t.get("log") or [])
                        stats["done"] += 1
                        stats["ok" if r["accepted"] else "rej"] += 1
                        note_progress()
                    print(f"[{wid}] {'OK ' if r['accepted'] else 'REJ'} {len(r['attempts'])}x {p['category']:<15} "
                          f"{p['domain']:<30} {r['reason'][:70]}", flush=True)
            finally:
                drivers.pop(wid, None)  # closing on purpose is not a crash
                try:
                    await bs.bounded(cm.__aexit__(None, None, None), 30)
                except Exception:  # noqa: BLE001
                    pass
                bs.kill_driver(cm)

    await asyncio.gather(*(worker(i) for i in range(a.concurrency)))


if __name__ == "__main__":
    asyncio.run(main())
