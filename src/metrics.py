"""Player and team metrics from nflverse play-by-play and friends (polars).

Everything here is a pure function: DataFrames in, plain dicts out, so the tests can feed tiny fixtures.
Conventions:
- Regular season only. "Plays" are dropbacks (pass==1, includes sacks and scrambles) plus designed runs
  (rush==1); kneels, spikes, two-point tries and no-plays are dropped.
- Carries = rush_attempt (includes QB scrambles, like official rushing stats). Targets = pass attempts
  (not sacks) with a receiver.
- Recent games count more: a game k weeks before the latest played week has weight RECENCY**k.
- Early-season shrinkage: blended = (n*this_season + PRIOR_GAMES*last_season) / (n + PRIOR_GAMES), n = games.
- Opponent adjustment: a rate is scaled by league average / the average of the opponents faced
  (multiplicative for per-play yards and rates, additive for EPA).
"""
import math
from statistics import median

import polars as pl

RECENCY = 0.8
PRIOR_GAMES = 3.0
SMALL_SAMPLE = 4
RZ, GL = 20, 5
TEAM_FIX = {"LAR": "LA"}  # Next Gen Stats uses LAR; every other nflverse table uses LA

POSITIONS = ("QB", "RB", "WR", "TE")
# minimum volume (this season) to be ranked in a position percentile
QUALIFY = {"carries": 10, "targets": 8, "dropbacks": 40}


# ---------------------------------------------------------------- basics ----------------------------
def fix_team(df, col):
    return df.with_columns(pl.col(col).replace(TEAM_FIX)) if col in df.columns else df


def offense_plays(pbp):
    return pbp.filter(
        (pl.col("season_type") == "REG")
        & pl.col("play_type").is_in(["pass", "run"])
        & ((pl.col("pass") == 1) | (pl.col("rush") == 1))
        & (pl.col("qb_kneel").fill_null(0) == 0)
        & (pl.col("qb_spike").fill_null(0) == 0)
        & (pl.col("two_point_attempt").fill_null(0) == 0)
        & pl.col("posteam").is_not_null()
    )


def week_weights(weeks, latest):
    return {w: RECENCY ** max(0, latest - w) for w in weeks}


def blend(cur, n, prior, k=PRIOR_GAMES):
    """Shrink a this-season value toward last season's. Missing prior -> this season as is."""
    if cur is None:
        return prior
    if prior is None or n is None:
        return cur
    return (n * cur + k * prior) / (n + k)


def safe_div(a, b):
    return a / b if b else None


def passer_rating(comp, att, yds, td, ints):
    """NFL passer rating, here applied to targets (att = targets) for 'rating allowed'."""
    if not att:
        return None
    clamp = lambda x: max(0.0, min(2.375, x))
    a = clamp((comp / att - 0.3) * 5)
    b = clamp((yds / att - 3) * 0.25)
    c = clamp(td / att * 20)
    d = clamp(2.375 - ints / att * 25)
    return (a + b + c + d) / 6 * 100


def rank_desc(values):
    """{key: value} -> {key: rank}, 1 = highest. None values get None."""
    items = sorted(((k, v) for k, v in values.items() if v is not None), key=lambda kv: -kv[1])
    out, prev, prev_rank = {}, None, 0
    for i, (k, v) in enumerate(items, 1):
        rank = prev_rank if v == prev else i
        out[k], prev, prev_rank = rank, v, rank
    for k, v in values.items():
        if v is None:
            out[k] = None
    return out


def percentile(value, population):
    """Share of the population at or below value, 0-100 (rounded). None if no population."""
    pop = [x for x in population if x is not None]
    if value is None or not pop:
        return None
    return round(100 * sum(1 for x in pop if x <= value) / len(pop))


