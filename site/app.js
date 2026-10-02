"use strict";
// Prop Sheet page logic. Data: data.json (scan), analytics.json (stats), live Kalshi prices via /api/prices.
// Math lives in parlay.js (parlays), model.js (hit chance for any line), analytics.js (why-this-pick).
const $ = id => document.getElementById(id);
const P = window.Parlay, AN = window.Analytics, M = window.Model;
const store = {get:k => { try { return localStorage.getItem(k); } catch(e) { return null; } },
               set:(k, v) => { try { localStorage.setItem(k, v); } catch(e) {} }};
const jget = (k, d) => { try { return JSON.parse(store.get(k) || "null") ?? d; } catch(e) { return d; } };
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const TD = "player_anytime_td";
const BUILD = "2026-10-02 · live injuries";
const STAT = {
  player_rush_yds:      {t:"Rushing yards",   u:"rushing yards",   d:"Yards a player gains running the ball"},
  player_reception_yds: {t:"Receiving yards", u:"receiving yards", d:"Yards a player gains on catches"},
  player_pass_yds:      {t:"Passing yards",   u:"passing yards",   d:"Yards a quarterback throws for"},
  player_receptions:    {t:"Receptions",      u:"catches",         d:"How many passes a player catches"},
  player_pass_tds:      {t:"Passing TDs",     u:"passing TDs",     d:"Touchdown passes a quarterback throws"},
  player_anytime_td:    {t:"Anytime TD",      u:"touchdown",       d:"Player scores at least once, running or catching"},
  player_rush_reception_yds: {t:"Rush + rec yards", u:"rushing + receiving yards", d:"Rushing and receiving yards added together"},
  player_pass_attempts: {t:"Passing attempts", u:"pass attempts",   d:"Passes a quarterback throws, complete or not"},
  player_pass_completions: {t:"Completions",   u:"completions",     d:"Passes a quarterback completes"},
  player_pass_interceptions: {t:"Interceptions thrown", u:"interceptions", d:"Passes a quarterback throws that get picked off"},
  player_rush_attempts: {t:"Rushing attempts", u:"carries",         d:"How many times a player runs the ball"},
  game_ml:     {t:"Moneyline",  u:"", d:"Pick the team that wins the game", game:true},
  game_spread: {t:"Spread",     u:"", d:"Favorite must win by more than the spread; underdog can lose by less", game:true},
  game_total:  {t:"Game total", u:"total points", d:"Both teams' points added up, over or under the line", game:true},
};
const TEAM_ABBR = {"Arizona Cardinals":"ARI","Atlanta Falcons":"ATL","Baltimore Ravens":"BAL","Buffalo Bills":"BUF","Carolina Panthers":"CAR",
  "Chicago Bears":"CHI","Cincinnati Bengals":"CIN","Cleveland Browns":"CLE","Dallas Cowboys":"DAL","Denver Broncos":"DEN","Detroit Lions":"DET",
  "Green Bay Packers":"GB","Houston Texans":"HOU","Indianapolis Colts":"IND","Jacksonville Jaguars":"JAX","Kansas City Chiefs":"KC",
  "Las Vegas Raiders":"LV","Los Angeles Chargers":"LAC","Los Angeles Rams":"LAR","Miami Dolphins":"MIA","Minnesota Vikings":"MIN",
  "New England Patriots":"NE","New Orleans Saints":"NO","New York Giants":"NYG","New York Jets":"NYJ","Philadelphia Eagles":"PHI",
  "Pittsburgh Steelers":"PIT","San Francisco 49ers":"SF","Seattle Seahawks":"SEA","Tampa Bay Buccaneers":"TB","Tennessee Titans":"TEN",
  "Washington Commanders":"WAS"};
const NV = {...TEAM_ABBR, "Los Angeles Rams":"LA"};   // nflverse codes (final scores in analytics.json)
const SORTS = [
  {k:"best",  t:"Best bets",          d:"Good chance to hit (40%+), priced fairly or better, and backed by the stats"},
  {k:"hit",   t:"Most likely to hit", d:"Highest hit chance first (still hides “No TD” and prices shorter than −400)"},
  {k:"value", t:"Best value",         d:"Biggest gap between the price and the true odds"},
  {k:"game",  t:"By kickoff",         d:"Earliest games first, then most likely to hit"},
];
const SIDES = [
  {k:"all", t:"Overs and unders", d:"Every side"},
  {k:"over", t:"Overs only", d:"Over a line, YES on Kalshi, scores a TD. Moneylines and spreads are hidden"},
  {k:"under", t:"Unders only", d:"Under a line, NO on Kalshi. Moneylines and spreads are hidden"},
];
const PAGE = 40, MIN_DEC = 1.25;   // hide prices shorter than −400 (about 80¢ on Kalshi): they barely pay anything
const OVERSIDE = new Set(["Over", "Yes", "YES"]);
const VWORD = {agree:"✓ Stats agree", neutral:"= Stats neutral", disagree:"✕ Stats disagree", "n/a":"Stats: n/a"};
const DESK = window.matchMedia("(min-width:1180px)");

let A = null, aNote = "", openWhy = new Set();
let D = null, Q = null, liveAt = null, shown = PAGE, current = new Map(), lastTrigger = null, sheetMode = null;
const pref = {where:store.get("ps_where") || "best", prop:store.get("ps_prop") || "all", side:store.get("ps_side") || "all",
              game:store.get("ps_slate") || "all", sort:store.get("ps_sort2") || "best", legsN:Number(store.get("ps_legsN")) || 3};
let slip = jget("ps_slip", []);
let bank = jget("ps_bank", {amount:0, frac:0.25, max:0.02});
let bets = jget("ps_bets", []);

/* ---------- helpers ---------- */
const pct = p => Math.round(p * 100);
function teamShort(n){ const w = String(n || "").trim().split(/\s+/); return w[w.length - 1] || ""; }
function game(gid){ return (D && D.games && D.games[gid]) || null; }
function gameName(gid){ const g = game(gid); return g ? teamShort(g.a) + " @ " + teamShort(g.h) : ""; }
function kickText(gid){
  const g = game(gid); if (!g || !g.t) return "";
  const d = new Date(g.t);
  return d.toLocaleDateString([], {weekday:"short"}) + " " + d.toLocaleTimeString([], {hour:"numeric", minute:"2-digit"});
}
const SLATES = [
  {k:"thu", t:"Thursday Night"}, {k:"fri", t:"Friday"}, {k:"sat", t:"Saturday"},
  {k:"sun_main", t:"Sunday main slate", d:"all Sunday daytime games"},
  {k:"sun_intl", t:"Sunday morning (international)"}, {k:"sun_early", t:"Sunday early (1pm ET)"},
  {k:"sun_late", t:"Sunday late (4pm ET)"}, {k:"snf", t:"Sunday Night"}, {k:"mnf", t:"Monday Night"},
  {k:"other", t:"Other days"},
];
function etParts(iso){
  const p = {};
  for (const x of new Intl.DateTimeFormat("en-US", {timeZone:"America/New_York", weekday:"short", hour:"numeric", hourCycle:"h23"}).formatToParts(new Date(iso))) p[x.type] = x.value;
  return {day:p.weekday, hour:Number(p.hour)};
}
function slateOf(gid){
  const g = game(gid); if (!g || !g.t) return "other";
  const {day, hour} = etParts(g.t);
  if (day === "Thu") return "thu";
  if (day === "Fri") return "fri";
  if (day === "Sat") return "sat";
  if (day === "Sun") return hour < 12 ? "sun_intl" : hour < 16 ? "sun_early" : hour < 19 ? "sun_late" : "snf";
  if (day === "Mon") return "mnf";
  return "other";
}
function slateList(ids){
  const by = {};
  for (const g of ids) (by[slateOf(g)] = by[slateOf(g)] || []).push(g);
  const main = ["sun_intl", "sun_early", "sun_late"].flatMap(k => by[k] || []);
  if (main.length && ["sun_intl", "sun_early", "sun_late"].filter(k => by[k]).length > 1) by.sun_main = main;
  return SLATES.filter(s => by[s.k]).map(s => ({...s, games:by[s.k]}));
}
function inGameFilter(gid){
  if (pref.game === "all") return true;
  if (pref.game.startsWith("slate:")){
    const k = pref.game.slice(6), sl = slateOf(gid);
    return k === sl || (k === "sun_main" && ["sun_intl", "sun_early", "sun_late"].includes(sl));
  }
  return gid === pref.game;
}
function gameFilterLabel(){
  if (pref.game === "all") return "All games";
  if (pref.game.startsWith("slate:")) return (SLATES.find(s => s.k === pref.game.slice(6)) || {t:"Slate"}).t;
  return gameName(pref.game);
}
function kickMs(gid){ const g = game(gid); return g && g.t ? +new Date(g.t) : Infinity; }
function bookName(k){
  if (k === "kalshi") return "Kalshi";
  const b = D && (D.books || []).find(x => x.k === k);
  return b ? b.name : k;
}
function ago(iso){
  const m = Math.round((Date.now() - new Date(iso)) / 60000);
  if (m < 2) return "just now";
  if (m < 60) return m + " min ago";
  const h = Math.round(m / 60);
  return h < 36 ? h + " hr ago" : Math.round(h / 24) + " days ago";
}
function tier(p){ return p >= .75 ? "Very likely" : p >= .6 ? "Likely" : p >= .45 ? "Coin flip" : p >= .25 ? "Unlikely" : "Long shot"; }
// "about 6 in 10" / "about 1 in 4": the easiest way to feel a percentage
function inTen(p){
  if (!(p > 0)) return "";
  if (p >= 0.095) return "about " + Math.max(1, Math.round(p * 10)) + " in 10";
  return "about 1 in " + Math.round(1 / p);
}
function fmtPt(x){ return Number(x) % 1 ? Number(x).toFixed(1) : String(Number(x)); }
function sgnPt(x){ return (x > 0 ? "+" : x < 0 ? "−" : "") + fmtPt(Math.abs(x)); }
function money(x){ const a = Math.abs(x), sign = x < 0 ? "−" : "+"; return a < 0.995 ? sign + Math.round(a * 100) + "¢" : sign + "$" + a.toFixed(2); }
function dollars(x){ return "$" + (x >= 100 ? Math.round(x).toLocaleString() : x >= 10 ? Math.round(x) : x.toFixed(2)); }
function oneIn(p){ if (!(p > 0)) return ""; return p >= 0.5 ? "Wins about " + Math.round(p * 10) + " times in 10" : "About 1 in " + Math.round(1 / p); }

/* ---------- bankroll: suggested stake (fractional Kelly, capped) ---------- */
// Kelly: bet f = (p·d − 1)/(d − 1) of bankroll, where p is the hit chance AFTER the safety margin and d the
// decimal odds. We use a fraction of it (default 1/4) and a hard cap per bet (default 2%): full Kelly is far too
// swingy when the hit chances themselves are estimates.
function stakeFor(p, dec, parlay){
  if (!(bank.amount > 0) || !dec || dec <= 1) return null;
  const f = (p * dec - 1) / (dec - 1);
  if (f <= 0) return 0;
  return Math.min(f * bank.frac, parlay ? bank.max / 2 : bank.max) * bank.amount;
}

