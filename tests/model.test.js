// Run with: node tests/model.test.js (pytest runs it too). Whole-number lines: win / push / loss.
const assert = require("node:assert/strict");
const M = require("../site/model.js");
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);
const D = {
  model: {sigma: {player_receptions: 0.45}, dist: 0.5, td_curve: [0.8092, 0.1843, 0.8, 0.93]},
  games: {g1: {a: "New England Patriots", h: "Buffalo Bills", t: "x"}},
  props: [{player: "Jaylen Warren", stat: "player_receptions", m: "player_receptions", pt: 3.5, p: 0.5, b: {dk: [-110, -110], fd: [-115, -105]}}],
  lines: [{g: "g1", m: "totals", stat: "game_total", pt: 47.5, p: 0.5, b: {dk: [-110, -110]}},
          {g: "g1", m: "spreads", stat: "game_spread", pt: -3.5, p: 0.5, b: {dk: [-110, -110]}}],
};
const pl = (side, line) => M.price(D, {kind: "player", player: "Jaylen Warren", stat: "player_receptions", side, line});
// Over 3 and Over 3.5 both need 4+ to WIN: same win chance; only Over 3 can push (at exactly 3)
near(pl("Over", 3).hit, pl("Over", 3.5).hit);
assert.equal(pl("Over", 3.5).push, 0);
assert.ok(pl("Over", 3).push > 0.05);
// Under 3 wins only at 2 or fewer: Under 3.5 = Under 3 + the push at exactly 3
near(pl("Under", 3.5).hit, pl("Under", 3).hit + pl("Under", 3).push);
assert.ok(pl("Under", 3).hit < pl("Under", 3.5).hit);
// win + push + loss = 1, and the push equals Under 3.5 - Under 2.5 (lands on exactly 3)
near(pl("Over", 3).hit + pl("Under", 3).hit + pl("Over", 3).push, 1);
near(pl("Over", 3).push, pl("Under", 3.5).hit - pl("Under", 2.5).hit, 1e-9);
// game total 47: Over wins at 48+ (= Over 47.5), Under at 46 or less (= Under 46.5), 47 pushes
const tot = (side, line) => M.price(D, {kind: "game", g: "g1", stat: "game_total", side, line});
near(tot("Over", 47).hit, tot("Over", 47.5).hit);
near(tot("Under", 47).hit, tot("Under", 46.5).hit);
near(tot("Over", 47).hit + tot("Under", 47).hit + tot("Over", 47).push, 1);
// spread: Bills -3 win by 4+, push at exactly 3; Patriots +3 = the other side of the same game
const sp = (team, line) => M.price(D, {kind: "game", g: "g1", stat: "game_spread", team, side: team, line});
near(sp("Buffalo Bills", -3).hit, sp("Buffalo Bills", -3.5).hit);
near(sp("Buffalo Bills", -3).push, sp("New England Patriots", 3).push);
near(sp("Buffalo Bills", -3).hit + sp("New England Patriots", 3).hit + sp("Buffalo Bills", -3).push, 1);
// the hit-rate check: exactly on a whole-number line is a push, not a hit
global.Parlay = require("../site/parlay.js");
const AN = require("../site/analytics.js");
assert.equal(AN.cleared(3, "player_receptions", 3, "Under"), null);
assert.equal(AN.cleared(3, "player_receptions", 3.5, "Under"), true);
assert.equal(AN.cleared(4, "player_receptions", 3.5, "Over"), true);
assert.equal(AN.cleared(3, "player_receptions", 3.5, "Over"), false);
console.log("model.js: all tests passed");
