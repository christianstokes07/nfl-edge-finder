// Hit chance for ANY line, in the browser: the same no-vig consensus math as src/model.py and
// src/games.py, so a custom pick ("Over 52.5 instead of 65.5") is priced exactly like the picks the scan
// generates. tests/test_model_js.py checks this file against the Python numbers.
(function (root) {
  // ---- normal distribution ------------------------------------------------------------------------------
  function erfc(x) {   // Numerical Recipes erfcc, |error| < 1.2e-7
    const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
    const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 +
      t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? r : 2 - r;
  }
  const cdf = x => 0.5 * erfc(-x / Math.SQRT2);
  function inv(p) {    // Acklam's inverse normal + one Newton step
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.3577518672690, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    let q, r, x;
    if (p < 0.02425) { q = Math.sqrt(-2 * Math.log(p)); x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    else if (p > 1 - 0.02425) { q = Math.sqrt(-2 * Math.log(1 - p)); x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1); }
    else { q = p - 0.5; r = q * q; x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1); }
    const e = cdf(x) - p, u = e * Math.sqrt(2 * Math.PI) * Math.exp(x * x / 2);
    return x - u / (1 + x * u / 2);
  }
  const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

  // ---- prices ------------------------------------------------------------------------------------------
  const prob = a => (a > 0 ? 100 / (a + 100) : -a / (-a + 100));
  const devig = (a, b) => { const x = prob(a), y = prob(b); return x / (x + y); };

  function lognormalAtLeast(threshold, line, pOver, sigma) {
    const p = clamp(pOver, 1e-4, 1 - 1e-4), cut = Math.max(threshold - 0.5, 0.5);
    const mu = Math.log(line) - sigma * inv(1 - p);
    return 1 - cdf((Math.log(cut) - mu) / sigma);
  }
  function poissonRate(line, pOver) {
    const k = Math.floor(line), target = clamp(pOver, 1e-4, 1 - 1e-4);
    const gt = lam => { let term = Math.exp(-lam), c = 0; for (let i = 0; i <= k; i++) { c += term; term *= lam / (i + 1); } return 1 - c; };
    let lo = 1e-6, hi = 30;
    for (let i = 0; i < 80; i++) { const m = (lo + hi) / 2; if (gt(m) < target) lo = m; else hi = m; }
    return (lo + hi) / 2;
  }
  function poissonAtLeast(threshold, line, pOver) {
    const lam = poissonRate(line, pOver), n = Math.ceil(threshold - 1e-9);
    let term = Math.exp(-lam), c = 0;
    for (let i = 0; i < n; i++) { c += term; term *= lam / (i + 1); }
    return 1 - c;
  }
  function normalOver(line, bookLine, pOver, sd) {
    const p = clamp(pOver, 1e-4, 1 - 1e-4), mu = bookLine + sd * inv(p);
    return 1 - cdf((line - mu) / sd);
  }

  const YARDS = new Set(["player_pass_yds", "player_rush_yds", "player_reception_yds", "player_rush_reception_yds"]);
  const COUNTS = new Set(["player_receptions", "player_pass_completions", "player_pass_attempts", "player_rush_attempts"]);
  const POISSON = new Set(["player_pass_tds", "player_pass_interceptions"]);
  const TD = "player_anytime_td";
  const norm = s => String(s || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/)
    .filter(t => t && !["jr", "sr", "ii", "iii", "iv"].includes(t)).join(" ");

  // Every book's main line for this player and stat, as {point, over, under} (or {yes, no} for TD).
  function bookLines(D, player, stat) {
    const k = norm(player), out = [];
    for (const p of D.props || []) {
      if (p.stat !== stat || p.m !== stat || norm(p.player) !== k) continue;
      for (const [book, pr] of Object.entries(p.b)) out.push({book, point: p.pt, a: pr[0], b: pr[1]});
    }
    return out;
  }

  // Chance that player's stat is >= threshold ("Over X.5" = threshold X+1), from all books. Mirrors
  // src/model.py fair_probability with the Kalshi distance rule (custom lines may sit far from the book line).
  function playerAtLeast(D, player, stat, threshold) {
    const M = D.model || {}, sig = (M.sigma || {})[stat], dist = M.dist || 0.5, tdVig = M.td_vig || 0.12;
    const probs = [], pts = [];
    for (const l of bookLines(D, player, stat)) {
      if (stat === TD) {
        if (l.a != null && l.b != null) probs.push(devig(l.a, l.b));
        else if (l.a != null) probs.push(Math.min(prob(l.a) / (1 + tdVig), 0.99));
        continue;
      }
      if (l.a == null || l.b == null || !l.point) continue;
      const pOver = devig(l.a, l.b);
      if (POISSON.has(stat)) {
        if (Math.abs(threshold - (l.point + 0.5)) <= 2)
          probs.push(Math.abs(l.point - (threshold - 0.5)) < 1e-6 ? pOver : poissonAtLeast(threshold, l.point, pOver));
      } else if ((YARDS.has(stat) || COUNTS.has(stat)) && sig) {
        let near = Math.abs(threshold - l.point) / l.point <= dist;
        if (COUNTS.has(stat)) near = near || Math.abs(threshold - (l.point + 0.5)) <= 2;
        if (near) { probs.push(lognormalAtLeast(threshold, l.point, pOver, sig)); pts.push(l.point); }
      }
    }
    if (!probs.length) return null;
    const p = probs.reduce((s, x) => s + x, 0) / probs.length;
    let unc = 0.04;
    if (POISSON.has(stat)) unc = 0.03;
    else if (stat !== TD) {
      const d = Math.min(...pts.map(x => Math.abs(threshold - x) / x));
      unc = 0.02 + 0.06 * Math.min(1, d / dist);
    }
    return {p, n: probs.length, unc};
  }

  // Game lines: kind h2h -> home wins; spreads -> home covers `line` (home spread); totals -> over `line`.
  function gameChance(D, gid, kind, line) {
    const sd = D.game_sd || {}, probs = [];
    let exact = true;
    for (const p of D.lines || []) {
      if (p.g !== gid || p.m !== kind) continue;
      for (const pr of Object.values(p.b)) {
        if (pr[0] == null || pr[1] == null) continue;
        const q = devig(pr[0], pr[1]);
        if (kind === "h2h") probs.push(q);
        else if (kind === "spreads") { probs.push(normalOver(-line, -p.pt, q, sd.margin || 12.7)); exact = exact && p.pt === line; }
        else { probs.push(normalOver(line, p.pt, q, sd.total || 13.0)); exact = exact && p.pt === line; }
      }
    }
    if (!probs.length) return null;
    return {p: probs.reduce((s, x) => s + x, 0) / probs.length, n: probs.length, unc: kind === "h2h" || exact ? 0.02 : 0.03};
  }

  // One pick at any line: {kind:"player", player, stat, side:"Over"|"Under"|"Yes"|"No", line}
  // or {kind:"game", g, stat:"game_ml"|"game_spread"|"game_total", team, side, line}. Returns {hit, n, unc} or null.
  function price(D, pick) {
    if (pick.kind === "game") {
      const gm = (D.games || {})[pick.g]; if (!gm) return null;
      if (pick.stat === "game_total") {
        const r = gameChance(D, pick.g, "totals", pick.line); if (!r) return null;
        return {hit: pick.side === "Under" ? 1 - r.p : r.p, n: r.n, unc: r.unc};
      }
      const home = pick.team === gm.h;
      if (pick.stat === "game_ml") {
        const r = gameChance(D, pick.g, "h2h", null); if (!r) return null;
        return {hit: home ? r.p : 1 - r.p, n: r.n, unc: r.unc};
      }
      // spread from the picked team's side: team +3.5 = home spread +3.5 (home) or -3.5 (away)
      const homeLine = home ? pick.line : -pick.line;
      const r = gameChance(D, pick.g, "spreads", homeLine); if (!r) return null;
      return {hit: home ? r.p : 1 - r.p, n: r.n, unc: r.unc};
    }
    if (pick.stat === TD) {
      const r = playerAtLeast(D, pick.player, TD, 1); if (!r) return null;
      return {hit: pick.side === "No" ? 1 - r.p : r.p, n: r.n, unc: r.unc};
    }
    const r = playerAtLeast(D, pick.player, pick.stat, Math.floor(pick.line) + 1); if (!r) return null;
    return {hit: pick.side === "Under" ? 1 - r.p : r.p, n: r.n, unc: r.unc};
  }

  const api = {cdf, inv, prob, devig, lognormalAtLeast, poissonAtLeast, normalOver, playerAtLeast, gameChance, price, bookLines, norm};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Model = api;
})(this);