/* ---------- picks for the chosen platform (cached until data changes) ---------- */
let pickCache = new Map();
function bumpData(){ pickCache = new Map(); }
function mk(c){
  c.implied = 1 / c.dec;
  c.ev = c.hit * c.dec - 1;
  c.evSafe = (c.hit - c.unc) * c.dec - 1;
  const who = P.norm(c.player);
  c.key = (c.plat === "kalshi" ? "k|" + c.ticker : "b|" + c.book + "|" + who + "|" + c.m + "|" + c.pt) + "|" + c.side;
  c.prop = who + "|" + c.m + "|" + c.pt;
  c.group = c.game ? c.g + "|" + c.stat : who + "|" + c.stat;   // one pick per player & prop (per game & market)
  return c;
}
function kalshiPicks(){
  const out = [], P2 = D.params || {fee:.07, max_spread:8};
  const fee = c => P2.fee * c * (1 - c);
  for (const u of D.kalshi || []){
    const q = (Q && Q[u.ticker]) || {bid:u.bid, ask:u.ask};
    if (!q || !q.bid || !q.ask || q.ask >= 99 || q.ask - q.bid > P2.max_spread) continue;
    const fair = u.km ? (q.bid + q.ask) / 200 : u.fair;
    for (const [side, hit, cost] of [["YES", fair, q.ask / 100], ["NO", 1 - fair, 1 - q.bid / 100]]){
      if (side === "NO" && (u.stat === TD || u.stat === "game_ml")) continue;
      if (1 / (cost + fee(cost)) < MIN_DEC) continue;
      out.push(mk({plat:"kalshi", book:"kalshi", ticker:u.ticker, player:u.player, g:u.g, stat:u.stat, m:u.stat, game:!!(STAT[u.stat] || {}).game,
                   team:u.team || null, km:!!u.km, pt:u.threshold, side, hit, unc:u.km ? 0.03 : (u.unc || .03), n:u.books,
                   cents:Math.round(cost * 100), dec:1 / (cost + fee(cost))}));
    }
  }
  return out;
}
function bestOf(p, s, books){
  let best = null;
  for (const b of books){
    const a = p.b[b][s], dec = a == null ? null : P.americanToDecimal(a);
    if (dec && (!best || dec > best.dec)) best = {b, a, dec};
  }
  return best;
}
function bookPicks(where){
  const out = [];
  const add = (p, s, extra) => {
    const books = where === "best" ? Object.keys(p.b) : (p.b[where] ? [where] : []);
    const best = bestOf(p, s, books);
    if (!best || best.dec < MIN_DEC) return;
    // on a single book, point out a clearly better price elsewhere (same line)
    let alt = null;
    if (where !== "best"){ const o = bestOf(p, s, Object.keys(p.b).filter(b => b !== where)); if (o && o.dec > best.dec + 0.02) alt = o; }
    out.push(mk({plat:"book", book:best.b, g:p.g, stat:p.stat, m:p.m, unc:p.unc, n:p.n, american:best.a, dec:best.dec, alt, ...extra}));
  };
  for (const p of D.props || []){
    for (const s of [0, 1]){
      if (p.stat === TD && s === 1) continue;   // "No TD" bets hidden
      add(p, s, {player:p.player, pt:p.pt, side:p.stat === TD ? "Yes" : (s ? "Under" : "Over"), hit:s ? 1 - p.p : p.p, prop_mv:p.mv || null});
    }
  }
  for (const p of D.lines || []){
    const gm = game(p.g); if (!gm) continue;
    for (const s of [0, 1]){
      const team = p.m === "totals" ? null : (s ? gm.a : gm.h);
      add(p, s, {game:true, player:team || "Game total", team, side:p.m === "totals" ? (s ? "Under" : "Over") : team,
                 pt:p.m === "spreads" ? (s ? -p.pt : p.pt) : p.pt, hit:s ? 1 - p.p : p.p});
    }
  }
  return out;
}
function picksFor(where){
  if (!pickCache.has(where)) pickCache.set(where, where === "kalshi" ? kalshiPicks() : bookPicks(where));
  return pickCache.get(where);
}
const VBONUS = {agree:0.03, neutral:0, "n/a":-0.02, disagree:-0.06};
function bestScore(c){
  if (c.hit < 0.4) return -1 + c.hit;
  return (c.km ? -0.02 : c.evSafe) + 0.2 * (c.hit - 0.5) + VBONUS[anaFor(c).v];
}
const SORTKEY = {best:bestScore, hit:c => c.hit + c.evSafe * 1e-3, value:c => c.evSafe, game:c => c.hit};
function sideOf(c){
  if (c.stat === "game_ml" || c.stat === "game_spread") return null;
  return OVERSIDE.has(c.side) ? "over" : "under";
}
function filtered(where, sortKey){
  const key = SORTKEY[sortKey] || SORTKEY.best, best = new Map();
  for (const c of picksFor(where)){
    if (pref.prop !== "all" && c.stat !== pref.prop) continue;
    if (pref.side !== "all" && sideOf(c) !== pref.side) continue;
    if (!inGameFilter(c.g)) continue;
    const cur = best.get(c.group);
    if (!cur || key(c) > key(cur)) best.set(c.group, c);
  }
  const out = [...best.values()];
  if (sortKey === "game") out.sort((a, b) => kickMs(a.g) - kickMs(b.g) || b.hit - a.hit);
  else out.sort((a, b) => key(b) - key(a));
  return out;
}

/* ---------- text for a pick ---------- */
function lineText(c){
  const s = STAT[c.stat] || {u:c.stat};
  if (c.game){
    const tn = c.team ? esc(teamShort(c.team)) : "";
    if (c.stat === "game_ml") return "<b>" + tn + "</b> to win";
    if (c.stat === "game_spread"){
      if (c.plat === "kalshi") return (c.side === "YES" ? "<b>" + tn + " win by " : "<b>" + tn + " don't win by ") + (Math.floor(c.pt) + 1) + "+</b>";
      return "<b>" + tn + " " + (c.pt === 0 ? "pick'em" : sgnPt(c.pt)) + "</b> (spread)";
    }
    if (c.plat === "kalshi") return "<b>" + (c.side === "YES" ? "Over " : "Under ") + fmtPt(c.pt) + "</b> total points";
    return "<b>" + c.side + " " + fmtPt(c.pt) + "</b> total points";
  }
  if (c.stat === TD) return OVERSIDE.has(c.side) ? "<b>Scores a TD</b> (anytime)" : "<b>No TD</b>";
  if (c.plat === "kalshi") return c.side === "YES" ? "<b>" + fmtPt(c.pt) + "+</b> " + s.u : "<b>Under " + fmtPt(c.pt) + "</b> " + s.u;
  return "<b>" + c.side + " " + fmtPt(c.pt) + "</b> " + s.u;
}
function priceText(c){
  if (c.plat === "kalshi") return "Buy <b>" + c.side + "</b> at <b>" + c.cents + "¢</b> on Kalshi";
  return "<b>" + P.fmtAmerican(c.american) + "</b> at " + esc(bookName(c.book)) +
    (c.alt ? ' <span class="alt">· ' + esc(bookName(c.alt.b)) + " pays " + P.fmtAmerican(c.alt.a) + "</span>" : "");
}
function valueHtml(c){
  const k = c.plat === "kalshi";
  if (c.km) return '<div class="value"><span class="ic" aria-hidden="true">?</span><span class="txt">Value: n/a' +
    '<small>Only Kalshi prices this, so there\'s no outside price to compare</small></span></div>';
  if (c.evSafe >= 0)
    return '<div class="value good"><span class="ic" aria-hidden="true">✓</span><span class="txt">Good value: ' +
      (k ? "Kalshi's price is below what it's worth" : "this book pays more than it's worth") +
      '<small>On average about ' + money(c.ev) + " per $1 bet</small></span></div>";
  if (c.ev >= -0.06)
    return '<div class="value"><span class="ic" aria-hidden="true">=</span><span class="txt">Fair price: about what it\'s worth' +
      '<small>' + (k ? "after Kalshi's fee" : "the book's usual cut is built in") + '</small></span></div>';
  return '<div class="value"><span class="ic" aria-hidden="true">−</span><span class="txt">Poor value: pays less than it\'s worth' +
    '<small>On average about ' + money(c.ev) + " per $1 bet</small></span></div>";
}

/* ---------- editable form of a pick (custom lines, slip edits, bet grading) ---------- */
function edOf(c){
  if (c.game){
    const gm = game(c.g) || {};
    if (c.stat === "game_total") return {kind:"game", g:c.g, stat:c.stat, team:null, side:c.plat === "kalshi" ? (c.side === "YES" ? "Over" : "Under") : c.side, line:c.pt};
    if (c.stat === "game_ml") return {kind:"game", g:c.g, stat:c.stat, team:c.team, side:c.team, line:null};
    if (c.plat === "kalshi"){
      const other = c.team === gm.h ? gm.a : gm.h;
      return c.side === "YES" ? {kind:"game", g:c.g, stat:c.stat, team:c.team, side:c.team, line:-c.pt}
                              : {kind:"game", g:c.g, stat:c.stat, team:other, side:other, line:c.pt};
    }
    return {kind:"game", g:c.g, stat:c.stat, team:c.team, side:c.team, line:c.pt};
  }
  if (c.stat === TD) return {kind:"player", player:c.player, g:c.g, stat:TD, side:OVERSIDE.has(c.side) ? "Yes" : "No", line:null};
  return {kind:"player", player:c.player, g:c.g, stat:c.stat, side:OVERSIDE.has(c.side) ? "Over" : "Under", line:c.plat === "kalshi" ? c.pt - 0.5 : c.pt};
}
function edLabel(ed){
  const s = STAT[ed.stat] || {u:""};
  if (ed.kind === "game"){
    if (ed.stat === "game_total") return ed.side + " " + fmtPt(ed.line) + " total points";
    if (ed.stat === "game_ml") return teamShort(ed.team) + " to win";
    return teamShort(ed.team) + " " + (ed.line === 0 ? "pick'em" : sgnPt(ed.line));
  }
  if (ed.stat === TD) return ed.side === "Yes" ? "Scores a TD" : "No TD";
  return ed.side + " " + fmtPt(ed.line) + " " + s.u;
}
function lineStep(ed){
  if (ed.kind === "game") return 0.5;
  return ["player_rush_yds", "player_reception_yds", "player_pass_yds", "player_rush_reception_yds"].includes(ed.stat) ? 5 : 1;
}

