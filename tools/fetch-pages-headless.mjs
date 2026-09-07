// Добор страниц, которые не отдались обычному HTTP (403, SPA без текста): headless Chromium.
// Вход: results/ai/pages.jsonl → берёт status 403 / err / words<=50; пишет HTML в results/ai/pages/<sha>.html (тот же ключ, что у fetch-pages.py).
import { chromium } from 'playwright';
import fs from 'fs'; import crypto from 'crypto';
const ROOT = new URL('..', import.meta.url).pathname;
const rows = fs.readFileSync(`${ROOT}results/ai/pages.jsonl`, 'utf8').trim().split('\n').map(l => JSON.parse(l));
const todo = rows.filter(r => !((r.status === '200' || r.status === 'cached') && (r.words || 0) > 50)).map(r => r.url);
console.log('to fetch headless:', todo.length);
const sha = u => crypto.createHash('sha1').update(u).digest('hex').slice(0, 12);
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36', locale: 'ru-RU', viewport: { width: 1280, height: 900 } });
let done = 0, ok = 0;
const worker = async (urls) => {
  const page = await ctx.newPage();
  for (const u of urls) {
    try {
      const resp = await page.goto(u, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await page.waitForTimeout(2500);
      const html = await page.content();
      if (html.length > 2000 && !/Just a moment|Checking your browser|Attention Required/.test(html)) { fs.writeFileSync(`${ROOT}results/ai/pages/${sha(u)}.html`, html); ok++; }
    } catch (e) {}
    done++; if (done % 25 === 0) console.log(`  ${done}/${todo.length} ok ${ok}`);
  }
  await page.close();
};
const N = 5; const buckets = Array.from({ length: N }, (_, i) => todo.filter((_, j) => j % N === i));
await Promise.all(buckets.map(worker));
await browser.close();
console.log(`headless done: ${done}, saved ${ok}`);
