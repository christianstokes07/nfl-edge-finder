// Shared setup for the browser tests (optional dev tooling, not run by pytest).
// Setup:  cd tests/browser && npm i playwright-core
// Run:    python -m src.demo && (cd site && python3 -m http.server 8765 &) && node tests/browser/<test>.js
// CHROME: path to a Chrome/Chromium binary (defaults to the macOS install).
const { chromium } = require("playwright-core");
const URL0 = process.env.PS_URL || "http://localhost:8765/index.html?demo";
const CHROME = process.env.CHROME || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

async function open(opts = {}) {
  const browser = await chromium.launch({ executablePath: CHROME, headless: true });
  const ctx = await browser.newContext({ viewport: { width: opts.width || 390, height: 900 }, isMobile: !opts.desktop, hasTouch: !opts.desktop,
                                         colorScheme: opts.scheme || "light" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.route("**/api/*", r => r.fulfill({ status: 404, body: "" }));   // no Pages Functions locally
  await page.route(/fonts\.(googleapis|gstatic)\.com/, r => r.abort());       // don't wait on web fonts
  await page.goto(URL0, { waitUntil: "domcontentloaded" }); await page.waitForSelector(".pick");
  await page.evaluate(() => localStorage.clear()); await page.reload({ waitUntil: "domcontentloaded" }); await page.waitForSelector(".pick");
  const h = {
    page, browser, errors,
    async picker(name, value) {                    // single-choice pickers close on tap
      await page.click(`[data-picker="${name}"]`); await page.waitForSelector("#sheet.on"); await page.waitForTimeout(200);
      await page.click(`#sheet .opt[data-v="${value}"]`); await page.waitForTimeout(350);
    },
    async where(...values) {                       // multi-select "Where I bet"
      await page.click('[data-picker="where"]'); await page.waitForSelector("#sheet.on"); await page.waitForTimeout(200);
      for (const v of values) await page.click(`#sheet .opt[data-v="${v}"]`);
      await page.click("#sheet [data-done]"); await page.waitForTimeout(350);
    },
    async toast() { await page.waitForTimeout(150); const t = (await page.isVisible("#toast")) ? await page.textContent("#toast") : "";
                    await page.evaluate(() => { document.getElementById("toast").hidden = true; }); return t; },
    async done(label) { if (errors.length) throw new Error("page errors: " + errors.join(" | ")); await browser.close(); console.log(label + " PASSED"); },
  };
  return h;
}
module.exports = { open };