# ---------------------------------------------------------------- team game table -------------------
def team_games(pbp):
    """One row per (game, offense): volume, efficiency and context, from the offense's point of view."""
    p = offense_plays(pbp)
    att = (pl.col("pass_attempt") == 1) & (pl.col("sack") == 0)
    tgt = att & pl.col("receiver_player_id").is_not_null()
    rz = pl.col("yardline_100") <= RZ
    gl = pl.col("yardline_100") <= GL
    run = pl.col("rush") == 1
    carry = pl.col("rush_attempt") == 1
    drop = pl.col("pass") == 1
    return (
        p.group_by(["season", "week", "game_id", "posteam", "defteam"])
        .agg(
            plays=pl.len(),
            dropbacks=drop.sum(),
            designed=run.sum(),
            carries=carry.sum(),
            scrambles=(pl.col("qb_scramble") == 1).sum(),
            attempts=att.sum(),
            completions=(att & (pl.col("complete_pass") == 1)).sum(),
            sacks=(pl.col("sack") == 1).sum(),
            targets=tgt.sum(),
            pass_yds=pl.when(att).then(pl.col("passing_yards")).otherwise(0).fill_null(0).sum(),
            pass_tds=(att & (pl.col("pass_touchdown") == 1)).sum(),
            ints=(pl.col("interception") == 1).sum(),
            air_yards=pl.when(tgt).then(pl.col("air_yards")).otherwise(0).fill_null(0).sum(),
            db_epa=pl.when(drop).then(pl.col("epa")).otherwise(0).fill_null(0).sum(),
            run_yds=pl.when(run).then(pl.col("rushing_yards")).otherwise(0).fill_null(0).sum(),
            run_epa=pl.when(run).then(pl.col("epa")).otherwise(0).fill_null(0).sum(),
            stuffs=(run & (pl.col("rushing_yards").fill_null(0) <= 0)).sum(),
            explosive_runs=(run & (pl.col("rushing_yards").fill_null(0) >= 10)).sum(),
            rz_carries=(carry & rz).sum(),
            rz_targets=(tgt & rz).sum(),
            gl_carries=(carry & gl).sum(),
            gl_targets=(tgt & gl).sum(),
            off_tds=((pl.col("rush_touchdown") == 1) | (pl.col("pass_touchdown") == 1)).sum(),
            xpass_n=pl.col("xpass").is_not_null().sum(),
            proe_sum=pl.when(pl.col("xpass").is_not_null()).then(pl.col("pass") - pl.col("xpass")).otherwise(0).sum(),
            home_team=pl.col("home_team").first(),
            spread_line=pl.col("spread_line").first(),
        )
        # nflverse spread_line = home team's expected margin; team_spread uses betting convention
        # (negative = favored), so a home team favored by 3 has team_spread -3
        .with_columns(
            team_spread=pl.when(pl.col("posteam") == pl.col("home_team"))
            .then(-pl.col("spread_line")).otherwise(pl.col("spread_line"))
        )
    )


def redzone_drives(pbp):
    """One row per (game, offense): drives that reached the opponent 20, and how many ended in a TD."""
    p = pbp.filter((pl.col("season_type") == "REG") & pl.col("posteam").is_not_null() & pl.col("fixed_drive").is_not_null())
    d = (p.group_by(["season", "week", "game_id", "posteam", "defteam", "fixed_drive"])
         .agg(best=pl.col("yardline_100").min(), result=pl.col("fixed_drive_result").first()))
    return (d.filter(pl.col("best") <= RZ)
            .group_by(["season", "week", "game_id", "posteam", "defteam"])
            .agg(rz_drives=pl.len(), rz_td_drives=(pl.col("result") == "Touchdown").sum()))


def position_targets(pbp, positions):
    """Targets by receiver position, per (game, defense). positions: {gsis_id: 'WR'|'TE'|'RB'}."""
    p = offense_plays(pbp).filter((pl.col("pass_attempt") == 1) & (pl.col("sack") == 0)
                                  & pl.col("receiver_player_id").is_not_null())
    pos = pl.DataFrame({"receiver_player_id": list(positions), "rpos": list(positions.values())})
    p = p.join(pos, on="receiver_player_id", how="inner").filter(pl.col("rpos").is_in(["WR", "TE", "RB"]))
    return (p.group_by(["season", "week", "game_id", "posteam", "defteam", "rpos"])
            .agg(targets=pl.len(), completions=(pl.col("complete_pass") == 1).sum(),
                 yards=pl.col("receiving_yards").fill_null(0).sum(),
                 tds=(pl.col("pass_touchdown") == 1).sum(), ints=(pl.col("interception") == 1).sum()))


