// Run with: node tests/parlay.test.js  (pytest runs it too, see test_parlay.py)
const assert = require("node:assert/strict");
const P = require("../site/parlay.js");
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} != ${b}`);

// odds conversions
near(P.americanToDecimal(-110), 1 + 100 / 110);
near(P.americanToDecimal(150), 2.5);
assert.equal(P.americanToDecimal(50), null);
assert.equal(P.decimalToAmerican(2.5), 150);
assert.equal(P.decimalToAmerican(1.5), -200);
assert.equal(P.probToAmerican(0.5), 100);
assert.equal(P.probToAmerican(0.8), -400);
assert.equal(P.probToAmerican(0.2), 400);
assert.equal(P.fmtAmerican(450), "+450");

// typed odds
near(P.parseOdds("+450"), 5.5);
near(P.parseOdds("450"), 5.5);
near(P.parseOdds("−120"), 1 + 100 / 120);  // unicode minus
near(P.parseOdds("5.5"), 5.5);
assert.equal(P.parseOdds("abc"), null);
assert.equal(P.parseOdds(""), null);
assert.equal(P.parseOdds("50"), null);

// independent legs multiply
let r = P.combine([{player: "A", g: "g1", hit: 0.6}, {player: "B", g: "g2", hit: 0.6}, {player: "C", g: "g3", hit: 0.6}]);
near(r.p, 0.216);
assert.equal(r.samePlayer + r.sameGame, 0);
assert.equal(r.fairAmerican, P.decimalToAmerican(1 / 0.216));

// same game and same player legs get a haircut
r = P.combine([{player: "A", g: "g1", hit: 0.6}, {player: "B", g: "g1", hit: 0.5}]);
assert.equal(r.sameGame, 1);
near(r.raw, 0.3);
near(r.p, 0.3 * P.SAME_GAME);
r = P.combine([{player: "Amon-Ra St. Brown", g: "g1", hit: 0.6}, {player: "amon ra st brown", g: "g1", hit: 0.5}]);
assert.equal(r.samePlayer, 1);
assert.equal(r.sameGame, 0);            // counted once, as the stronger link
near(r.p, 0.3 * P.SAME_PLAYER);
assert.equal(P.combine([]).p, 0);

// value of a parlay price
near(P.evPerDollar(0.25, 4), 0);
assert.ok(P.evPerDollar(0.25, 5) > 0);
near(P.multiplyOdds([{dec: 2}, {dec: 1.5}]), 3);
assert.equal(P.multiplyOdds([{dec: 2}, {dec: null}]), null);

// auto-build: highest hit chance, one leg per player, avoids repeat games when possible
const c = [
  {id: 1, player: "A", g: "g1", hit: 0.80},
  {id: 2, player: "A", g: "g1", hit: 0.78},   // same player as #1
  {id: 3, player: "B", g: "g1", hit: 0.75},   // same game as #1
  {id: 4, player: "C", g: "g2", hit: 0.70},
  {id: 5, player: "D", g: "g3", hit: 0.60},
];
assert.deepEqual(P.autoBuild(c, 3).map(x => x.id), [1, 4, 5]);
// when there aren't enough games, it falls back to same-game legs but never repeats a player
assert.deepEqual(P.autoBuild(c, 4).map(x => x.id), [1, 3, 4, 5]);
assert.deepEqual(P.autoBuild(c, 6).map(x => x.id), [1, 3, 4, 5]);

console.log("parlay.js: all tests passed");
