// Parlay and odds math. Plain script, no build step: the page loads it with <script src>, and the
// tests load it in Node (module.exports). Keep it free of DOM code.
(function (root) {
  // Conservative haircuts for legs that aren't independent. Legs in one game (or on one player) move
  // together; that can help or hurt, so we assume it hurts.
  const SAME_PLAYER = 0.90;
  const SAME_GAME = 0.96;

  function americanToDecimal(a) {
    a = Number(a);
    if (!isFinite(a) || (a > -100 && a < 100)) return null;
    return a > 0 ? 1 + a / 100 : 1 + 100 / -a;
  }

  function decimalToAmerican(d) {
    if (!isFinite(d) || d <= 1) return null;
    return d >= 2 ? Math.round((d - 1) * 100) : Math.round(-100 / (d - 1));
  }

  // Fair American odds for a probability (no house cut).
  function probToAmerican(p) {
    return p > 0 && p < 1 ? decimalToAmerican(1 / p) : null;
  }

  function fmtAmerican(a) {
    return a == null ? "–" : a > 0 ? "+" + a : String(a);
  }

  // What someone typed for the book's parlay odds: "+450", "450", "-120" (American) or "5.5" (decimal).
  // Returns decimal odds or null.
  function parseOdds(s) {
    s = String(s == null ? "" : s).trim().replace(/[−–]/g, "-");
    if (!s) return null;
    if (/^[+-]?\d+(\.\d+)?$/.test(s)) {
      const x = Number(s);
      if (/^\d+\.\d+$/.test(s) && x > 1 && x < 100) return x; // decimal odds like 5.5
      if (s[0] === "+" || s[0] === "-" || Math.abs(x) >= 100) return americanToDecimal(x);
    }
    return null;
  }

  // Expected return per $1 staked: +0.05 means you'd get back $1.05 per $1 over many tries.
  function evPerDollar(p, dec) {
    return dec ? p * dec - 1 : null;
  }

  // legs: [{player, g, hit}] -> combined chance, with the correlation haircut spelled out.
  function combine(legs) {
    let raw = 1;
    for (const l of legs) raw *= l.hit;
    let samePlayer = 0, sameGame = 0;
    for (let i = 0; i < legs.length; i++) {
      for (let j = i + 1; j < legs.length; j++) {
        if (norm(legs[i].player) === norm(legs[j].player)) samePlayer++;
        else if (legs[i].g && legs[i].g === legs[j].g) sameGame++;
      }
    }
    const factor = Math.pow(SAME_PLAYER, samePlayer) * Math.pow(SAME_GAME, sameGame);
    const p = legs.length ? raw * factor : 0;
    return { raw: legs.length ? raw : 0, p, factor, samePlayer, sameGame,
             fairDecimal: p > 0 ? 1 / p : null, fairAmerican: probToAmerican(p) };
  }

  // Product of each leg's decimal odds: what the book pays if it simply multiplies the legs.
  function multiplyOdds(legs) {
    let d = 1;
    for (const l of legs) { if (!l.dec) return null; d *= l.dec; }
    return legs.length ? d : null;
  }

  // Pick the n highest-hit-chance candidates, max one per player, avoiding a second leg from the same
  // game while there are other choices.
  function autoBuild(cands, n) {
    const sorted = cands.slice().sort((a, b) => b.hit - a.hit);
    const out = [], players = new Set(), games = new Set();
    for (const strict of [true, false]) {
      for (const c of sorted) {
        if (out.length >= n) break;
        const who = norm(c.player);
        if (players.has(who) || out.includes(c)) continue;
        if (strict && c.g && games.has(c.g)) continue;
        out.push(c); players.add(who); if (c.g) games.add(c.g);
      }
    }
    return out.sort((a, b) => b.hit - a.hit);
  }

  function norm(s) {
    return String(s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ")
      .split(/\s+/).filter(t => t && !["jr", "sr", "ii", "iii", "iv"].includes(t)).join(" ");
  }

  const api = { SAME_PLAYER, SAME_GAME, americanToDecimal, decimalToAmerican, probToAmerican, fmtAmerican,
                parseOdds, evPerDollar, combine, multiplyOdds, autoBuild, norm };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Parlay = api;
})(this);
