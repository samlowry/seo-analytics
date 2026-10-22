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
Writes <out-dir>/<class>/<domain>.mp4 (screenshots at 5 fps, real timing), <domain>.png (last frame) and <out-dir>/results.jsonl.
"""
import argparse
import asyncio
import csv
import importlib.util
import json
import re
import shutil
import sys
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
RETRIES = 2  # extra attempts when the click lands on Mostbet or times out
CLICK_CLASSES = {"mono_other", "mono_mixed", "mb_page_other"}

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
() => {
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
  document.querySelectorAll('[data-ev-pick]').forEach(e => e.removeAttribute('data-ev-pick'));
  els[0].setAttribute('data-ev-pick', '1');
  return { visible: true, n: els.length, text: (els[0].innerText || '').trim().slice(0, 60), how: 'cta' };
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
    other = [x for x in links if x[0] == "other"]
    c = r["category"]
    tags = set(r["tags"].split())
    start = f"https://{r['domain']}/"
    if c == "mb_page_other":
        m = re.search(r"https?://\S+", r["why"])
        if m:
            start = m[0].rstrip(".,)")
    if c == "mono_hidden":
        kind = "hidden"
    elif c in CLICK_CLASSES or other:
        kind = "click" if other else "page"
    elif c == "redirect_other":
        kind = "redirect"
    else:
        kind = "page"
    return {"domain": r["domain"], "category": c, "kind": kind, "start": start,
            "target": other[0][2] if other else "", "expect": other[0][3] if other else "",
            "brand": other[0][1] if other else "",
            "referer": "https://www.google.com/" if tags & {"ads_search_only", "cloaked:google-mobile"} else None,
            "phone": "ads_mobile_only" in tags}


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


async def left_site(page, site, ms=20_000):
    waited = 0
    while waited < ms:
        h = host(page.url)
        if h and h != site and not h.endswith("." + site):
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


async def landing(page, site) -> dict:
    """Brand of the page the click ended on, by the scan's own rules (tools/landing_brand.py)."""
    if host(page.url) == site or host(page.url).endswith("." + site):
        return {"kind": "same_site", "brand": ""}
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


