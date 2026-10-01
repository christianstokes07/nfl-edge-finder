"""Metric calculations on tiny hand-built play-by-play, so every expected number can be checked by hand."""
import math
from datetime import datetime, timezone

import pytest

pl = pytest.importorskip("polars")

from src import context as X  # noqa: E402
from src import metrics as M  # noqa: E402
from src import project  # noqa: E402

BASE = dict(season=2026, season_type="REG", week=1, game_id="G1", posteam="AAA", defteam="BBB", home_team="AAA",
            spread_line=3.0, play_type="run", **{"pass": 0}, rush=1, qb_kneel=0, qb_spike=0, two_point_attempt=0,
            pass_attempt=0, sack=0, receiver_player_id=None, complete_pass=0, passing_yards=None, pass_touchdown=0,
            interception=0, air_yards=None, epa=0.0, rushing_yards=None, rush_attempt=1, qb_scramble=0,
            rush_touchdown=0, yardline_100=50, xpass=0.5, rusher_player_id=None, cp=None, passer_id=None,
            qb_epa=0.0, cpoe=None, receiving_yards=None, fixed_drive=1, fixed_drive_result="Punt")


def run(rusher, yds, **kw):
    return {**BASE, "rusher_player_id": rusher, "rushing_yards": yds, **kw}


def pass_(qb, rec, yds, air, complete=1, **kw):
    return {**BASE, "play_type": "pass", "pass": 1, "rush": 0, "rush_attempt": 0, "pass_attempt": 1,
            "passer_id": qb, "receiver_player_id": rec, "complete_pass": complete,
            "passing_yards": yds if complete else None, "receiving_yards": yds if complete else None,
            "air_yards": air, "xpass": 0.6, "cp": 0.7, "cpoe": (100 - 70) if complete else -70, **kw}


def sack(qb, **kw):
    return {**BASE, "play_type": "pass", "pass": 1, "rush": 0, "rush_attempt": 0, "pass_attempt": 1, "sack": 1,
            "passer_id": qb, "xpass": 0.9, **kw}


def scramble(qb, yds, **kw):
    return {**BASE, "play_type": "run", "pass": 1, "rush": 0, "rush_attempt": 1, "qb_scramble": 1,
            "passer_id": qb, "rusher_player_id": qb, "rushing_yards": yds, "xpass": 0.9, **kw}


def df(rows):
    return pl.DataFrame(rows, infer_schema_length=None)


GAME = [
    run("RB1", 12), run("RB1", 0, yardline_100=15), run("RB1", 4, yardline_100=3, rush_touchdown=1),
    run("RB2", -2),
    pass_("QB1", "WR1", 20, 15), pass_("QB1", "WR1", 0, 10, complete=0, yardline_100=18),
    pass_("QB1", "TE1", 8, 4), sack("QB1"), scramble("QB1", 6),
    {**BASE, "play_type": "no_play", "rush": 1},          # penalty: dropped
    {**run("RB1", 1), "qb_kneel": 1},                       # kneel: dropped
]


def test_team_game_counts():
    tg = M.team_games(df(GAME))
    r = tg.row(0, named=True)
    assert r["plays"] == 9                       # 4 runs + 3 passes + sack + scramble
    assert r["dropbacks"] == 5 and r["designed"] == 4
    assert r["carries"] == 5                     # designed runs + the scramble
    assert r["attempts"] == 3 and r["targets"] == 3 and r["sacks"] == 1
    assert r["run_yds"] == 14 and r["stuffs"] == 2 and r["explosive_runs"] == 1
    assert r["rz_carries"] == 2 and r["gl_carries"] == 1 and r["rz_targets"] == 1
    assert r["team_spread"] == -3.0              # home team, spread_line 3 = favored by 3