/* ---------- stats layer ---------- */
function anaFor(c){
  if (c._ana !== undefined) return c._ana;
  const g = game(c.g), teams = g ? [g.a, g.h] : [];
  if (c.game){
    const sideText = lineText(c).replace(/<[^>]+>/g, "").trim();
    const fl = A && g ? AN.gameFlags(A, g.h, g.a, c.stat, c.side) : [];
    const head = "Why " + pct(c.hit) + "%: " + (c.km ? "that's Kalshi's own price (no sportsbook game lines in the last scan)." :
      (c.n > 1 ? c.n + " sportsbooks' prices" : "one sportsbook's price") + ", with the books' cut removed, give “" + sideText + "” a " + pct(c.hit) + "% chance.");
    return (c._ana = {p:null, pj:null, v:"n/a", fl, conf:AN.confidence(c.n, "n/a", fl), lineVal:c.pt, stale:false,
      whyText: head + " We don't project game results; the panel compares each offense with the other defense."});
  }
  const p = A ? AN.findPlayer(A, c.player, teams) : null;
  let stale = false;
  if (p){ const G = (A.games || {})[p.t], O = G && A.teams[G.opp]; stale = !G || !O || (teams.length && !teams.includes(O.name)); }
  // projection, with injured teammates' targets/carries handed to the players still active
  const pj = p && !stale ? AN.adjustProjection(c.stat, (p.pj || {})[c.stat], AN.injuryAdjust(A, p, c.stat)) : null;
  const lineVal = c.stat === TD ? null : c.plat === "kalshi" ? c.pt - 0.5 : c.pt;
  const overP = c.stat === TD ? (OVERSIDE.has(c.side) ? c.hit : 1 - c.hit) : null;
  const v = AN.verdict(c.stat, c.side, lineVal, pj, overP);
  const fl = p && !stale ? AN.flags(A, p, c.stat, c.side, c.prop_mv ? {mv:c.prop_mv} : null, D.updated) : [];
  const conf = AN.confidence(c.n, v, fl);
  const sideText = lineText(c).replace(/<[^>]+>/g, "").replace("(anytime)", "").trim();
  let whyText = AN.why(c, A, p, pj, v, lineVal, sideText);
  if (p && stale) whyText = whyText.replace(/Stats: n\/a \([^)]*\)\.|Stats .*$/, "") + " Stats: n/a (the stats file is for week " + A.week + ", not this game).";
  return (c._ana = {p, pj, v, fl, conf, lineVal, whyText, stale});
}
function anaHtml(c){
  const a = anaFor(c);
  let h = '<div class="why">' + esc(a.whyText) + '</div>';
  let st = "";
  if (bank.amount > 0 && !c.km){
    const s = stakeFor(c.hit - c.unc, c.dec);
    st = s > 0 ? '<span class="tag stake" title="Quarter-Kelly style stake from your bankroll settings">Bet ' + dollars(s) + '</span>'
               : '<span class="tag nobet" title="After the safety margin there is no edge at this price">No bet: no edge at this price</span>';
  }
  h += '<div class="tags"><span class="tag conf-' + a.conf.level + '" title="' + esc(a.conf.why) + '">Confidence: ' + a.conf.level + '</span>' +
    '<span class="tag ' + a.v.replace("/", "") + '">' + VWORD[a.v] + '</span>' + st + '</div>';
  if (a.v === "disagree") h += '<div class="flag sev"><span class="fi" aria-hidden="true">⚠</span><span>Stats disagree with this pick: the projection points the other way. Hit chance is still the market number.</span></div>';
  for (const f of a.fl) h += '<div class="flag' + (f.sev ? " sev" : "") + '"><span class="fi' + (f.sev ? "" : " info") + '" aria-hidden="true">' + (f.sev ? "⚠" : "i") + '</span><span>' + esc(f.text) + '</span></div>';
  const open = openWhy.has(c.key);
  h += '<button class="whybtn" type="button" data-why="' + esc(c.key) + '" aria-expanded="' + open + '" aria-controls="pn-' + esc(c.key) + '">Why this pick</button>' +
    '<div class="panel" id="pn-' + esc(c.key) + '"' + (open ? "" : " hidden") + '>' + (open ? panelHtml(c) : "") + '</div>';
  return h;
}
function term(key, text){ return '<button class="term" type="button" data-def="' + esc(key) + '">' + esc(text) + '</button>'; }
function secHtml(sct){
  if (!sct || !sct.lines || !sct.lines.length) return "";
  return '<div class="sec"><h4>' + esc(sct.title) + '</h4><ul>' + sct.lines.map(l => '<li' + (l.na ? ' class="na"' : "") + '>' +
    (l.key && AN.DEF[l.key] ? term(l.key, AN.DEF[l.key].t) + ": " : "") + esc(l.text) + '</li>').join("") + '</ul></div>';
}
function panelHtml(c){
  const a = anaFor(c);
  if (c.game){
    const gm = game(c.g);
    if (!A) return '<p class="src">Stats n/a: ' + esc(aNote || "analytics.json hasn't been generated yet.") + '</p>';
    const secs = gm ? AN.gameSections(A, gm.h, gm.a) : [];
    if (!secs.length) return '<p class="src">Stats n/a: these teams aren\'t in the stats file.</p>';
    return '<div class="proj"><div class="ph">The hit chance is the sportsbooks\' consensus. There\'s no stats projection for game results here; these are the team numbers behind the matchup.</div></div>' + secs.map(secHtml).join("");
  }
  if (!A) return '<p class="src">Stats n/a: ' + esc(aNote || "analytics.json hasn't been generated yet.") + '</p>';
  if (!a.p) return '<p class="src">Stats n/a: no nflverse play-by-play for ' + esc(c.player) + ' this season (rookie with no snaps yet, or a name we couldn\'t match).</p>';
  if (a.stale) return '<p class="src">Stats n/a for this game: the stats file covers week ' + A.week + '.</p>';
  const p = a.p;
  // 1) the short version: most important first, each marked helps / hurts this pick
  const sv = AN.shortVersion(A, p, c, a.lineVal, a.pj, a.v, D.updated);
  let h = sv.length ? '<div class="sec"><h4>The short version</h4><ul class="sv">' + sv.map(x =>
    '<li><span class="ar ' + (x.dir > 0 ? "up" : x.dir < 0 ? "dn" : "nt") + '" aria-hidden="true">' + (x.dir > 0 ? "▲" : x.dir < 0 ? "▼" : "•") + '</span>' +
    '<span>' + (x.dir > 0 ? '<span class="sr">Helps: </span>' : x.dir < 0 ? '<span class="sr">Hurts: </span>' : "") + esc(x.text) + '</span></li>').join("") +
    '</ul><p class="src" style="margin-top:6px">▲ helps this pick · ▼ hurts it · • context</p></div>' : "";
  // 2) the projection, with its math
  h += '<div class="proj" style="margin-top:12px">';
  if (a.pj){
    const isTd = c.stat === TD;
    h += '<div class="pv"><span class="pn">' + (isTd ? pct(a.pj.p) + "%" : (Math.round(a.pj.med * 10) / 10).toFixed(1)) + '</span><span class="pl">' +
      (isTd ? "stats chance to score vs " + pct(OVERSIDE.has(c.side) ? c.hit : 1 - c.hit) + "% market" : "stats projection (typical game) vs line " + fmtPt(a.lineVal)) + " · " + VWORD[a.v] + '</span></div>';
    h += '<div class="ph">' + esc(AN.projText(c.stat, a.pj)) + '</div>';
  } else h += '<div class="ph">Stats projection: n/a (not enough data to project this stat for him).</div>';
  h += "</div>";
  if (p.g < (A.consts || {}).small) h += '<div class="flag"><span class="fi info" aria-hidden="true">i</span><span>Small sample: ' + p.g + (p.g === 1 ? " game" : " games") + ' this season' + (p.prior ? "; projections lean on last season (" + p.prior.g + " games)" : "; no last-season data to lean on") + '.</span></div>';
  // 3) recent form with a game-by-game strip
  const rf = AN.recentSection(A, p, c.stat, a.lineVal, c.side);
  if (rf.log.length){
    h += '<div class="sec"><h4>Recent form</h4><div class="chips">' + rf.log.slice(-8).map(x => {
      const ok = AN.cleared(x.v, c.stat, a.lineVal, c.side);
      return '<span class="lc ' + (ok ? "hit" : "miss") + '">Wk ' + x.wk + (x.home ? " vs " : " @ ") + esc(x.opp) + ' <b>' + Math.round(x.v) + '</b> ' + (ok ? "✓" : "✕") + '</span>';
    }).join("") + '</div><ul>' + rf.lines.slice(1).map(l => '<li' + (l.na ? ' class="na"' : "") + '>' + esc(l.text) + '</li>').join("") + '</ul></div>';
  } else h += secHtml(rf);
  // 4) matchup, scheme, usage, efficiency, injuries, context
  const S = AN.sections(A, p, c.stat);
  h += secHtml(S[2]) + secHtml(AN.schemeSection(A, p, c.stat)) + secHtml(S[0]) + secHtml(S[1]) + secHtml(AN.injurySection(A, p)) + secHtml(S[3]);
  h += '<p class="src">' + p.g + (p.g === 1 ? " game" : " games") + " of " + A.season + " data (weeks " + (p.wk || []).join(", ") + "). \"Top 10%\" compares him with other players at his position who've had enough volume. Tap a dotted stat name for what it means.</p>";
  return h;
}
function showDef(key, side, trigger){
  const d = AN.DEF[key]; if (!d) return;
  openSheet("def", trigger);
  $("shTitle").textContent = d.t; $("shSub").textContent = "What this stat means";
  $("shBody").innerHTML = '<p style="margin:6px 6px 0;font-size:16px;line-height:1.5">' + esc(d.d) + '</p><p class="defdir" style="margin:12px 6px">' + esc(AN.dirNote(key, side)) + '</p>';
}

