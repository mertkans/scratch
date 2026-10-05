// index.html'deki animasyonu kare kare yakalayıp MP4'e çevirir.
// Kullanım: node render.mjs [çıktı.mp4]        -> tüm video
//           node render.mjs --shots 1.5 7 12  -> belirtilen saniyelerden PNG
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = path.dirname(fileURLToPath(import.meta.url));
const FPS = 30;
const args = process.argv.slice(2);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
await page.addInitScript(() => { window.__render = true; });
await page.goto('file://' + path.join(dir, 'index.html') + '?render');
await page.evaluate(() => document.fonts.ready);
await page.waitForTimeout(300);
const duration = await page.evaluate(() => window.DURATION);

// Zamanı ayarla ve tarayıcının o kareyi gerçekten çizmesini bekle
const seek = t => page.evaluate(t => new Promise(r => {
  window.seek(t);
  requestAnimationFrame(() => requestAnimationFrame(r));
}), t);

if (args[0] === '--shots') {
  for (const t of args.slice(1)) {
    await seek(Number(t));
    await page.screenshot({ path: path.join(dir, `shot-${t}.png`) });
  }
} else {
  const out = args[0] || path.join(dir, 'kasif-akademi-tanitim.mp4');
  const ff = spawn('ffmpeg', [
    '-y', '-v', 'error',
    '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-',
    '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
    '-shortest', '-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', out,
  ], { stdio: ['pipe', 'inherit', 'inherit'] });
  const total = Math.round(duration * FPS);
  for (let i = 0; i < total; i++) {
    await seek(i / FPS);
    const buf = await page.screenshot({ type: 'jpeg', quality: 95 });
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if (i % 90 === 0) console.log(`${i}/${total}`);
  }
  ff.stdin.end();
  await new Promise(r => ff.on('close', r));
  console.log('Bitti:', out);
}
await browser.close();
