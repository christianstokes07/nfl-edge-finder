"""Scheme matchups, game logs and pick grading for the "Why this pick" panel. Pure functions on polars
DataFrames, so tests can use tiny fixtures.

- Coverage (Cover 1/2/3/4/6, man vs zone) comes from nflverse participation, which is charted per pass
  play but only published through last season. So coverage tendencies and receiver-vs-coverage splits
  are LAST season's, and the page says so.
- Blitz and stacked-box tendencies come from FTN charting, which is published for this season."""
from collections import defaultdict
from datetime import datetime, timedelta

import polars as pl

from . import metrics as M
from .model import norm_name

COVERAGES = {"COVER_0": "Cover 0", "COVER_1": "Cover 1", "COVER_2": "Cover 2", "COVER_3": "Cover 3",
             "COVER_4": "Cover 4", "COVER_6": "Cover 6", "2_MAN": "2-Man"}
MIN_TARGETS = 8        # receiver vs a coverage: at least this many targets to show a split
MIN_DROPBACKS = 15     # QB vs blitz
MIN_CARRIES = 8        # RB vs stacked boxes


def _targets(pbp):
    p = M.offense_plays(pbp)
    return p.filter((pl.col("pass_attempt") == 1) & (pl.col("sack") == 0) & pl.col("receiver_player_id").is_not_null())


def coverage_profiles(part, pbp):
    """Returns (teams, receivers). teams[defense] = {"cov": {COVER_3: share, ...}, "man": share, "n": dropbacks
    charted}; receivers[gsis] = {key: [targets, yards per target]} for keys COVER_x / MAN / ZONE / ALL."""
    if part is None or pbp is None or not part.height:
        return {}, {}
    cov = part.select(pl.col("nflverse_game_id").alias("game_id"), pl.col("play_id").cast(pl.Int64),
                      "defense_coverage_type", "defense_man_zone_type")
    p = M.offense_plays(pbp).filter(pl.col("pass") == 1).select("game_id", "play_id", "defteam", "receiver_player_id",
                                                                  "pass_attempt", "sack", "receiving_yards") \
        .with_columns(pl.col("play_id").cast(pl.Int64))
    j = p.join(cov, on=["game_id", "play_id"], how="inner").filter(pl.col("defense_coverage_type").is_not_null())
    teams = {}
    for r in j.group_by(["defteam", "defense_coverage_type"]).len().iter_rows(named=True):
        teams.setdefault(r["defteam"], {"cov": {}, "n": 0})
        teams[r["defteam"]]["cov"][r["defense_coverage_type"]] = r["len"]
        teams[r["defteam"]]["n"] += r["len"]
    for r in j.group_by("defteam").agg(man=(pl.col("defense_man_zone_type") == "MAN_COVERAGE").sum(),
                                       mz=pl.col("defense_man_zone_type").is_in(["MAN_COVERAGE", "ZONE_COVERAGE"]).sum()).iter_rows(named=True):
        if r["defteam"] in teams:
            teams[r["defteam"]]["man"] = M.safe_div(r["man"], r["mz"])
    for t in teams.values():
        t["cov"] = {k: v / t["n"] for k, v in t["cov"].items() if k in COVERAGES}
    tg = j.filter((pl.col("pass_attempt") == 1) & (pl.col("sack") == 0) & pl.col("receiver_player_id").is_not_null())
    tg = tg.with_columns(pl.when(pl.col("defense_man_zone_type") == "MAN_COVERAGE").then(pl.lit("MAN"))
                         .when(pl.col("defense_man_zone_type") == "ZONE_COVERAGE").then(pl.lit("ZONE"))
                         .otherwise(None).alias("mz"))
    rec = defaultdict(dict)

    def add(df, key_col):
        for r in df.iter_rows(named=True):
            if r["n"] >= MIN_TARGETS and r[key_col] is not None:
                rec[r["receiver_player_id"]][r[key_col]] = [r["n"], r["yds"] / r["n"]]
    agg = dict(n=pl.len(), yds=pl.col("receiving_yards").fill_null(0).sum())
    add(tg.group_by(["receiver_player_id", "defense_coverage_type"]).agg(**agg).filter(pl.col("defense_coverage_type").is_in(list(COVERAGES))), "defense_coverage_type")
    add(tg.group_by(["receiver_player_id", "mz"]).agg(**agg), "mz")
    for r in tg.group_by("receiver_player_id").agg(**agg).iter_rows(named=True):
        if r["n"] >= MIN_TARGETS:
            rec[r["receiver_player_id"]]["ALL"] = [r["n"], r["yds"] / r["n"]]
    return teams, dict(rec)