/* ---------- cards ---------- */
function avatar(c){
  if (c.game){
    const lab = c.team ? (TEAM_ABBR[c.team] || teamShort(c.team).slice(0, 3).toUpperCase()) : "O/U";
    return '<span class="av tm" aria-hidden="true">' + esc(lab) + '</span>';
  }
  const p = anaFor(c).p, ini = c.player.split(/\s+/).map(w => w[0]).filter(ch => /[A-Za-z]/.test(ch)).slice(0, 2).join("");
  const src = p && p.img ? (/^https?:/.test(p.img) ? p.img : (A.img_base || "") + p.img) : null;
  // photo when we have one (initials only if it fails to load); initials otherwise
  return src ? '<span class="av" aria-hidden="true"><img src="' + esc(src) + '" alt="" loading="lazy" decoding="async" data-ini="' + esc(ini) +
               '" onerror="this.parentNode.textContent=this.dataset.ini"></span>'
             : '<span class="av" aria-hidden="true">' + esc(ini) + '</span>';
}
function inSlip(key){ return slip.some(l => l.key === key); }
function card(c){
  const label = c.player + " " + lineText(c).replace(/<[^>]+>/g, "");
  const added = inSlip(c.key);
  const gap = c.hit - c.implied > 0.12 && !c.km
    ? '<div class="gap">⚠ Big gap between this price and the other books: check injury news first</div>' : "";
  const books = c.km ? "Kalshi's own price" : c.n + (c.n === 1 ? " book" : " books");
  return '<li class="pick">' +
    '<div><div class="who">' + avatar(c) + '<span>' + esc(c.game ? gameName(c.g) : c.player) + '</span></div><div class="line">' + lineText(c) + '</div>' +
    '<div class="price">' + priceText(c) + '</div>' +
    '<div class="game">' + esc(gameName(c.g)) + (kickText(c.g) ? " · " + esc(kickText(c.g)) : "") + '</div></div>' +
    '<div class="hit"><div class="pct">' + pct(c.hit) + '<sup>%</sup></div><div class="cap">hit chance<span class="ten">' + inTen(c.hit) + '</span></div></div>' +
    '<div class="meter" aria-hidden="true"><div class="bar"><i style="width:' + pct(c.hit) + '%"></i></div>' +
    '<span class="tier">' + tier(c.hit) + '</span></div>' +
    '<div class="foot">' + valueHtml(c) + '<div class="btns">' +
    '<button class="add" type="button" data-add="' + esc(c.key) + '" aria-pressed="' + added + '" aria-label="' +
    (added ? "Remove from parlay: " : "Add to parlay: ") + esc(label) + '">' + (added ? "✓ In slip" : "+ Parlay") + '</button>' +
    '<button class="mini" type="button" data-custom="' + esc(c.key) + '">Try another line</button></div></div>' +
    gap + anaHtml(c) + '<span class="sr">Based on ' + books + '.</span></li>';
}

/* ---------- render ---------- */
function whereLabel(k){ return k === "best" ? "Best price anywhere" : bookName(k); }
function render(){
  if (!D) return;
  $("v-where").textContent = whereLabel(pref.where);
  $("v-prop").textContent = pref.prop === "all" ? "Everything" : (STAT[pref.prop] || {t:pref.prop}).t;
  $("v-side").textContent = (SIDES.find(s => s.k === pref.side) || SIDES[0]).t;
  const notes = [];
  if (pref.prop !== "all") notes.push('Showing only <b>' + esc((STAT[pref.prop] || {t:pref.prop}).t) + '</b>');
  if (pref.side !== "all") notes.push('<b>' + esc(SIDES.find(s => s.k === pref.side).t) + '</b>');
  const fn = $("filterNote");
  fn.hidden = !notes.length;
  if (notes.length) fn.innerHTML = notes.join(" · ") + ' · <button type="button" class="linkbtn" id="showAll">Show everything</button>';
  $("v-game").textContent = gameFilterLabel();
  $("v-sort").textContent = (SORTS.find(s => s.k === pref.sort) || SORTS[0]).t;
  if (pref.where !== "kalshi") $("live").textContent = "";
  const list = filtered(pref.where, pref.sort);
  current = new Map(list.map(c => [c.key, c]));
  $("list").innerHTML = list.slice(0, shown).map(card).join("");
  $("more").hidden = list.length <= shown;
  $("more").textContent = "Show " + Math.min(PAGE, list.length - shown) + " more";
  $("count").textContent = list.length ? list.length + (list.length === 1 ? " pick" : " picks") + " · " + whereLabel(pref.where) : "";
  const e = $("empty");
  e.hidden = list.length > 0;
  if (!list.length) e.textContent = emptyText();
  renderSlipBar();
  if (DESK.matches) renderSlip();
  $("betsN").textContent = bets.filter(b => betStatus(b) === "pending").length || "";
  $("betsN").hidden = !$("betsN").textContent;
}
function emptyText(){
  if (pref.where === "kalshi")
    return (D.kalshi || []).length ? "No Kalshi contracts with a tight enough price for this filter right now."
      : "The last scan didn't match any Kalshi contracts to sportsbook lines.";
  const b = (D.books || []).find(x => x.k === pref.where);
  if (b && !b.n) return "No " + b.name + " lines in the last scan." +
    (b.paid ? " The Odds API only sends " + b.name + " on paid plans." : " Try another book or Best price anywhere.");
  if (pref.game.startsWith("slate:") && !Object.keys(D.games || {}).some(inGameFilter))
    return "No " + gameFilterLabel() + " games in the last scan. Pick another slate or All games.";
  return "Nothing matches these filters. Try Everything, both sides or All games.";
}

/* ---------- pickers (bottom sheet / dialog) ---------- */
function opt(value, title, desc, checked, dim){
  return '<button class="opt' + (dim ? " dim" : "") + '" type="button" role="radio" aria-checked="' + checked + '" data-v="' + esc(value) + '">' +
    '<span class="dot" aria-hidden="true"></span><span class="o-x"><span class="o-t">' + esc(title) + '</span>' +
    '<span class="o-d">' + esc(desc) + '</span></span></button>';
}
const PICKERS = {
  where: {t:"Where I bet", d:"See each pick at your book's own line and odds", build(){
    let h = opt("best", "Best price anywhere", "Each pick at whichever book pays the most", pref.where === "best");
    h += '<div class="opt-sec">Sportsbooks</div>';
    for (const b of D.books || []){
      const desc = b.n ? b.n + " props in the last scan" : b.paid ? "No lines: The Odds API only sends this book on paid plans" : "No lines in the last scan";
      h += opt(b.k, b.name, desc, pref.where === b.k, !b.n);
    }
    h += '<div class="opt-sec">Prediction market</div>';
    h += opt("kalshi", "Kalshi", (D.kalshi || []).length ? "Prices in cents, refreshed live every 30 seconds" : "No contracts matched in the last scan", pref.where === "kalshi", !(D.kalshi || []).length);
    return h;
  }},
  prop: {t:"Prop", d:"Which stat the bet is about", build(){
    const have = new Set([...(D.props || []).map(p => p.stat), ...(D.kalshi || []).map(u => u.stat), ...(D.lines || []).map(p => p.stat)]);
    let h = opt("all", "Everything", "Game lines and every player prop in the last scan", pref.prop === "all");
    const gl = Object.keys(STAT).filter(k => STAT[k].game && have.has(k)), pp = Object.keys(STAT).filter(k => !STAT[k].game && have.has(k));
    if (gl.length) h += '<div class="opt-sec">Game lines</div>' + gl.map(k => opt(k, STAT[k].t, STAT[k].d, pref.prop === k)).join("");
    if (pp.length) h += '<div class="opt-sec">Player props</div>' + pp.map(k => opt(k, STAT[k].t, STAT[k].d, pref.prop === k)).join("");
    return h;
  }},
  side: {t:"Over / Under", d:"Only overs, only unders, or both", build(){ return SIDES.map(s => opt(s.k, s.t, s.d, pref.side === s.k)).join(""); }},
  game: {t:"Game / slate", d:"One slate (like Sunday Night) or one game. Updates with each week's schedule", build(){
    const n = {};
    for (const p of D.props || []) n[p.g] = (n[p.g] || 0) + 1;
    const ids = Object.keys(D.games || {}).sort((a, b) => kickMs(a) - kickMs(b));
    let h = opt("all", "All games", "Every game in the last scan (" + ids.length + ")", pref.game === "all");
    const slates = slateList(ids);
    if (slates.length) h += '<div class="opt-sec">Slates</div>';
    for (const sl of slates) h += opt("slate:" + sl.k, sl.t, sl.games.map(gameName).join(", "), pref.game === "slate:" + sl.k);
    h += '<div class="opt-sec">Games</div>';
    for (const g of ids) h += opt(g, gameName(g), [SLATES.find(x => x.k === slateOf(g)).t, kickText(g), n[g] ? n[g] + " props" : ""].filter(Boolean).join(" · "), pref.game === g);
    return h;
  }},
  sort: {t:"Show first", d:"How the list is ordered", build(){ return SORTS.map(s => opt(s.k, s.t, s.d, pref.sort === s.k)).join(""); }},
};
const SHEETS = {
  slip: ["Your parlay", "Every leg has to win", () => renderSlip($("shBody"))],
  custom: ["Custom pick", "Any player or game, any line: priced the same way as the list", () => renderCustom()],
  bank: ["Bankroll", "How much to bet, so one bad week can't sink you", () => renderBank()],
  bets: ["My bets", "Saved on this device and graded from final stats", () => renderBets()],
  track: ["Track record", "How the logged picks have actually done", () => renderTrack()],
  def: ["", "", () => {}],
};
function openSheet(mode, trigger, arg){
  sheetMode = mode;
  lastTrigger = trigger || document.activeElement;
  const sh = $("sheet"), sc = $("scrim");
  if (SHEETS[mode]){ $("shTitle").textContent = SHEETS[mode][0]; $("shSub").textContent = SHEETS[mode][1]; if (mode === "custom") renderCustom(arg); else SHEETS[mode][2](); }
  else {
    const p = PICKERS[mode];
    $("shTitle").textContent = p.t; $("shSub").textContent = p.d;
    $("shBody").innerHTML = '<div role="radiogroup" aria-label="' + esc(p.t) + '">' + p.build() + "</div>";
  }
  sh.hidden = false; sc.hidden = false;
  requestAnimationFrame(() => { sh.classList.add("on"); sc.classList.add("on"); });
  $("shBody").scrollTop = 0;
  const first = sh.querySelector('[aria-checked="true"]') || sh.querySelector("input,select") || sh.querySelector(".close");
  setTimeout(() => { if (sheetMode === mode && first) first.focus({preventScroll:true}); }, 30);
  document.body.style.overflow = "hidden";
}
function closeSheet(){
  const sh = $("sheet"), sc = $("scrim");
  if (sh.hidden) return;
  sh.classList.remove("on"); sc.classList.remove("on");
  sheetMode = null;
  document.body.style.overflow = "";
  setTimeout(() => { if (!sh.classList.contains("on")){ sh.hidden = true; sc.hidden = true; } }, 240);
  if (lastTrigger && lastTrigger.focus) lastTrigger.focus({preventScroll:true});
}
$("scrim").onclick = closeSheet;
document.addEventListener("keydown", e => {
  if ($("sheet").hidden) return;
  if (e.key === "Escape") closeSheet();
  if (e.key === "Tab"){
    const f = [...$("sheet").querySelectorAll("button,input,select,[tabindex]")].filter(x => !x.disabled && x.offsetParent);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]){ e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]){ e.preventDefault(); f[0].focus(); }
  }
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && document.activeElement.classList.contains("opt")){
    const o = [...$("sheet").querySelectorAll(".opt")], i = o.indexOf(document.activeElement);
    const n = o[(i + (e.key === "ArrowDown" ? 1 : o.length - 1)) % o.length];
    if (n){ e.preventDefault(); n.focus(); }
  }
});
$("sheet").addEventListener("click", e => {
  if (e.target.closest("[data-close]")) return closeSheet();
  const o = e.target.closest(".opt");
  if (o && sheetMode && PICKERS[sheetMode]){
    pref[sheetMode] = o.dataset.v;
    if (sheetMode === "game") store.set("ps_slate", o.dataset.v.startsWith("slate:") || o.dataset.v === "all" ? o.dataset.v : "");
    else store.set("ps_" + (sheetMode === "sort" ? "sort2" : sheetMode), o.dataset.v);
    shown = PAGE;
    closeSheet(); render();
    if (pref.where === "kalshi") live();
    return;
  }
  if (sheetMode === "slip") slipClick(e);
  else if (sheetMode === "custom") customClick(e);
  else if (sheetMode === "bank") bankClick(e);
  else if (sheetMode === "bets") betsClick(e);
});
document.querySelectorAll("[data-picker]").forEach(b => b.onclick = () => openSheet(b.dataset.picker, b));
document.querySelectorAll("[data-open]").forEach(b => b.onclick = () => openSheet(b.dataset.open, b));

