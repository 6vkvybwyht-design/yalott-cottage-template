// Скріншоти однієї сторінки для tools/design_review.py (Node + Playwright).
//   node tools/shots.js URL ПРЕФІКС_ФАЙЛІВ [ширини через кому, типово 375,1440]
// Для кожної ширини: перший екран (ПРЕФІКС-375.jpg) і вся сторінка (ПРЕФІКС-375-full.jpg).
// Сторінку прокручує повільно, щоб блоки з анімацією появи встигли показатись.
// Друкує JSON: помилки консолі (зокрема порушення CSP) і горизонтальна прокрутка на кожній ширині.
const { chromium } = require('playwright');

(async () => {
  const [url, prefix, widthsArg] = process.argv.slice(2);
  const widths = (widthsArg || '375,1440').split(',').map(Number);
  const browser = await chromium.launch();
  const report = {};
  for (const w of widths) {
    const page = await browser.newPage({ viewport: { width: w, height: w < 700 ? 760 : 900 }, deviceScaleFactor: 1,
      isMobile: w < 700, hasTouch: w < 700 });
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.waitForTimeout(1600);                          // анімація банера
    await page.screenshot({ path: `${prefix}-${w}.jpg`, type: 'jpeg', quality: 78 });
    const height = await page.evaluate(() => document.documentElement.scrollHeight);
    for (let y = 0; y < height; y += 400) { await page.evaluate((v) => window.scrollTo(0, v), y); await page.waitForTimeout(90); }
    await page.waitForTimeout(1400);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(500);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    await page.screenshot({ path: `${prefix}-${w}-full.jpg`, type: 'jpeg', quality: 70, fullPage: true });
    report[w] = { errors, overflow };
    await page.close();
  }
  await browser.close();
  console.log(JSON.stringify(report));
})().catch((e) => { console.error(e); process.exit(1); });