# ---------------------------------------------------------------- aggregation helpers ---------------
def _wsum(rows, key, weights):
    return sum((r.get(key) or 0) * weights.get(r["week"], 1.0) for r in rows)


def _ratio(rows, num, den, weights=None):
    w = weights or {}
    return safe_div(_wsum(rows, num, w), _wsum(rows, den, w))


TEAM_RATES = {
    # name: (numerator, denominator) summed over games
    "plays_pg": ("plays", "_games"),
    "pass_rate": ("dropbacks", "plays"),
    "proe": ("proe_sum", "xpass_n"),
    "scramble_rate": ("scrambles", "dropbacks"),
    "att_per_db": ("attempts", "dropbacks"),
    "sack_rate": ("sacks", "dropbacks"),
    "ypc": ("run_yds", "designed"),
    "run_epa": ("run_epa", "designed"),
    "stuff_rate": ("stuffs", "designed"),
    "explosive_run_rate": ("explosive_runs", "designed"),
    "ypa": ("pass_yds", "attempts"),
    "db_epa": ("db_epa", "dropbacks"),
    "comp_pct": ("completions", "attempts"),
    "pass_td_rate": ("pass_tds", "attempts"),
    "int_rate": ("ints", "attempts"),
}


def team_rates(rows, weights=None):
    rows = [dict(r, _games=1) for r in rows]
    return {k: _ratio(rows, a, b, weights) for k, (a, b) in TEAM_RATES.items()}


def by_team(df, col):
    out = {}
    for r in df.iter_rows(named=True):
        out.setdefault(r[col], []).append(r)
    return out


# ---------------------------------------------------------------- team profiles ---------------------
DEF_MULT = ("ypc", "stuff_rate", "explosive_run_rate", "ypa", "comp_pct", "pass_td_rate", "sack_rate", "int_rate")
DEF_ADD = ("run_epa", "db_epa")


def team_profiles(tg_cur, tg_prior, latest_week, rz_cur=None, rz_prior=None, pressures=None):
    """Offense and defense profiles per team.

    tg_*: team_games() output for this and last season. pressures: {team: (pressures, opp_dropbacks)}
    from PFR defender data. Returns {team: {"off": {...}, "def": {...}, "games": n}} where defensive
    numbers are 'allowed', opponent-adjusted ('adj') and blended with last season ('proj')."""
    weights = week_weights(set(tg_cur["week"].to_list()) if tg_cur.height else [], latest_week)
    off_cur, def_cur = by_team(tg_cur, "posteam"), by_team(tg_cur, "defteam")
    off_pri, def_pri = by_team(tg_prior, "posteam") if tg_prior is not None else {}, \
        by_team(tg_prior, "defteam") if tg_prior is not None else {}
    league = team_rates(tg_cur.to_dicts())
    teams = sorted(set(off_cur) | set(def_cur))
    off_raw = {t: team_rates(off_cur.get(t, []), weights) for t in teams}
    out = {}
    for t in teams:
        games = len(off_cur.get(t, []))
        o = off_raw[t]
        d_rows = def_cur.get(t, [])
        d = team_rates(d_rows, weights)
        # what the offenses this defense faced usually do (their own season rates), weighted like the games
        faced = {}
        for k in DEF_MULT + DEF_ADD:
            vals = [(off_raw.get(r["posteam"], {}).get(k), weights.get(r["week"], 1.0)) for r in d_rows]
            vals = [(v, w) for v, w in vals if v is not None]
            faced[k] = safe_div(sum(v * w for v, w in vals), sum(w for _, w in vals)) if vals else None
        adj = {}
        for k in DEF_MULT:
            adj[k] = d[k] * league[k] / faced[k] if d[k] is not None and faced[k] and league[k] else d[k]
        for k in DEF_ADD:
            adj[k] = d[k] - (faced[k] - league[k]) if d[k] is not None and faced[k] is not None else d[k]
        prior_o = team_rates(off_pri.get(t, [])) if off_pri.get(t) else {}
        prior_d = team_rates(def_pri.get(t, [])) if def_pri.get(t) else {}
        out[t] = {
            "games": games,
            "off": {k: v for k, v in o.items()},
            "off_proj": {k: blend(o[k], games, prior_o.get(k)) for k in o},
            "def": d,
            "def_adj": adj,
            "def_proj": {k: blend(adj[k], games, prior_d.get(k)) for k in adj},
        }
        if rz_cur is not None:
            rz_rows = [r for r in rz_cur.to_dicts() if r["defteam"] == t]
            rz = _ratio(rz_rows, "rz_td_drives", "rz_drives")
            out[t]["def"]["rz_td_pct"] = rz
            out[t]["def"]["rz_drives"] = sum(r["rz_drives"] for r in rz_rows)
            prior = None
            if rz_prior is not None:
                pr = [r for r in rz_prior.to_dicts() if r["defteam"] == t]
                prior = _ratio(pr, "rz_td_drives", "rz_drives")
            out[t]["def_proj"]["rz_td_pct"] = blend(rz, games, prior)
        if pressures and t in pressures:
            pr, dbs = pressures[t]
            out[t]["def"]["pressure_rate"] = safe_div(pr, dbs)
    return out, league