/* ---------- parlay slip ---------- */
function snapshot(c){
  const gm = game(c.g) || {};
  return {key:c.key, prop:c.prop, plat:c.plat, book:c.book, ticker:c.ticker, player:c.player, g:c.g, game:gameName(c.g),
          stat:c.stat, m:c.m, pt:c.pt, side:c.side, hit:c.hit, unc:c.unc, n:c.n, dec:c.plat === "book" ? c.dec : null,
          american:c.american, ed:edOf(c), kick:gm.t, a:gm.a, h:gm.h,
          line:lineText(c).replace(/<[^>]+>/g, ""), price:priceText(c).replace(/<[^>]+>/g, "")};
}
function saveSlip(){ store.set("ps_slip", JSON.stringify(slip)); }
function toggleLeg(c){
  if (inSlip(c.key)) slip = slip.filter(l => l.key !== c.key);
  else { slip = slip.filter(l => l.prop !== c.prop); slip.push(snapshot(c)); }
  saveSlip();
}
// a custom-line leg: priced with the same no-vig consensus as the list (model.js)
function repriceLeg(l){
  const r = M.price(D, l.ed);
  if (!r) return false;
  Object.assign(l, {hit:r.hit, unc:r.unc, n:r.n, custom:true, plat:"custom", line:edLabel(l.ed),
    key:"c|" + JSON.stringify(l.ed), prop:"c|" + (l.ed.player || l.ed.g) + "|" + l.ed.stat,
    dec:l.myOdds ? P.parseOdds(l.myOdds) : null,
    price:l.myOdds ? "your odds " + l.myOdds : "type your book's odds to check value"});
  return true;
}
function refreshSlip(){
  if (!D) return;
  for (const l of slip){
    if (l.custom){ if (!repriceLeg(l)) l.stale = true; continue; }
    const w = l.plat === "kalshi" ? "kalshi" : l.book;
    const c = picksFor(w).find(x => x.key === l.key);
    if (c) Object.assign(l, snapshot(c), {stale:false}); else l.stale = true;
  }
  saveSlip();
}
function renderSlipBar(){
  const n = slip.length;
  $("sbN").textContent = n;
  if (!n){ $("sbT").textContent = "Parlay slip"; $("sbS").textContent = "Tap + Parlay on picks, add a custom pick, or auto-build"; return; }
  const r = P.combine(slip);
  $("sbT").textContent = n + (n === 1 ? " leg" : "-leg parlay") + " · " + pct(r.p) + "% to hit";
  $("sbS").textContent = inTen(r.p) + " · fair odds " + P.fmtAmerican(r.fairAmerican) + (r.samePlayer + r.sameGame ? " · linked legs" : "");
}
function slipTarget(){ return DESK.matches ? $("slipBody") : $("shBody"); }
function rerenderSlip(){ if (DESK.matches || sheetMode === "slip") renderSlip(); }
function renderSlip(el){
  el = el || slipTarget();
  if (!el) return;
  const n = slip.length, r = P.combine(slip);
  let h = "";
  if (n){
    h += '<div class="combo"><div><div class="big">' + (r.p < .005 ? "<1" : pct(r.p)) + '<sup>%</sup></div></div>' +
      '<div><div class="lbl">Chance all ' + n + " legs hit</div>" + '<div class="sub">' + oneIn(r.p) + "</div></div>" +
      '<div class="meter" style="grid-column:1/-1" aria-hidden="true"><div class="bar"><i style="width:' + pct(r.p) + '%"></i></div><span class="tier">' + tier(r.p) + "</span></div></div>";
    h += '<dl class="kv"><dt>Fair odds</dt><dd>' + P.fmtAmerican(r.fairAmerican) + '</dd>' +
      '<div class="hint">What this parlay is really worth. A payout better than this is good value.</div>';
    const mult = P.multiplyOdds(slip);
    if (mult) h += '<dt>If your book just multiplies the legs</dt><dd>' + P.fmtAmerican(P.decimalToAmerican(mult)) + '</dd>' +
      '<div class="hint">' + (mult * r.p >= 1 ? "That would beat fair odds." : "That would be below fair odds.") + " Same-game parlays usually pay less than this.</div>";
    h += "</dl>";
    if (r.samePlayer || r.sameGame){
      h += '<div class="callout"><b>⚠ Linked legs.</b> ';
      if (r.samePlayer) h += r.samePlayer + (r.samePlayer === 1 ? " pair is" : " pairs are") + " on the same player or team. ";
      if (r.sameGame) h += r.sameGame + (r.sameGame === 1 ? " pair is" : " pairs are") + " from the same game. ";
      h += "Results in one game move together, so we lowered the combined chance to be safe (" + pct(r.raw) + "% → " + pct(r.p) + "%: " +
        [r.samePlayer ? "−" + Math.round((1 - P.SAME_PLAYER) * 100) + "% per same-player pair" : "", r.sameGame ? "−" + Math.round((1 - P.SAME_GAME) * 100) + "% per same-game pair" : ""].filter(Boolean).join(", ") + ").</div>";
    }
    h += '<ul class="legs">' + slip.map((l, i) => {
      const editable = l.ed && l.ed.line != null;
      return '<li><div class="l-x"><div class="l-t">' + esc(l.player) + (l.custom ? '<span class="custom-tag">custom</span>' : "") + '</div>' +
        '<div class="l-d">' + esc(l.custom ? edLabel(l.ed) : l.line) + " · " + esc(l.price) + (l.stale ? " · <b>can't price this any more</b>" : "") + '</div>' +
        '<div class="l-d">' + esc(l.game) + '</div>' +
        (editable ? '<div class="leg-ed"><button type="button" data-step="-1" data-i="' + i + '" aria-label="Lower the line">−</button>' +
          '<input class="l-line" data-i="' + i + '" inputmode="decimal" value="' + esc(fmtPt(l.ed.line)) + '" aria-label="Line for ' + esc(l.player) + '">' +
          '<button type="button" data-step="1" data-i="' + i + '" aria-label="Raise the line">+</button>' +
          '<input class="l-odds" data-i="' + i + '" placeholder="your odds" value="' + esc(l.myOdds || "") + '" aria-label="Your odds for this leg"></div>' : "") +
        '</div><div class="l-p">' + pct(l.hit) + '%</div><button class="rm" type="button" data-rm="' + i + '" aria-label="Remove ' + esc(l.player) + '">✕</button></li>';
    }).join("") + "</ul>";
    h += '<div class="field"><label for="odds">Odds your book offers for this parlay</label>' +
      '<div class="row"><input id="odds" inputmode="text" autocomplete="off" placeholder="e.g. +450" value="' + esc(store.get("ps_odds") || "") + '"></div>' +
      '<p class="verdict" id="verdict" aria-live="polite"></p></div>';
    h += '<div class="field"><label for="stakeIn">Log this bet</label><div class="row"><input id="stakeIn" inputmode="decimal" placeholder="stake, e.g. 10"></div>' +
      '<p class="fine" style="padding:6px 0 0;margin:0" id="stakeHint"></p><button class="ghost" type="button" data-logbet>Save to My bets</button></div>';
  } else {
    h += '<div class="callout info"><b>Your slip is empty.</b> Tap "+ Parlay" on any pick, add a custom pick, or let auto-build pick the legs.</div>';
  }
  h += '<p style="margin:10px 6px 0"><button class="ghost" type="button" data-custom-new>+ Custom pick (any player, any line)</button></p>';
  h += '<div class="auto"><h3>Auto-build</h3><p>Picks the highest hit chances from the list you\'re looking at (' + esc(whereLabel(pref.where)) +
    ", " + esc(pref.prop === "all" ? "everything" : STAT[pref.prop].t.toLowerCase()) + ", " + esc(gameFilterLabel().toLowerCase()) +
    "). One leg per player, no two legs from one game when it can avoid it, and it skips poor-value picks and picks the stats disagree with when there are enough others. Replaces your current slip.</p>" +
    '<div class="seg" role="radiogroup" aria-label="Number of legs">' + [2, 3, 4, 5, 6].map(k =>
      '<button type="button" role="radio" aria-checked="' + (pref.legsN === k) + '" data-legs="' + k + '">' + k + "</button>").join("") + "</div>" +
    '<button class="primary" type="button" data-auto>Build a ' + pref.legsN + "-leg parlay</button></div>";
  h += '<div class="fine"><p><b>More legs, fewer wins.</b> Three 60% legs hit together about 22% of the time, five about 8%.</p>' +
    "<p><b>High hit chance is not the same as profitable.</b> If the payout is too small for the risk, you still lose money over time.</p>" +
    (n ? '<p><button class="ghost" type="button" data-clear>Clear slip</button></p>' : "") + "</div>";
  el.innerHTML = h;
  verdict();
}
function parlayDec(){
  const typed = P.parseOdds(store.get("ps_odds") || "");
  return typed || P.multiplyOdds(slip) || (slip.length === 1 && slip[0].dec) || null;
}
function verdict(){
  const el = $("verdict"), inp = $("odds"); if (!el || !inp) return;
  const r = P.combine(slip), dec = P.parseOdds(inp.value);
  el.className = "verdict";
  if (!inp.value.trim()) el.textContent = "Type the parlay odds from your book to see if they beat fair odds (" + P.fmtAmerican(r.fairAmerican) + ").";
  else if (!dec) el.textContent = "Use American odds like +450 or −120, or decimal odds like 5.5.";
  else {
    const ev = P.evPerDollar(r.p, dec);
    if (ev >= 0){ el.className = "verdict good"; el.textContent = "✓ Beats fair odds. On average you'd win about " + money(ev).slice(1) + " per $1 bet."; }
    else { el.className = "verdict bad"; el.textContent = "✕ Below fair odds. On average you'd lose about " + money(-ev).slice(1) + " per $1 bet."; }
  }
  const hint = $("stakeHint"); if (!hint) return;
  const d = parlayDec(), pSafe = slip.reduce((p, l) => p * Math.max(0, l.hit - (l.unc || 0.03)), 1) * (r.p / (r.raw || 1));
  const s = stakeFor(pSafe, d, slip.length > 1);
  hint.textContent = !(bank.amount > 0) ? "Set your bankroll (top of the page) to get a suggested stake." :
    !d ? "Type the parlay odds above to get a suggested stake." :
    s > 0 ? "Suggested stake: " + dollars(s) + " (" + (Math.round(s / bank.amount * 1000) / 10) + "% of your bankroll)." :
    "Suggested stake: $0. After the safety margin this doesn't beat the price.";
  const si = $("stakeIn"); if (si && !si.value && s > 0) si.placeholder = "stake, e.g. " + Math.round(s);
}
function slipClick(e){
  const t = e.target.closest("button"); if (!t) return;
  if (t.dataset.rm != null){ slip.splice(Number(t.dataset.rm), 1); saveSlip(); rerenderSlip(); render(); }
  else if (t.dataset.step){
    const l = slip[Number(t.dataset.i)]; if (!l || !l.ed) return;
    l.ed.line = Math.round((l.ed.line + Number(t.dataset.step) * lineStep(l.ed)) * 2) / 2;
    if (!repriceLeg(l)) toast("No sportsbook prices to work from for that line.");
    saveSlip(); rerenderSlip(); renderSlipBar(); render();
  }
  else if (t.dataset.legs){ pref.legsN = Number(t.dataset.legs); store.set("ps_legsN", pref.legsN); rerenderSlip(); }
  else if (t.dataset.auto != null){
    const pool = filtered(pref.where, "hit"), ok = pool.filter(c => anaFor(c).v !== "disagree" && c.ev >= -0.06);
    const picks = P.autoBuild(ok.length >= pref.legsN ? ok : pool, pref.legsN);
    if (!picks.length){ toast("No picks to build from. Change the filters."); return; }
    slip = picks.map(snapshot); saveSlip(); rerenderSlip(); render();
    const tgt = slipTarget(); if (tgt) tgt.scrollTop = 0;
    toast(picks.length < pref.legsN ? "Only found " + picks.length + " legs with different players." : "Built a " + picks.length + "-leg parlay.");
  }
  else if (t.dataset.clear != null){ slip = []; saveSlip(); rerenderSlip(); render(); }
  else if (t.dataset.customNew != null){ openSheet("custom", t); }
  else if (t.dataset.logbet != null) logBet();
}
function slipInput(e){
  const t = e.target;
  if (t.id === "odds"){ store.set("ps_odds", t.value); verdict(); }
  if (t.classList.contains("l-odds")){ const l = slip[Number(t.dataset.i)]; if (l){ l.myOdds = t.value.trim(); repriceLeg(l); saveSlip(); renderSlipBar(); } }
}
function slipChange(e){
  const t = e.target;
  if (t.classList.contains("l-line")){
    const l = slip[Number(t.dataset.i)], v = Number(String(t.value).replace(/[^\d.\-]/g, ""));
    if (l && isFinite(v)){ l.ed.line = v; if (!repriceLeg(l)) toast("No sportsbook prices to work from for that line."); saveSlip(); rerenderSlip(); renderSlipBar(); render(); }
  }
  if (t.classList.contains("l-odds")) rerenderSlip();
}
for (const el of [$("shBody"), $("slipBody")]){
  el.addEventListener("input", e => { if (sheetMode === "slip" || el.id === "slipBody") slipInput(e); });
  el.addEventListener("change", e => { if (sheetMode === "slip" || el.id === "slipBody") slipChange(e); });
}
$("slipBody").addEventListener("click", slipClick);
$("slipBtn").onclick = () => openSheet("slip", $("slipBtn"));

