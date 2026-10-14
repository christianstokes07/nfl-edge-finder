// Picks render, every picker opens, slip works, no horizontal scroll at 390px, dark mode applies.
const assert = require("node:assert/strict");
const { open } = require("./lib");
(async () => {
  const t = await open(), p = t.page;
  assert.ok(await p.$$eval(".pick", x => x.length) > 0);
  for (const k of ["where", "prop", "side", "game", "sort"]) {
    await p.click(`[data-picker="${k}"]`); await p.waitForSelector("#sheet.on"); await p.keyboard.press("Escape"); await p.waitForTimeout(300);
  }
  await t.where("kalshi");
  assert.match(await p.textContent("#v-where"), /Kalshi/);
  await t.where("best");
  await p.click(".pick:first-child .add"); await p.waitForTimeout(200);
  assert.match(await p.textContent("#sbT"), /1 leg/);
  await p.click(".pick:first-child .whybtn"); await p.waitForSelector(".pick:first-child .panel .sec");
  assert.ok(await p.evaluate(() => document.documentElement.scrollWidth) <= 390);
  await p.emulateMedia({ colorScheme: "dark" });
  assert.equal(await p.evaluate(() => getComputedStyle(document.body).backgroundColor), "rgb(20, 19, 15)");
  await t.done("SMOKE");
})().catch(e => { console.error(e); process.exit(1); });
