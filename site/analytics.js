// "Why this pick": turns site/analytics.json into evidence lines, a stats verdict, a confidence tag and a
// one-line explanation. Plain script, no DOM code (the page renders), and Node can load it for tests.
// Numbers only ever come from analytics.json / data.json. Missing ones say "n/a" and why.
(function (root) {
  const P = root.Parlay || (typeof require === "function" ? require("./parlay.js") : null);

  // ---- verdict rules: keep in sync with src/verdict.py ---------------------------------------------
  const YARDS_REL = 0.07, RECEPTIONS_ABS = 0.5, PASS_TDS_ABS = 0.25, TD_PROB_ABS = 0.05;
  const YARDS = new Set(["player_rush_yds", "player_reception_yds", "player_pass_yds", "player_rush_reception_yds",
    "player_pass_attempts", "player_pass_completions", "player_rush_attempts"]);   // 7%-of-the-line rule
  const INTS_ABS = 0.2;
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
      : stat === "player_receptions" ? Math.abs(d) >= RECEPTIONS_ABS
      : stat === "player_pass_interceptions" ? Math.abs(d) >= INTS_ABS : Math.abs(d) >= PASS_TDS_ABS;
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
    comp_pct: {t: "Completion %", d: "Completed passes ÷ pass attempts (sacks not counted).", up: true},
    int_rate: {t: "Interception rate", d: "Interceptions ÷ pass attempts. For an interceptions Over, higher is better; for passing props it's a red flag.", up: true},
    attempts_pg: {t: "Pass attempts per game", d: "Passes thrown per game (sacks and scrambles not counted).", up: true},
    o_db_epa: {t: "Pass offense EPA", d: "Expected points added per dropback by this offense. Higher = the passing game is working.", up: true},
    o_run_epa: {t: "Run offense EPA", d: "Expected points added per run by this offense.", up: true},
    d_int_rate: {t: "Interceptions forced", d: "Interceptions per opponent pass attempt.", up: true},
    d_comp_pct: {t: "Completion % allowed", d: "Share of pass attempts against this defense that are completed.", up: true},
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
    if (!A._byName) {  // built once per file: the page looks players up thousands of times per render
      A._byName = new Map();
      for (const p of A.players) { const k = P.norm(p.n); A._byName.set(k, (A._byName.get(k) || []).concat(p)); }
    }
    const hits = A._byName.get(P.norm(name)) || [];
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
  // percentile -> plain words: 89 -> "top 11% of running backs", 30 -> "bottom 30%"
  function pctText(m, pos) {
    if (m.pct == null) return "";
    if (m.pct >= 50) return " (top " + Math.max(1, 100 - m.pct) + "% of " + POSN[pos] + ")";
    return " (bottom " + Math.max(1, m.pct) + "% of " + POSN[pos] + ")";
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
      case "comp_pct": return line(key, "Completes " + pct(v) + " of his passes" + pt);
      case "int_rate": return line(key, "Intercepted on " + d1(v * 100) + "% of attempts" + pt);
      case "attempts_pg": return line(key, d1(v) + " pass attempts per game" + pt);
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
      case "int_rate": return line(k, opp + " intercept " + d1(v * 100) + "% of passes" + a + rkHigh);
      case "comp_pct": return line(k, opp + " allow " + pct(v) + " of passes to be completed" + a + rk);
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
    player_pass_attempts: {u: ["db_share", "attempts_pg", "dropbacks_pg"], e: ["sack_rate", "ttt", "pressure_faced", "epa_db"],
      d: ["db_epa", "pressure_rate", "sack_rate"]},
    player_pass_completions: {u: ["attempts_pg", "db_share", "dropbacks_pg"], e: ["comp_pct", "cpoe", "ttt", "pressure_faced"],
      d: ["comp_pct", "db_epa", "pressure_rate", "cov_rating"]},
    player_pass_interceptions: {u: ["attempts_pg", "dropbacks_pg"], e: ["int_rate", "cpoe", "pressure_faced", "epa_db"],
      d: ["int_rate", "pressure_rate", "cov_rating"]},
    player_rush_attempts: {u: ["carry_share", "carries_pg", "snap_share", "rz_carries"], e: ["ypc", "stuff_rate", "explosive_rate"],
      d: ["ypc", "run_epa", "stuff_rate"]},
    player_rush_reception_yds: {u: ["carry_share", "target_share", "touches_pg", "snap_share"], e: ["ypc", "ypt", "yprr_proxy", "explosive_rate"],
      d: ["ypc", "run_epa", "db_epa", "missed_tackle_pct"]},
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
                player_receptions: "catches", player_pass_tds: "passing TDs", player_pass_attempts: "pass attempts",
                player_pass_completions: "completions", player_rush_attempts: "carries", player_pass_interceptions: "interceptions",
                player_rush_reception_yds: "rushing + receiving yards"};
  function projText(stat, pj) {
    if (!pj) return null;
    const i = pj.in || {};
    const note = pj.adj ? " Includes teammates' freed-up " + Object.values(pj.adj).map(a => (a.kind === "target_share" ? "targets" : "carries") + " (" + pct(a.share) + " → " + pct(a.newShare) + " share)").join(" and ") + "." : "";
    return projBase(stat, pj, i) + note;
  }
  function projBase(stat, pj, i) {
    if (stat === "player_anytime_td")
      return "Expected TDs " + d2(i.lam) + " = " + d2(i.team_tds) + " team TDs × (" + pct(i.rush_frac) + " rushing × " + pct(i.rush_share) +
        " of his rushing chances + " + pct(1 - i.rush_frac) + " receiving × " + pct(i.rec_share) + " of his receiving chances) → " + pct(pj.p) + " to score at least once.";
    const typical = " A typical game is " + pct(i.mf || 1) + " of the average (big games pull the average up), so " + d1(pj.med) + ".";
    if (stat === "player_rush_yds") return d1(i.carries) + " carries (" + pct(i.share) + " of " + d1(i.team_carries) + " team carries) × " + d1(i.ypc) + " yards per carry × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_reception_yds") return d1(i.targets) + " targets (" + pct(i.share) + " of " + d1(i.team_att) + " team attempts) × " + d1(i.ypt) + " yards per target × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_receptions") return d1(i.targets) + " targets × " + pct(i.catch) + " catch rate × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_pass_yds") return d1(i.attempts) + " attempts × " + d1(i.ypa) + " yards per attempt × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_pass_tds") return d1(i.attempts) + " attempts × " + pct(i.td_rate) + " TD rate × " + d2(i.opp) + " defense factor = " + d2(pj.mean) + ".";
    if (stat === "player_pass_attempts") return pct(i.share) + " of " + d1(i.team_att) + " expected team pass attempts (" + d1(i.plays) + " plays × " + pct(i.pass_rate) + " pass rate) = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_pass_completions") return d1(i.attempts) + " attempts × " + pct(i.comp) + " completion rate × " + d2(i.opp) + " defense factor = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_pass_interceptions") return d1(i.attempts) + " attempts × " + d1(i.int_rate * 100) + "% interception rate × " + d2(i.opp) + " defense factor = " + d2(pj.mean) + " expected interceptions.";
    if (stat === "player_rush_attempts") return pct(i.share) + " of " + d1(i.team_carries) + " expected team carries = " + d1(pj.mean) + " on average." + typical;
    if (stat === "player_rush_reception_yds") return d1(i.rush) + " rushing + " + d1(i.rec) + " receiving yards = " + d1(pj.mean) + " on average." + typical;
    return null;
  }

  function flags(A, p, stat, side, prop, linesTime) {
    const out = [];
    if (!A || !p) return out;
    const news = newsAfterLines(A, p, linesTime);
    if (news.length) out.push({k: "news", sev: 1, text: "Injury news since these lines were pulled: " + news.map(x => x.n + " " + x.s + " (" +
      new Date(x.d).toLocaleString([], {weekday: "short", hour: "numeric", minute: "2-digit"}) + ")").join(", ") + ". Books have probably moved this line, so check your book's current number."});
    if (p.inj) {
      const [status, injury, practice] = p.inj;
      if (status) out.push({k: "injury", sev: status === "Questionable" ? 1 : 2, text: nick(p.n) + " is listed " + status + (injury ? " (" + injury + ")" : "") + " on the week " + A.inj_week + " injury report"});
      else if (practice && /Did Not/i.test(practice)) out.push({k: "injury", sev: 1, text: nick(p.n) + " did not practice" + (injury ? " (" + injury + ")" : "") + " per the week " + A.inj_week + " report"});
    }
    const T = A.teams[p.t] || {}, G = (A.games || {})[p.t] || {}, O = A.teams[G.opp] || {};
    for (const x of T.out || []) {
      if (x.side !== "off" || P.norm(x.n) === P.norm(p.n)) continue;
      if (x.role === "on the injury report") continue;
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
    const head = c.km
      ? "Why " + Math.round(c.hit * 100) + "%: that's Kalshi's own price for \u201c" + sideText + "\u201d. No sportsbook line for this stat was bought, so there's no outside price to check it against."
      : "Why " + Math.round(c.hit * 100) + "%: " + (c.n > 1 ? c.n + " sportsbooks' prices" : "one sportsbook's price") +
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
    else if ((c.stat === "player_pass_attempts" || c.stat === "player_pass_completions") && M.attempts_pg)
      driver = d1(M.attempts_pg.v) + " attempts per game" + (M.comp_pct && c.stat === "player_pass_completions" ? ", " + pct(M.comp_pct.v) + " completed" : "");
    else if (c.stat === "player_pass_interceptions" && M.int_rate) driver = d1(M.int_rate.v * 100) + "% interception rate";
    else if (c.stat === "player_rush_attempts" && M.carry_share) driver = pct(M.carry_share.v) + " carry share";
    else if (c.stat === "player_rush_reception_yds" && M.touches_pg) driver = d1(M.touches_pg.v) + " touches per game";
    else if (c.stat === "player_anytime_td" && M.rz_opp_share) driver = pct(M.rz_opp_share.v) + " of the team's red-zone touches; team expected to score " + d1(G.implied) + " points";
    const projStr = c.stat === "player_anytime_td" ? pct(pj.p) + " to score" : d1(pj.med) + " " + (UNIT[c.stat] || "");
    const vs = c.stat === "player_anytime_td" ? "" : " vs the " + fmt(lineVal) + " line";
    const word = {agree: "Stats agree", neutral: "Stats are neutral", disagree: "Stats disagree", "n/a": "Stats: n/a"}[v];
    return head + " " + word + ": projection " + projStr + vs + (driver ? " (" + driver + ")" : "") + ".";
  }

  // ---- game picks (moneyline / spread / total): team context, no game-result model -------------------
  function gameSections(A, homeName, awayName) {
    const h = teamAbbr(A, homeName), a = teamAbbr(A, awayName), nT = A.nteams || 32;
    if (!h || !a) return [];
    const sec = (off, def) => {
      const O = A.teams[off] || {o: {}}, Dd = A.teams[def] || {d: {}}, on = nick(O.name || off), dn = nick(Dd.name || def), out = [];
      const o = O.o || {}, d = Dd.d || {};
      const rkO = r => r ? ", " + rankText(r, nT, "highest", "lowest") : "";
      if (o.db_epa && o.db_epa[0] != null) out.push(line("o_db_epa", on + " pass offense: " + sgn(o.db_epa[0], d2) + " EPA per dropback" + rkO(o.db_epa[1])));
      if (o.run_epa && o.run_epa[0] != null) out.push(line("o_run_epa", on + " run offense: " + sgn(o.run_epa[0], d2) + " EPA per run" + rkO(o.run_epa[1])));
      out.push(defLine("db_epa", Dd, dn, nT), defLine("run_epa", Dd, dn, nT));
      if (o.plays_pg && o.plays_pg[0] != null) out.push(line("pace", on + " run " + d1(o.plays_pg[0]) + " plays per game, " + rankText(o.plays_pg[1], nT, "most", "fewest")));
      return {title: on + " offense vs " + dn + " defense", lines: out.filter(Boolean).slice(0, 5)};
    };
    const G = (A.games || {})[h], ctx = [];
    if (G) {
      if (G.spread != null) ctx.push(line("implied", nick(A.teams[h].name) + " expected to score " + d1(G.implied) + ", " + nick(A.teams[a].name) + " " +
        d1((A.games[a] || {}).implied) + " (spread " + (G.spread > 0 ? "+" : "") + d1(G.spread) + " for the home team, total " + d1(G.total) + ")"));
      ctx.push(weatherLine(G));
      if (G.rest != null && G.opp_rest != null) ctx.push(line("rest", nick(A.teams[h].name) + " " + G.rest + " days of rest, " + nick(A.teams[a].name) + " " + G.opp_rest));
      const outs = [...(A.teams[h].out || []), ...(A.teams[a].out || [])].filter(x => x.side === "off");
      if (outs.length) ctx.push(line(null, "Out: " + outs.map(x => x.pos + " " + x.n + " (" + x.s + ")").join(", ")));
    } else ctx.push(line(null, "n/a (this game isn't in the stats file's week " + A.week + ")", true));
    return [sec(h, a), sec(a, h), {title: "Game context", lines: ctx}];
  }
  function gameFlags(A, homeName, awayName, stat, side) {
    const h = teamAbbr(A, homeName), G = h && (A.games || {})[h], out = [];
    if (!G) return out;
    if (stat === "game_total" && G.wx && G.roof !== "indoors" && G.wx.wind > 15) {
      const over = side === "Over" || side === "YES";
      out.push({k: "weather", sev: over ? 1 : 0, text: "Wind " + int(G.wx.wind) + " mph forecast: strong wind tends to lower scoring" + (over ? " (works against this Over)" : "")});
    }
    for (const t of [h, teamAbbr(A, awayName)]) for (const x of ((A.teams[t] || {}).out || [])) if (x.side === "off" && /QB/.test(x.pos))
      out.push({k: "injury", sev: 1, text: nick(A.teams[t].name) + " QB " + x.n + " is " + x.s + (x.i ? " (" + x.i + ")" : "")});
    return out;
  }

  // ---- recent form, home/away, last season ------------------------------------------------------------
  const LOGF = {player_rush_yds: "rush_yds", player_reception_yds: "rec_yds", player_receptions: "receptions",
    player_pass_yds: "pass_yds", player_pass_completions: "completions", player_pass_attempts: "attempts",
    player_rush_attempts: "carries", player_pass_tds: "pass_tds", player_pass_interceptions: "ints", player_anytime_td: "tds"};
  function statValue(fields, row, stat, offset) {
    const get = f => { const i = fields.indexOf(f); return i < 0 ? null : row[i + offset]; };
    if (stat === "player_rush_reception_yds") {
      const a = get("rush_yds"), b = get("rec_yds");
      return a == null && b == null ? null : (a || 0) + (b || 0);
    }
    return LOGF[stat] ? get(LOGF[stat]) : null;
  }
  // [{season, wk, opp, home, v}] oldest first, for this stat. Rows reach back into last season so "last 10"
  // works early in the year; anything labeled "this season" filters on season.
  function gameLog(A, p, stat) {
    const fields = (A.logk || {})[p.pos] || [];
    return (p.log || []).map(r => ({season: r[0], wk: r[1], opp: r[2], home: !!r[3], v: statValue(fields, r, stat, 4)})).filter(x => x.v != null);
  }
  const thisSeason = (A, L) => L.filter(x => x.season === A.season);
  const wkLabel = (A, x) => (x.season === A.season ? "Wk " : "'" + String(x.season).slice(2) + " Wk ") + x.wk;
  function lastYear(A, p, stat) {
    if (!p.ly) return null;
    const v = statValue((A.logk || {})[p.pos] || [], p.ly, stat, 1);
    return v == null ? null : {g: p.ly[0], avg: v};
  }
  const avg = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
  // did this game beat the pick? (TD: scored or not)
  function cleared(v, stat, line, side) {
    const over = OVER.has(side);
    if (stat === "player_anytime_td") return (v > 0) === over;
    return line == null ? null : (v > line) === over;
  }
  function recentSection(A, p, stat, line, side) {
    const all = gameLog(A, p, stat), L = thisSeason(A, all), out = [], ly = lastYear(A, p, stat), isTd = stat === "player_anytime_td";
    const unit = isTd ? "TDs" : (UNIT[stat] || "");
    if (all.length) {
      const last = all.slice(-5).reverse();
      out.push(line_(null, "Last " + last.length + (last.length === 1 ? " game: " : " games: ") +
        last.map(x => fmtv(x.v, stat) + (x.home ? " vs " : " @ ") + x.opp + (x.season !== A.season ? " ('" + String(x.season).slice(2) + ")" : "")).join(", ") + " (newest first)"));
    }
    if (L.length) {
      const hits = L.filter(x => cleared(x.v, stat, line, side));
      if (isTd) out.push(line_(null, "Scored in " + L.filter(x => x.v > 0).length + " of " + L.length + " games this season"));
      else if (line != null) out.push(line_(null, (OVER.has(side) ? "Over " : "Under ") + fmt(line) + " in " + hits.length + " of " + L.length + " games this season (average " + d1(avg(L.map(x => x.v))) + ")"));
      const H = L.filter(x => x.home), W = L.filter(x => !x.home);
      if (H.length && W.length && !isTd) out.push(line_(null, "Home: " + d1(avg(H.map(x => x.v))) + " a game (" + H.length + ") · Away: " + d1(avg(W.map(x => x.v))) + " (" + W.length + ")"));
    } else out.push(line_(null, "No games this season yet", true));
    if (ly) out.push(line_(null, "Last season: " + (isTd ? d2(ly.avg) + " TDs" : d1(ly.avg) + " " + unit) + " per game over " + ly.g + " games"));
    const G = (A.games || {})[p.t];
    if (G) out.push(line_(null, "This week he's " + (G.home ? "at home" : "on the road") + (G.rest != null && G.opp_rest != null && G.rest !== G.opp_rest ? ", " + G.rest + " days of rest vs " + G.opp_rest : "")));
    return {title: "Recent form", lines: out, log: all};
  }
  const line_ = (key, text, na) => ({key, text, na: !!na});
  const fmtv = (v, stat) => String(Math.round(v));

  // ---- scheme matchups --------------------------------------------------------------------------------
  function schemeSection(A, p, stat) {
    const G = (A.games || {})[p.t], O = G && A.teams[G.opp], out = [];
    let edge = 0;
    if (!O) return {title: "Scheme matchup", lines: [], edge};
    const on = nick(O.name), who = nick(p.n), nT = A.nteams || 32, covk = A.covk || {};
    if (/reception|receptions|rush_reception/.test(stat) && p.pos !== "QB") {
      const cov = Object.entries(O.cov || {}).filter(([k]) => k !== "MAN").sort((a, b) => b[1][0] - a[1][0]);
      if (cov.length) {
        const [k, [share, rank]] = cov[0];
        out.push(line_(null, on + " played " + (covk[k] || k) + " on " + pct(share) + " of dropbacks last season (" + rankText(rank, nT, "most", "least") + ")"));
        const cv = p.cv || {}, all = cv.ALL, mine = cv[k];
        if (mine && all) {
          const rel = mine[1] / all[1] - 1;
          if (Math.abs(rel) >= 0.15) edge += rel > 0 ? 1 : -1;
          out.push(line_(null, who + " vs " + (covk[k] || k) + ": " + d1(mine[1]) + " yards per target (" + mine[0] + " targets) vs " + d1(all[1]) + " overall" +
            (rel >= 0.15 ? " · good matchup" : rel <= -0.15 ? " · tough matchup" : "")));
        } else out.push(line_(null, who + " vs " + (covk[k] || k) + ": n/a (fewer than 8 targets against it last season)", true));
      }
      const man = (O.cov || {}).MAN, cv = p.cv || {};
      if (man) {
        const leanMan = man[0] >= 0.4, mine = cv[leanMan ? "MAN" : "ZONE"], other = cv[leanMan ? "ZONE" : "MAN"];
        out.push(line_(null, on + " were in man coverage " + pct(man[0]) + " of the time (" + rankText(man[1], nT, "most", "least") + ")" +
          (mine && other ? "; " + who + " averaged " + d1(mine[1]) + " yards per target vs " + (leanMan ? "man" : "zone") + ", " + d1(other[1]) + " vs " + (leanMan ? "zone" : "man") : "")));
      }
      if (out.length) out.push(line_(null, "Coverage charting is last season's (2025): this season's isn't public yet, and coaching changes can shift it.", true));
    }
    if (/pass_/.test(stat) && p.pos === "QB") {
      if (O.blitz) out.push(line_(null, on + " blitz on " + pct(O.blitz[0]) + " of dropbacks (" + rankText(O.blitz[1], nT, "most", "least") + ", this season)"));
      const bz = p.bz || {};
      if (bz.blitz && bz.no) {
        const diff = bz.blitz[1] - bz.no[1];
        if (O.blitz && O.blitz[1] <= 8 && Math.abs(diff) >= 0.15) edge += diff > 0 ? 1 : -1;
        out.push(line_(null, who + ": " + sgn(bz.blitz[1], d2) + " EPA per dropback when blitzed (" + bz.blitz[0] + ") vs " + sgn(bz.no[1], d2) + " when not (" + bz.no[0] + ")"));
      }
    }
    if (/rush/.test(stat) && p.pos !== "WR") {
      if (O.box8) out.push(line_(null, on + " put 8+ defenders in the box on " + pct(O.box8[0]) + " of runs (" + rankText(O.box8[1], nT, "most", "least") + ", this season)"));
      const bx = p.bx || {};
      if (bx.box8 && bx.lt8) {
        const diff = bx.box8[1] - bx.lt8[1];
        if (O.box8 && O.box8[1] <= 8 && diff <= -1) edge -= 1;
        out.push(line_(null, who + ": " + d1(bx.box8[1]) + " yards per carry vs 8+ in the box (" + bx.box8[0] + " carries) vs " + d1(bx.lt8[1]) + " against lighter boxes"));
      }
    }
    return {title: "Scheme matchup", lines: out, edge};
  }

  // ---- injuries, both teams ---------------------------------------------------------------------------
  function injurySection(A, p) {
    const G = (A.games || {})[p.t], out = [];
    if (p.inj && (p.inj[0] || p.inj[2])) out.push(line_(null, nick(p.n) + ": " + (p.inj[0] || p.inj[2]) + (p.inj[1] ? " (" + p.inj[1] + ")" : "")));
    for (const t of [p.t, G && G.opp]) {
      const T = A.teams[t]; if (!T) continue;
      const xs = (T.out || []).filter(x => P.norm(x.n) !== P.norm(p.n)).slice(0, 5);
      out.push(line_(null, nick(T.name) + ": " + (xs.length ? xs.map(x => x.pos + " " + x.n + " " + x.s + (x.i ? " (" + x.i + ")" : "") + " · " + x.role).join("; ") : "no regulars on the report")));
    }
    out.push(line_(null, "Injury report from week " + A.inj_week + ". Final inactives come out 90 minutes before kickoff.", true));
    return {title: "Injuries", lines: out};
  }

  // ---- the short version: what matters most, first ---------------------------------------------------
  // Each point says whether it helps or hurts THIS pick. Ordered by how much it should move you.
  function shortVersion(A, p, c, lineVal, pj, v, linesTime) {
    const pts = [], over = OVER.has(c.side), stat = c.stat, M = metrics(A, p), G = (A.games || {})[p.t] || {}, O = A.teams[G.opp];
    const add = (w, dir, text) => pts.push({w, dir, text});
    if (pj && pj.adj) add(6, over ? 1 : -1, adjustText(p, pj.adj));
    if (p.inj && /Out|Doubtful|Questionable/.test(p.inj[0] || "")) add(10, -1, nick(p.n) + " is listed " + p.inj[0] + (p.inj[1] ? " (" + p.inj[1] + ")" : "") + ": check inactives before betting");
    if (pj) {
      if (stat === "player_anytime_td") {
        const mk = over ? c.hit : 1 - c.hit, d = pj.p - mk;
        add(Math.abs(d) * 40, (d > 0) === over ? 1 : -1, "Stats give him a " + pct(pj.p) + " chance to score vs " + pct(mk) + " in the market");
      } else if (lineVal != null) {
        const gap = (pj.med - lineVal) / Math.max(lineVal, 1);
        add(Math.abs(gap) * 30, v === "agree" ? 1 : v === "disagree" ? -1 : 0, "Stats project " + d1(pj.med) + " " + (UNIT[stat] || "") + " vs the " + fmt(lineVal) + " line" +
          (v === "agree" ? " (backs this pick)" : v === "disagree" ? " (points the other way)" : " (close to the line)"));
      }
    }
    const L = gameLog(A, p, stat).slice(-10);
    if (L.length >= 2) {
      const hits = L.filter(x => cleared(x.v, stat, lineVal, c.side)).length, rate = hits / L.length;
      add(1 + Math.abs(rate - 0.5) * 6 * Math.min(1, L.length / 6), rate > 0.5 ? 1 : rate < 0.5 ? -1 : 0,
        (stat === "player_anytime_td" ? (c.side === "No" ? "Kept out of the end zone in " + L.filter(x => x.v === 0).length : "Scored in " + L.filter(x => x.v > 0).length) + " of his last " + L.length + " games"
          : "This pick would have hit in " + hits + " of his last " + L.length + " games"));
    }
    const usage = {player_rush_yds: "carry_share", player_rush_attempts: "carry_share", player_reception_yds: "target_share", player_receptions: "target_share",
                   player_rush_reception_yds: "touches_pg", player_anytime_td: "rz_opp_share", player_pass_yds: "attempts_pg", player_pass_attempts: "attempts_pg",
                   player_pass_completions: "comp_pct", player_pass_tds: "epa_db", player_pass_interceptions: "int_rate"}[stat];
    if (usage && M[usage] && M[usage].pct != null) {
      const good = M[usage].pct >= 70, bad = M[usage].pct <= 30;
      const l = playerLine(usage, M, p, A);
      if (l && (good || bad)) add(1.5, (good === over) ? 1 : -1, l.text);
    }
    if (O) {
      const pos = p.pos === "QB" ? null : p.pos, nT = A.nteams || 32;
      const key = /rush/.test(stat) && stat !== "player_rush_reception_yds" ? ["d", "ypc"] : pos && /reception|receptions/.test(stat) ? ["dp", pos, "ypt"] : /pass/.test(stat) ? ["d", "ypa"] : stat === "player_anytime_td" ? ["d", "rz_td_pct"] : null;
      let x = null;
      if (key && key[0] === "d") x = (O.d || {})[key[1]];
      if (key && key[0] === "dp") x = ((O.dp || {})[key[1]] || {})[key[2]];
      if (x && x[2] && (x[2] <= 8 || x[2] >= nT - 7)) {
        const soft = x[2] <= 8;   // allows a lot
        const what = key[0] === "dp" ? d1(x[0]) + " yards per target to " + POSN[pos] : key[1] === "ypc" ? d1(x[0]) + " yards per carry" : key[1] === "ypa" ? d1(x[0]) + " yards per pass" : pct(x[0]) + " TDs on red-zone trips";
        add(2, soft === over ? 1 : -1, nick(O.name) + " allow " + what + " (" + rankText(x[2], nT, "most", "fewest") + ")");
      }
    }
    const sc = schemeSection(A, p, stat);
    if (sc.edge) add(1.8, (sc.edge > 0) === over ? 1 : -1, sc.lines.find(l => /good matchup|tough matchup|EPA per dropback when blitzed|8\+ in the box \(/.test(l.text)).text);
    // warnings (wind on a passing pick, line moving against you) hurt; teammate/defense news is context
    for (const f of flags(A, p, stat, c.side, c.prop_mv ? {mv: c.prop_mv} : null, linesTime)) {
      if (f.k === "injury" || (f.k === "teammate" && pj && pj.adj)) continue;
      add(f.k === "news" ? 8 : f.sev ? 3 : 1.2, f.sev ? -1 : 0, f.text);
    }
    if (G.implied != null && stat !== "player_pass_interceptions") {
      const hi = G.implied >= 26, lo = G.implied <= 18;
      if (hi || lo) add(1, (hi === over) ? 1 : -1, nick((A.teams[p.t] || {}).name || p.t) + " are expected to score " + d1(G.implied) + " points" + (hi ? " (a high total)" : " (a low total)"));
    }
    pts.sort((a, b) => b.w - a.w);
    return pts.slice(0, 5);
  }

  // ---- injuries: live statuses and the usage they free up ------------------------------------------------
  const OUTSET = new Set(["Out", "Doubtful", "Injured Reserve", "Suspension", "Physically Unable to Perform", "Reserve/PUP", "IR"]);
  const ORDER = {Out: 0, "Injured Reserve": 0, Suspension: 0, Doubtful: 1, Questionable: 2};
  const OFFPOS = new Set(["QB", "RB", "FB", "WR", "TE", "T", "OT", "G", "OG", "C", "OL"]);
  const lastName = n => P.norm(n).split(" ").slice(-1)[0];
  function roleOf(A, p) {
    const M = metrics(A, p), r = [];
    if (p.pos === "QB" && M.db_share && M.db_share.v >= 0.5) r.push(pct(M.db_share.v) + " of dropbacks");
    if (M.target_share && M.target_share.v >= 0.15) r.push(pct(M.target_share.v) + " target share");
    if (M.carry_share && M.carry_share.v >= 0.3) r.push(pct(M.carry_share.v) + " carry share");
    return r.join(", ");
  }
  // live = {updated, teams: {"Philadelphia Eagles": [{n, pos, s, d, i, c}]}} from /api/injuries (ESPN)
  function applyLiveInjuries(A, live) {
    if (!A || !live || !live.teams) return 0;
    let n = 0;
    for (const [abbr, T] of Object.entries(A.teams || {})) {
      const L = live.teams[T.name];
      if (!L) continue;
      const byName = new Map(L.map(e => [P.norm(e.n), e]));
      const find = (name, pos) => byName.get(P.norm(name)) || (() => {
        const c = L.filter(e => lastName(e.n) === lastName(name) && e.pos === pos);
        return c.length === 1 ? c[0] : null;
      })();
      const mine = A.players.filter(p => p.t === abbr), oldRole = new Map((T.out || []).map(x => [P.norm(x.n), x]));
      for (const p of mine) {
        const e = find(p.n, p.pos);
        if (e) { p.inj = [e.s, e.i, (p.inj || [])[2] || null, e.d, e.c]; n++; }
        else if (p.inj && p.inj[0]) p.inj = [null, p.inj[1], p.inj[2], null, null];   // no longer on ESPN's list
      }
      const out = [];
      for (const e of L) {
        const p = mine.find(x => P.norm(x.n) === P.norm(e.n)) || mine.find(x => lastName(x.n) === lastName(e.n) && x.pos === e.pos);
        const prev = oldRole.get(P.norm(e.n));
        const role = (p && roleOf(A, p)) || (prev && prev.role) || "";
        const side = p ? "off" : prev ? prev.side : OFFPOS.has(e.pos) ? "off" : "def";
        if (role || (["QB", "RB", "WR", "TE"].includes(e.pos) && (OUTSET.has(e.s) || e.s === "Questionable")))
          out.push({n: e.n, pos: e.pos, s: e.s, i: e.i, side, role: role || "on the injury report", d: e.d, c: e.c});
      }
      T.out = out.sort((a, b) => (ORDER[a.s] ?? 3) - (ORDER[b.s] ?? 3) || (a.side === "off" ? -1 : 1));
    }
    A.inj_src = "ESPN injury feed, live (as of " + new Date(live.updated).toLocaleTimeString([], {weekday: "short", hour: "numeric", minute: "2-digit"}) + ")";
    A.inj_live = true;
    return n;
  }
  function teamLatestWeek(A, team) {
    let w = 0;
    for (const p of A.players) if (p.t === team) for (const r of p.log || []) if (r[0] === A.season) w = Math.max(w, r[1]);
    return w;
  }
  // Teammates ruled Out / Doubtful who were part of the offense until now: their share of the team's targets
  // (or carries) is handed to the players still active, in proportion to the shares those players already
  // have. Returns {kind, share, newShare, factor, freed: [{n, pos, s, share}]} or null.
  function injuryAdjust(A, p, stat) {
    if (!A || !p || p.pos === "QB") return null;
    const kinds = /rush_yds$|rush_attempts/.test(stat) ? ["carry_share"] : /reception|receptions/.test(stat) && stat !== "player_rush_reception_yds" ? ["target_share"]
      : stat === "player_rush_reception_yds" || stat === "player_anytime_td" ? ["carry_share", "target_share"] : [];
    if (!kinds.length) return null;
    const latest = teamLatestWeek(A, p.t), mates = A.players.filter(x => x.t === p.t && x !== p && x.pos !== "QB");
    const res = {};
    for (const k of kinds) {
      const sh = x => (metrics(A, x)[k] || {}).v || 0;
      const mine = sh(p);
      if (!(mine > 0)) continue;
      const isOut = x => { const r = x.inj && OUTSET.has(x.inj[0]) && x.log && x.log[x.log.length - 1]; return !!r && r[0] === A.season && r[1] === latest; };
      const freed = mates.filter(x => isOut(x) && sh(x) > 0.03).map(x => ({n: x.n, pos: x.pos, s: x.inj[0], share: sh(x)}));
      if (!freed.length) continue;
      // 60% of a missing player's share goes to active teammates at his position (a WR's targets mostly go to
      // the other WRs), 40% to everyone active; both in proportion to the shares they already have
      const active = mates.filter(x => !(x.inj && OUTSET.has(x.inj[0]))).concat([p]);
      let newShare = mine;
      for (const f of freed) {
        const same = active.filter(x => x.pos === f.pos), sameSum = same.reduce((a, x) => a + sh(x), 0);
        const allSum = active.reduce((a, x) => a + sh(x), 0);
        const toSame = sameSum > 0 ? 0.6 : 0;
        if (p.pos === f.pos && sameSum > 0) newShare += f.share * toSame * mine / sameSum;
        newShare += f.share * (1 - toSame) * mine / allSum;
      }
      res[k] = {kind: k, share: mine, newShare, factor: Math.min(newShare / mine, 1.75), freed};
    }
    return Object.keys(res).length ? res : null;
  }
  // the projection with freed-up usage folded in (volume scales with share; efficiency unchanged)
  function adjustProjection(stat, pj, adj) {
    if (!pj || !adj) return pj;
    const fT = (adj.target_share || {}).factor || 1, fC = (adj.carry_share || {}).factor || 1;
    const i = {...(pj.in || {})};
    if (stat === "player_anytime_td") {
      const lam = i.team_tds * (i.rush_frac * i.rush_share * fC + (1 - i.rush_frac) * i.rec_share * fT);
      return {...pj, p: 1 - Math.exp(-lam), in: {...i, lam, rush_share: i.rush_share * fC, rec_share: i.rec_share * fT}, adj};
    }
    let f = /reception|receptions/.test(stat) ? fT : fC;
    if (stat === "player_rush_reception_yds") {
      const mean = (i.rush || 0) * fC + (i.rec || 0) * fT;
      return {...pj, mean, med: mean * (i.mf || 1), in: {...i, rush: (i.rush || 0) * fC, rec: (i.rec || 0) * fT}, adj};
    }
    const scaled = {...i};
    for (const k of ["carries", "targets", "share"]) if (scaled[k] != null) scaled[k] *= f;
    return {...pj, mean: pj.mean * f, med: pj.med * f, in: scaled, adj};
  }
  function adjustText(p, adj) {
    if (!adj) return null;
    return Object.values(adj).map(a => a.freed.map(x => x.pos + " " + x.n + " (" + x.s + ")").join(" and ") + (a.freed.length > 1 ? " are likely out: their " : " is likely out: his ") +
      pct(a.freed.reduce((s, x) => s + x.share, 0)) + " of the team's " + (a.kind === "target_share" ? "targets" : "carries") + " get spread around, so " +
      nick(p.n) + " projects for " + pct(a.newShare) + " instead of " + pct(a.share)).join(". ") + ".";
  }
  // injury news that came out after the sportsbook lines were pulled: books have probably moved since
  function newsAfterLines(A, p, linesTime) {
    if (!linesTime) return [];
    const t0 = new Date(linesTime), out = [];
    const T = A.teams[p.t] || {};
    if (p.inj && p.inj[3] && new Date(p.inj[3]) > t0) out.push({n: p.n, s: p.inj[0] || "on the report", d: p.inj[3]});
    for (const x of T.out || []) if (x.side === "off" && x.d && new Date(x.d) > t0 && P.norm(x.n) !== P.norm(p.n) && x.role !== "on the injury report")
      out.push({n: x.n, s: x.s, d: x.d});
    return out;
  }

  const api = {thisSeason, wkLabel, applyLiveInjuries, injuryAdjust, adjustProjection, adjustText, newsAfterLines, OUTSET, shortVersion, recentSection, schemeSection, injurySection, gameLog, lastYear, cleared, gameSections, gameFlags, lean, verdict, DEF, dirNote, findPlayer, metrics, sections, projText, flags, confidence, why, teamAbbr, ord,
               YARDS_REL, RECEPTIONS_ABS, PASS_TDS_ABS, TD_PROB_ABS};
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.Analytics = api;
})(this);
