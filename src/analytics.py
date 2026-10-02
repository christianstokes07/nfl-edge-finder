"""Weekly analytics job: nflverse data -> site/analytics.json (the "Why this pick" panels).

python -m src.analytics                 # current season, upcoming week
python -m src.analytics --out PATH

Free data only (nflverse via nflreadpy, Open-Meteo for forecasts). The only paid-API call is the
optional Odds API fallback for spreads/totals (2 credits, only if nflverse has none for a game).
Every number written here comes from loaded data. Anything we couldn't compute is left out (null),
and the page shows "n/a" with the reason recorded under "sources" / "notes"."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import polars as pl

from . import context as X
from . import metrics as M
from . import injuries as INJ
from . import matchups as MU
from .model import norm_name
from . import project
from . import teams as teams_mod

OUT = os.environ.get("ANALYTICS_PATH", "site/analytics.json")
# order matters: rush+rec yards is built from the rushing and receiving projections before it
STATS_BY_POS = {
    "QB": ("player_pass_yds", "player_pass_tds", "player_pass_attempts", "player_pass_completions",
           "player_pass_interceptions", "player_rush_yds", "player_rush_attempts", "player_anytime_td"),
    "RB": ("player_rush_yds", "player_rush_attempts", "player_reception_yds", "player_receptions",
           "player_rush_reception_yds", "player_anytime_td"),
    "WR": ("player_reception_yds", "player_receptions", "player_anytime_td", "player_rush_yds", "player_rush_reception_yds"),
    "TE": ("player_reception_yds", "player_receptions", "player_anytime_td"),
}


# metrics kept per position (keeps the file small and the panels relevant)
SHOW = {
    "RB": ("carry_share", "snap_share", "carries_pg", "rz_carries", "gl_carries", "rz_carry_share", "ypc", "ypc_adj",
           "ryoe_att", "ybc", "explosive_rate", "stuff_rate", "target_share", "targets_pg", "ypt", "catch_rate",
           "yprr_proxy", "rz_targets", "rz_opp_share", "gl_opp_share", "td_per_touch", "tds", "touches_pg",
           "rush_yds_pg", "rec_yds_pg"),
    "WR": ("target_share", "air_share", "targets_pg", "tprr_proxy", "snap_share", "adot", "ypt", "ypt_adj", "yprr_proxy",
           "catch_rate", "croe", "separation", "cushion", "rz_targets", "rz_target_share", "rz_opp_share", "gl_opp_share",
           "td_per_touch", "tds", "touches_pg", "rec_yds_pg", "carries_pg", "ypc", "rush_yds_pg"),
    "QB": ("db_share", "dropbacks_pg", "epa_db", "cpoe", "ypa", "ypa_adj", "ttt", "sack_rate", "pressure_faced",
           "pass_yds_pg", "carries_pg", "carry_share", "rz_carries", "rz_carry_share", "gl_carries", "ypc", "rush_yds_pg",
           "tds", "gl_opp_share", "explosive_rate", "snap_share", "ryoe_att", "ybc", "stuff_rate",
           "comp_pct", "int_rate", "attempts_pg"),
}
SHOW["TE"] = SHOW["WR"]


IMG_BASE = "https://static.www.nfl.com/image/upload/"


def short_img(url):
    """Headshot URLs from nflverse player stats; the common NFL CDN prefix is stored once (img_base)."""
    if not url:
        return None
    return url[len(IMG_BASE):] if url.startswith(IMG_BASE) else url


def r3(x, nd=3):
    return None if x is None else round(float(x), nd)


# ------------------------------------------------------------------ loading --------------------------
class Sources:
    def __init__(self):
        self.info = {}

    def load(self, name, fn, *args, required=False, **kw):
        try:
            df = fn(*args, **kw)
        except Exception as e:  # noqa: BLE001
            self.info[name] = {"ok": False, "note": f"not available: {str(e)[:160]}"}
            if required:
                raise
            return None
        if df is None or not df.height:
            self.info[name] = {"ok": False, "note": "published but empty for this season so far"}
            return None
        weeks = sorted(set(df["week"].to_list())) if "week" in df.columns else None
        self.info[name] = {"ok": True, "rows": df.height, **({"weeks": [w for w in weeks if w]} if weeks else {})}
        return df


def cache_for(seconds):
    """With NFLREADPY_CACHE=filesystem, how old a cached download may be before it's fetched again.
    Last season's files never change (keep 30 days); this season's change daily (keep 6 hours)."""
    try:
        from nflreadpy.config import update_config
        update_config(cache_duration=seconds)
    except Exception:  # noqa: BLE001
        pass


def load_all(season, prior):
    import nflreadpy as nfl
    S = Sources()
    cache_for(30 * 86400)
    prior_d = {
        "sched_prior": S.load("schedules (last season)", nfl.load_schedules, [prior]),
        "pbp_prior": S.load("play-by-play (last season)", nfl.load_pbp, [prior]),
        "ps_prior": S.load("player stats (last season)", nfl.load_player_stats, [prior]),
        # coverage type per pass play (Cover 1/2/3...): published through last season only
        "part_prior": S.load("coverage charting (last season, participation)", nfl.load_participation, [prior]),
    }
    cache_for(6 * 3600)
    d = {
        **prior_d,
        "sched": S.load("schedules", nfl.load_schedules, [season], required=True),
        "pbp": S.load("play-by-play", nfl.load_pbp, [season]),
        "ps": S.load("player stats", nfl.load_player_stats, [season]),
        "rosters": S.load("weekly rosters", nfl.load_rosters_weekly, [season]),
        "snaps": S.load("snap counts", nfl.load_snap_counts, [season]),
        "ngs_rec": S.load("Next Gen Stats receiving", nfl.load_nextgen_stats, [season], stat_type="receiving"),
        "ngs_pass": S.load("Next Gen Stats passing", nfl.load_nextgen_stats, [season], stat_type="passing"),
        "ngs_rush": S.load("Next Gen Stats rushing", nfl.load_nextgen_stats, [season], stat_type="rushing"),
        "pfr_def": S.load("PFR defense charting", nfl.load_pfr_advstats, [season], stat_type="def", summary_level="week"),
        "pfr_rush": S.load("PFR rushing charting", nfl.load_pfr_advstats, [season], stat_type="rush", summary_level="week"),
        "pfr_pass": S.load("PFR passing charting", nfl.load_pfr_advstats, [season], stat_type="pass", summary_level="week"),
        "inj": S.load("injury reports", nfl.load_injuries, [season]),
        "ftn": S.load("FTN charting (blitzes, box counts)", nfl.load_ftn_charting, [season]),
        "teams": S.load("teams", nfl.load_teams),
    }
    # Participation (who was on the field each play) would give exact routes/pass snaps. Record whether
    # it exists for this season; we only use it as a status note (the proxies below don't need it).
    S.load("participation (per-play on-field players)", nfl.load_participation, [season])
    for k in ("ngs_rec", "ngs_pass", "ngs_rush"):
        if d[k] is not None:
            d[k] = M.fix_team(d[k], "team_abbr")
    return d, S.info


# ------------------------------------------------------------------ build ----------------------------
def _ranked(values, games=None):
    """{team: value} -> {team: [value, rank(1 = highest)]}"""
    ranks = M.rank_desc(values)
    return {t: [r3(v), ranks.get(t)] for t, v in values.items()}


def snap_info(snaps, rosters, tg):
    """Per gsis id: average offensive snap share and estimated pass-play snaps (team dropbacks x snap
    share, game by game). Also average defensive snap share (to spot injured defensive starters)."""
    out = {}
    if snaps is None or rosters is None:
        return out
    pfr2gsis = {r["pfr_id"]: r["gsis_id"] for r in rosters.select(["pfr_id", "gsis_id"]).unique().iter_rows(named=True)
                if r["pfr_id"] and r["gsis_id"]}
    # fallback when a roster row has no PFR id: same normalized name on the same team
    by_name = {(norm_name(r["full_name"] or ""), r["team"]): r["gsis_id"]
               for r in rosters.select(["full_name", "team", "gsis_id"]).unique().iter_rows(named=True) if r["gsis_id"]}
    db = {(r["game_id"], r["posteam"]): r["dropbacks"] for r in tg.iter_rows(named=True)}
    for r in snaps.filter(pl.col("game_type") == "REG").iter_rows(named=True):
        gid = pfr2gsis.get(r["pfr_player_id"]) or by_name.get((norm_name(r["player"] or ""), r["team"]))
        if not gid:
            continue
        o = out.setdefault(gid, {"off": [], "def": [], "pass_snaps": 0.0, "name": r["player"], "team": r["team"]})
        if (r["offense_snaps"] or 0) > 0:
            pct = r["offense_pct"] or 0
            pct = pct / 100 if pct > 1 else pct
            o["off"].append(pct)
            o["pass_snaps"] += db.get((r["game_id"], r["team"]), 0) * pct
        if (r["defense_snaps"] or 0) > 0:
            pct = r["defense_pct"] or 0
            o["def"].append(pct / 100 if pct > 1 else pct)
    return out


def injury_map(inj, week):
    """gsis id -> latest report for the upcoming week (falls back to the latest week published)."""
    if inj is None:
        return {}, None
    weeks = sorted(set(inj["week"].to_list()))
    use = week if week in weeks else weeks[-1]
    out = {}
    for r in inj.filter(pl.col("week") == use).iter_rows(named=True):
        out[r["gsis_id"]] = {"status": r["report_status"], "injury": r["report_primary_injury"] or r["practice_primary_injury"],
                             "practice": r["practice_status"], "name": r["full_name"], "pos": r["position"], "team": r["team"]}
    return out, use


def build(d, sources, now=None, odds_key=None, fetch_injuries=True):
    now = now or datetime.now(timezone.utc)
    sched = d["sched"]
    season = int(sched["season"][0])
    prior = season - 1
    week = X.upcoming_week(sched, now)
    notes = []
    pbp, pbp_prior = d["pbp"], d["pbp_prior"]
    if pbp is None:
        notes.append("No play-by-play for this season yet: everything below uses last season only.")
        pbp = pbp_prior.head(0)
    tg = M.team_games(pbp)
    tg_prior = M.team_games(pbp_prior) if pbp_prior is not None else None
    played = sorted(set(tg["week"].to_list()))
    latest = played[-1] if played else 0

    # positions/names (gsis id -> ...), from player stats (both seasons) then rosters
    info = {}
    for df in (d["ps_prior"], d["ps"]):
        if df is not None:
            cols = ["player_id", "player_display_name", "position", "team"] + (["headshot_url"] if "headshot_url" in df.columns else [])
            for r in df.select(cols).iter_rows(named=True):
                img = r.get("headshot_url") or (info.get(r["player_id"]) or {}).get("img")
                info[r["player_id"]] = {"name": r["player_display_name"], "pos": r["position"], "team": r["team"], "img": img}
    positions = {k: v["pos"] for k, v in info.items() if v["pos"] in ("WR", "TE", "RB", "QB")}

    rz = M.redzone_drives(pbp)
    rz_prior = M.redzone_drives(pbp_prior) if pbp_prior is not None else None
    cov = M.coverage_from_pfr(d["pfr_def"])
    # pressure rate generated: PFR pressures / opponent dropbacks in the same games
    pressures = {}
    if d["pfr_def"] is not None:
        pg = d["pfr_def"].group_by(["team", "game_id"]).agg(p=pl.col("def_pressures").fill_null(0).sum())
        dbs = {(r["game_id"], r["defteam"]): r["dropbacks"] for r in tg.iter_rows(named=True)}
        for r in pg.iter_rows(named=True):
            if (r["game_id"], r["team"]) in dbs:
                a = pressures.setdefault(r["team"], [0, 0])
                a[0] += r["p"]
                a[1] += dbs[(r["game_id"], r["team"])]
    teams_p, league = M.team_profiles(tg, tg_prior, latest, rz, rz_prior, pressures)
    games_by_team = {t: v["games"] for t, v in teams_p.items()}
    pt = M.position_targets(pbp, positions)
    pt_prior = M.position_targets(pbp_prior, positions) if pbp_prior is not None else None
    pos_allowed, league_pos = M.position_allowed(pt, latest, pt_prior, games_by_team)

    # defenses' raw per-play numbers, used to opponent-adjust player efficiency
    team_def = {t: {"ypc": v["def"]["ypc"], "ypa": v["def"]["ypa"]} for t, v in teams_p.items()}
    for t, rows in M.by_team(tg, "defteam").items():
        team_def.setdefault(t, {})["ypt_any"] = M.safe_div(sum(r["pass_yds"] for r in rows), sum(r["targets"] for r in rows))
    team_def["_league"] = {"ypc": league["ypc"], "ypa": league["ypa"],
                           "ypt_any": M.safe_div(sum(tg["pass_yds"].to_list()), sum(tg["targets"].to_list()))}
    pg_cur = M.player_games(pbp)
    pg_prior = M.player_games(pbp_prior) if pbp_prior is not None else None
    players_p = M.player_profiles(pg_cur, tg, latest, pg_prior, tg_prior, team_def)
    script = M.script_model(pl.concat([x for x in (tg_prior, tg) if x is not None and x.height]))
    sched_all = pl.concat([x for x in (d["sched_prior"], sched) if x is not None], how="diagonal_relaxed")
    tdpp = M.td_per_point(pl.concat([x for x in (tg_prior, tg) if x is not None and x.height]), sched_all)
    medf = M.median_factors(pg_prior)
    split = M.td_split([pbp_prior, pbp])
    sigmas = M.stat_sigmas(pg_prior)
    gsd = M.game_spreads(sched_all)
    snaps = snap_info(d["snaps"], d["rosters"], tg)
    inj, inj_week = injury_map(d["inj"], week)
    # ESPN's feed carries today's game designations (Doubtful, Out...) with a time and a news note: it wins
    espn, espn_note = (INJ.fetch() if fetch_injuries else ({}, "not fetched"))
    inj_src = "nflverse injury report (week %s)" % inj_week
    if espn:
        idx = {}
        for gid, v in info.items():
            idx[(v["team"], norm_name(v["name"] or ""))] = gid
        for gid, sv in snaps.items():
            idx.setdefault((sv["team"], norm_name(sv["name"] or "")), gid)
        # nickname fallback ("Hollywood Brown" = Marquise Brown): same team, last name and position, if unique
        by_last = {}
        for (team, nm), gid in idx.items():
            pos = (info.get(gid) or {}).get("pos")
            by_last.setdefault((team, nm.split(" ")[-1] if nm else "", pos), set()).add(gid)
        for (team, nm), e in INJ.by_name(espn).items():
            gid = idx.get((team, nm))
            if not gid:
                cands = by_last.get((team, nm.split(" ")[-1] if nm else "", e["pos"]), set())
                gid = next(iter(cands)) if len(cands) == 1 else None
            gid = gid or f"espn:{team}:{nm}"
            cur = inj.get(gid, {})
            inj[gid] = {**cur, "status": e["s"], "injury": e["i"] or cur.get("injury"), "practice": cur.get("practice"),
                        "name": e["n"], "pos": e["pos"] or cur.get("pos"), "team": team, "date": e["d"], "news": e["c"]}
        sources["ESPN injury feed (current designations)"] = {"ok": True, "rows": sum(len(v) for v in espn.values())}
        inj_src = "ESPN injury feed, " + now.strftime("%Y-%m-%d %H:%M UTC")
    else:
        sources["ESPN injury feed (current designations)"] = {"ok": False, "note": espn_note}

    # ---------------- game context for the upcoming week
    names = {}
    if d["teams"] is not None:
        names = {r["team_abbr"]: r["team_name"] for r in d["teams"].iter_rows(named=True)}
    games = {}
    week_games = sched.filter((pl.col("week") == week) & (pl.col("game_type") == "REG")) if week else sched.head(0)
    missing_lines = [g for g in week_games.iter_rows(named=True) if g["spread_line"] is None or g["total_line"] is None]
    odds_lines, odds_cost = {}, None
    if missing_lines and odds_key and os.environ.get("ANALYTICS_ODDS_FALLBACK", "1") != "0":
        try:
            odds_lines, odds_cost = X.odds_api_lines(odds_key, {v: k for k, v in names.items()})
            notes.append(f"Spreads/totals for {len(missing_lines)} games came from one Odds API call "
                         f"({odds_cost or 2} credits) because nflverse hadn't posted them.")
        except Exception as e:  # noqa: BLE001
            notes.append(f"Odds API fallback for spreads/totals failed: {type(e).__name__}.")
    for g in week_games.iter_rows(named=True):
        spread, total = g["spread_line"], g["total_line"]
        line_src = "nflverse"
        if (spread is None or total is None) and (g["home_team"], g["away_team"]) in odds_lines:
            spread, total = odds_lines[(g["home_team"], g["away_team"])]
            line_src = "Odds API"
        home_imp, away_imp = X.implied_totals(spread, total)
        kick = X.kickoff_utc(g["gameday"], g["gametime"])
        kind = X.roof_kind(g["roof"], g["stadium_id"])
        wx, wx_note = None, None
        if kind == "indoors":
            wx_note = "indoors"
        elif g["stadium_id"] in X.STADIUMS and kick:
            wx, wx_note = X.forecast(*X.STADIUMS[g["stadium_id"]], kick, now=now)
        else:
            wx_note = "no stadium location on file"
        for side, team, opp, imp, rest, orest in (("home", g["home_team"], g["away_team"], home_imp, g["home_rest"], g["away_rest"]),
                                                  ("away", g["away_team"], g["home_team"], away_imp, g["away_rest"], g["home_rest"])):
            tspread = None if spread is None else (-spread if side == "home" else spread)
            vol = project.team_volume(teams_p[team], tspread, script) if team in teams_p else None
            games[team] = {
                "opp": opp, "home": side == "home", "kick": kick.isoformat() if kick else None,
                "spread": r3(tspread, 1), "total": r3(total, 1), "implied": r3(imp, 1), "lines": line_src if spread is not None else None,
                "roof": kind, "stadium": g["stadium"], "wx": {k: r3(v, 0) for k, v in wx.items()} if wx else None, "wx_note": wx_note,
                "rest": rest, "opp_rest": orest, "div": bool(g["div_game"]),
                "vol": {k: r3(v, 3) for k, v in vol.items()} if vol else None,
                "tds": r3(imp * tdpp, 2) if imp is not None and tdpp else None,
            }

    # ---------------- team tables for the page
    t_out = {}
    def_keys = ("ypc", "run_epa", "stuff_rate", "explosive_run_rate", "ypa", "db_epa", "comp_pct", "sack_rate", "pass_td_rate")
    for k in def_keys:
        raw = {t: v["def"].get(k) for t, v in teams_p.items()}
        adj = {t: v["def_adj"].get(k) for t, v in teams_p.items()}
        ranks = M.rank_desc(adj)
        for t in teams_p:
            t_out.setdefault(t, {"name": names.get(t, t), "g": teams_p[t]["games"], "d": {}, "dp": {}, "o": {}})["d"][k] = \
                [r3(raw[t]), r3(adj[t]), ranks.get(t)]
    for k in ("rz_td_pct", "pressure_rate"):
        vals = {t: v["def"].get(k) for t, v in teams_p.items()}
        ranks = M.rank_desc(vals)
        for t in teams_p:
            t_out[t]["d"][k] = [r3(vals[t]), None, ranks.get(t)]
            if k == "rz_td_pct":
                t_out[t]["d"]["rz_drives"] = teams_p[t]["def"].get("rz_drives")
    for k in ("cov_ypt", "cov_comp", "cov_rating", "missed_tackle_pct"):
        vals = {t: (cov.get(t) or {}).get(k) for t in teams_p}
        ranks = M.rank_desc(vals)
        for t in teams_p:
            t_out[t]["d"][k] = [r3(vals[t]), None, ranks.get(t)]
    for pos in ("WR", "TE", "RB"):
        for k in ("ypt", "comp", "rating"):
            vals = {t: (pos_allowed.get(t, {}).get(pos) or {}).get(k) for t in teams_p}
            adjv = {t: (pos_allowed.get(t, {}).get(pos) or {}).get("ypt_adj") for t in teams_p} if k == "ypt" else vals
            ranks = M.rank_desc(adjv)
            for t in teams_p:
                t_out[t]["dp"].setdefault(pos, {})[k] = [r3(vals[t]), r3(adjv[t]) if k == "ypt" else None, ranks.get(t)]
            for t in teams_p:
                t_out[t]["dp"][pos]["n"] = (pos_allowed.get(t, {}).get(pos) or {}).get("targets")
    for k in ("plays_pg", "proe", "pass_rate", "db_epa", "run_epa", "ypa", "ypc", "sack_rate"):
        vals = {t: v["off"].get(k) for t, v in teams_p.items()}
        ranks = M.rank_desc(vals)
        for t in teams_p:
            t_out[t]["o"][k] = [r3(vals[t]), ranks.get(t)]

    # ---------------- players
    ngs = {}
    for key, df in (("rec", d["ngs_rec"]), ("pass", d["ngs_pass"]), ("rush", d["ngs_rush"])):
        if df is not None:
            for r in df.filter((pl.col("week") == 0) & (pl.col("season_type") == "REG")).iter_rows(named=True):
                ngs.setdefault(r["player_gsis_id"], {})[key] = r
    pfr2gsis = {}
    if d["rosters"] is not None:
        pfr2gsis = {r["pfr_id"]: r["gsis_id"] for r in d["rosters"].select(["pfr_id", "gsis_id"]).unique().iter_rows(named=True) if r["pfr_id"]}
    ybc, pressured = {}, {}
    if d["pfr_rush"] is not None:
        for r in d["pfr_rush"].iter_rows(named=True):
            gid = pfr2gsis.get(r["pfr_player_id"])
            if gid and r["carries"]:
                a = ybc.setdefault(gid, [0.0, 0])
                a[0] += r["rushing_yards_before_contact"] or 0
                a[1] += r["carries"]
    if d["pfr_pass"] is not None:
        qbdb = {(r["game_id"], r["player_id"]): r["dropbacks"] for r in pg_cur.iter_rows(named=True)}
        for r in d["pfr_pass"].iter_rows(named=True):
            gid = pfr2gsis.get(r["pfr_player_id"])
            dbn = qbdb.get((r["game_id"], gid))
            if gid and dbn and r["times_pressured"] is not None:
                a = pressured.setdefault(gid, [0, 0])
                a[0] += r["times_pressured"]
                a[1] += dbn
    # team totals in the games each player played (unweighted) for display shares
    tbg = {(r["game_id"], r["posteam"]): r for r in tg.iter_rows(named=True)}
    pg_rows = M.by_team(pg_cur, "player_id") if pg_cur.height else {}

    week_teams = set(games)
    disp = {}
    for pid, p in players_p.items():
        pos = (info.get(pid) or {}).get("pos")
        if pos not in M.POSITIONS:
            continue
        rows = pg_rows[pid]
        team_raw = M._totals([tbg[(r["game_id"], r["posteam"])] for r in rows if (r["game_id"], r["posteam"]) in tbg], M.TEAM_SUMS)
        rr = M.player_rates(p["raw"], team_raw)
        s = snaps.get(pid, {})
        n = p["games"]
        m = {
            "carry_share": rr["carry_share"], "rz_carries": p["raw"]["rz_carries"], "gl_carries": p["raw"]["gl_carries"],
            "rz_carry_share": rr["rz_carry_share"], "ypc": rr["ypc"], "ypc_adj": p["adj"]["ypc"],
            "explosive_rate": rr["explosive_rate"], "stuff_rate": rr["stuff_rate"],
            "carries_pg": M.safe_div(p["raw"]["carries"], n), "targets_pg": M.safe_div(p["raw"]["targets"], n),
            "target_share": rr["target_share"], "air_share": rr["air_share"], "adot": rr["adot"], "ypt": rr["ypt"],
            "ypt_adj": p["adj"]["ypt"], "catch_rate": rr["catch_rate"], "croe": rr["croe"], "rz_targets": p["raw"]["rz_targets"],
            "rz_opp_share": rr["rz_opp_share"], "rz_target_share": rr["rz_target_share"], "gl_opp_share": rr["gl_opp_share"], "td_per_touch": rr["td_per_touch"],
            "tds": p["raw"]["rush_tds"] + p["raw"]["rec_tds"], "touches_pg": M.safe_div(p["raw"]["carries"] + p["raw"]["receptions"], n),
            "db_share": rr["db_share"], "dropbacks_pg": M.safe_div(p["raw"]["dropbacks"], n), "epa_db": rr["epa_db"],
            "cpoe": rr["cpoe"], "ypa": rr["ypa"], "ypa_adj": p["adj"]["ypa"], "sack_rate": rr["sack_rate"],
            "comp_pct": rr["comp_pct"], "int_rate": rr["int_rate"], "attempts_pg": M.safe_div(p["raw"]["attempts"], n),
            "snap_share": (sum(s["off"]) / len(s["off"])) if s.get("off") else None,
            "yprr_proxy": M.safe_div(p["raw"]["rec_yds"], s.get("pass_snaps")) if s.get("pass_snaps") else None,
            "tprr_proxy": M.safe_div(p["raw"]["targets"], s.get("pass_snaps")) if s.get("pass_snaps") else None,
            "rec_yds_pg": M.safe_div(p["raw"]["rec_yds"], n), "rush_yds_pg": M.safe_div(p["raw"]["rush_yds"], n),
            "pass_yds_pg": M.safe_div(p["raw"]["pass_yds"], n),
        }
        nr = ngs.get(pid, {})
        if "rec" in nr:
            m["separation"], m["cushion"] = nr["rec"]["avg_separation"], nr["rec"]["avg_cushion"]
        if "pass" in nr:
            m["ttt"] = nr["pass"]["avg_time_to_throw"]
        if "rush" in nr:
            m["ryoe_att"] = nr["rush"]["rush_yards_over_expected_per_att"]
        if pid in ybc:
            m["ybc"] = M.safe_div(*ybc[pid])
        if pid in pressured:
            m["pressure_faced"] = M.safe_div(*pressured[pid])
        disp[pid] = (pos, m)

    # percentiles among qualified players at the same position
    def qualifies(pos, raw):
        return (raw["carries"] >= M.QUALIFY["carries"] if pos == "RB" else
                raw["dropbacks"] >= M.QUALIFY["dropbacks"] if pos == "QB" else raw["targets"] >= M.QUALIFY["targets"])
    pops = {}
    for pid, (pos, m) in disp.items():
        if qualifies(pos, players_p[pid]["raw"]):
            for k, v in m.items():
                pops.setdefault((pos, k), []).append(v)

    out_players = []
    for pid, (pos, m) in disp.items():
        p = players_p[pid]
        team = p["team"]
        if team not in week_teams:
            continue
        raw = p["raw"]
        if raw["carries"] < 5 and raw["targets"] < 4 and raw["dropbacks"] < 15:
            continue  # deep backups: books rarely post props for them
        g = games[team]
        opp = g["opp"]
        projs = {}
        for stat in STATS_BY_POS[pos]:
            if stat in ("player_rush_yds", "player_rush_reception_yds") and pos == "WR" and raw["carries"] < 5:
                continue
            pr = project.project_player(
                stat, p, g["vol"] and {k: g["vol"][k] for k in g["vol"]}, teams_p.get(opp, {}).get("def_proj", {}),
                (pos_allowed.get(opp) or {}).get(pos if pos in ("WR", "TE", "RB") else "WR"), league,
                league_pos.get(pos if pos in ("WR", "TE", "RB") else "WR"), pos, medf.get(stat),
                {"team_tds": g["tds"], "implied": g["implied"], "split": split, "parts": projs})
            if pr:
                projs[stat] = {k: (r3(v, 3) if not isinstance(v, dict) else {a: r3(b, 3) for a, b in v.items()})
                               for k, v in pr.items()}
        # metrics as an array in SHOW[pos] order (names are listed once under "mk"): [value, percentile] or null
        pm = []
        for k in SHOW[pos]:
            v = m.get(k)
            if v is None:
                pm.append(None)
                continue
            pct = M.percentile(v, pops.get((pos, k), [])) if len(pops.get((pos, k), [])) >= 8 else None
            pm.append([r3(v), pct])
        injr = inj.get(pid)
        out_players.append({
            "n": (info.get(pid) or {}).get("name"),
            "id": pid, "pos": pos, "t": team, "g": p["games"], "wk": p["weeks"],
            "img": short_img((info.get(pid) or {}).get("img")),
            "qual": qualifies(pos, raw), "m": pm, "pj": projs,
            "prior": {"g": p["prior"]["games"]} if p["prior"] else None,
            "inj": [injr["status"], injr["injury"], injr["practice"], injr.get("date"), injr.get("news")]
                   if injr and (injr["status"] or injr["practice"]) else None,
        })

    # ---------------- key injuries per team (offense: role players; defense: regular starters)
    roles = {}
    for pl_ in out_players:
        m = {k: v for k, v in zip(SHOW[pl_["pos"]], pl_["m"]) if v}
        role = []
        if pl_["pos"] == "QB" and (m.get("db_share") or [0])[0] >= 0.5:
            role.append(f"{round(m['db_share'][0] * 100)}% of dropbacks")
        if (m.get("target_share") or [0])[0] >= 0.15:
            role.append(f"{round(m['target_share'][0] * 100)}% target share")
        if (m.get("carry_share") or [0])[0] >= 0.3:
            role.append(f"{round(m['carry_share'][0] * 100)}% carry share")
        if role:
            roles[pl_["id"]] = ", ".join(role)
    inj_out = {}
    for gid, r in inj.items():
        if r["status"] not in INJ.OUT or r["team"] not in week_teams:
            continue
        s = snaps.get(gid, {})
        extra = {"d": r.get("date"), "c": r.get("news")}
        if gid in roles:
            inj_out.setdefault(r["team"], []).append({"n": r["name"], "pos": r["pos"], "s": r["status"], "i": r["injury"], "side": "off", "role": roles[gid], **extra})
        elif s.get("def") and sum(s["def"]) / len(s["def"]) >= 0.6:
            inj_out.setdefault(r["team"], []).append({"n": r["name"], "pos": r["pos"], "s": r["status"], "i": r["injury"], "side": "def",
                                                      "role": f"{round(100 * sum(s['def']) / len(s['def']))}% of defensive snaps", **extra})
    # Questionable players and other regulars, both sides of the ball (the panel's injury report)
    for gid, r in inj.items():
        if r["team"] not in week_teams or not r["status"] or (r["status"] in INJ.OUT and
                                                              any(x["n"] == r["name"] for x in inj_out.get(r["team"], []))):
            continue
        s = snaps.get(gid, {})
        off = sum(s["off"]) / len(s["off"]) if s.get("off") else 0
        dfn = sum(s["def"]) / len(s["def"]) if s.get("def") else 0
        if gid in roles or off >= 0.5 or dfn >= 0.5:
            side = "off" if (gid in roles or off >= dfn) else "def"
            role = roles.get(gid) or f"{round(100 * max(off, dfn))}% of {'offensive' if side == 'off' else 'defensive'} snaps"
            inj_out.setdefault(r["team"], []).append({"n": r["name"], "pos": r["pos"], "s": r["status"], "i": r["injury"],
                                                      "side": side, "role": role, "d": r.get("date"), "c": r.get("news")})
    order = {"Out": 0, "Injured Reserve": 0, "Suspension": 0, "Doubtful": 1, "Questionable": 2}
    for t in t_out:
        t_out[t]["out"] = sorted(inj_out.get(t, []), key=lambda x: (order.get(x["s"], 3), x["side"]))

    # ---------------- scheme matchups (coverage: last season; blitz / box: this season)
    cov_teams, cov_rec = MU.coverage_profiles(d.get("part_prior"), pbp_prior)
    bb_teams, qb_blitz, rb_box = MU.blitz_box_profiles(d.get("ftn"), pbp)
    for key in list(MU.COVERAGES) + ["MAN"]:
        vals = {t: (cov_teams.get(t) or {}).get("man") if key == "MAN" else ((cov_teams.get(t) or {}).get("cov") or {}).get(key)
                for t in teams_p}
        ranks = M.rank_desc(vals)
        for t in teams_p:
            if vals[t] is not None:
                t_out[t].setdefault("cov", {})[key] = [r3(vals[t]), ranks.get(t)]
    for key in ("blitz", "box8"):
        vals = {t: (bb_teams.get(t) or {}).get(key) for t in teams_p}
        ranks = M.rank_desc(vals)
        for t in teams_p:
            if vals[t] is not None:
                t_out[t][key] = [r3(vals[t]), ranks.get(t)]
    home_by_game = {r["game_id"]: r["home_team"] for r in tg.iter_rows(named=True)}
    logs = MU.game_logs(pg_cur, home_by_game)
    last_year = MU.season_averages(pg_prior) if pg_prior is not None else {}
    for pl_ in out_players:
        fields = MU.LOG_FIELDS[pl_["pos"]]
        pid = pl_["id"]
        pl_["log"] = [[r["week"], r["defteam"], r["home"]] + [round(r.get(f) or 0) for f in fields] for r in logs.get(pid, [])]
        if pid in last_year:
            pl_["ly"] = [last_year[pid]["g"]] + [round(last_year[pid][f], 1) for f in fields]
        if pid in cov_rec:
            pl_["cv"] = {k: [v[0], round(v[1], 1)] for k, v in cov_rec[pid].items()}
        if pid in qb_blitz:
            pl_["bz"] = {k: [v[0], round(v[1], 2)] for k, v in qb_blitz[pid].items()}
        if pid in rb_box:
            pl_["bx"] = {k: [v[0], round(v[1], 1)] for k, v in rb_box[pid].items()}

    # ---------------- final scores (bet grading on the page) and the pick log's track record
    results = []
    for g in sched.filter(pl.col("home_score").is_not_null() & (pl.col("game_type") == "REG")).iter_rows(named=True):
        results.append({"game_id": g["game_id"], "week": g["week"], "away": names.get(g["away_team"], g["away_team"]),
                        "home": names.get(g["home_team"], g["home_team"]), "away_score": g["away_score"],
                        "home_score": g["home_score"], "kick": X.kickoff_utc(g["gameday"], g["gametime"])})
    track = None
    log_path = os.environ.get("LOG_PATH", "data/picks_log.csv")
    if os.path.exists(log_path):
        import csv
        with open(log_path) as f:
            rows = list(csv.DictReader(f))
        if rows and "analytics" in rows[0]:
            graded = MU.grade(rows, pg_cur, results, {k: v["name"] for k, v in info.items()}, now)
            track = MU.track_record(graded)

    if "participation (per-play on-field players)" in sources and not sources["participation (per-play on-field players)"]["ok"]:
        notes.append("Per-play participation isn't published for this season, so routes and pass snaps are estimated "
                     "(team dropbacks x the player's snap share). YPRR and targets per pass snap are proxies.")
    if any(pl_["g"] < M.SMALL_SAMPLE for pl_ in out_players):
        notes.append(f"Fewer than {M.SMALL_SAMPLE} games played: player rates are blended with last season "
                     f"(last season counts as {M.PRIOR_GAMES:g} games).")
    if inj_week is not None and inj_week != week:
        notes.append(f"Injury report shown is from week {inj_week} (week {week} not published yet).")

    return {
        "version": 1, "generated": now.isoformat(timespec="seconds"), "season": season, "week": week,
        "played": played, "prior": prior, "inj_week": inj_week, "inj_src": inj_src,
        "script": {k: r3(v, 4) for k, v in script.items()}, "tdpp": r3(tdpp, 4),
        "mf": {k: {"factor": r3(v["factor"]), "n": v["n"]} for k, v in medf.items()},
        "league": {k: r3(v) for k, v in league.items()},
        "league_pos": {p: {k: r3(v) for k, v in x.items()} for p, x in league_pos.items()},
        "mk": SHOW, "nteams": len(teams_p), "img_base": IMG_BASE,
        "pop": {pos: sum(1 for pid, (p_, _) in disp.items() if p_ == pos and qualifies(pos, players_p[pid]["raw"]))
                for pos in M.POSITIONS},
        "td_split": {k: r3(v) for k, v in split.items()},
        "sigma": {k: r3(v["sigma"]) for k, v in sigmas.items()}, "sigma_n": {k: v["n"] for k, v in sigmas.items()},
        "game_sd": {"margin": r3(gsd["margin"], 2), "total": r3(gsd["total"], 2), "n": gsd["n"]},
        "sources": sources, "notes": notes, "games": games, "teams": t_out, "players": out_players,
        "logk": MU.LOG_FIELDS, "covk": MU.COVERAGES, "track": track,
        "results": [[r["week"], teams_mod.abbr(r["away"]) or r["away"], teams_mod.abbr(r["home"]) or r["home"],
                     r["away_score"], r["home_score"], r["kick"].strftime("%Y-%m-%d") if r["kick"] else None] for r in results],
        "consts": {"recency": M.RECENCY, "prior_games": M.PRIOR_GAMES, "small": M.SMALL_SAMPLE},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    ap.add_argument("--season", type=int)
    args = ap.parse_args()
    import nflreadpy as nfl
    season = args.season or nfl.get_current_season()
    d, sources = load_all(season, season - 1)
    data = build(d, sources, odds_key=os.environ.get("ODDS_API_KEY"))
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    size = os.path.getsize(args.out)
    print(f"[analytics] season {season} week {data['week']}: {len(data['players'])} players, "
          f"{len(data['games'])} teams playing, {size // 1024} KB -> {args.out}")
    for k, v in sources.items():
        print(f"  {'ok ' if v['ok'] else 'n/a'} {k}: {v.get('rows', v.get('note'))}")
    for n in data["notes"]:
        print("  note:", n)
    if size > 600_000:
        sys.exit("analytics.json is over 600 KB; trim before publishing")


if __name__ == "__main__":
    main()
