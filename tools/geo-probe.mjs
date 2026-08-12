#!/usr/bin/env node
// Замер mostbet.com из конкретного гео.
// Запуск:  ./tools/geo LT
// Результат: results/geo-<CC>.json, .png, .html  + сводка в консоль.

import { chromium } from 'playwright';
import { execSync } from 'child_process';
import fs from 'fs';
import path from 'path';

const CC = (process.argv[2] || '').toUpperCase();
if (!CC) {
  console.error('Укажи код страны: ./tools/geo LT');
  process.exit(1);
}

const OUT = path.resolve('results');
fs.mkdirSync(OUT, { recursive: true });

const UA_CHROME = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const UA_GBOT = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)';

const sh = (c, t = 30000) => { try { return execSync(c, { timeout: t, maxBuffer: 64 * 1024 * 1024 }).toString(); } catch { return ''; } };
const q = s => `'${String(s).replace(/'/g, "'\\''")}'`;
const R = {}; // результат

const line = (k, v) => console.log(`  ${String(k).padEnd(26)} ${v}`);
const hr = t => console.log(`\n${'─'.repeat(64)}\n${t}\n${'─'.repeat(64)}`);

// ───────────────────────── 1. где мы на самом деле ─────────────────────────
hr(`ЗАМЕР ИЗ: ${CC}`);
try { R.geo = JSON.parse(sh('curl -s -m 20 https://ipinfo.io/json') || '{}'); } catch { R.geo = {}; }
R.actualCountry = R.geo.country || '??';
R.labelMatches = R.actualCountry === CC;
line('заявлено', CC);
line('фактически', `${R.actualCountry}  ${R.geo.city || ''}  ${R.geo.org || ''}`);
line('IP', R.geo.ip || '?');
if (!R.labelMatches) {
  console.log(`\n  ⚠️  ВНИМАНИЕ: VPN отдаёт ${R.actualCountry}, а не ${CC}.`);
  console.log(`      Файл будет помечен как MISMATCH. Проверь локацию и перезапусти.\n`);
}

// ───────────────────────── 2. апекс: что за сборка ─────────────────────────
const apexRaw = sh(`curl -s -m 30 -A ${q(UA_CHROME)} -D ${q(OUT + '/h.tmp')} https://mostbet.com/`);
const hdrs = fs.existsSync(OUT + '/h.tmp') ? fs.readFileSync(OUT + '/h.tmp', 'utf8') : '';
R.apexStatus = (hdrs.match(/HTTP\/[\d.]+ (\d+)/) || [])[1] || '?';
R.apexBytes = Buffer.byteLength(apexRaw);
R.serverTiming = (hdrs.match(/server-timing: *(.+)/i) || [])[1]?.trim() || null;
R.setCookie = [...hdrs.matchAll(/set-cookie: *(.+)/gi)].map(m => m[1].trim());
fs.writeFileSync(`${OUT}/geo-${CC}.html`, apexRaw);

// отпечатки сборок
const has = s => apexRaw.includes(s);
R.build =
  R.apexStatus === '204' ? 'BLOCK-204 (пусто, как США)' :
  has('stub__title') || has('not available in your country') ? 'BLOCK-451 (заглушка We are sorry)' :
  has('__reactRouterContext') ? 'ЛИЦЕНЗИРОВАННАЯ (React Router SSR)' :
  has('_next/static') ? 'NEXT.JS' :
  has('spa-static') || (has('id="root"') && R.apexBytes < 20000) ? 'СТАРЫЙ SPA-ШЕЛЛ (редиректит)' :
  R.apexBytes === 0 ? 'ПУСТО' : 'НЕОПОЗНАННАЯ';

hr('АПЕКС');
line('статус / размер', `${R.apexStatus}  ${R.apexBytes.toLocaleString('ru')} Б`);
line('СБОРКА', R.build);
line('server-timing', R.serverTiming || '—');