def test_player_rates_from_games():
    pg = M.player_games(df(GAME))
    tg = M.team_games(df(GAME))
    prof = M.player_profiles(pg, tg, latest_week=1)
    rb = prof["RB1"]["rates"]
    assert rb["carry_share"] == pytest.approx(3 / 5)
    assert rb["ypc"] == pytest.approx(16 / 3)
    assert rb["rz_carry_share"] == pytest.approx(1.0)
    assert rb["stuff_rate"] == pytest.approx(1 / 3) and rb["explosive_rate"] == pytest.approx(1 / 3)
    wr = prof["WR1"]["rates"]
    assert wr["target_share"] == pytest.approx(2 / 3)
    assert wr["adot"] == pytest.approx(12.5) and wr["ypt"] == pytest.approx(10)
    assert wr["air_share"] == pytest.approx(25 / 29)
    assert wr["croe"] == pytest.approx((1 - 1.4) / 2)   # 1 catch vs 0.7 + 0.7 expected
    qb = prof["QB1"]["rates"]
    assert qb["db_share"] == pytest.approx(1.0) and qb["sack_rate"] == pytest.approx(1 / 5)
    assert qb["ypa"] == pytest.approx(28 / 3)


def test_recency_shrinkage_and_ranks():
    assert M.week_weights([1, 2, 3], 3) == {1: pytest.approx(0.64), 2: pytest.approx(0.8), 3: 1.0}
    assert M.blend(0.30, 1, 0.20) == pytest.approx((0.30 + 3 * 0.20) / 4)
    assert M.blend(0.30, 3, None) == 0.30 and M.blend(None, 0, 0.2) == 0.2
    assert M.rank_desc({"a": 5, "b": 9, "c": 5, "d": None}) == {"b": 1, "a": 2, "c": 2, "d": None}
    assert M.percentile(5, [1, 2, 5, 9]) == 75 and M.percentile(None, [1]) is None
    assert M.passer_rating(20, 20, 400, 6, 0) == pytest.approx(158.333, abs=0.01)
    assert M.passer_rating(0, 10, 0, 0, 3) == pytest.approx(0.0)


def test_recent_games_count_more():
    rows = [run("RB1", 3, week=1, game_id="G1"), run("RB2", 3, week=1, game_id="G1"),
            run("RB1", 3, week=2, game_id="G2"), run("RB1", 3, week=2, game_id="G2"), run("RB2", 3, week=2, game_id="G2")]
    prof = M.player_profiles(M.player_games(df(rows)), M.team_games(df(rows)), latest_week=2)
    # weeks weighted 0.8 and 1.0: (0.8*1 + 1*2) / (0.8*2 + 1*3)
    assert prof["RB1"]["rates"]["carry_share"] == pytest.approx(2.8 / 4.6)


def test_defense_opponent_adjustment():
    # BBB's run defense faced AAA (who gains 6 ypc vs everyone) -> its 6 ypc allowed is adjusted down
    rows = [run("A", 6, game_id="G1", posteam="AAA", defteam="BBB"), run("A", 6, week=2, game_id="G2", posteam="AAA", defteam="CCC"),
            run("C", 2, week=1, game_id="G3", posteam="CCC", defteam="DDD"), run("C", 2, week=2, game_id="G4", posteam="CCC", defteam="DDD")]
    tg = M.team_games(df(rows))
    teams, league = M.team_profiles(tg, None, 2)
    assert league["ypc"] == pytest.approx(4.0)
    assert teams["BBB"]["def"]["ypc"] == pytest.approx(6.0)
    assert teams["BBB"]["def_adj"]["ypc"] == pytest.approx(6.0 * 4.0 / 6.0)
    assert teams["DDD"]["def_adj"]["ypc"] == pytest.approx(2.0 * 4.0 / 2.0)


def test_redzone_td_pct():
    rows = [run("A", 5, yardline_100=15, fixed_drive=1, fixed_drive_result="Touchdown"),
            run("A", 5, yardline_100=40, fixed_drive=2, fixed_drive_result="Punt"),
            run("A", 2, yardline_100=19, fixed_drive=3, fixed_drive_result="Field goal")]
    rz = M.redzone_drives(df(rows)).row(0, named=True)
    assert rz["rz_drives"] == 2 and rz["rz_td_drives"] == 1