/* ---------- custom pick ---------- */
let cust = null;
function customNames(){
  const players = new Map();
  for (const p of D.props || []) if (p.m === p.stat && !players.has(p.player)) players.set(p.player, p.g);
  const out = [...players.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([n, g]) => ({label:n, kind:"player", player:n, g}));
  for (const g of Object.keys(D.games || {})) if ((D.lines || []).some(p => p.g === g)) out.push({label:"Game: " + gameName(g), kind:"game", g});
  return out;
}
function consensusLine(kind, who, stat){
  // the point most books use (players: main market; spreads: home team's spread)
  const ps = kind === "player" ? (D.props || []).filter(p => p.stat === stat && p.m === stat && M.norm(p.player) === M.norm(who))
                               : (D.lines || []).filter(p => p.g === who && p.stat === stat);
  ps.sort((a, b) => Object.keys(b.b).length - Object.keys(a.b).length);
  return ps.length ? ps[0].pt : null;
}
function renderCustom(pre){
  const names = customNames();
  cust = pre ? {...pre} : cust || {kind:"player", player:"", stat:"", side:"Over", line:null, g:null};
  const label = cust.kind === "game" ? "Game: " + gameName(cust.g) : cust.player || "";
  $("shBody").innerHTML = '<div class="form">' +
    '<label>Player or game<input id="cName" list="cNames" autocomplete="off" placeholder="Start typing a name" value="' + esc(label) + '"></label>' +
    '<datalist id="cNames">' + names.map(n => '<option value="' + esc(n.label) + '">').join("") + '</datalist>' +
    '<div class="two"><label>Prop<select id="cStat"></select></label><label>Side<select id="cSide"></select></label></div>' +
    '<div class="two"><label>Line<input id="cLine" inputmode="decimal"></label><label><span>Your odds <span class="hint">· optional</span></span><input id="cOdds" placeholder="e.g. -110" inputmode="text"></label></div>' +
    '<div class="out" id="cOut" aria-live="polite"></div>' +
    '<button class="primary" type="button" id="cAdd">Add to slip</button>' +
    '<p class="hint">The hit chance comes from every book\'s price for this player, moved to your line with the same model the list uses. It only works where the last scan has sportsbook lines.</p></div>';
  fillCustom(!pre || pre.line == null);   // a pick opened from the list keeps its own line
  const sync = () => { readCustom(); outCustom(); };
  $("cName").addEventListener("change", () => { pickName(names); fillCustom(true); });
  $("cName").addEventListener("input", () => { if (names.some(n => n.label === $("cName").value)){ pickName(names); fillCustom(true); } });
  $("cStat").addEventListener("change", () => { cust.stat = $("cStat").value; fillCustom(true); });
  for (const id of ["cSide", "cLine", "cOdds"]) $(id).addEventListener("input", sync);
}
function pickName(names){
  const n = names.find(x => x.label === $("cName").value);
  if (!n) return;
  cust = n.kind === "game" ? {kind:"game", g:n.g, stat:"game_spread", line:null, side:null, team:null}
                           : {kind:"player", player:n.player, g:n.g, stat:"", side:"Over", line:null};
}
function fillCustom(resetLine){
  const st = $("cStat"), sd = $("cSide");
  let stats = [];
  if (cust.kind === "game") stats = ["game_ml", "game_spread", "game_total"].filter(k => (D.lines || []).some(p => p.g === cust.g && p.stat === k));
  else if (cust.player){
    stats = [...new Set((D.props || []).filter(p => p.m === p.stat && M.norm(p.player) === M.norm(cust.player)).map(p => p.stat))];
    // main yardage prop first (passing yards for a QB), anytime TD last
    const ap = A ? AN.findPlayer(A, cust.player, []) : null, order = Object.keys(STAT);
    if (ap && ap.pos === "QB") order.unshift("player_pass_yds");
    stats.sort((a, b) => (a === TD) - (b === TD) || order.indexOf(a) - order.indexOf(b));
  }
  if (!stats.includes(cust.stat)) cust.stat = stats[0] || "";
  st.innerHTML = stats.map(k => '<option value="' + k + '"' + (k === cust.stat ? " selected" : "") + '>' + esc(STAT[k].t) + '</option>').join("") || '<option value="">Pick a player or game first</option>';
  const gm = game(cust.g) || {};
  let sides = ["Over", "Under"];
  if (cust.stat === TD) sides = ["Yes", "No"];
  if (cust.stat === "game_ml" || cust.stat === "game_spread") sides = [gm.a, gm.h].filter(Boolean);
  if (!sides.includes(cust.side)) cust.side = cust.stat === "game_spread" || cust.stat === "game_ml" ? gm.h : sides[0];
  sd.innerHTML = sides.map(s => '<option' + (s === cust.side ? " selected" : "") + ' value="' + esc(s) + '">' + esc(cust.stat.startsWith("game_m") || cust.stat === "game_spread" ? teamShort(s) : s === "Yes" ? "Scores a TD" : s === "No" ? "No TD" : s) + '</option>').join("");
  const noLine = cust.stat === TD || cust.stat === "game_ml" || !cust.stat;
  $("cLine").disabled = noLine;
  if (resetLine || cust.line == null){
    let l = noLine ? null : consensusLine(cust.kind, cust.kind === "game" ? cust.g : cust.player, cust.stat);
    if (l != null && cust.stat === "game_spread" && cust.side === gm.a) l = -l;   // stored as the home team's spread
    cust.line = l;
  }
  $("cLine").value = cust.line == null ? "" : fmtPt(cust.line);
  outCustom();
}
function readCustom(){
  const gm = game(cust.g) || {}, prevSide = cust.side;
  cust.side = $("cSide").value;
  if (cust.stat === "game_spread" && prevSide && prevSide !== cust.side && cust.line != null && $("cLine").value === fmtPt(cust.line)){
    cust.line = -cust.line; $("cLine").value = fmtPt(cust.line);   // switching team flips the spread
  }
  const v = Number(String($("cLine").value).replace(/[^\d.\-]/g, ""));
  cust.line = $("cLine").disabled || $("cLine").value === "" || !isFinite(v) ? (cust.stat === TD || cust.stat === "game_ml" ? null : cust.line) : v;
  cust.odds = $("cOdds").value.trim();
  cust.team = cust.kind === "game" && cust.stat !== "game_total" ? cust.side : null;
}
function custEd(){
  if (cust.kind === "game") return {kind:"game", g:cust.g, stat:cust.stat, team:cust.stat === "game_total" ? null : cust.side, side:cust.side, line:cust.stat === "game_ml" ? null : cust.line};
  return {kind:"player", player:cust.player, g:cust.g, stat:cust.stat, side:cust.side, line:cust.stat === TD ? null : cust.line};
}
function outCustom(){
  const out = $("cOut"); if (!out || !cust) return;
  if (!cust.stat || (cust.stat !== TD && cust.stat !== "game_ml" && cust.line == null)){ out.innerHTML = '<div class="sub">Pick a player or game, a prop and a line.</div>'; return; }
  const ed = custEd(), r = M.price(D, ed);
  if (!r){
    const base = consensusLine(cust.kind, cust.kind === "game" ? cust.g : cust.player, cust.stat);
    out.innerHTML = '<div class="sub">' + (base != null && cust.kind === "player"
      ? "Can't price " + fmtPt(ed.line) + ": the books' line is " + fmtPt(base) + ", and lines more than about 50% away from it (or 2 away for catches and attempts) aren't priced. That far out the math stops being reliable."
      : "No sportsbook prices for this in the last scan, so there's nothing to price it from.") + '</div>';
    return;
  }
  const fair = P.probToAmerican(r.hit), dec = P.parseOdds(cust.odds || "");
  let h = '<div class="big">' + pct(r.hit) + '%</div><div class="sub"><b>' + esc(edLabel(ed)) + '</b> · ' + inTen(r.hit) + ' · fair odds ' + P.fmtAmerican(fair) +
    ' · from ' + r.n + (r.n === 1 ? " book" : " books") + '</div>';
  if (dec){
    const evS = (r.hit - r.unc) * dec - 1, ev = r.hit * dec - 1;
    h += '<div class="sub">' + (evS >= 0 ? "✓ Good value at " + esc(cust.odds) + ": about " + money(ev) + " per $1 on average." :
      ev >= -0.06 ? "= Fair price at " + esc(cust.odds) + "." : "✕ Poor value at " + esc(cust.odds) + ": about " + money(ev) + " per $1 on average.") + '</div>';
    const s = stakeFor(r.hit - r.unc, dec);
    if (s != null) h += '<div class="sub">' + (s > 0 ? "Suggested stake: " + dollars(s) : "Suggested stake: $0 (no edge at this price)") + '</div>';
  }
  if (cust.kind === "player" && A){
    const gm = game(cust.g) || {}, p = AN.findPlayer(A, cust.player, [gm.a, gm.h]);
    const pj = p && AN.adjustProjection(cust.stat, (p.pj || {})[cust.stat], AN.injuryAdjust(A, p, cust.stat));
    if (pj){
      const v = AN.verdict(cust.stat, cust.side, ed.line, pj, cust.stat === TD ? (cust.side === "Yes" ? r.hit : 1 - r.hit) : null);
      h += '<div class="sub">' + VWORD[v] + ": projection " + (cust.stat === TD ? pct(pj.p) + "% to score" : (Math.round(pj.med * 10) / 10) + " vs " + fmtPt(ed.line)) + '</div>';
      const L = AN.gameLog(A, p, cust.stat);
      if (L.length) h += '<div class="sub">This line would have hit in ' + L.filter(x => AN.cleared(x.v, cust.stat, ed.line, cust.side)).length + " of his " + L.length + " games this season.</div>";
    }
  }
  out.innerHTML = h;
}
function customClick(e){
  const t = e.target.closest("button"); if (!t || t.id !== "cAdd") return;
  readCustom();
  const ed = custEd(), gm = game(cust.g) || {};
  const leg = {player:ed.player || (ed.team || "Game total"), g:cust.g, game:gameName(cust.g), stat:ed.stat, side:ed.side, pt:ed.line,
               ed, myOdds:cust.odds || "", kick:gm.t, a:gm.a, h:gm.h};
  if (!repriceLeg(leg)){ toast("No sportsbook prices to work from for that."); return; }
  slip = slip.filter(l => l.prop !== leg.prop); slip.push(leg); saveSlip();
  closeSheet(); render(); toast("Added " + edLabel(ed) + " (" + pct(leg.hit) + "%).");
}
$("list").addEventListener("click", e => {
  const w = e.target.closest("[data-why]");
  if (w){
    const key = w.dataset.why, pn = document.getElementById("pn-" + key), c = current.get(key);
    const open = w.getAttribute("aria-expanded") !== "true";
    w.setAttribute("aria-expanded", open);
    if (open){ openWhy.add(key); if (c) pn.innerHTML = panelHtml(c); pn.hidden = false; }
    else { openWhy.delete(key); pn.hidden = true; }
    return;
  }
  const t = e.target.closest("[data-def]");
  if (t){ const c = current.get(t.closest(".panel").id.slice(3)); showDef(t.dataset.def, c ? c.side : "Over", t); return; }
  const cu = e.target.closest("[data-custom]");
  if (cu){ const c = current.get(cu.dataset.custom); if (c){ const ed = edOf(c); openSheet("custom", cu, {kind:ed.kind, player:ed.player, g:ed.g, stat:ed.stat, side:ed.side, line:ed.line, team:ed.team}); } return; }
  const b = e.target.closest("[data-add]"); if (!b) return;
  const c = current.get(b.dataset.add); if (!c) return;
  toggleLeg(c); render();
  const nb = $("list").querySelector('[data-add="' + CSS.escape(c.key) + '"]'); if (nb) nb.focus({preventScroll:true});
});
$("more").onclick = () => { shown += PAGE; render(); };
$("filterNote").addEventListener("click", e => {
  if (e.target.id === "showAll"){ pref.prop = "all"; pref.side = "all"; store.set("ps_prop", "all"); store.set("ps_side", "all"); shown = PAGE; render(); }
});
let toastT = null;
function toast(msg){ const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, 2600); }