def position_allowed(pt_cur, latest_week, pt_prior=None, games=None):
    """Per defense and receiver position: yards/target, completion %, passer rating allowed (on targets).
    Opponent-adjusted yards/target uses each offense's own yards/target to that position."""
    weights = week_weights(set(pt_cur["week"].to_list()) if pt_cur.height else [], latest_week)
    rows = pt_cur.to_dicts()
    out = {}
    league = {}
    for pos in ("WR", "TE", "RB"):
        pr = [r for r in rows if r["rpos"] == pos]
        league[pos] = {"ypt": _ratio(pr, "yards", "targets"), "comp": _ratio(pr, "completions", "targets"),
                       "rating": passer_rating(*(sum(r[k] for r in pr) for k in ("completions", "targets", "yards", "tds", "ints")))}
        off_ypt = {}
        for team, rs in by_team(pl.DataFrame(pr) if pr else pl.DataFrame({"posteam": []}), "posteam").items():
            off_ypt[team] = _ratio(rs, "yards", "targets")
        prior_rows = [r for r in pt_prior.to_dicts() if r["rpos"] == pos] if pt_prior is not None else []
        for team in sorted({r["defteam"] for r in pr}):
            rs = [r for r in pr if r["defteam"] == team]
            tot = {k: _wsum(rs, k, {}) for k in ("targets", "completions", "yards", "tds", "ints")}
            ypt = _ratio(rs, "yards", "targets", weights)
            faced = [(off_ypt.get(r["posteam"]), weights.get(r["week"], 1.0) * r["targets"]) for r in rs]
            faced = [(v, w) for v, w in faced if v is not None]
            faced_avg = safe_div(sum(v * w for v, w in faced), sum(w for _, w in faced)) if faced else None
            adj = ypt * league[pos]["ypt"] / faced_avg if ypt is not None and faced_avg and league[pos]["ypt"] else ypt
            prs = [r for r in prior_rows if r["defteam"] == team]
            n = (games or {}).get(team)
            out.setdefault(team, {})[pos] = {
                "ypt": ypt, "ypt_adj": adj,
                "ypt_proj": blend(adj, n, _ratio(prs, "yards", "targets") if prs else None),
                "comp": _ratio(rs, "completions", "targets", weights),
                "comp_proj": blend(_ratio(rs, "completions", "targets", weights), n,
                                   _ratio(prs, "completions", "targets") if prs else None),
                "rating": passer_rating(tot["completions"], tot["targets"], tot["yards"], tot["tds"], tot["ints"]),
                "targets": tot["targets"],
            }
    return out, league


