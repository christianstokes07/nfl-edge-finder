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

  // Yes-only price (anytime TD): same curve as src/model.py yes_only_fair (fitted to Kalshi's prices)
  function yesOnlyFair(a, curve, flat) {
    const py = prob(a);
    if (curve) return Math.min(py * clamp(curve[0] + curve[1] * py, curve[2], curve[3]), 0.99);
    return Math.min(py / (1 + (flat || 0.12)), 0.99);
  }
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
    const M = D.model || {}, sig = (M.sigma || {})[stat], dist0 = M.dist || 0.5, tdVig = M.td_vig;
    const dist = Math.max(dist0, 0.8);   // custom lines may sit far out: priced up to 80% away, flagged "rough"
    const probs = [], pts = [];
    for (const l of bookLines(D, player, stat)) {
      if (stat === TD) {
        if (l.a != null && l.b != null) probs.push(devig(l.a, l.b));
        else if (l.a != null) probs.push(yesOnlyFair(l.a, M.td_curve, tdVig));
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
    if (!probs.length) return marketAtLeast(D, player, stat, threshold);
    const p = probs.reduce((s, x) => s + x, 0) / probs.length;
    let unc = 0.04, rough = false;
    if (POISSON.has(stat)) unc = 0.03;
    else if (stat !== TD) {
      const d = Math.min(...pts.map(x => Math.abs(threshold - x) / x));
      unc = 0.02 + 0.06 * Math.min(1, d / dist0) + (d > dist0 ? 0.04 : 0);
      rough = d > dist0;
    }
    return {p, n: probs.length, unc, src: "books", rough};
  }

  // ---- no sportsbook line: Kalshi / Polymarket ladders -----------------------------------------------------
  // Their contracts are rungs ("60+ rushing yards" at 41c). Each rung says P(stat >= t) = its fair chance (the
  // sportsbook-based fair when the scan priced it, else the market's mid price). A lognormal is fitted through the
  // rungs (least squares on the probit scale), which prices any line between and a little beyond them.
  function marketRows(D, test) {
    const out = [];
    for (const [src, rows] of [["Kalshi", D.kalshi || []], ["Polymarket", D.poly || []]])
      for (const u of rows) if (test(u)) {
        const f = u.km ? (u.bid + u.ask) / 200 : u.fair;
        if (f > 0.01 && f < 0.99) out.push({t: u.threshold, p: f, team: u.team, src});
      }
    return out;
  }
  function marketAtLeast(D, player, stat, threshold) {
    const k = norm(player);
    const rungs = marketRows(D, u => u.stat === stat && norm(u.player) === k);
    if (!rungs.length) return null;
    const srcs = [...new Set(rungs.map(r => r.src))].join(" + ");
    if (stat === TD) {
      const p = rungs.reduce((s, r) => s + r.p, 0) / rungs.length;
      return {p, n: rungs.length, unc: 0.04, src: srcs};
    }
    // average rungs at the same threshold (Kalshi and Polymarket often both list one)
    const by = new Map();
    for (const r of rungs) by.set(r.t, (by.get(r.t) || []).concat(r.p));
    const pts = [...by.entries()].map(([t, ps]) => ({t, p: ps.reduce((a, b) => a + b, 0) / ps.length})).sort((a, b) => a.t - b.t);
    const exact = pts.find(x => Math.abs(x.t - threshold) < 1e-9);
    const lo = pts[0].t, hi = pts[pts.length - 1].t;
    const beyond = threshold < lo ? (lo - threshold) / lo : threshold > hi ? (threshold - hi) / hi : 0;
    if (beyond > 0.5) return null;                                  // too far outside the ladder
    const unc = 0.03 + 0.06 * Math.min(1, beyond / 0.25);
    if (exact) return {p: exact.p, n: pts.length, unc: 0.03, src: srcs};
    if (POISSON.has(stat)) {                                         // small counts: Poisson from the nearest rung
      const near = pts.reduce((a, b) => Math.abs(b.t - threshold) < Math.abs(a.t - threshold) ? b : a);
      return {p: poissonAtLeast(threshold, near.t - 0.5, near.p), n: pts.length, unc, src: srcs};
    }
    const sig0 = ((D.model || {}).sigma || {})[stat] || 0.5;
    // z = (ln(t - 0.5) - mu) / sigma where z = inv(1 - p); fit z = a + b * ln(t - 0.5)
    const xs = pts.map(x => Math.log(Math.max(x.t - 0.5, 0.5))), zs = pts.map(x => inv(clamp(1 - x.p, 1e-3, 1 - 1e-3)));
    const ws = pts.map(x => x.p * (1 - x.p));
    let sigma = sig0, mu;
    if (pts.length >= 2) {
      const W = ws.reduce((a, b) => a + b, 0), mx = xs.reduce((s, x, i) => s + ws[i] * x, 0) / W, mz = zs.reduce((s, z, i) => s + ws[i] * z, 0) / W;
      const sxx = xs.reduce((s, x, i) => s + ws[i] * (x - mx) ** 2, 0), sxz = xs.reduce((s, x, i) => s + ws[i] * (x - mx) * (zs[i] - mz), 0);
      const b = sxx > 1e-9 ? sxz / sxx : 0;
      sigma = b > 0 ? clamp(1 / b, sig0 * 0.5, sig0 * 2) : sig0;
      mu = mx - sigma * mz;
    } else mu = xs[0] - sigma * zs[0];
    const p = 1 - cdf((Math.log(Math.max(threshold - 0.5, 0.5)) - mu) / sigma);
    return {p, n: pts.length, unc, src: srcs};
  }
  // games from market ladders: estimate the expected home margin / total from every rung (normal, measured spread)
  function marketGame(D, gid, kind) {
    const gm = (D.games || {})[gid]; if (!gm) return null;
    const sd = D.game_sd || {}, msd = sd.margin || 12.7, tsd = sd.total || 13.0;
    const stat = kind === "totals" ? "game_total" : kind === "h2h" ? "game_ml" : "game_spread";
    const rows = marketRows(D, u => u.g === gid && (u.stat === stat || (kind !== "totals" && (u.stat === "game_spread" || u.stat === "game_ml"))));
    if (!rows.length) return null;
    let sw = 0, sm = 0;
    for (const r of rows) {
      const q = clamp(r.p, 0.02, 0.98), w = q * (1 - q);           // rungs near 50/50 say the most
      let m;
      if (kind === "totals") m = r.t + tsd * inv(q);
      else {
        const x = r.t == null ? 0 : r.t;                            // moneyline = wins by over 0
        // P(team margin > x) = q  ->  home margin mean
        m = r.team === gm.h ? x + msd * inv(q) : -(x + msd * inv(q));
      }
      sw += w; sm += w * m;
    }
    const mu = sm / sw;
    return {mu, sd: kind === "totals" ? tsd : msd, n: rows.length, src: [...new Set(rows.map(r => r.src))].join(" + ")};
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
    if (!probs.length) {
      const m = marketGame(D, gid, kind); if (!m) return null;
      const over = x => 1 - cdf((x - m.mu) / m.sd);
      const p = kind === "h2h" ? over(0) : kind === "spreads" ? over(-line) : over(line);
      return {p, n: m.n, unc: 0.04, src: m.src};
    }
    return {p: probs.reduce((s, x) => s + x, 0) / probs.length, n: probs.length, unc: kind === "h2h" || exact ? 0.02 : 0.03, src: "books"};
  }

  // One pick at any line: {kind:"player", player, stat, side:"Over"|"Under"|"Yes"|"No", line}
  // or {kind:"game", g, stat:"game_ml"|"game_spread"|"game_total", team, side, line}.
  // Returns {hit, push, n, unc} or null. A whole-number line can land exactly on the number: Over 3 wins at 4+,
  // loses at 2 or fewer and PUSHES (stake back) at exactly 3, so win, push and loss are priced separately;
  // a .5 line can't push.
  function price(D, pick) {
    const r = price0(D, pick);
    if (!r) return null;
    // never claim certainty: keep hit chances between 1% and 99%
    r.hit = clamp(r.hit, 0.01, 0.99);
    if (r.push) r.push = clamp(r.push, 0, 0.99 - r.hit);
    return r;
  }
  function price0(D, pick) {
    const whole = pick.line != null && Number.isInteger(pick.line);
    if (pick.kind === "game") {
      const gm = (D.games || {})[pick.g]; if (!gm) return null;
      if (pick.stat === "game_spread" && Math.abs(pick.line) > 30) return null;       // no sane spread is this big
      if (pick.stat === "game_total" && (pick.line < 20 || pick.line > 80)) return null;
      if (pick.stat === "game_total") {
        const L = pick.line;
        const o = gameChance(D, pick.g, "totals", whole ? L + 0.5 : L), u = whole ? gameChance(D, pick.g, "totals", L - 0.5) : o;
        if (!o || !u) return null;
        const over = o.p, under = 1 - u.p, push = whole ? Math.max(0, 1 - over - under) : 0;
        return {hit: pick.side === "Under" ? under : over, push, n: o.n, unc: o.unc, src: o.src};
      }
      const home = pick.team === gm.h;
      if (pick.stat === "game_ml") {
        const r = gameChance(D, pick.g, "h2h", null); if (!r) return null;
        return {hit: home ? r.p : 1 - r.p, push: 0, n: r.n, unc: r.unc, src: r.src};
      }
      // spread from the picked team's side: team +3 = home spread +3 (home) or -3 (away). Home covers spread H when
      // margin + H > 0; with a whole number H it wins at margin >= 1 - H, pushes at margin = -H.
      const H = home ? pick.line : -pick.line;
      const a = gameChance(D, pick.g, "spreads", whole ? H - 0.5 : H), b = whole ? gameChance(D, pick.g, "spreads", H + 0.5) : a;
      if (!a || !b) return null;
      const homeWin = a.p, homeLose = 1 - b.p, push = whole ? Math.max(0, 1 - homeWin - homeLose) : 0;
      return {hit: home ? homeWin : homeLose, push, n: a.n, unc: a.unc, src: a.src};
    }
    if (pick.stat === TD) {
      const r = playerAtLeast(D, pick.player, TD, 1); if (!r) return null;
      return {hit: pick.side === "No" ? 1 - r.p : r.p, push: 0, n: r.n, unc: r.unc, src: r.src};
    }
    const L = pick.line;
    if (whole) {
      const o = playerAtLeast(D, pick.player, pick.stat, L + 1), atL = playerAtLeast(D, pick.player, pick.stat, L);
      if (!o || !atL) return null;
      const over = o.p, under = 1 - atL.p, push = Math.max(0, atL.p - o.p);
      return {hit: pick.side === "Under" ? under : over, push, n: o.n, unc: Math.max(o.unc, atL.unc), src: o.src, rough: o.rough || atL.rough};
    }
    const r = playerAtLeast(D, pick.player, pick.stat, Math.floor(L) + 1); if (!r) return null;
    return {hit: pick.side === "Under" ? 1 - r.p : r.p, push: 0, n: r.n, unc: r.unc, src: r.src, rough: r.rough};
  }

  const api = {marketAtLeast, marketGame, yesOnlyFair, cdf, inv, prob, devig, lognormalAtLeast, poissonAtLeast, normalOver, playerAtLeast, gameChance, price, bookLines, norm};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Model = api;
})(this);