/* ---------- bankroll ---------- */
function renderBank(){
  const fr = [[0.125, "1/8 Kelly", "Most cautious"], [0.25, "1/4 Kelly", "Recommended"], [0.5, "1/2 Kelly", "Aggressive"]];
  const mx = [0.01, 0.02, 0.03, 0.05];
  $("shBody").innerHTML = '<div class="form">' +
    '<label>Bankroll: money set aside only for betting<input id="bAmt" inputmode="decimal" placeholder="e.g. 500" value="' + (bank.amount || "") + '"></label>' +
    '<div><div style="font-weight:700;font-size:14px;margin-bottom:6px">How hard to press an edge</div><div class="seg" style="grid-template-columns:repeat(3,1fr)" role="radiogroup">' +
    fr.map(([v, t, d]) => '<button type="button" role="radio" aria-checked="' + (bank.frac === v) + '" data-frac="' + v + '" style="font-size:14px;line-height:1.2">' + t + '<br><small style="font-weight:600">' + d + '</small></button>').join("") + '</div></div>' +
    '<div><div style="font-weight:700;font-size:14px;margin-bottom:6px">Never more than this per bet</div><div class="seg" style="grid-template-columns:repeat(4,1fr)" role="radiogroup">' +
    mx.map(v => '<button type="button" role="radio" aria-checked="' + (bank.max === v) + '" data-max="' + v + '">' + v * 100 + '%</button>').join("") + '</div></div>' +
    '<button class="primary" type="button" id="bSave">Save</button>' +
    '<div class="fine"><p><b>How the stake is worked out.</b> Only picks that are good value after the safety margin get a stake. The size comes from the Kelly formula (bet more when the edge is bigger), cut to the fraction you choose and capped per bet. Parlays are capped at half that.</p>' +
    '<p><b>Be realistic.</b> Sportsbooks keep a cut on every bet, and most people who bet lose over time. Even a real edge means losing streaks of 5 to 10 bets. Small, steady stakes are what keep you in the game. Don\'t bet money you need for rent or bills.</p></div></div>';
}
function bankClick(e){
  const t = e.target.closest("button"); if (!t) return;
  if (t.dataset.frac){ bank.frac = Number(t.dataset.frac); renderBankKeep(); }
  else if (t.dataset.max){ bank.max = Number(t.dataset.max); renderBankKeep(); }
  else if (t.id === "bSave"){
    bank.amount = Math.max(0, Number(String($("bAmt").value).replace(/[^\d.]/g, "")) || 0);
    store.set("ps_bank", JSON.stringify(bank)); closeSheet(); render(); updateBankChip();
    toast(bank.amount ? "Bankroll set: " + dollars(bank.amount) + ". Stakes now show on value picks." : "Bankroll cleared.");
  }
}
function renderBankKeep(){ const v = $("bAmt").value; renderBank(); $("bAmt").value = v; }
function updateBankChip(){ $("bankChip").textContent = bank.amount > 0 ? "Bankroll " + dollars(bank.amount) : "Set bankroll"; }