def test_script_model_recovers_slope():
    rows = []
    for i, spread in enumerate([-10, -7, -3, 0, 3, 7, 10, -5, 5, 1, -1, 2]):
        rate = 0.6 + 0.01 * spread                     # underdogs pass more
        rows.append({"team_spread": float(spread), "plays": 100, "dropbacks": round(rate * 100)})
    m = M.script_model(pl.DataFrame(rows))
    assert m["b"] == pytest.approx(0.01, abs=1e-3) and m["a"] == pytest.approx(0.6, abs=0.01)


def test_median_factor_and_td_split():
    rows = []
    for wk, y in enumerate([40, 50, 60, 70, 200, 45, 55, 65], 1):
        rows.append({"player_id": "X", "rush_yds": y, "carries": 10, "rec_yds": 0, "targets": 0, "receptions": 0,
                     "pass_yds": 0, "attempts": 0})
    mf = M.median_factors(pl.DataFrame(rows))
    mean = sum([40, 50, 60, 70, 200, 45, 55, 65]) / 8
    assert mf["player_rush_yds"]["factor"] == pytest.approx(57.5 / mean)
    split = M.td_split([df([run("A", 3, yardline_100=3, rush_touchdown=1), run("A", 30, yardline_100=30, rush_touchdown=1),
                            pass_("Q", "W", 10, 8, yardline_100=10, pass_touchdown=1)])])
    assert split["rush_frac"] == pytest.approx(2 / 3) and split["rush_rz_frac"] == pytest.approx(0.5)
    assert split["rec_rz_frac"] == pytest.approx(1.0)


def test_projection_rushing_by_hand():
    team = {"off_proj": {"plays_pg": 60, "proe": 0.02, "scramble_rate": 0.05, "att_per_db": 0.9, "pass_rate": 0.6}}
    vol = project.team_volume(team, -3.0, {"a": 0.6, "b": 0.01})
    assert vol["pass_rate"] == pytest.approx(0.6 - 0.03 + 0.02)
    assert vol["carries"] == pytest.approx(60 * (1 - 0.59) + 60 * 0.59 * 0.05)
    player = {"proj": {"carry_share": 0.5, "ypc": 4.4}}
    pr = project.project_player("player_rush_yds", player, vol, {"ypc": 4.4}, None, {"ypc": 4.0}, None, "RB",
                                {"factor": 0.9})
    assert pr["mean"] == pytest.approx(0.5 * vol["carries"] * 4.4 * 1.1)
    assert pr["med"] == pytest.approx(pr["mean"] * 0.9)


def test_projection_anytime_td():
    player = {"proj": {"rz_carry_share": 0.6, "carry_share": 0.5, "rz_target_share": 0.1, "target_share": 0.1}}
    split = {"rush_frac": 0.4, "rush_rz_frac": 0.8, "rec_rz_frac": 0.7}
    pr = project.project_player("player_anytime_td", player, {"x": 1}, {}, None, {}, None, "RB", None,
                                {"team_tds": 2.5, "split": split})
    lam = 2.5 * (0.4 * (0.8 * 0.6 + 0.2 * 0.5) + 0.6 * 0.1)
    assert pr["p"] == pytest.approx(1 - math.exp(-lam))


def test_game_context_helpers():
    assert X.implied_totals(7.0, 50.5) == (28.75, 21.75)        # home favored by 7
    k = X.kickoff_utc("2026-10-04", "13:00")                    # EDT = UTC-4
    assert k == datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)
    assert X.kickoff_utc("2026-12-06", "13:00").hour == 18      # EST = UTC-5
    assert X.roof_kind("dome", "DET00") == "indoors" and X.roof_kind(None, "DAL00") == "retractable"
    assert X.roof_kind("outdoors", "BUF00") == "outdoors"
    sched = pl.DataFrame([{"game_type": "REG", "home_score": 20, "week": 3, "gameday": "2026-09-27", "gametime": "13:00"},
                          {"game_type": "REG", "home_score": None, "week": 4, "gameday": "2026-10-04", "gametime": "13:00"}])
    assert X.upcoming_week(sched, datetime(2026, 10, 1, tzinfo=timezone.utc)) == 4
    _, reason = X.forecast(0, 0, datetime(2026, 12, 1, tzinfo=timezone.utc), now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert "15 days" in reason