async def record(browser, p, out: Path, proxy):
    t0 = time.time()
    res = {**p, "status": "", "note": "", "final_url": "", "final_title": ""}
    vp = PHONE if p["phone"] else DESKTOP
    opts = dict(ignore_https_errors=True, viewport=vp)
    if p["phone"]:
        opts["user_agent"] = PHONE_UA
    if proxy:
        opts["proxy"] = proxy
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
    frames_dir = out / "_tmp" / p["domain"]
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True)
    frames, stop = [], asyncio.Event()
    cam = asyncio.create_task(capture(page, frames_dir, frames, stop))
    st = {"xy": (vp["width"] * 0.5, vp["height"] * 0.3)}
    site = p["domain"].lower().removeprefix("www.")
    try:
        try:
            await page.goto(p["start"], wait_until="domcontentloaded", timeout=45_000, referer=p["referer"])
        except Exception as e:  # noqa: BLE001
            res.update(status="open_failed", note=f"{type(e).__name__}: {str(e)[:160]}")
            return res
        await page.mouse.move(*st["xy"])
        if await bot_check(page):
            res.update(status="bot_check", note="bot check did not clear by itself; not clicked")
            return res
        await settle(page, 2500)
        if p["kind"] == "redirect":
            moved = await left_site(page, site, 20_000)
            await settle(page, 4000)
            res["status"] = "redirected" if moved else "no_redirect"
        elif p["kind"] == "page":
            for dy in (vp["height"] * 0.8,) * 3 + (-vp["height"] * 2.4,):
                await page.mouse.wheel(0, dy)
                await page.wait_for_timeout(1400)
            await page.wait_for_timeout(2000)
            res["status"] = "shown"
        else:
            if p["kind"] == "hidden":
                info = await page.evaluate(HIDDEN, site)
                if not info:
                    res.update(status="hidden_not_found", note="no hidden external links on the page now")
                    await page.wait_for_timeout(3000)
                    return res
                res["note"] = f"hidden ({info['how']}) hosts: " + ", ".join(info["hosts"])
                await page.wait_for_timeout(2500)
            else:
                info = await page.evaluate(FIND, [p["target"], site]) or await page.evaluate(CTA)
                if not info:
                    res.update(status="link_not_found", note=f"no element with {p['target'][:120]} and no call to action")
                    await page.mouse.wheel(0, vp["height"] * 0.8)
                    await page.wait_for_timeout(3000)
                    return res
                res["how"] = info["how"]
                res["note"] = f"{info['how']} text: {info['text']!r}" + ("" if info["visible"] else " (not visible)")
            el = page.locator("[data-ev-pick]").first
            await el.evaluate("e => { e.removeAttribute('target'); e.style.outline = '3px solid #e11d48';"
                              " e.style.outlineOffset = '2px' }")
            await wheel_to(page, el, vp)
            await page.wait_for_timeout(1200)
            box = await el.bounding_box()
            if box and box["width"] > 0:
                await glide(page, st, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                await page.wait_for_timeout(900)
                await page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            else:
                await el.evaluate("e => e.click()")
            moved = await left_site(page, site, 20_000)
            if moved:
                await bot_check(page)
            await settle(page, 6000)
            res["status"] = "clicked_left_site" if moved else "clicked_stayed"
        res["final_url"] = page.url
        try:
            res["final_title"] = (await page.title())[:120]
        except Exception:  # noqa: BLE001
            pass
        res["landing"] = await landing(page, site)
        if p["kind"] in ("click", "hidden", "redirect") and res["status"] in ("clicked_left_site", "redirected"):
            res["status"] = {"mostbet": "landed_mostbet", "other_gambling": "landed_other"}.get(
                res["landing"]["kind"], "landed_" + (res["landing"]["kind"] or "unknown"))
        if p["expect"] and res["final_url"]:
            res["same_target"] = reg(host(res["final_url"])) == reg(host(p["expect"]))
        await page.screenshot(path=str(out / p["category"] / f"{p['domain']}.png"))
        return res
    except Exception as e:  # noqa: BLE001
        res.update(status="error", note=f"{type(e).__name__}: {str(e)[:200]}")
        return res
    finally:
        res["our_refs_aborted"] = our
        res["seconds"] = round(time.time() - t0, 1)
        res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0))
        stop.set()
        await cam
        try:
            await ctx.close()
        except Exception:  # noqa: BLE001
            pass
        dst = out / p["category"] / f"{p['domain']}.mp4"
        err = await encode(frames, frames_dir, dst)
        shutil.rmtree(frames_dir, ignore_errors=True)
        if err:
            res["note"] += f" | video: {err}"
        else:
            res["video"] = str(dst.relative_to(out))


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scan_dir")
    ap.add_argument("domains")
    ap.add_argument("out")
    ap.add_argument("--proxy")
    ap.add_argument("--concurrency", type=int, default=4)
    a = ap.parse_args()
    d, out = Path(a.scan_dir), Path(a.out)
    want = [x.strip() for x in Path(a.domains).read_text().split() if x.strip()]
    rows = {r["domain"]: r for r in csv.DictReader(open(d / "classified.csv", newline="", encoding="utf-8"))}
    done = set()
    if (out / "results.jsonl").exists():
        done = {json.loads(x)["domain"] for x in open(out / "results.jsonl")}
    todo = [plan(rows[x]) for x in want if x in rows and x not in done]
    for p in todo:
        (out / p["category"]).mkdir(parents=True, exist_ok=True)
    (out / "_tmp").mkdir(parents=True, exist_ok=True)
    proxy = bs.parse_proxy(a.proxy)
    q = asyncio.Queue()
    for p in todo:
        q.put_nowait(p)
    print(f"{len(todo)} to record, {len(done)} done before", flush=True)
    from camoufox import DefaultAddons
    from camoufox.async_api import AsyncCamoufox
    lock = asyncio.Lock()

    async def worker(wid):
        while not q.empty():
            cm = AsyncCamoufox(headless=True, geoip=True, humanize=False, i_know_what_im_doing=True,
                               exclude_addons=[DefaultAddons.UBO], **({"proxy": proxy} if proxy else {}))
            browser = await cm.__aenter__()
            try:
                for _ in range(20):  # fresh browser every 20 sites
                    if q.empty():
                        break
                    p = q.get_nowait()
                    tries = []
                    for attempt in range(RETRIES + 1):  # rotating ads: Mostbet this time, another brand the next
                        try:
                            res = await asyncio.wait_for(record(browser, p, out, None), 180)
                        except asyncio.TimeoutError:
                            res = {**p, "status": "timeout"}
                        tries.append(res["status"])
                        if res["status"] not in ("landed_mostbet", "timeout"):
                            break
                    res["tries"] = tries
                    async with lock:
                        with open(out / "results.jsonl", "a", encoding="utf-8") as f:
                            f.write(json.dumps(res, ensure_ascii=False) + "\n")
                    print(f"[{wid}] {res['status']:<18} {res.get('seconds', '')!s:>6}s {p['category']:<15} {p['domain']}",
                          flush=True)
            finally:
                try:
                    await cm.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    bs.kill_driver(cm)

    await asyncio.gather(*(worker(i) for i in range(a.concurrency)))


if __name__ == "__main__":
    asyncio.run(main())