def coverage_from_pfr(pfr_def):
    """Team coverage totals from PFR's per-defender charting (targets, completions, yards, TDs, INTs
    where that defender was in coverage, plus missed tackles)."""
    out = {}
    if pfr_def is None or not pfr_def.height:
        return out
    g = (pfr_def.group_by("team").agg(
        targets=pl.col("def_targets").fill_null(0).sum(),
        completions=pl.col("def_completions_allowed").fill_null(0).sum(),
        yards=pl.col("def_yards_allowed").fill_null(0).sum(),
        tds=pl.col("def_receiving_td_allowed").fill_null(0).sum(),
        ints=pl.col("def_ints").fill_null(0).sum(),
        missed=pl.col("def_missed_tackles").fill_null(0).sum(),
        tackles=pl.col("def_tackles_combined").fill_null(0).sum(),
        pressures=pl.col("def_pressures").fill_null(0).sum()))
    for r in g.iter_rows(named=True):
        out[r["team"]] = {
            "cov_ypt": safe_div(r["yards"], r["targets"]),
            "cov_comp": safe_div(r["completions"], r["targets"]),
            "cov_rating": passer_rating(r["completions"], r["targets"], r["yards"], r["tds"], r["ints"]),
            "missed_tackle_pct": safe_div(r["missed"], r["missed"] + r["tackles"]),
            "pressures": r["pressures"],
        }
    return out


# ---------------------------------------------------------------- game script -----------------------
def script_model(tg):
    """Least-squares fit of a team's pass rate on its point spread (negative spread = favored), across
    team-games. Returns {'a', 'b', 'n'}: expected pass rate = a + b * team_spread (before team tendency)."""
    rows = [(r["team_spread"], r["dropbacks"] / r["plays"]) for r in tg.iter_rows(named=True)
            if r["team_spread"] is not None and r["plays"]]
    n = len(rows)
    if n < 10:
        return {"a": None, "b": None, "n": n}
    mx = sum(x for x, _ in rows) / n
    my = sum(y for _, y in rows) / n
    var = sum((x - mx) ** 2 for x, _ in rows)
    b = sum((x - mx) * (y - my) for x, y in rows) / var if var else 0.0
    return {"a": my - b * mx, "b": b, "n": n}


def td_per_point(tg, schedules):
    """Offensive TDs per point scored, league-wide, from completed games (turns an implied team total
    into expected offensive touchdowns)."""
    done = schedules.filter(pl.col("home_score").is_not_null() & (pl.col("game_type") == "REG"))
    games = set(done["game_id"].to_list())
    pts = sum(done["home_score"].to_list()) + sum(done["away_score"].to_list())
    tds = sum(r["off_tds"] for r in tg.iter_rows(named=True) if r["game_id"] in games)
    return safe_div(tds, pts)


def stat_sigmas(pg_prior, min_games=8):
    """Game-to-game spread of each stat as a lognormal sigma, from last season: for each regular player,
    sigma = sqrt(ln(1 + CV^2)) with CV = sd / mean of his games; the median across players. Used to price
    lines and Kalshi rungs away from the sportsbook line."""
    out = {}
    if pg_prior is None or not pg_prior.height:
        return out
    df = pg_prior.with_columns(scrim_yds=pl.col("rush_yds") + pl.col("rec_yds"))
    for stat, col, vol, floor in (("player_rush_yds", "rush_yds", "carries", 8), ("player_reception_yds", "rec_yds", "targets", 4),
                                  ("player_pass_yds", "pass_yds", "attempts", 20), ("player_receptions", "receptions", "targets", 4),
                                  ("player_pass_completions", "completions", "attempts", 20),
                                  ("player_pass_attempts", "attempts", "attempts", 20), ("player_rush_attempts", "carries", "carries", 8),
                                  ("player_rush_reception_yds", "scrim_yds", "carries", 8)):
        sig = []
        for _, rows in by_team(df.filter(pl.col(vol) > 0), "player_id").items():
            vals = [r[col] for r in rows]
            if len(vals) < min_games:
                continue
            mean = sum(vals) / len(vals)
            if mean < floor:
                continue  # part-timers' spread isn't the starters' spread
            var = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
            sig.append(math.sqrt(math.log(1 + var / mean ** 2)))
        out[stat] = {"sigma": median(sig) if sig else None, "n": len(sig)}
    return out