// метаданные
const pick = re => (apexRaw.match(re) || [])[1]?.trim() || null;
R.title = pick(/<title[^>]*>([^<]*)/);
R.description = pick(/<meta name="description" content="([^"]*)"/);
R.canonical = pick(/<link[^>]*rel="canonical"[^>]*href="([^"]*)"/) || pick(/<link[^>]*href="([^"]*)"[^>]*rel="canonical"/);
R.h1 = [...apexRaw.matchAll(/<h1[^>]*>([^<]*)/g)].map(m => m[1].trim()).filter(Boolean);
R.h2count = (apexRaw.match(/<h2[\s>]/g) || []).length;
R.words = apexRaw.replace(/<script[\s\S]*?<\/script>/g, ' ').replace(/<[^>]*>/g, ' ').split(/\s+/).filter(Boolean).length;
R.hreflang = [...apexRaw.matchAll(/<link[^>]*rel="alternate"[^>]*>/gi)].map(m => {
  const t = m[0];
  const l = (t.match(/hrefLang="([^"]*)"/i) || t.match(/hreflang="([^"]*)"/i) || [])[1];
  const h = (t.match(/href="([^"]*)"/i) || [])[1];
  return l && h ? `${l} → ${h}` : null;
}).filter(Boolean);

line('title', R.title || '—');
line('description', R.description || '—');
line('canonical', R.canonical || '— НЕТ');
line('h1', R.h1.length ? R.h1.join(' | ') : '— НЕТ');
line('h2 / слов', `${R.h2count} / ${R.words}`);
line('HREFLANG', R.hreflang.length ? `${R.hreflang.length} записей` : '— НЕТ');
if (R.hreflang.length) R.hreflang.forEach(x => console.log(`      ${x}`));

// ───────────────────────── 3. API редиректа и служебные ─────────────────────────
R.apiRedirect = sh(`curl -s -m 20 -A ${q(UA_CHROME)} https://mostbet.com/api/v3/common/redirect`).slice(0, 200).replace(/\s+/g, ' ');
const code = (u, ua = UA_CHROME, extra = '') =>
  sh(`curl -s -o /dev/null -w "%{http_code}|%{size_download}" -m 25 -A ${q(ua)} ${extra} ${q(u)}`) || '?|?';
R.robots = code('https://mostbet.com/robots.txt');
R.sitemap = code('https://mostbet.com/sitemap.xml');
R.localePaths = Object.fromEntries(['en', 'pl', 'pt', 'de'].map(l => [l, code(`https://mostbet.com/${l}`)]));

hr('СЛУЖЕБНОЕ');
line('API /common/redirect', R.apiRedirect.startsWith('{') ? R.apiRedirect : `(не JSON) ${R.apiRedirect.slice(0, 60)}`);
line('robots.txt', R.robots);
line('sitemap.xml', R.sitemap);
line('локали /en /pl /pt /de', Object.entries(R.localePaths).map(([k, v]) => `${k}:${v.split('|')[0]}`).join('  '));

// ───────────────────────── 4. клоакинг: Googlebot vs Chrome ─────────────────────────
R.asGooglebot = code('https://mostbet.com/', UA_GBOT);
R.asChrome = code('https://mostbet.com/', UA_CHROME);
R.asNoUA = sh(`curl -s -o /dev/null -w "%{http_code}|%{size_download}" -m 25 -H "User-Agent:" https://mostbet.com/`) || '?|?';
R.cloaking = R.asGooglebot !== R.asChrome;

hr('КЛОАКИНГ (одинаковый IP, разный User-Agent)');
line('Chrome', R.asChrome);
line('без UA', R.asNoUA);
line('Googlebot', R.asGooglebot);
line('РАЗЛИЧАЮТСЯ?', R.cloaking ? '⚠️  ДА — контент отдаётся только Googlebot' : 'нет');

// ───────────────────────── 5. ветка design=new ─────────────────────────
R.designNew = sh(`curl -sIL -m 30 -A ${q(UA_CHROME)} -b "design=new" https://mostbet.com/ | grep -iE "^(HTTP/|location:)"`)
  .split('\n').map(s => s.trim()).filter(Boolean);
hr('ВЕТКА design=new');
R.designNew.length ? R.designNew.forEach(l => console.log(`  ${l}`)) : console.log('  —');

// ───────────────────────── 6. смежные домены ─────────────────────────
const RELATED = {
  'guidebook.mostbet.com': 'https://guidebook.mostbet.com/',
  'mostbet.net.pl (сетка pid=35818)': 'https://mostbet.net.pl/',
  'mostbet-pl.com (наш)': 'https://mostbet-pl.com/',
  'mostbett.bet (x-default)': 'https://mostbett.bet/',
};
R.related = Object.fromEntries(Object.entries(RELATED).map(([k, u]) => [k, code(u)]));
hr('СМЕЖНЫЕ ДОМЕНЫ');
Object.entries(R.related).forEach(([k, v]) => line(k, v));

// ───────────────────────── 7. браузер: реальный путь юзера ─────────────────────────
hr('ПУТЬ ПОЛЬЗОВАТЕЛЯ (headless Chromium)');
try {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, userAgent: UA_CHROME });
  const page = await ctx.newPage();
  const chain = [];
  page.on('framenavigated', f => { if (f === page.mainFrame()) chain.push(f.url()); });
  const t0 = Date.now();
  await page.goto('https://mostbet.com/', { waitUntil: 'domcontentloaded', timeout: 45000 });
  try { await page.waitForURL(u => !u.href.includes('mostbet.com'), { timeout: 20000 }); } catch {}
  await page.waitForTimeout(6000);
  R.finalUrl = page.url();
  R.finalHost = new URL(R.finalUrl).host;
  R.redirected = R.finalHost !== 'mostbet.com';
  R.elapsedMs = Date.now() - t0;
  R.chain = chain;
  const d = await page.evaluate(() => ({
    title: document.title,
    words: document.body.innerText.trim().split(/\s+/).filter(Boolean).length,
    h1: [...document.querySelectorAll('h1')].map(e => e.innerText.trim()).slice(0, 3),
    hreflang: document.querySelectorAll('link[rel=alternate][hreflang]').length,
    canonical: document.querySelector('link[rel=canonical]')?.href || null,
  }));
  R.rendered = d;
  line('редирект произошёл?', R.redirected ? `ДА → ${R.finalHost}` : 'НЕТ, остались на апексе');
  line('финальный URL', R.finalUrl);
  line('время до готовности', `${R.elapsedMs} мс`);
  line('title после рендера', d.title);
  line('слов / h1 / hreflang', `${d.words} / ${d.h1.length ? d.h1.join('|') : '—'} / ${d.hreflang}`);
  line('цепочка', chain.join('  →  '));
  if (R.redirected) {
    R.mirrorRobots = sh(`curl -s -m 20 ${q(new URL(R.finalUrl).origin + '/robots.txt')} | head -3 | tr '\\n' ' '`).trim();
    line('robots.txt зеркала', R.mirrorRobots || '—');
  }
  await page.screenshot({ path: `${OUT}/geo-${CC}.png` });
  await browser.close();
} catch (e) {
  R.browserError = e.message;
  console.log(`  ошибка браузера: ${e.message}`);
}

// ───────────────────────── сохранение ─────────────────────────
const name = R.labelMatches ? `geo-${CC}` : `geo-${CC}-MISMATCH-${R.actualCountry}`;
fs.writeFileSync(`${OUT}/${name}.json`, JSON.stringify(R, null, 1));
try { fs.unlinkSync(OUT + '/h.tmp'); } catch {}

hr('ИТОГ');
line('сборка', R.build);
line('редирект', R.redirected ? `→ ${R.finalHost}` : 'нет');
line('hreflang на апексе', R.hreflang.length);
line('клоакинг', R.cloaking ? 'ДА' : 'нет');
console.log(`\n  сохранено: results/${name}.json  +  .png  +  .html`);
if (!R.labelMatches) console.log(`  ⚠️  ГЕО НЕ СОВПАЛО: заявлено ${CC}, получено ${R.actualCountry}\n`);
else console.log('');
