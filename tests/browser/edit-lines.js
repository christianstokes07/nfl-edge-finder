// Every way to change a line: custom pick (player + spread with ±), slip − / + / typed / empty / ±, far lines.
// Works on data with sportsbook lines (demo) and without (live data early in the week: Kalshi/Polymarket ladders).
const assert = require("node:assert/strict");
const { open } = require("./lib");
(async () => {
  const t = await open(), p = t.page;
  const D = await p.evaluate(() => fetch(location.search.includes("demo") ? "demo-data.json" : "data.json").then(r => r.json()));
  const out = async () => (await p.$eval("#cOut", e => e.innerText)).split("\n").slice(0, 2).join(" | ");
  const name = (D.props.find(x => x.stat === "player_reception_yds") || D.kalshi.find(u => u.stat === "player_reception_yds")).player;
  await p.click('[data-open="custom"]'); await p.waitForSelector("#sheet.on");
  await p.fill("#cName", name); await p.dispatchEvent("#cName", "change"); await p.waitForTimeout(150);
  await p.selectOption("#cStat", "player_reception_yds"); await p.dispatchEvent("#cStat", "change"); await p.waitForTimeout(150);
  const l0 = Number(await p.$eval("#cLine", e => e.value));
  assert.match(await out(), /^\d+%/, "prefilled line priced");
  const type = async v => { await p.fill("#cLine", v); await p.dispatchEvent("#cLine", "input"); await p.waitForTimeout(100); return out(); };
  const lower = await type(String(Math.max(0.5, l0 - 10)));
  assert.ok(Number(lower.match(/^(\d+)%/)[1]) > Number((await type(String(l0))).match(/^(\d+)%/)[1]), "lower Over line is likelier");
  assert.match(await type("−" + l0), /above 0/);
  assert.match(await type("abc"), /Type a line/);
  assert.match(await type("  " + l0 + " "), /^\d+%/);
  assert.match(await type(String(l0 * 6)), /Can't price/);
  await type(String(l0)); await p.click("#cAdd"); await p.waitForTimeout(350);
  // spread with ±
  await p.click('[data-open="custom"]'); await p.waitForSelector("#sheet.on");
  const g = await p.$eval("#cNames option[value^='Game:']", o => o.value);
  await p.fill("#cName", g); await p.dispatchEvent("#cName", "change"); await p.waitForTimeout(150);
  await p.selectOption("#cStat", "game_spread"); await p.dispatchEvent("#cStat", "change"); await p.waitForTimeout(150);
  const s0 = await p.$eval("#cLine", e => e.value);
  await p.click("#cFlip"); await p.waitForTimeout(100);
  assert.equal(Number(await p.$eval("#cLine", e => e.value)), -Number(s0));
  assert.match(await out(), /^\d+%/);
  await p.click("#cAdd"); await p.waitForTimeout(350);
  // slip editing
  await p.click("#slipBtn"); await p.waitForSelector("#sheet.on"); await p.waitForTimeout(250);
  const leg = i => `.legs li:nth-child(${i + 1})`;
  for (let i = 0; i < 2; i++) {
    const before = await p.$eval(leg(i) + " .l-line", e => e.value);
    await t.toast();                                   // clear any earlier message
    await p.click(leg(i) + ' [data-step="1"]'); assert.ok(!(await t.toast()), "step priced");
    assert.notEqual(await p.$eval(leg(i) + " .l-line", e => e.value), before);
    await p.fill(leg(i) + " .l-line", "999"); await p.dispatchEvent(leg(i) + " .l-line", "change");
    assert.match(await t.toast(), /Can't price 999|Spreads are priced/);
    assert.notEqual(await p.$eval(leg(i) + " .l-line", e => e.value), "999", "bad line reverted");
    await p.fill(leg(i) + " .l-line", ""); await p.dispatchEvent(leg(i) + " .l-line", "change");
    assert.match(await t.toast(), /Type a line/);
    for (let k = 0; k < 30; k++) await p.click(leg(i) + ' [data-step="-1"]');
    await t.toast();
    const v = Number(await p.$eval(leg(i) + " .l-line", e => e.value));
    if (i === 0) assert.ok(v >= 0.5, "player line never below 0.5");
    const pctTxt = await p.$eval(leg(i) + " .l-p", e => e.innerText);
    assert.ok(!/^(0|100)%$/.test(pctTxt), "never 0% or 100%: " + pctTxt);
  }
  if (await p.$(leg(1) + " [data-flip]")) { await p.click(leg(1) + " [data-flip]"); await t.toast(); }
  await t.done("EDIT LINES");
})().catch(e => { console.error(e); process.exit(1); });
