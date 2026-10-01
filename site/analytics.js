// "Why this pick": turns site/analytics.json into evidence lines, a stats verdict, a confidence tag and a
// one-line explanation. Plain script, no DOM code (the page renders), and Node can load it for tests.
// Numbers only ever come from analytics.json / data.json. Missing ones say "n/a" and why.
(function (root) {
  const P = root.Parlay || (typeof require === "function" ? require("./parlay.js") : null);

  // ---- verdict rules: keep in sync with src/verdict.py ---------------------------------------------
  const YARDS_REL = 0.07, RECEPTIONS_ABS = 0.5, PASS_TDS_ABS = 0.25, TD_PROB_ABS = 0.05;
  const YARDS = new Set(["player_rush_yds", "player_reception_yds", "player_pass_yds"]);
  const OVER = new Set(["Over", "Yes", "YES"]);
  function lean(stat, line, proj, marketP) {
    if (!proj) return null;
    if (stat === "player_anytime_td") {
      if (proj.p == null || marketP == null) return null;
      const d = proj.p - marketP;
      return Math.abs(d) < TD_PROB_ABS ? "neutral" : d > 0 ? "over" : "under";
    }
    if (proj.med == null || line == null) return null;
    const d = proj.med - line;
    const big = YARDS.has(stat) ? Math.abs(d) >= YARDS_REL * Math.max(line, 1)
      : stat === "player_receptions" ? Math.abs(d) >= RECEPTIONS_ABS : Math.abs(d) >= PASS_TDS_ABS;
    return !big ? "neutral" : d > 0 ? "over" : "under";
  }
  function verdict(stat, side, line, proj, marketP) {
    const l = lean(stat, line, proj, marketP);
    if (l == null) return "n/a";
    if (l === "neutral") return "neutral";
    return (l === "over") === OVER.has(side) ? "agree" : "disagree";
  }

  // ---- formatting ----------------------------------------------------------------------------------
  const pct = v => Math.round(v * 100) + "%";
  const d1 = v => (Math.round(v * 10) / 10).toFixed(1);
  const d2 = v => v.toFixed(2);
  const sgn = (v, f) => (v > 0 ? "+" : v < 0 ? "−" : "") + f(Math.abs(v));
  const int = v => String(Math.round(v));
  function ord(n) {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  }
  // rank 1 = highest of n teams. Bottom half reads better from the other end: "29th most" -> "4th fewest".
  function rankText(rank, n, most, fewest) {
    if (!rank) return "";
    if (rank > n) return ord(rank) + " " + most;
    return rank <= Math.ceil(n / 2) ? ord(rank) + " " + most : ord(n - rank + 1) + " " + fewest;
  }
  const POSN = {WR: "wide receivers", TE: "tight ends", RB: "running backs", QB: "quarterbacks"};
  const nick = name => { const w = String(name || "").trim().split(/\s+/); return w[w.length - 1] || name; };

  // ---- glossary: every stat name on the page is a button that opens this ---------------------------
  // up: does a higher number help the OVER (or "scores a TD") side? true / false / null (context only)
  const DEF = {
    carry_share: {t: "Carry share", d: "Share of the team's rushing attempts (carries) this player gets. Volume is the biggest driver of rushing yards.", up: true},
    snap_share: {t: "Snap share", d: "Share of the offense's plays this player is on the field for.", up: true},
    carries_pg: {t: "Carries per game", d: "Average rushing attempts per game played.", up: true},
    rz_carries: {t: "Red-zone carries", d: "Carries starting inside the opponent's 20-yard line, where most touchdowns are scored.", up: true},
    gl_carries: {t: "Goal-line carries", d: "Carries starting inside the opponent's 5-yard line. The best touchdown chances.", up: true},
    rz_carry_share: {t: "Red-zone carry share", d: "Share of the team's carries inside the 20 that go to this player.", up: true},
    ypc: {t: "Yards per carry", d: "Rushing yards divided by carries. 'Adjusted' scales it for how tough the run defenses he faced were.", up: true},
    ryoe_att: {t: "Rush yards over expected", d: "Next Gen Stats: yards per carry beyond what an average back would gain given blockers and defenders at handoff. Above 0 = creating extra yards.", up: true},
    ybc: {t: "Yards before contact", d: "Average yards gained before the first defender touches the runner (PFR charting). Mostly reflects the blocking.", up: true},
    explosive_rate: {t: "Explosive-run rate", d: "Share of carries that gain 10 or more yards. Big runs swing yardage props.", up: true},
    stuff_rate: {t: "Stuff rate", d: "Share of carries stopped at or behind the line of scrimmage. Lower is better for the runner.", up: false},
    target_share: {t: "Target share", d: "Share of the team's pass attempts thrown to this player. The best single predictor of receiving volume.", up: true},
    air_share: {t: "Air-yards share", d: "Share of the team's air yards (how far passes travel past the line before the catch) aimed at this player.", up: true},
    targets_pg: {t: "Targets per game", d: "Passes thrown to this player per game played.", up: true},
    tprr_proxy: {t: "Targets per pass snap (estimate)", d: "Targets divided by the pass plays he was on the field for. Estimate: exact routes run are paywalled, so pass plays on field = team dropbacks × his snap share.", up: true},
    adot: {t: "aDOT", d: "Average depth of target: how far downfield, on average, passes to him travel. Deep targets mean bigger but less frequent gains.", up: null},
    ypt: {t: "Yards per target", d: "Receiving yards divided by targets (including incompletions). 'Adjusted' scales it for the pass defenses he faced.", up: true},
    yprr_proxy: {t: "YPRR (estimate)", d: "Yards per route run, estimated: receiving yards ÷ pass plays he was on the field for (team dropbacks × snap share). Real YPRR needs paywalled route data.", up: true},
    catch_rate: {t: "Catch rate", d: "Receptions divided by targets.", up: true},
    croe: {t: "Catch rate over expected", d: "Catches beyond what the nflverse completion model expects given throw depth, location and pressure. Above 0 = catching more than expected.", up: true},
    separation: {t: "Separation", d: "Next Gen Stats: average yards between receiver and nearest defender when the ball arrives. More = more open.", up: true},
    cushion: {t: "Cushion", d: "Next Gen Stats: average yards between receiver and nearest defender at the snap. Big cushion = defenders playing off.", up: null},
    rz_targets: {t: "Red-zone targets", d: "Targets inside the opponent's 20-yard line.", up: true},
    rz_target_share: {t: "Red-zone target share", d: "Share of the team's red-zone targets that go to this player.", up: true},
    rz_opp_share: {t: "Red-zone touch share", d: "Share of the team's carries + targets inside the 20 that go to this player.", up: true},
    gl_opp_share: {t: "Goal-line touch share", d: "Share of the team's carries + targets inside the 5.", up: true},
    td_per_touch: {t: "TD rate per touch", d: "Touchdowns divided by touches (carries + catches).", up: true},
    tds: {t: "Touchdowns", d: "Rushing + receiving touchdowns this season.", up: true},
    touches_pg: {t: "Touches per game", d: "Carries + catches per game.", up: true},
    db_share: {t: "Dropback share", d: "Share of the team's dropbacks (pass plays, including sacks and scrambles) this QB took.", up: true},
    dropbacks_pg: {t: "Dropbacks per game", d: "Pass plays per game, including sacks and scrambles.", up: true},
    epa_db: {t: "EPA per dropback", d: "Expected points added: how much each play changes the expected score, averaged over dropbacks. Above 0 = plays are helping; 0.2+ is elite.", up: true},
    cpoe: {t: "CPOE", d: "Completion % over expected: completions beyond what the nflverse model expects given throw difficulty. Above 0 = accurate.", up: true},
    ypa: {t: "Yards per attempt", d: "Passing yards per pass attempt. 'Adjusted' scales it for the pass defenses faced.", up: true},
    ttt: {t: "Time to throw", d: "Next Gen Stats: seconds from snap to throw. Quick throws avoid pressure; long ones allow deep shots but invite sacks.", up: null},
    sack_rate: {t: "Sack rate", d: "Sacks per dropback. Sacks cost yards and end plays without a pass.", up: false},
    pressure_faced: {t: "Pressure rate faced", d: "Share of dropbacks where the QB was hurried, hit or sacked (PFR charting). Pressure hurts passing.", up: false},
    pass_yds_pg: {t: "Passing yards per game", d: "Season average.", up: true},
    rush_yds_pg: {t: "Rushing yards per game", d: "Season average.", up: true},
    rec_yds_pg: {t: "Receiving yards per game", d: "Season average.", up: true},
    // defense (opponent) metrics: "up" = does a higher number help the offensive player's Over?
    d_ypc: {t: "Yards per carry allowed", d: "Rushing yards the defense gives up per carry. 'Adjusted' corrects for the offenses it faced.", up: true},
    d_run_epa: {t: "Rush EPA allowed", d: "Expected points added per run against this defense. Higher = runs work better against them.", up: true},
    d_stuff_rate: {t: "Stuff rate (defense)", d: "Share of runs this defense stops at or behind the line. Higher is bad for the runner.", up: false},
    d_explosive_run_rate: {t: "Explosive runs allowed", d: "Share of runs against them that gain 10+ yards.", up: true},
    d_ypa: {t: "Yards per attempt allowed", d: "Passing yards allowed per pass attempt.", up: true},
    d_db_epa: {t: "Pass EPA allowed", d: "Expected points added per dropback against this defense. Higher = easier to pass on.", up: true},
    d_pressure_rate: {t: "Pressure rate (defense)", d: "Share of opponent dropbacks where this defense hurried, hit or sacked the QB (PFR charting).", up: false},
    d_sack_rate: {t: "Sack rate (defense)", d: "Sacks per opponent dropback.", up: false},
    d_rz_td_pct: {t: "Red-zone TD% allowed", d: "Share of opponent drives reaching the 20 that end in a touchdown.", up: true},
    d_cov_ypt: {t: "Coverage yards per target", d: "PFR charting: yards allowed per target by this team's defenders in coverage, added up across the roster.", up: true},
    d_cov_rating: {t: "Passer rating in coverage", d: "PFR charting: passer rating on throws at this team's defenders (39.6 is a perfect-defense score, 158.3 the max).", up: true},
    d_missed_tackle_pct: {t: "Missed tackle rate", d: "PFR charting: missed tackles ÷ (tackles + missed tackles). Higher = more yards after contact.", up: true},
    dp_ypt: {t: "Yards per target allowed (by position)", d: "Yards this defense allows per target to this position (WR / TE / RB), from play-by-play.", up: true},
    dp_comp: {t: "Catch rate allowed (by position)", d: "Share of targets to this position the defense lets be caught.", up: true},
    dp_rating: {t: "Passer rating allowed (by position)", d: "NFL passer rating on targets to this position. League average is about 90–100.", up: true},
    spread: {t: "Point spread", d: "How many points the betting market expects a team to win or lose by. Favorites tend to run more late; underdogs throw more.", up: null},
    implied: {t: "Implied team total", d: "Points the market expects this team to score: half the game total, plus or minus half the spread.", up: null},
    script: {t: "Game script", d: "How the score is expected to shape play-calling. Our expected pass rate = a league fit of pass rate vs. point spread (from nflverse play-by-play) + this team's pass rate over expected.", up: null},
    proe: {t: "Pass rate over expected", d: "How much more (or less) a team passes than the nflverse model expects given down, distance, score and time.", up: null},
    pace: {t: "Pace", d: "Offensive plays per game. More plays = more chances to pile up stats.", up: true},
    weather: {t: "Weather", d: "Forecast at kickoff from Open-Meteo. Wind over 15 mph hurts passing and long kicks; heavy rain lowers passing efficiency.", up: null},
    rest: {t: "Rest days", d: "Days since each team's last game. Short weeks (Thursday games) can slow teams down.", up: null},
    team_tds: {t: "Expected team TDs", d: "Implied team total × the league's offensive touchdowns per point (from nflverse results).", up: true},
  };

  function dirNote(key, side) {
    const def = DEF[key];
    if (!def || def.up == null) return "Context only: neither higher nor lower directly helps this pick.";
    const over = OVER.has(side);
    const higherHelps = def.up === over;
    return "For this " + (over ? (side === "Over" ? "Over" : "\"yes\"") : (side === "Under" ? "Under" : "\"no\"")) + " pick, " +
      (higherHelps ? "higher is better." : "lower is better.");
  }

  // ---- finding the player ---------------------------------------------------------------------------
  function teamAbbr(A, fullName) {
    for (const [k, t] of Object.entries(A.teams || {})) if (t.name === fullName) return k;
    return null;
  }
  function findPlayer(A, name, gameTeams) {
    if (!A || !A.players) return null;
    const k = P.norm(name);
    const hits = A.players.filter(p => P.norm(p.n) === k);
    if (hits.length <= 1) return hits[0] || null;
    const abbrs = (gameTeams || []).map(t => teamAbbr(A, t)).filter(Boolean);
    return hits.find(p => abbrs.includes(p.t)) || hits[0];
  }
  function metrics(A, p) {
    const out = {}, keys = (A.mk || {})[p.pos] || [];
    keys.forEach((k, i) => { if (p.m[i]) out[k] = {v: p.m[i][0], pct: p.m[i][1]}; });
    return out;
  }

  // ---- evidence lines ---------------------------------------------------------------------------------
  const NA_REASON = {
    ryoe_att: "Next Gen Stats only lists runners with enough carries", separation: "Next Gen Stats only lists receivers with enough targets",
    cushion: "Next Gen Stats only lists receivers with enough targets", ttt: "Next Gen Stats only lists QBs with enough attempts",
    ybc: "not in PFR charting yet", pressure_faced: "not in PFR charting yet",
    yprr_proxy: "not found in nflverse snap counts", tprr_proxy: "not found in nflverse snap counts", snap_share: "not found in nflverse snap counts",
  };
  function pctText(m, pos) {
    return m.pct == null ? "" : " (" + ord(m.pct) + " percentile among " + POSN[pos] + ")";
  }
  function line(key, text, na) { return {key, text, na: !!na}; }

  function playerLine(key, M, p, A) {
    const m = M[key], who = nick(p.n), team = nick((A.teams[p.t] || {}).name || p.t);
    if (!m) return NA_REASON[key] && ((A.mk || {})[p.pos] || []).includes(key) ? line(key, "n/a (" + NA_REASON[key] + ")", true) : null;
    const v = m.v, pt = pctText(m, p.pos);
    const adj = (k) => M[k] && d1(M[k].v) !== d1(v) ? " (" + d1(M[k].v) + " adjusted for defenses faced)" : "";
    switch (key) {
      case "carry_share": return line(key, who + " gets " + pct(v) + " of the " + team + "' carries" + pt);
      case "snap_share": return line(key, "On the field for " + pct(v) + " of offensive snaps" + pt);
      case "carries_pg": return line(key, d1(v) + " carries per game" + pt);
      case "rz_carries": return line(key, int(v) + " carries inside the 20 this season" + (M.rz_carry_share ? ", " + pct(M.rz_carry_share.v) + " of the team's" : "") + pt);
      case "gl_carries": return line(key, int(v) + " carries inside the 5 this season" + pt);
      case "ypc": return line(key, d1(v) + " yards per carry" + adj("ypc_adj") + pt);
      case "ryoe_att": return line(key, sgn(v, d1) + " rushing yards over expected per carry" + pt);
      case "ybc": return line(key, d1(v) + " yards before contact per carry" + pt);
      case "explosive_rate": return line(key, pct(v) + " of his carries go 10+ yards" + pt);
      case "stuff_rate": return line(key, "Stopped at or behind the line on " + pct(v) + " of carries" + pt);
      case "target_share": return line(key, who + " gets " + pct(v) + " of the " + team + "' targets" + pt);
      case "air_share": return line(key, pct(v) + " of the team's air yards" + pt);
      case "targets_pg": return line(key, d1(v) + " targets per game" + pt);
      case "tprr_proxy": return line(key, d2(v) + " targets per pass snap (estimate)" + pt);
      case "adot": return line(key, "Average target " + d1(v) + " yards downfield" + pt);
      case "ypt": return line(key, d1(v) + " yards per target" + adj("ypt_adj") + pt);
      case "yprr_proxy": return line(key, d2(v) + " yards per pass snap (YPRR estimate)" + pt);
      case "catch_rate": return line(key, "Catches " + pct(v) + " of his targets" + pt);
      case "croe": return line(key, sgn(v * 100, d1) + " points of catch rate over expected" + pt);
      case "separation": return line(key, d1(v) + " yards of separation when the ball arrives" + pt);
      case "cushion": return line(key, d1(v) + " yards of cushion at the snap" + pt);
      case "rz_targets": return line(key, int(v) + " targets inside the 20 this season" + (M.rz_target_share ? ", " + pct(M.rz_target_share.v) + " of the team's" : "") + pt);
      case "rz_opp_share": return line(key, pct(v) + " of the team's red-zone carries + targets" + pt);
      case "gl_opp_share": return line(key, pct(v) + " of the team's carries + targets inside the 5" + pt);
      case "td_per_touch": return line(key, "Scores on " + pct(v) + " of his touches" + pt);
      case "tds": return line(key, int(v) + " rushing + receiving TDs in " + p.g + (p.g === 1 ? " game" : " games") + pt);
      case "touches_pg": return line(key, d1(v) + " touches (carries + catches) per game" + pt);
      case "db_share": return line(key, "Took " + pct(v) + " of the team's dropbacks" + pt);
      case "dropbacks_pg": return line(key, d1(v) + " dropbacks per game" + pt);
      case "epa_db": return line(key, sgn(v, d2) + " EPA per dropback" + pt);
      case "cpoe": return line(key, sgn(v, d1) + " points of completion % over expected" + pt);
      case "ypa": return line(key, d1(v) + " yards per attempt" + adj("ypa_adj") + pt);
      case "ttt": return line(key, d2(v) + " seconds to throw on average" + pt);
      case "sack_rate": return line(key, "Sacked on " + pct(v) + " of dropbacks" + pt);
      case "pressure_faced": return line(key, "Pressured on " + pct(v) + " of dropbacks" + pt);
      case "pass_yds_pg": return line(key, d1(v) + " passing yards per game" + pt);
      case "rush_yds_pg": return line(key, d1(v) + " rushing yards per game" + pt);
      case "rec_yds_pg": return line(key, d1(v) + " receiving yards per game" + pt);
    }
    return null;
  }

  const MOST = {up: "most", down: "fewest"};
  function defLine(key, T, opp, nTeams) {
    const x = T.d[key];
    const k = "d_" + key;
    if (!x || x[0] == null) return line(k, "n/a (no " + opp + " data yet)", true);
    const [v, adj, rank] = x;
    const rk = rank ? ", " + rankText(rank, nTeams, "most", "fewest") + " in the NFL" : "";
    const rkHigh = rank ? ", " + rankText(rank, nTeams, "highest", "lowest") + " in the NFL" : "";
    const f = key === "run_epa" || key === "db_epa" ? x => sgn(x, d2) : key.includes("rate") || key === "comp_pct" ? pct : d1;
    const a = adj != null && f(adj) !== f(v) ? " (" + f(adj) + " adjusted for offenses faced)" : "";
    switch (key) {
      case "ypc": return line(k, opp + " allow " + d1(v) + " yards per carry" + a + rk);
      case "run_epa": return line(k, opp + " allow " + sgn(v, d2) + " EPA per run" + a + rk);
      case "stuff_rate": return line(k, opp + " stop " + pct(v) + " of runs at or behind the line" + a + rkHigh);
      case "explosive_run_rate": return line(k, opp + " allow 10+ yard runs on " + pct(v) + " of carries" + a + rk);
      case "ypa": return line(k, opp + " allow " + d1(v) + " yards per pass attempt" + a + rk);
      case "db_epa": return line(k, opp + " allow " + sgn(v, d2) + " EPA per dropback" + a + rk);
      case "pressure_rate": return line(k, opp + " pressure the QB on " + pct(v) + " of dropbacks" + rkHigh);
      case "sack_rate": return line(k, opp + " sack the QB on " + pct(v) + " of dropbacks" + a + rkHigh);
      case "rz_td_pct": return line(k, opp + " allow TDs on " + pct(v) + " of red-zone trips" + rk + (T.d.rz_drives ? " (" + T.d.rz_drives + " trips)" : ""));
      case "cov_ypt": return line(k, opp + " defenders allow " + d1(v) + " yards per target in coverage" + rk);
      case "cov_rating": return line(k, opp + " defenders allow a " + d1(v) + " passer rating in coverage" + rk);
      case "missed_tackle_pct": return line(k, opp + " miss " + pct(v) + " of tackle attempts" + rkHigh);
    }
    return null;
  }
  function posLine(kind, T, opp, pos, nTeams) {
    const x = (T.dp[pos] || {})[kind], k = "dp_" + kind, n = (T.dp[pos] || {}).n;
    if (!x || x[0] == null) return line(k, "n/a (no targets to " + POSN[pos] + " against " + opp + " yet)", true);
    const [v, adj, rank] = x, rk = rank ? ", " + rankText(rank, nTeams, kind === "rating" ? "highest" : "most", kind === "rating" ? "lowest" : "fewest") : "", nn = n ? " (" + int(n) + " targets)" : "";
    if (kind === "ypt") return line(k, opp + " allow " + d1(v) + " yards per target to " + POSN[pos] + (adj != null && d1(adj) !== d1(v) ? " (" + d1(adj) + " adjusted)" : "") + rk + nn);
    if (kind === "comp") return line(k, opp + " let " + pct(v) + " of targets to " + POSN[pos] + " be caught" + rk + nn);
    return line(k, opp + " allow a " + d1(v) + " passer rating on throws to " + POSN[pos] + rk + nn);
  }

  function contextLines(A, p, stat) {
    const G = (A.games || {})[p.t], T = A.teams[p.t] || {}, out = [];
    const team = nick(T.name || p.t);
    if (!G) return [line("spread", "n/a (no game for the " + team + " in week " + A.week + ")", true)];
    if (G.spread == null) out.push(line("spread", "n/a (not posted yet)", true));
    else out.push(line("implied", team + (G.spread < 0 ? " are " + d1(-G.spread) + "-point favorites" : G.spread > 0 ? " are " + d1(G.spread) + "-point underdogs" : " are in a pick'em") +
      "; expected to score " + d1(G.implied) + " points (game total " + d1(G.total) + ")"));
    if (G.vol && (stat !== "player_anytime_td")) {
      const v = G.vol;
      out.push(line("script", "Expected pass rate " + pct(v.pass_rate) + (v.script_pass_rate != null ? " (" + pct(v.script_pass_rate) + " league fit for this spread, adjusted by the " + team + "' tendencies)" : "") +
        (stat === "player_rush_yds" ? ": about " + d1(v.carries) + " team carries" : ": about " + d1(v.attempts) + " team pass attempts")));
    }
    if (stat === "player_anytime_td" && G.tds != null) out.push(line("team_tds", "Expected " + d2(G.tds) + " offensive TDs for the " + team + " (" + d1(G.implied) + " implied points × " + d2(A.tdpp) + " TDs per point)"));
    const pace = (T.o || {}).plays_pg;
    if (pace && pace[0] != null) out.push(line("pace", "The " + team + " run " + d1(pace[0]) + " plays per game, " + rankText(pace[1], (A.nteams || 32), "most", "fewest")));
    out.push(weatherLine(G));
    if (G.rest != null && G.opp_rest != null && G.rest !== G.opp_rest) out.push(line("rest", G.rest + " days of rest vs " + G.opp_rest + " for the opponent"));
    return out.slice(0, 5);
  }
  function weatherLine(G) {
    if (G.roof === "indoors") return line("weather", "Indoors (" + (G.stadium || "dome") + "): weather won't matter");
    if (!G.wx) return line("weather", "n/a (" + (G.wx_note || "no forecast") + ")", true);
    const w = G.wx;
    return line("weather", (G.roof === "retractable" ? "Retractable roof, may be closed. " : "") + "Kickoff forecast " + int(w.temp) + "°F, wind " + int(w.wind) + " mph, " + int(w.precip) + "% chance of rain");
  }

  const PLAN = {
    player_rush_yds: {u: ["carry_share", "snap_share", "carries_pg", "rz_carries"], e: ["ypc", "ryoe_att", "ybc", "explosive_rate", "stuff_rate"],
      d: ["ypc", "run_epa", "stuff_rate", "explosive_run_rate", "missed_tackle_pct"]},
    player_reception_yds: {u: ["target_share", "air_share", "tprr_proxy", "snap_share", "targets_pg"], e: ["yprr_proxy", "ypt", "adot", "croe", "separation"],
      pos: ["ypt", "comp", "rating"], d: ["db_epa", "pressure_rate", "cov_ypt"]},
    player_receptions: {u: ["target_share", "targets_pg", "tprr_proxy", "snap_share"], e: ["catch_rate", "croe", "adot", "separation"],
      pos: ["comp", "ypt", "rating"], d: ["db_epa", "cov_ypt"]},
    player_pass_yds: {u: ["db_share", "dropbacks_pg", "pass_yds_pg"], e: ["epa_db", "cpoe", "ypa", "ttt", "pressure_faced"],
      d: ["db_epa", "ypa", "pressure_rate", "sack_rate", "cov_rating"]},
    player_pass_tds: {u: ["db_share", "dropbacks_pg"], e: ["epa_db", "cpoe", "ypa", "sack_rate"], d: ["db_epa", "rz_td_pct", "pressure_rate", "cov_rating"]},
    player_anytime_td: {u: ["rz_opp_share", "gl_opp_share", "rz_carries", "rz_targets", "touches_pg"], e: ["td_per_touch", "tds", "ypc", "ypt"],
      d: ["rz_td_pct", "ypc", "db_epa"]},
  };

  function sections(A, p, stat) {
    const plan = PLAN[stat];
    if (!plan) return [];
    const M = metrics(A, p), G = (A.games || {})[p.t] || {}, oppT = A.teams[G.opp] || null, opp = oppT ? nick(oppT.name) : null;
    const pick = (keys, fn) => keys.map(fn).filter(Boolean).slice(0, 5);
    const usage = pick(plan.u, k => playerLine(k, M, p, A));
    const eff = pick(plan.e, k => playerLine(k, M, p, A));
    let match = [];
    if (oppT) {
      const pos = p.pos === "QB" ? null : p.pos;
      const nT = (A.nteams || 32);
      match = [...(plan.pos && pos ? plan.pos.map(k => posLine(k, oppT, opp, pos, nT)) : []), ...plan.d.map(k => defLine(k, oppT, opp, nT))].filter(Boolean).slice(0, 4);
      if (p.pos === "QB" && M.pressure_faced && oppT.d.pressure_rate && oppT.d.pressure_rate[0] != null)
        match.push(line("d_pressure_rate", nick(p.n) + " is pressured on " + pct(M.pressure_faced.v) + " of dropbacks; " + opp + " generate pressure on " + pct(oppT.d.pressure_rate[0])));
      else if (plan.pos) match.push(line(null, "Cornerback-vs-receiver matchups (who covers whom) are paywalled, so these are team-level numbers.", true));
      match = match.slice(0, 5);
    } else match = [line(null, "Matchup: n/a (no opponent this week)", true)];
    return [
      {title: "Usage", lines: usage}, {title: "Efficiency", lines: eff},
      {title: "Matchup" + (opp ? " vs " + opp : ""), lines: match}, {title: "Game context", lines: contextLines(A, p, stat)},
    ];
  }

  // ---- projection text, flags, confidence, one-line "why" -------------------------------------------
  const UNIT = {player_rush_yds: "rushing yards", player_reception_yds: "receiving yards", player_pass_yds: "passing yards",
                player_receptions: "catches", player_pass_tds: "passing TDs"};
  function projText(stat, pj) {
    if (!pj) return null;
    const i = pj.in || {};
    if (stat === "player_anytime_td")
      return "Expected TDs " + d2(i.lam) + " = " + d2(i.team_tds) + " team TDs × (" + pct(i.rush_frac) + " rushing × " + pct(i.rush_share) +
        " of his rushing chances + " + pct(1 - i.rush_frac) + " receiving × " + pct(i.rec_share) + " of his receiving chances) → " + pct(pj.p) + " to score at least once.";
    const typical = " A typical game is " + pct(i.mf || 1) + " of the average (big games pull the average up), so " + d1(pj.med) + ".";
    if (stat === "player_rush_yds") return d1(i.carries) + " carries (" + pct(i.share) + " of " + d1(i.team_carries) + " team carries) × " + d1(i.ypc) + " yards per carry × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_reception_yds") return d1(i.targets) + " targets (" + pct(i.share) + " of " + d1(i.team_att) + " team attempts) × " + d1(i.ypt) + " yards per target × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_receptions") return d1(i.targets) + " targets × " + pct(i.catch) + " catch rate × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_pass_yds") return d1(i.attempts) + " attempts × " + d1(i.ypa) + " yards per attempt × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_pass_tds") return d1(i.attempts) + " attempts × " + pct(i.td_rate) + " TD rate × " + d2(i.opp) + " defense factor = " + d2(pj.mean) + ".";
    return null;
  }

  function flags(A, p, stat, side, prop) {
    const out = [];
    if (!A || !p) return out;
    if (p.inj) {
      const [status, injury, practice] = p.inj;
      if (status) out.push({k: "injury", sev: status === "Questionable" ? 1 : 2, text: nick(p.n) + " is listed " + status + (injury ? " (" + injury + ")" : "") + " on the week " + A.inj_week + " injury report"});
      else if (practice && /Did Not/i.test(practice)) out.push({k: "injury", sev: 1, text: nick(p.n) + " did not practice" + (injury ? " (" + injury + ")" : "") + " per the week " + A.inj_week + " report"});
    }
    const T = A.teams[p.t] || {}, G = (A.games || {})[p.t] || {}, O = A.teams[G.opp] || {};
    for (const x of T.out || []) {
      if (x.side !== "off" || P.norm(x.n) === P.norm(p.n)) continue;
      out.push({k: "teammate", sev: 0, text: "Teammate " + x.pos + " " + x.n + " is " + x.s + (x.i ? " (" + x.i + ")" : "") + ": had " + x.role});
    }
    const defOut = (O.out || []).filter(x => x.side === "def");
    if (defOut.length) out.push({k: "defense", sev: 0, text: nick(O.name) + " defense missing " + defOut.map(x => x.pos + " " + x.n + " (" + x.s + ")").join(", ")});
    if (G.wx && G.roof !== "indoors" && G.wx.wind > 15 && /pass|reception/.test(stat))
      out.push({k: "weather", sev: 1, text: "Wind " + int(G.wx.wind) + " mph forecast: wind over 15 mph hurts passing and long kicks"});
    if (prop && prop.mv) {
      const [from, to] = prop.mv;
      const big = stat === "player_anytime_td" ? Math.abs(to - from) >= 0.05
        : stat === "player_receptions" || stat === "player_pass_tds" ? Math.abs(to - from) >= 1 : Math.abs(to - from) >= Math.max(3, 0.05 * from);
      if (big) {
        const against = OVER.has(side) ? to > from : to < from;
        out.push({k: "move", sev: against ? 1 : 0, text: stat === "player_anytime_td"
          ? "Market TD chance moved from " + pct(from) + " to " + pct(to) + " since the previous scan"
          : "Line moved from " + fmt(from) + " to " + fmt(to) + " since the previous scan" + (against ? " (against this pick)" : "")});
      }
    }
    return out;
  }
  const fmt = x => (Number(x) % 1 ? Number(x).toFixed(1) : String(Number(x)));

  const LEVELS = ["Low", "Medium", "High"];
  function confidence(books, v, fl) {
    let i = books >= 3 ? 1 : 0;
    const why = [books >= 3 ? books + " books agree on the price" : "only " + books + " book" + (books === 1 ? "" : "s") + " priced it"];
    if (v === "agree") { i++; why.push("stats agree"); }
    if (v === "disagree") { i--; why.push("stats disagree"); }
    if ((fl || []).some(f => f.sev >= 1)) { i--; why.push("warning below"); }
    return {level: LEVELS[Math.max(0, Math.min(2, i))], why: why.join(", ")};
  }

  function why(c, A, p, pj, v, lineVal, sideText) {
    const head = "Why " + Math.round(c.hit * 100) + "%: " + (c.n > 1 ? c.n + " sportsbooks' prices" : "one sportsbook's price") +
      ", with the books' cut removed, give \u201c" + sideText + "\u201d a " + Math.round(c.hit * 100) + "% chance.";
    if (!A) return head + " Stats: n/a (analytics haven't loaded).";
    if (!p) return head + " Stats: n/a (no nflverse stats for this player this season).";
    if (!pj) return head + " Stats: n/a (not enough data to project this stat).";
    const M = metrics(A, p), G = (A.games || {})[p.t] || {}, O = A.teams[G.opp];
    const opp = O ? nick(O.name) : "the opponent", nT = (A.nteams || 32);
    const rk = r => rankText(r, nT, "most", "fewest");
    let driver = "";
    if (c.stat === "player_rush_yds" && M.carry_share) driver = pct(M.carry_share.v) + " carry share" + (O && O.d.ypc && O.d.ypc[2] ? "; " + opp + " allow " + d1(O.d.ypc[0]) + " yards per carry, " + rk(O.d.ypc[2]) : "");
    else if ((c.stat === "player_reception_yds" || c.stat === "player_receptions") && M.target_share) {
      const dp = O && (O.dp[p.pos] || {}).ypt;
      driver = pct(M.target_share.v) + " target share" + (dp && dp[0] != null ? "; " + opp + " allow " + d1(dp[0]) + " yards per target to " + POSN[p.pos] + ", " + rk(dp[2]) : "");
    } else if (c.stat === "player_pass_yds" && M.ypa) driver = d1(M.ypa.v) + " yards per attempt" + (O && O.d.ypa && O.d.ypa[2] ? "; " + opp + " allow " + d1(O.d.ypa[0]) + " yards per attempt, " + rk(O.d.ypa[2]) : "");
    else if (c.stat === "player_anytime_td" && M.rz_opp_share) driver = pct(M.rz_opp_share.v) + " of the team's red-zone touches; team expected to score " + d1(G.implied) + " points";
    const projStr = c.stat === "player_anytime_td" ? pct(pj.p) + " to score" : d1(pj.med) + " " + (UNIT[c.stat] || "");
    const vs = c.stat === "player_anytime_td" ? "" : " vs the " + fmt(lineVal) + " line";
    const word = {agree: "Stats agree", neutral: "Stats are neutral", disagree: "Stats disagree", "n/a": "Stats: n/a"}[v];
    return head + " " + word + ": projection " + projStr + vs + (driver ? " (" + driver + ")" : "") + ".";
  }

  const api = {lean, verdict, DEF, dirNote, findPlayer, metrics, sections, projText, flags, confidence, why, teamAbbr, ord,
               YARDS_REL, RECEPTIONS_ABS, PASS_TDS_ABS, TD_PROB_ABS};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Analytics = api;
})(this);
