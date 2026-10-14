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
// ---- no sportsbook line: price from Kalshi / Polymarket ladders ----
const L = {model: {sigma: {player_rush_yds: 0.6}}, games: {g2: {a: "Seattle Seahawks", h: "Denver Broncos", t: "x"}},
  kalshi: [40, 60, 80].map((t, i) => ({player: "RJ Harvey", stat: "player_rush_yds", g: "g2", threshold: t, fair: [0.72, 0.45, 0.22][i], books: 0})).concat(
          [{player: "", stat: "game_ml", g: "g2", team: "Denver Broncos", threshold: null, km: 1, bid: 43, ask: 45},
           {player: "", stat: "game_spread", g: "g2", team: "Seattle Seahawks", threshold: 3.5, km: 1, bid: 44, ask: 46},
           {player: "", stat: "game_total", g: "g2", team: null, threshold: 44.5, km: 1, bid: 39, ask: 41}]),
  poly: [{player: "RJ Harvey", stat: "player_rush_yds", g: "g2", threshold: 60, km: 1, bid: 44, ask: 48}]};
const rush = line => M.price(L, {kind: "player", player: "RJ Harvey", stat: "player_rush_yds", side: "Over", line});
near(rush(39.5).hit, 0.72, 0.03);                      // reproduces a rung closely
near(rush(59.5).hit, (0.45 + 0.46) / 2, 1e-9);         // Kalshi + Polymarket at the same rung: averaged
assert.ok(rush(49.5).hit < rush(39.5).hit && rush(49.5).hit > rush(59.5).hit);   // in between, monotone
assert.equal(rush(49.5).src, "Kalshi + Polymarket");
assert.ok(rush(89.5).unc > rush(49.5).unc);            // beyond the top rung: priced, but less sure
assert.equal(rush(200.5), null);                        // far outside the ladder: refused
const gm = (stat, team, side, line) => M.price(L, {kind: "game", g: "g2", stat, team, side, line});
near(gm("game_ml", "Denver Broncos", "Denver Broncos", null).hit, 0.44, 0.04);
assert.ok(gm("game_spread", "Denver Broncos", "Denver Broncos", -3.5).hit < gm("game_ml", "Denver Broncos", "Denver Broncos", null).hit);
near(gm("game_total", null, "Over", 44.5).hit, 0.40, 0.04);
// sportsbook line far away (50-80%): priced as a rough estimate; beyond 80%: refused
const F = {model: {sigma: {player_rush_yds: 0.6}, dist: 0.5}, games: {}, props: [{player: "X", stat: "player_rush_yds", m: "player_rush_yds", pt: 60.5, p: 0.5, b: {dk: [-110, -110]}}]};
const fx = line => M.price(F, {kind: "player", player: "X", stat: "player_rush_yds", side: "Over", line});
assert.equal(fx(45.5).rough, false);
assert.equal(fx(20.5).rough, true);
assert.equal(fx(5.5), null);
console.log("model.js: all tests passed");