def blitz_box_profiles(ftn, pbp):
    """From FTN charting (this season). Returns (teams, qbs, rbs):
    teams[defense] = {"blitz": share of dropbacks with 1+ blitzer, "box8": share of runs vs 8+ in the box}
    qbs[gsis] = {"blitz": [dropbacks, EPA/db], "no": [dropbacks, EPA/db]}; rbs[gsis] = {"box8": [carries, ypc], "lt8": [...]}"""
    if ftn is None or pbp is None or not ftn.height:
        return {}, {}, {}
    f = ftn.select(pl.col("nflverse_game_id").alias("game_id"), pl.col("nflverse_play_id").cast(pl.Int64).alias("play_id"),
                   "n_blitzers", "n_defense_box")
    p = M.offense_plays(pbp).select("game_id", "play_id", "defteam", "pass", "rush", "passer_id", "rusher_player_id",
                                    "epa", "rushing_yards").with_columns(pl.col("play_id").cast(pl.Int64))
    j = p.join(f, on=["game_id", "play_id"], how="inner")
    db = j.filter(pl.col("pass") == 1).with_columns(bl=pl.col("n_blitzers").fill_null(0) > 0)
    rn = j.filter(pl.col("rush") == 1).with_columns(st=pl.col("n_defense_box").fill_null(0) >= 8)
    teams = {}
    for r in db.group_by("defteam").agg(n=pl.len(), b=pl.col("bl").sum()).iter_rows(named=True):
        teams.setdefault(r["defteam"], {})["blitz"] = M.safe_div(r["b"], r["n"])
    for r in rn.group_by("defteam").agg(n=pl.len(), b=pl.col("st").sum()).iter_rows(named=True):
        teams.setdefault(r["defteam"], {})["box8"] = M.safe_div(r["b"], r["n"])
    qbs, rbs = defaultdict(dict), defaultdict(dict)
    for r in db.filter(pl.col("passer_id").is_not_null()).group_by(["passer_id", "bl"]).agg(
            n=pl.len(), epa=pl.col("epa").fill_null(0).sum()).iter_rows(named=True):
        if r["n"] >= MIN_DROPBACKS:
            qbs[r["passer_id"]]["blitz" if r["bl"] else "no"] = [r["n"], r["epa"] / r["n"]]
    for r in rn.filter(pl.col("rusher_player_id").is_not_null()).group_by(["rusher_player_id", "st"]).agg(
            n=pl.len(), y=pl.col("rushing_yards").fill_null(0).sum()).iter_rows(named=True):
        if r["n"] >= (MIN_CARRIES if r["st"] else MIN_CARRIES * 2):
            rbs[r["rusher_player_id"]]["box8" if r["st"] else "lt8"] = [r["n"], r["y"] / r["n"]]
    return teams, dict(qbs), dict(rbs)


LOG_FIELDS = {
    "QB": ("pass_yds", "attempts", "completions", "pass_tds", "ints", "rush_yds", "carries", "tds"),
    "RB": ("rush_yds", "carries", "rec_yds", "receptions", "targets", "tds"),
    "WR": ("rec_yds", "receptions", "targets", "rush_yds", "carries", "tds"),
}
LOG_FIELDS["TE"] = LOG_FIELDS["WR"]
LOG_GAMES = 8


def game_logs(pg, home_by_game):
    """Per player: his most recent games, newest last: [week, opponent, home(1/0), *LOG_FIELDS[pos]]."""
    out = defaultdict(list)
    for r in pg.sort(["week"]).iter_rows(named=True):
        out[r["player_id"]].append(r)
    logs = {}
    for pid, rows in out.items():
        logs[pid] = [{**r, "tds": (r.get("rush_tds") or 0) + (r.get("rec_tds") or 0),
                      "home": 1 if home_by_game.get(r["game_id"]) == r["posteam"] else 0} for r in rows[-LOG_GAMES:]]
    return logs


def season_averages(pg):
    """Per player, last season: games and per-game averages of the log fields."""
    out = {}
    keys = sorted({k for v in LOG_FIELDS.values() for k in v} - {"tds"})
    for pid, rows in M.by_team(pg, "player_id").items():
        n = len(rows)
        avg = {k: sum(r.get(k) or 0 for r in rows) / n for k in keys}
        avg["tds"] = sum((r.get("rush_tds") or 0) + (r.get("rec_tds") or 0) for r in rows) / n
        out[pid] = {"g": n, **avg}
    return out


