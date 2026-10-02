// Run with: node tests/analytics.test.js  (pytest runs it too, see test_parlay.py)
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
global.Parlay = require("../site/parlay.js");
const AN = require("../site/analytics.js");
const A = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "analytics_mock.json"), "utf8"));
const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "verdict_cases.json"), "utf8"));

// same verdict rules as src/verdict.py
for (const c of CASES) assert.equal(AN.verdict(c.stat, c.side, c.line, c.proj, c.market_p ?? null), c.want, JSON.stringify(c));

// player lookup by name, disambiguated by the game's teams
assert.equal(AN.findPlayer(A, "Jaylen Warren", []).id, "00-1");
assert.equal(AN.findPlayer(A, "Josh Allen", ["Pittsburgh Steelers", "Cleveland Browns"]).id, "00-4");
assert.equal(AN.findPlayer(A, "Nobody Here", []), null);

// evidence: 4 sections, real numbers from the file, ranks, and n/a with a reason
const warren = AN.findPlayer(A, "Jaylen Warren", []);
const secs = AN.sections(A, warren, "player_rush_yds");
assert.deepEqual(secs.map(s => s.title), ["Usage", "Efficiency", "Matchup vs Browns", "Game context"]);
for (const s of secs) assert.ok(s.lines.length >= 3 && s.lines.length <= 5, s.title + " has " + s.lines.length);
const all = secs.flatMap(s => s.lines.map(l => l.text)).join("\n");
assert.match(all, /gets 58% of the Steelers' carries \(top 19% of running backs\)/);
assert.match(all, /4\.9 yards per carry \(4\.7 adjusted for defenses faced\)/);
assert.match(all, /Browns allow 4\.6 yards per carry, 6th most in the NFL/);            // adjusted rounds the same: not repeated
assert.match(all, /Browns stop 17% of runs at or behind the line \(21% adjusted for offenses faced\), 8th highest/);
assert.ok(secs[1].lines.some(l => l.key === "ryoe_att" && l.na && l.text === "n/a (Next Gen Stats only lists runners with enough carries)"));
assert.match(all, /Steelers are 2\.5-point underdogs; expected to score 19\.5 points \(game total 41\.5\)/);
assert.match(all, /wind 18 mph/);
const te = AN.sections(A, AN.findPlayer(A, "Pat Freiermuth", []), "player_reception_yds");
assert.match(te[2].lines.map(l => l.text).join("\n"), /Browns allow 8\.7 yards per target to tight ends \(8\.1 adjusted\), 6th most \(26 targets\)/);
assert.ok(te[1].lines.some(l => l.key === "yprr_proxy" && l.text === "n/a (not found in nflverse snap counts)"));

// glossary: every key used in an evidence line has a definition and a direction note
for (const s of secs.concat(te)) for (const l of s.lines) assert.ok(l.key === null || AN.DEF[l.key], "no definition for " + l.key);
assert.equal(AN.dirNote("stuff_rate", "Over"), "For this Over pick, lower is better.");
assert.equal(AN.dirNote("target_share", "Under"), "For this Under pick, lower is better.");
assert.match(AN.dirNote("adot", "Over"), /Context only/);

// projection breakdown uses the stored inputs
assert.match(AN.projText("player_rush_yds", warren.pj.player_rush_yds), /^15\.2 carries \(58% of 26\.2 team carries\) × 4\.8 yards per carry × 1\.10 defense factor = 80\.0 on average\. .* so 68\.4\.$/);
assert.match(AN.projText("player_anytime_td", warren.pj.player_anytime_td), /→ 46% to score at least once/);

// flags: player injury, teammate out, opposing defense starter out, wind on a passing stat, line move
const fl = AN.flags(A, warren, "player_rush_yds", "Over", {mv: [60.5, 66.5]});
const txt = fl.map(f => f.text).join("\n");
assert.match(txt, /Warren is listed Questionable \(Knee\)/);
assert.match(txt, /Teammate WR Calvin Austin is Out \(Ankle\): had 18% target share/);
assert.match(txt, /Browns defense missing CB Denzel Ward \(Out\)/);
assert.match(txt, /Line moved from 60\.5 to 66\.5 since the previous scan \(against this pick\)/);
assert.ok(!/Wind/.test(txt), "wind shouldn't flag a rushing prop");
assert.match(AN.flags(A, AN.findPlayer(A, "Pat Freiermuth", []), "player_reception_yds", "Over").map(f => f.text).join(), /Wind 18 mph/);

// confidence: books set the base, stats agree/disagree move it, serious warnings lower it
assert.equal(AN.confidence(5, "agree", []).level, "High");
assert.equal(AN.confidence(5, "neutral", []).level, "Medium");
assert.equal(AN.confidence(5, "disagree", []).level, "Low");
assert.equal(AN.confidence(1, "agree", []).level, "Medium");
assert.equal(AN.confidence(5, "agree", [{sev: 1}]).level, "Medium");

// the one-line why
const c = {hit: 0.55, n: 6, stat: "player_rush_yds"};
const w = AN.why(c, A, warren, warren.pj.player_rush_yds, "neutral", 65.5, "Over 65.5 rushing yards");
assert.equal(w, "Why 55%: 6 sportsbooks' prices, with the books' cut removed, give \u201cOver 65.5 rushing yards\u201d a 55% chance. Stats are neutral: projection 68.4 rushing yards vs the 65.5 line (58% carry share; Browns allow 4.6 yards per carry, 6th most).");
assert.match(AN.why(c, null, null, null, "n/a", 65.5, "x"), /Stats: n\/a \(analytics haven't loaded\)/);
assert.match(AN.why(c, A, null, null, "n/a", 65.5, "x"), /Stats: n\/a \(no nflverse stats for this player this season\)/);

// bottom-half ranks read from the other end: rank 18 of 32 -> "15th fewest"
assert.match(all, /Browns allow −0\.04 EPA per run \(−0\.07 adjusted for offenses faced\), 15th fewest in the NFL/);
assert.match(all, /The Steelers run 61\.2 plays per game, 9th most/);
// recent form: game log for the stat, hits vs the line, home/away split, last season
const L = AN.gameLog(A, warren, "player_rush_yds");
assert.deepEqual(L.map(x => x.v), [80, 52, 71]);
assert.deepEqual(AN.gameLog(A, warren, "player_rush_reception_yds").map(x => x.v), [90, 57, 93]);
const rf = AN.recentSection(A, warren, "player_rush_yds", 65.5, "Over").lines.map(l => l.text).join("\n");
assert.match(rf, /Last 3 games: 71 vs NE, 52 @ SEA, 80 vs ATL/);
assert.match(rf, /Over 65\.5 in 2 of 3 games this season \(average 67\.7\)/);
assert.match(rf, /Home: 75\.5 a game \(2\) · Away: 52\.0 \(1\)/);
assert.match(rf, /Last season: 58\.2 rushing yards per game over 17 games/);
assert.match(rf, /on the road/);
// coverage: CLE's most-used coverage, and the TE's split against it (good matchup when 15%+ better)
const sc = AN.schemeSection(A, AN.findPlayer(A, "Pat Freiermuth", []), "player_reception_yds");
const sct = sc.lines.map(l => l.text).join("\n");
assert.match(sct, /Browns played Cover 1 on 35% of dropbacks last season \(2nd most\)/);
assert.match(sct, /Freiermuth vs Cover 1: 10\.4 yards per target \(12 targets\) vs 7\.5 overall · good matchup/);
assert.match(sct, /man coverage 41% of the time \(5th most\); Freiermuth averaged 9\.8 yards per target vs man, 6\.4 vs zone/);
assert.equal(sc.edge, 1);
// the short version leads with what matters and marks direction for THIS pick
const sv = AN.shortVersion(A, warren, {stat: "player_rush_yds", side: "Over", hit: 0.55}, 65.5, warren.pj.player_rush_yds, "neutral");
assert.match(sv[0].text, /listed Questionable/);          // the player's own injury always comes first
assert.equal(sv[0].dir, -1);
assert.ok(sv.some(x => /would have hit in 2 of 3 games/.test(x.text) && x.dir === 1));
const svU = AN.shortVersion(A, warren, {stat: "player_rush_yds", side: "Under", hit: 0.45}, 65.5, warren.pj.player_rush_yds, "neutral");
assert.ok(svU.some(x => /would have hit in 1 of 3 games/.test(x.text) && x.dir === -1));
// injuries for both teams
const inj = AN.injurySection(A, warren).lines.map(l => l.text).join("\n");
assert.match(inj, /Steelers: WR Calvin Austin Out \(Ankle\)/);
assert.match(inj, /Browns: CB Denzel Ward Out \(Hamstring\)/);
// ---- injuries: freed-up targets go to the active players in proportion to their shares
const mk = A.mk.WR, wr = (n, share, inj, lastWk) => ({n, id: n, pos: "WR", t: "PIT", g: 3, wk: [1, 2, 3], m: mk.map(k => k === "target_share" ? [share, 50] : null),
  pj: {}, inj, log: [[lastWk, "CLE", 1, 50, 4, 6, 0, 0, 0]]});
A.players.push(wr("Calvin Austin", 0.18, ["Out", "Ankle", null, "2026-10-02T16:00Z", "Ruled out Friday."], 3));
A.players.push(wr("DK Metcalf", 0.40, null, 3));
A.players.push(wr("Long Gone", 0.10, ["Injured Reserve", "Knee", null, null, null], 1));   // hasn't played since week 1: already priced in
A._byName = null;   // players added after the lookup index was built
const fm = AN.findPlayer(A, "Pat Freiermuth", []);
const adj = AN.injuryAdjust(A, fm, "player_reception_yds");
assert.deepEqual(adj.target_share.freed.map(x => x.n), ["Calvin Austin"]);
assert.ok(Math.abs(adj.target_share.newShare - (0.17 + 0.18 * 0.4 * 0.17 / 0.57)) < 1e-9);
const mAdj = AN.injuryAdjust(A, AN.findPlayer(A, "DK Metcalf", []), "player_reception_yds");    // the WR gets the WR-only 60% too
assert.ok(Math.abs(mAdj.target_share.newShare - (0.40 + 0.18 * 0.6 * 0.40 / 0.40 + 0.18 * 0.4 * 0.40 / 0.57)) < 1e-9);
const pjA = AN.adjustProjection("player_reception_yds", fm.pj.player_reception_yds, adj);
assert.ok(Math.abs(pjA.med - 37.0 * adj.target_share.factor) < 1e-9 && pjA.adj === adj);
assert.match(AN.adjustText(fm, adj), /WR Calvin Austin \(Out\) is likely out: his 18% of the team's targets get spread around, so Freiermuth projects for 19% instead of 17%/);
assert.match(AN.projText("player_reception_yds", pjA), /Includes teammates' freed-up targets \(17% → 19% share\)/);
assert.equal(AN.injuryAdjust(A, AN.findPlayer(A, "DK Metcalf", []), "player_pass_yds"), null);
// the short version leads with it, pointing the right way for each side
const vI = AN.verdict("player_reception_yds", "Under", 30.5, pjA, null);
assert.equal(vI, "disagree");                                       // an Under on a player gaining targets
const svI = AN.shortVersion(A, fm, {stat: "player_reception_yds", side: "Under", hit: 0.5}, 30.5, pjA, vI);
assert.ok(svI.slice(0, 2).some(x => x.dir === -1 && /Calvin Austin \(Out\) is likely out/.test(x.text)), JSON.stringify(svI));
assert.ok(svI.some(x => /points the other way/.test(x.text) && x.dir === -1));
// live statuses from ESPN replace the stats file's, and the team report is rebuilt
const live = {updated: "2026-10-02T17:00:00Z", teams: {"Pittsburgh Steelers": [
  {n: "Pat Freiermuth", pos: "TE", s: "Doubtful", d: "2026-10-02T16:30Z", i: "Hamstring", c: "Didn't practice Friday."}]}};
assert.equal(AN.applyLiveInjuries(A, live), 1);
assert.equal(fm.inj[0], "Doubtful");
assert.equal(warren.inj[0], null);                                  // off ESPN's list now
assert.deepEqual(A.teams.PIT.out.map(x => x.n + " " + x.s), ["Pat Freiermuth Doubtful"]);
assert.match(A.inj_src, /ESPN injury feed, live/);
// news after the lines were pulled -> a warning to check the current line
const fl2 = AN.flags(A, fm, "player_reception_yds", "Over", null, "2026-10-01T20:58:00Z");
assert.match(fl2[0].text, /Injury news since these lines were pulled: Pat Freiermuth Doubtful/);
assert.equal(AN.flags(A, fm, "player_reception_yds", "Over", null, "2026-10-02T18:00:00Z").filter(f => f.k === "news").length, 0);
console.log("analytics.js: all tests passed");
