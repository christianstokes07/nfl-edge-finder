from datetime import datetime, timezone

import pytest

pl = pytest.importorskip("polars")

from src import matchups as MU  # noqa: E402
from tests.test_metrics import BASE, df, pass_, run  # noqa: E402


def _pbp():
    rows = []
    for i in range(10):   # WR1 vs Cover 3: 10 targets, 12 yards each
        rows.append({**pass_("QB1", "WR1", 12, 8), "play_id": i, "defteam": "DEF"})
    for i in range(10, 20):  # WR1 vs Cover 1 (man): 10 targets, 4 yards each
        rows.append({**pass_("QB1", "WR1", 4, 8), "play_id": i, "defteam": "DEF"})
    for i in range(20, 30):
        rows.append({**run("RB1", 3), "play_id": i, "defteam": "DEF"})
    return df(rows)


def test_coverage_profiles():
    part = pl.DataFrame({"nflverse_game_id": ["G1"] * 20, "play_id": list(range(20)),
                         "defense_coverage_type": ["COVER_3"] * 10 + ["COVER_1"] * 10,
                         "defense_man_zone_type": ["ZONE_COVERAGE"] * 10 + ["MAN_COVERAGE"] * 10})
    teams, rec = MU.coverage_profiles(part, _pbp())
    assert teams["DEF"]["cov"] == {"COVER_3": 0.5, "COVER_1": 0.5} and teams["DEF"]["man"] == 0.5
    assert rec["WR1"]["COVER_3"] == [10, 12.0] and rec["WR1"]["MAN"] == [10, 4.0] and rec["WR1"]["ALL"] == [20, 8.0]


def test_blitz_and_box():
    ftn = pl.DataFrame({"nflverse_game_id": ["G1"] * 30, "nflverse_play_id": list(range(30)),
                        "n_blitzers": [1] * 15 + [0] * 15, "n_defense_box": [0] * 20 + [8] * 10})
    teams, qbs, rbs = MU.blitz_box_profiles(ftn, _pbp())
    assert teams["DEF"]["blitz"] == 0.75 and teams["DEF"]["box8"] == 1.0
    assert qbs["QB1"]["blitz"][0] == 15 and rbs["RB1"]["box8"] == [10, 3.0]


def test_game_log_and_grading():
    from src import metrics as M
    rows = [run("RB1", 30, week=1, game_id="G1", posteam="AAA", defteam="BBB", home_team="AAA"),
            run("RB1", 50, week=1, game_id="G1", posteam="AAA", defteam="BBB", home_team="AAA", rush_touchdown=1)]
    pg = M.player_games(df(rows))
    logs = MU.game_logs(pg, {"G1": "AAA"})
    assert logs["RB1"][0]["rush_yds"] == 80 and logs["RB1"][0]["home"] == 1 and logs["RB1"][0]["tds"] == 1
    kick = datetime(2026, 9, 13, 17, tzinfo=timezone.utc)
    results = [{"game_id": "G1", "week": 1, "away": "Bees", "home": "Aces", "away_score": 10, "home_score": 24, "kick": kick}]
    log = [  # logged Thursday, re-logged Sunday morning: only the later row counts
        {"ts_utc": "2026-09-10T16:00:00+00:00", "source": "book", "game": "Bees @ Aces", "player": "Runner One",
         "stat": "player_rush_yds", "line": "85.5", "side": "Over", "hit_chance": "0.55", "analytics": "agree"},
        {"ts_utc": "2026-09-13T16:15:00+00:00", "source": "book", "game": "Bees @ Aces", "player": "Runner One",
         "stat": "player_rush_yds", "line": "75.5", "side": "Over", "hit_chance": "0.52", "analytics": "agree"},
        {"ts_utc": "2026-09-13T16:15:00+00:00", "source": "book", "game": "Bees @ Aces", "player": "Runner One",
         "stat": "player_anytime_td", "line": "", "side": "Yes", "hit_chance": "0.40", "analytics": "neutral"},
        {"ts_utc": "2026-09-13T16:15:00+00:00", "source": "game", "game": "Bees @ Aces", "player": "", "stat": "game_spread",
         "line": "-6.5", "side": "Aces", "hit_chance": "0.5", "analytics": "n/a"},
        {"ts_utc": "2026-09-13T16:15:00+00:00", "source": "game", "game": "Bees @ Aces", "player": "", "stat": "game_total",
         "line": "37.5", "side": "Over", "hit_chance": "0.5", "analytics": "n/a"},
        {"ts_utc": "2026-09-13T18:00:00+00:00", "source": "book", "game": "Bees @ Aces", "player": "Runner One",
         "stat": "player_rush_yds", "line": "99.5", "side": "Over", "hit_chance": "0.3", "analytics": "agree"},  # after kickoff: ignored
    ]
    graded = MU.grade(log, pg, results, {"RB1": "Runner One"})
    by = {(g["stat"], g["line"]): g["hit"] for g in graded}
    assert by == {("player_rush_yds", "75.5"): True, ("player_anytime_td", ""): True,
                  ("game_spread", "-6.5"): True, ("game_total", "37.5"): False}
    tr = MU.track_record(graded)
    assert tr["all"]["n"] == 4 and tr["all"]["hits"] == 3 and tr["verdict"]["agree"] == {"n": 1, "hits": 1, "expected": 0.52}


def test_espn_injury_feed_parse():
    from src import injuries as INJ
    feed = {"timestamp": "2026-10-02T17:00:00Z", "injuries": [{"displayName": "Philadelphia Eagles", "injuries": [
        {"status": "Doubtful", "date": "2026-10-02T16:28Z", "athlete": {"displayName": "DeVonta Smith", "position": {"abbreviation": "WR"}},
         "details": {"type": "Hamstring"}, "shortComment": "Smith (hamstring) remained sidelined for Friday's practice."},
        {"status": "Active", "athlete": {"displayName": "Jalen Hurts", "position": {"abbreviation": "QB"}}}]},
        {"displayName": "Not A Team", "injuries": []}]}
    out = INJ.parse(feed)
    assert list(out) == ["PHI"] and out["PHI"] == [{"n": "DeVonta Smith", "pos": "WR", "s": "Doubtful", "d": "2026-10-02T16:28Z",
                                                    "i": "Hamstring", "c": "Smith (hamstring) remained sidelined for Friday's practice."}]
    assert INJ.by_name(out)[("PHI", "devonta smith")]["s"] == "Doubtful"
    assert "Doubtful" in INJ.OUT and "Questionable" not in INJ.OUT