def game_spreads(schedules):
    """How far final margins and totals land from the closing spread / total (standard deviation), over
    completed games in the schedules given."""
    done = schedules.filter(pl.col("result").is_not_null() & pl.col("spread_line").is_not_null() & pl.col("total_line").is_not_null())
    m = [r["result"] - r["spread_line"] for r in done.iter_rows(named=True)]
    t = [r["total"] - r["total_line"] for r in done.iter_rows(named=True)]
    sd = lambda xs: math.sqrt(sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else None
    return {"margin": sd(m), "total": sd(t), "n": len(m)}


def td_split(pbp_list):
    """League-wide shape of offensive touchdowns, from play-by-play: the share that are rushing TDs, and
    for rushing and receiving TDs, the share scored on plays starting inside the opponent's 20."""
    rush = rush_rz = rec = rec_rz = 0
    for pbp in pbp_list:
        if pbp is None or not pbp.height:
            continue
        p = offense_plays(pbp)
        rz = pl.col("yardline_100") <= RZ
        c = p.select(rush=(pl.col("rush_touchdown") == 1).sum(), rush_rz=((pl.col("rush_touchdown") == 1) & rz).sum(),
                     rec=(pl.col("pass_touchdown") == 1).sum(), rec_rz=((pl.col("pass_touchdown") == 1) & rz).sum()).row(0, named=True)
        rush, rush_rz, rec, rec_rz = rush + c["rush"], rush_rz + c["rush_rz"], rec + c["rec"], rec_rz + c["rec_rz"]
    return {"rush_frac": safe_div(rush, rush + rec), "rush_rz_frac": safe_div(rush_rz, rush),
            "rec_rz_frac": safe_div(rec_rz, rec), "n": rush + rec}


# ---------------------------------------------------------------- player game table -----------------
def player_games(pbp):
    """One row per (game, player, team): rushing, receiving and passing volume and efficiency."""
    p = offense_plays(pbp)
    att = (pl.col("pass_attempt") == 1) & (pl.col("sack") == 0)
    rz = pl.col("yardline_100") <= RZ
    gl = pl.col("yardline_100") <= GL
    keys = ["season", "week", "game_id", "posteam", "defteam"]
    rush = (p.filter(pl.col("rush_attempt") == 1).group_by(keys + [pl.col("rusher_player_id").alias("player_id")])
            .agg(carries=pl.len(), rush_yds=pl.col("rushing_yards").fill_null(0).sum(),
                 rush_tds=(pl.col("rush_touchdown") == 1).sum(), rz_carries=rz.sum(), gl_carries=gl.sum(),
                 explosive=(pl.col("rushing_yards").fill_null(0) >= 10).sum(),
                 stuffed=(pl.col("rushing_yards").fill_null(0) <= 0).sum(),
                 designed=(pl.col("rush") == 1).sum(),
                 designed_yds=pl.when(pl.col("rush") == 1).then(pl.col("rushing_yards")).otherwise(0).fill_null(0).sum()))
    rec = (p.filter(att & pl.col("receiver_player_id").is_not_null())
           .group_by(keys + [pl.col("receiver_player_id").alias("player_id")])
           .agg(targets=pl.len(), receptions=(pl.col("complete_pass") == 1).sum(),
                rec_yds=pl.col("receiving_yards").fill_null(0).sum(),
                air_yards=pl.col("air_yards").fill_null(0).sum(),
                rec_tds=(pl.col("pass_touchdown") == 1).sum(), rz_targets=rz.sum(), gl_targets=gl.sum(),
                cp_sum=pl.col("cp").fill_null(0).sum(), cp_n=pl.col("cp").is_not_null().sum(),
                caught_cp=pl.when(pl.col("cp").is_not_null()).then(pl.col("complete_pass")).otherwise(0).sum()))
    qb = (p.filter((pl.col("pass") == 1) & pl.col("passer_id").is_not_null())
          .group_by(keys + [pl.col("passer_id").alias("player_id")])
          .agg(dropbacks=pl.len(), qb_epa=pl.col("qb_epa").fill_null(0).sum(),
               attempts=((pl.col("pass_attempt") == 1) & (pl.col("sack") == 0)).sum(),
               pass_yds=pl.when((pl.col("pass_attempt") == 1) & (pl.col("sack") == 0))
               .then(pl.col("passing_yards")).otherwise(0).fill_null(0).sum(),
               pass_tds=(pl.col("pass_touchdown") == 1).sum(), sacks=(pl.col("sack") == 1).sum(),
               completions=((pl.col("pass_attempt") == 1) & (pl.col("sack") == 0) & (pl.col("complete_pass") == 1)).sum(),
               ints=(pl.col("interception") == 1).sum(),
               cpoe_sum=pl.col("cpoe").fill_null(0).sum(), cpoe_n=pl.col("cpoe").is_not_null().sum()))
    rush, rec, qb = (x.with_columns(pl.col("player_id").cast(pl.Utf8)) for x in (rush, rec, qb))
    out = rush.join(rec, on=keys + ["player_id"], how="full", coalesce=True)
    out = out.join(qb, on=keys + ["player_id"], how="full", coalesce=True)
    num = [c for c, t in out.schema.items() if c not in keys + ["player_id"] and t.is_numeric()]
    return out.filter(pl.col("player_id").is_not_null()).with_columns([pl.col(c).fill_null(0) for c in num])


# ---------------------------------------------------------------- player profiles -------------------
PLAYER_SUMS = ("carries", "rush_yds", "rush_tds", "rz_carries", "gl_carries", "explosive", "stuffed", "designed",
               "designed_yds", "targets", "receptions", "rec_yds", "air_yards", "rec_tds", "rz_targets",
               "gl_targets", "cp_sum", "cp_n", "caught_cp", "dropbacks", "qb_epa", "attempts", "pass_yds",
               "pass_tds", "sacks", "cpoe_sum", "cpoe_n", "completions", "ints")
TEAM_SUMS = ("plays", "dropbacks", "carries", "targets", "air_yards", "attempts", "rz_carries", "rz_targets",
             "gl_carries", "gl_targets")


def _totals(rows, keys, weights=None):
    w = weights or {}
    return {k: sum((r.get(k) or 0) * w.get(r["week"], 1.0) for r in rows) for k in keys}


def player_rates(p, t):
    """Shares and efficiency from summed player (p) and team-in-same-games (t) totals."""
    touches = p["carries"] + p["receptions"]
    rz_opps = p["rz_carries"] + p["rz_targets"]
    return {
        "carry_share": safe_div(p["carries"], t["carries"]),
        "rz_carry_share": safe_div(p["rz_carries"], t["rz_carries"]),
        "gl_carry_share": safe_div(p["gl_carries"], t["gl_carries"]),
        "ypc": safe_div(p["rush_yds"], p["carries"]),
        "explosive_rate": safe_div(p["explosive"], p["carries"]),
        "stuff_rate": safe_div(p["stuffed"], p["carries"]),
        "target_share": safe_div(p["targets"], t["targets"]),
        "air_share": safe_div(p["air_yards"], t["air_yards"]),
        "rz_target_share": safe_div(p["rz_targets"], t["rz_targets"]),
        "adot": safe_div(p["air_yards"], p["targets"]),
        "ypt": safe_div(p["rec_yds"], p["targets"]),
        "catch_rate": safe_div(p["receptions"], p["targets"]),
        "croe": safe_div(p["caught_cp"] - p["cp_sum"], p["cp_n"]),
        "rz_opp_share": safe_div(rz_opps, t["rz_carries"] + t["rz_targets"]),
        "gl_opp_share": safe_div(p["gl_carries"] + p["gl_targets"], t["gl_carries"] + t["gl_targets"]),
        "td_per_touch": safe_div(p["rush_tds"] + p["rec_tds"], touches),
        "db_share": safe_div(p["dropbacks"], t["dropbacks"]),
        "epa_db": safe_div(p["qb_epa"], p["dropbacks"]),
        "cpoe": safe_div(p["cpoe_sum"], p["cpoe_n"]),
        "ypa": safe_div(p["pass_yds"], p["attempts"]),
        "sack_rate": safe_div(p["sacks"], p["dropbacks"]),
        "pass_td_rate": safe_div(p["pass_tds"], p["attempts"]),
        "comp_pct": safe_div(p["completions"], p["attempts"]),
        "int_rate": safe_div(p["ints"], p["attempts"]),
        "att_per_db": safe_div(p["attempts"], p["dropbacks"]),
    }


def player_profiles(pg_cur, tg_cur, latest_week, pg_prior=None, tg_prior=None, team_def=None):
    """Per player (gsis id): games, raw season totals, rates (recency-weighted), opponent-adjusted
    efficiency, last-season rates and blended ('proj') rates used by the projections."""
    weights = week_weights(set(pg_cur["week"].to_list()) if pg_cur.height else [], latest_week)
    team_by_game = {(r["game_id"], r["posteam"]): r for r in tg_cur.iter_rows(named=True)}
    prior_team = {(r["game_id"], r["posteam"]): r for r in tg_prior.iter_rows(named=True)} if tg_prior is not None else {}
    prior_rows = by_team(pg_prior, "player_id") if pg_prior is not None and pg_prior.height else {}
    team_def = team_def or {}
    out = {}
    for pid, rows in by_team(pg_cur, "player_id").items():
        trows = [team_by_game[(r["game_id"], r["posteam"])] for r in rows if (r["game_id"], r["posteam"]) in team_by_game]
        pt = _totals(rows, PLAYER_SUMS, weights)
        tt = _totals(trows, TEAM_SUMS, weights)
        rates = player_rates(pt, tt)
        raw = _totals(rows, PLAYER_SUMS)
        # opponent adjustment for per-carry and per-target yards: what the defenses faced allowed on average
        def faced(metric, vol):
            vals = [((team_def.get(r["defteam"]) or {}).get(metric), (r.get(vol) or 0) * weights.get(r["week"], 1.0)) for r in rows]
            vals = [(v, w) for v, w in vals if v is not None and w]
            return safe_div(sum(v * w for v, w in vals), sum(w for _, w in vals)) if vals else None
        adj = {}
        for metric, vol, key in (("ypc", "carries", "ypc"), ("ypa", "attempts", "ypa")):
            f = faced(metric, vol)
            lg = (team_def.get("_league") or {}).get(metric)
            adj[key] = rates[key] * lg / f if rates[key] is not None and f and lg else rates[key]
        f = faced("ypt_any", "targets")
        lg = (team_def.get("_league") or {}).get("ypt_any")
        adj["ypt"] = rates["ypt"] * lg / f if rates["ypt"] is not None and f and lg else rates["ypt"]
        prior = None
        if pid in prior_rows:
            prs = prior_rows[pid]
            ptr = [prior_team[(r["game_id"], r["posteam"])] for r in prs if (r["game_id"], r["posteam"]) in prior_team]
            prior = {"games": len(prs), **player_rates(_totals(prs, PLAYER_SUMS), _totals(ptr, TEAM_SUMS))}
        games = len(rows)
        proj = {}
        for k, v in {**rates, **adj}.items():
            pv = prior.get(k) if prior and prior["games"] >= SMALL_SAMPLE else None
            proj[k] = blend(v, games, pv)
        out[pid] = {"games": games, "team": rows[-1]["posteam"], "raw": raw, "rates": rates, "adj": adj,
                    "prior": prior, "proj": proj, "weeks": sorted(r["week"] for r in rows)}
    return out


def median_factors(pg_prior, min_games=8):
    """Typical game vs average game, per stat, from last season: the median over player-games of
    (game value / that player's season average). Yardage is right-skewed, so a typical game sits a bit
    below the average, and sportsbook lines are set near the typical game."""
    out = {}
    if pg_prior is None or not pg_prior.height:
        return out
    for stat, col, vol in (("player_rush_yds", "rush_yds", "carries"), ("player_reception_yds", "rec_yds", "targets"),
                           ("player_receptions", "receptions", "targets"), ("player_pass_yds", "pass_yds", "attempts"),
                           ("player_pass_completions", "completions", "attempts"), ("player_pass_attempts", "attempts", "attempts"),
                           ("player_rush_attempts", "carries", "carries"), ("player_rush_reception_yds", "scrim_yds", "carries")):
        ratios = []
        df = pg_prior.with_columns(scrim_yds=pl.col("rush_yds") + pl.col("rec_yds")) if "rec_yds" in pg_prior.columns else pg_prior
        if col not in df.columns:
            continue
        for _, rows in by_team(df.filter(pl.col(vol) > 0), "player_id").items():
            if len(rows) < min_games:
                continue
            mean = sum(r[col] for r in rows) / len(rows)
            if mean <= 0:
                continue
            ratios += [r[col] / mean for r in rows]
        out[stat] = {"factor": median(ratios) if ratios else None, "n": len(ratios)}
    return out