/* ---------- my bets: saved on this device, graded from final stats ---------- */
function logBet(){
  if (!slip.length) return;
  const stake = Number(String(($("stakeIn") || {}).value || "").replace(/[^\d.]/g, ""));
  const dec = parlayDec();
  if (!(stake > 0)){ toast("Type your stake first."); return; }
  if (!dec){ toast("Type the odds your book gave you (top of the slip)."); return; }
  const r = P.combine(slip);
  bets.unshift({id:Date.now(), ts:new Date().toISOString(), stake, dec, odds:P.fmtAmerican(P.decimalToAmerican(dec)), p:r.p,
    legs:slip.map(l => ({ed:l.ed, label:(l.ed && l.ed.kind === "player" ? l.player + ": " : "") + (l.ed ? edLabel(l.ed) : l.line), hit:l.hit, kick:l.kick || (game(l.g) || {}).t,
                         a:l.a || (game(l.g) || {}).a, h:l.h || (game(l.g) || {}).h}))});
  store.set("ps_bets", JSON.stringify(bets));
  toast("Saved to My bets."); render();
}
function legResult(leg){
  if (leg.res && leg.res !== "pending") return leg.res;
  if (!A || !leg.ed || !leg.kick) return "pending";
  const a = NV[leg.a], h = NV[leg.h], kd = new Date(leg.kick);
  const res = (A.results || []).find(r => r[1] === a && r[2] === h && r[5] && Math.abs(new Date(r[5] + "T12:00:00Z") - kd) < 2.5 * 864e5);
  if (!res) return "pending";
  const ed = leg.ed, wk = res[0], as = res[3], hs = res[4];
  if (ed.kind === "game"){
    if (ed.stat === "game_total"){ const t = as + hs; return t === ed.line ? "push" : (t > ed.line) === (ed.side === "Over") ? "won" : "lost"; }
    const m = ed.team === leg.h ? hs - as : as - hs;
    if (ed.stat === "game_ml") return m === 0 ? "push" : m > 0 ? "won" : "lost";
    const x = m + ed.line; return x === 0 ? "push" : x > 0 ? "won" : "lost";
  }
  const p = AN.findPlayer(A, ed.player, [leg.a, leg.h]); if (!p) return "pending";
  const g = AN.gameLog(A, p, ed.stat).find(x => x.wk === wk);
  if (!g) return "void";
  if (ed.stat === TD) return (g.v > 0) === (ed.side === "Yes") ? "won" : "lost";
  return g.v === ed.line ? "push" : (g.v > ed.line) === (ed.side === "Over") ? "won" : "lost";
}
function betStatus(b){
  if (b.manual) return b.manual;
  const rs = b.legs.map(l => { const r = legResult(l); if (r !== "pending") l.res = r; return r; });
  if (rs.includes("lost")) return "lost";
  if (rs.includes("pending")) return "pending";
  if (rs.every(r => r === "won")) return "won";
  return "push";
}
function profit(b){ const s = betStatus(b); return s === "won" ? b.stake * (b.dec - 1) : s === "lost" ? -b.stake : 0; }
function renderBets(){
  const settled = bets.filter(b => ["won", "lost"].includes(betStatus(b)));
  const staked = settled.reduce((s, b) => s + b.stake, 0), pl = settled.reduce((s, b) => s + profit(b), 0);
  const won = settled.filter(b => betStatus(b) === "won").length, exp = settled.reduce((s, b) => s + (b.p || 0), 0);
  store.set("ps_bets", JSON.stringify(bets));
  let h = '<dl class="kv"><dt>Record</dt><dd>' + won + "–" + (settled.length - won) + '</dd>' +
    '<dt>Profit</dt><dd>' + (pl >= 0 ? "+" : "−") + dollars(Math.abs(pl)) + '</dd>' +
    '<dt>Return on money staked</dt><dd>' + (staked ? (pl / staked * 100).toFixed(1) + "%" : "–") + '</dd>' +
    '<dt>Wins vs what the hit chances predicted</dt><dd>' + won + " vs " + exp.toFixed(1) + '</dd>' +
    '<div class="hint">If you\'re winning less often than predicted over 30+ bets, slow down: the edges may not be real.</div></dl>';
  if (!bets.length) h += '<div class="callout info"><b>No bets saved yet.</b> Build a slip, type your stake and the odds you got, and tap "Save to My bets". Finished games are graded automatically from nflverse stats.</div>';
  for (const [i, b] of bets.entries()){
    const st = betStatus(b);
    h += '<div class="bet"><div class="bh"><span>' + new Date(b.ts).toLocaleDateString([], {month:"short", day:"numeric"}) + " · " + dollars(b.stake) + " at " + esc(b.odds) +
      '</span><span class="res ' + st + '">' + st + (b.manual ? " (you set)" : "") + '</span></div>' +
      b.legs.map(l => '<div class="bl">' + ({won:"✓", lost:"✕", push:"↺", void:"–"}[l.res || legResult(l)] || "…") + " " + esc(l.label) + " · " + pct(l.hit) + "%</div>").join("") +
      '<div class="acts"><button type="button" data-bi="' + i + '" data-set="won">Mark won</button><button type="button" data-bi="' + i + '" data-set="lost">Mark lost</button>' +
      '<button type="button" data-bi="' + i + '" data-set="">Auto-grade</button><button type="button" data-bi="' + i + '" data-del>Delete</button></div></div>';
  }
  if (bets.length) h += '<p><button class="ghost" type="button" data-export>Download as CSV</button></p>';
  h += '<p class="fine">Auto-grading uses the final scores and player game logs in the stats file. A player who didn\'t play shows as void; check how your book settled it. Bets live only in this browser.</p>';
  $("shBody").innerHTML = h;
}
function betsClick(e){
  const t = e.target.closest("button"); if (!t) return;
  if (t.dataset.export != null){
    const rows = [["date", "stake", "odds", "result", "profit", "legs"]].concat(bets.map(b => [b.ts, b.stake, b.odds, betStatus(b), profit(b).toFixed(2), b.legs.map(l => l.label).join(" | ")]));
    const blob = new Blob([rows.map(r => r.map(x => '"' + String(x).replace(/"/g, '""') + '"').join(",")).join("\n")], {type:"text/csv"});
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "my-bets.csv"; a.click(); return;
  }
  const i = Number(t.dataset.bi); if (!bets[i]) return;
  if (t.dataset.del != null) bets.splice(i, 1);
  else if (t.dataset.set != null){ bets[i].manual = t.dataset.set || null; if (!t.dataset.set) bets[i].legs.forEach(l => delete l.res); }
  store.set("ps_bets", JSON.stringify(bets)); renderBets(); render();
}

/* ---------- track record of the logged picks ---------- */
function renderTrack(){
  const T = A && A.track;
  if (!T || !T.all){ $("shBody").innerHTML = '<div class="callout info"><b>Nothing graded yet.</b> Every scan logs its picks; once those games finish, the weekly stats job grades them here.</div>'; return; }
  const row = (k, x) => x ? '<tr><td>' + esc(k) + '</td><td class="r">' + x.n + '</td><td class="r">' + pct(x.hits / x.n) + '%</td><td class="r">' + pct(x.expected) + '%</td></tr>' : "";
  const tbl = (title, obj, order) => '<h4 style="margin:14px 6px 2px">' + title + '</h4><table class="tr"><tr><th></th><th class="r">Picks</th><th class="r">Hit</th><th class="r">Predicted</th></tr>' +
    (order || Object.keys(obj)).map(k => row(k, obj[k])).join("") + '</table>';
  $("shBody").innerHTML = '<dl class="kv"><dt>Graded picks</dt><dd>' + T.all.n + '</dd><dt>Hit</dt><dd>' + pct(T.all.hits / T.all.n) + "% vs " + pct(T.all.expected) + '% predicted</dd>' +
    '<div class="hint">' + (T.all.n < 200 ? "Small sample: a few hundred picks are needed before these numbers mean much." : "") + '</div></dl>' +
    tbl("By stats verdict", T.verdict, ["agree", "neutral", "disagree", "n/a"]) + tbl("Calibration: do 60% picks hit 60% of the time?", T.calibration) +
    tbl("By source", T.source) + '<p class="fine">Each scan logs one side of every main sportsbook line (the side the market favors) plus Kalshi edge picks, with the hit chance at the time. Games are graded from nflverse final stats.</p>';
}

/* ---------- theme ---------- */
const THEMES = ["auto", "light", "dark"];
function applyTheme(t){
  if (t === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", t);
  $("theme").textContent = {auto:"◐ Auto", light:"☀ Light", dark:"☾ Dark"}[t];
  $("theme").setAttribute("aria-label", "Color theme: " + t + ". Tap to change.");
}
let theme = store.get("ps_theme") || "auto";
applyTheme(theme);
$("theme").onclick = () => { theme = THEMES[(THEMES.indexOf(theme) + 1) % 3]; store.set("ps_theme", theme); applyTheme(theme); };

/* ---------- data ---------- */
async function live(){
  const needs = D && (D.kalshi || []).length && (pref.where === "kalshi" || slip.some(l => l.plat === "kalshi"));
  if (!needs || document.hidden) return;
  const tickers = D.kalshi.map(u => u.ticker), out = {};
  try{
    for (let i = 0; i < tickers.length; i += 400){
      const r = await fetch("/api/prices?tickers=" + encodeURIComponent(tickers.slice(i, i + 400).join(",")), {cache:"no-store"});
      if (!r.ok) throw new Error(r.status);
      Object.assign(out, await r.json());
    }
    Q = out; liveAt = new Date(); bumpData();
    refreshSlip(); render();
    if (sheetMode === "slip") renderSlip();
    $("live").textContent = pref.where === "kalshi" ? "Kalshi prices live as of " + liveAt.toLocaleTimeString([], {hour:"numeric", minute:"2-digit", second:"2-digit"}) : "";
  }catch(e){
    if (pref.where === "kalshi") $("live").textContent = "Live Kalshi prices unavailable, showing prices from the last scan.";
  }
}
function statusLine(){
  const hrs = (Date.now() - new Date(D.updated)) / 36e5;
  let h = (D.demo ? '<span class="demo">Demo data, made up</span>' : "") + "<span>Lines from " + ago(D.updated) + "</span>";
  if (hrs > 72) h += '<span class="warnline">Old data: run a new scan</span>';
  const older = Object.entries(D.markets_updated || {}).filter(([, t]) => t && (new Date(D.updated) - new Date(t)) > 6 * 36e5);
  if (older.length) h += "<span>" + older.map(([m]) => (STAT[m] || {t:m}).t).join(", ") + " from " + ago(older[0][1]) + "</span>";
  return h;
}
async function load(){
  const demo = /[?&]demo\b/.test(location.search);
  try{
    D = await (await fetch((demo ? "demo-data.json" : "data.json") + "?t=" + Date.now(), {cache:"no-store"})).json();
  }catch(e){ $("status").textContent = "Couldn't load data.json."; return; }
  if (!D.updated || D.version !== 2){
    $("status").textContent = D.updated ? "This data is from an older version of the scan." : "No scan has run yet.";
    $("empty").hidden = false;
    $("empty").textContent = "Run the workflow from the Actions tab on GitHub to get fresh picks.";
    D = null; return;
  }
  bumpData();
  const valid = new Set(["best", "kalshi", ...(D.books || []).map(b => b.k)]);
  if (!valid.has(pref.where)) pref.where = "best";
  if (pref.game !== "all" && !pref.game.startsWith("slate:") && !game(pref.game)) pref.game = "all";
  $("status").innerHTML = statusLine();
  const s = D.stats || {};
  $("diag").textContent = (D.props || []).length + " sportsbook props and " + (D.lines || []).length + " game lines across " + Object.keys(D.games || {}).length + " games. Kalshi: " +
    (D.kalshi || []).length + " contracts shown." + (s.credits_used != null ? " The last scan used " + s.credits_used + " Odds API credits." : "");
  await loadAnalytics(demo);
  bumpData();
  refreshSlip();
  render();
  live();
}
async function loadAnalytics(demo){
  A = null; aNote = "";
  try{
    const r = await fetch((demo ? "demo-analytics.json" : "analytics.json") + "?t=" + Date.now(), {cache:"no-store"});
    if (!r.ok) throw new Error(r.status === 404 ? "analytics.json hasn't been generated yet (run the weekly analytics job)" : "HTTP " + r.status);
    A = await r.json();
    if (A.version !== 1) { aNote = "analytics.json is from a different version"; A = null; }
  }catch(e){ aNote = String(e.message || e); A = null; }
  const el = $("anaSrc");
  if (!A){ el.innerHTML = "<b>Stats layer:</b> n/a (" + esc(aNote) + ")."; return; }
  // live injury statuses (ESPN, via the Pages Function): newer than the stats file's copy
  try{
    const r = await fetch("/api/injuries", {cache:"no-store"});
    if (r.ok){ const live = await r.json(); if (live && live.teams) AN.applyLiveInjuries(A, live); }
  }catch(e){ /* keep the stats file's injury report */ }
  const src = Object.entries(A.sources || {}).map(([k, v]) => (v.ok ? "✓ " : "✕ ") + k + (v.ok ? "" : ": " + v.note)).join("<br>");
  el.innerHTML = "<b>Stats layer:</b> nflverse data through week " + (A.played || []).slice(-1)[0] + " of " + A.season + ", built " + ago(A.generated) +
    " for week " + A.week + ". Injuries: " + esc(A.inj_src || "week " + A.inj_week + " report") + ".<br>" + (A.notes || []).map(esc).join("<br>") +
    '<details style="margin-top:6px"><summary style="cursor:pointer;min-height:32px">Data sources</summary><p style="margin:6px 0 0">' + src + "</p></details>";
}
$("reload").onclick = load;
$("build").textContent = "Page version " + BUILD + ".";
DESK.addEventListener("change", () => render());
updateBankChip();
setInterval(live, 30000);
document.addEventListener("visibilitychange", live);
load();
