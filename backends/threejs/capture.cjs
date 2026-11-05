#!/usr/bin/env node
/**
 * capture.cjs — mở index.html trong Chromium headless (Playwright), gọi window.capture.renderFrame(i)
 * cho từng khung và ghi PNG. Được capture.py gọi; cũng chạy tay được:
 *   node capture.cjs --url http://127.0.0.1:8000/repo/backends/threejs/index.html?bundle=/bundle.json \
 *                    --out out/x/frames --width 1920 --height 1080
 */
const fs = require('fs');
const path = require('path');

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : def;
}

const url = arg('url');
const outDir = arg('out');
const width = Number(arg('width', 1920));
const height = Number(arg('height', 1080));
const pattern = arg('pattern', 'frame_%05d.png');
const timeoutMs = Number(arg('timeout', 120000));
if (!url || !outDir) {
  console.error('cần --url và --out');
  process.exit(64);
}

let chromium;
try {
  ({ chromium } = require('playwright'));
} catch (e) {
  console.error('không tìm thấy module playwright: cài `npm i -g playwright` hoặc đặt NODE_PATH');
  process.exit(69);
}

const exe = process.env.CARTOON3D_CHROMIUM || undefined;

(async () => {
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch({
    executablePath: exe,
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
      '--ignore-gpu-blocklist', '--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(url, { waitUntil: 'load', timeout: timeoutMs });
  try {
    await page.waitForFunction(() => window.capture && window.capture.ready, null, { timeout: timeoutMs });
  } catch (e) {
    console.error('trang không sẵn sàng:', errors.join('\n') || e.message);
    await browser.close();
    process.exit(70);
  }
  const n = await page.evaluate(() => window.capture.frames);
  const t0 = Date.now();
  for (let i = 0; i < n; i++) {
    const dataUrl = await page.evaluate(k => window.capture.renderFrame(k), i);
    const b64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
    fs.writeFileSync(path.join(outDir, pattern.replace('%05d', String(i).padStart(5, '0'))), Buffer.from(b64, 'base64'));
  }
  await browser.close();
  if (errors.length) {
    console.error('lỗi trong trang:\n' + errors.join('\n'));
    process.exit(71);
  }
  console.log(JSON.stringify({ frames: n, ms: Date.now() - t0 }));
})().catch(e => { console.error(e); process.exit(1); });