# ------------------------------------------------------------------ grading the pick log --------------
STAT_COL = {"player_rush_yds": "rush_yds", "player_reception_yds": "rec_yds", "player_pass_yds": "pass_yds",
            "player_receptions": "receptions", "player_pass_completions": "completions", "player_pass_attempts": "attempts",
            "player_rush_attempts": "carries", "player_pass_tds": "pass_tds", "player_pass_interceptions": "ints"}
OVER = {"Over", "Yes", "YES"}


def grade(rows, pg, results, name_by_id, now=None):
    """Grade logged picks whose games are final. rows: dicts from data/picks_log.csv. results: list of
    {away, home (full names), away_score, home_score, kick (datetime)}. Keeps the last row logged before
    kickoff for each (game, player, stat, side). Returns graded rows: {..., hit: True/False}."""
    by_name_week = {}
    for r in pg.iter_rows(named=True):
        by_name_week[(norm_name(name_by_id.get(r["player_id"], "")), r["game_id"])] = r
    game_of = {}
    for g in results:
        game_of[(g["away"], g["home"], g["kick"].date())] = g
    latest = {}
    for r in rows:
        try:
            ts = datetime.fromisoformat(r["ts_utc"])
        except (KeyError, ValueError):
            continue
        away, _, home = (r.get("game") or "").partition(" @ ")
        g = None
        for d in range(0, 8):
            g = game_of.get((away, home, (ts + timedelta(days=d)).date()))
            if g:
                break
        if not g or g["kick"] < ts or g.get("home_score") is None:
            continue
        key = (g["game_id"], r.get("player"), r.get("stat"), r.get("side"))
        if key not in latest or latest[key][0] < ts:
            latest[key] = (ts, r, g)
    out = []
    for ts, r, g in latest.values():
        hit = _hit(r, g, by_name_week)
        if hit is not None:
            out.append({**r, "hit": hit})
    return out


def _hit(r, g, by_name_week):
    stat, side = r.get("stat"), r.get("side")
    margin = g["home_score"] - g["away_score"]
    try:
        line = float(r["line"]) if r.get("line") not in (None, "") else None
    except ValueError:
        line = None
    if stat == "game_total":
        tot = g["home_score"] + g["away_score"]
        return None if line is None or tot == line else (tot > line) == (side in OVER)
    if stat in ("game_ml", "game_spread"):
        team_home = side == g["home"]
        m = margin if team_home else -margin
        if stat == "game_ml":
            return None if m == 0 else m > 0
        return None if line is None or m + line == 0 else m + line > 0
    pr = by_name_week.get((norm_name(r.get("player") or ""), g["game_id"]))
    if pr is None:
        return None  # didn't play / not found: a void, not a loss
    if stat == "player_anytime_td":
        scored = (pr.get("rush_tds") or 0) + (pr.get("rec_tds") or 0) > 0
        return scored == (side in OVER)
    col = STAT_COL.get(stat)
    if col is None or line is None:
        return None
    val = pr.get(col) or 0
    if val == line:
        return None
    return (val > line) == (side in OVER)


def track_record(graded):
    """Summary for the page: overall, by stats verdict, by source, and calibration (does a 60% pick hit
    about 60% of the time?)."""
    def summ(rs):
        n = len(rs)
        if not n:
            return None
        exp = sum(float(r.get("hit_chance") or 0) for r in rs) / n
        return {"n": n, "hits": sum(1 for r in rs if r["hit"]), "expected": round(exp, 3)}
    by_v, by_src, cal = defaultdict(list), defaultdict(list), defaultdict(list)
    for r in graded:
        by_v[r.get("analytics") or "n/a"].append(r)
        by_src[r.get("source") or "?"].append(r)
        try:
            hc = float(r.get("hit_chance") or 0)
        except ValueError:
            continue
        lo = min(int(hc * 10) * 10, 90)
        cal[f"{lo}-{lo + 10}%"].append(r)
    return {"all": summ(graded), "verdict": {k: summ(v) for k, v in by_v.items()},
            "source": {k: summ(v) for k, v in by_src.items()},
            "calibration": {k: summ(v) for k, v in sorted(cal.items())}}
