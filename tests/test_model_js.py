"""site/model.js (custom lines on the page) must give the same hit chance as the Python scan."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from src import config as C
from src import games, model, props, run


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_custom_line_pricing_matches_python(tmp_path):
    def ln(book, pt, o, u, market="player_rush_yds", player="Jaylen Warren"):
        return {"player": player, "market": market, "book": book, "point": pt, "prices": {"Over": o, "Under": u}, "game_id": "g1"}
    lines = [ln("draftkings", 65.5, -115, -105), ln("fanduel", 66.5, -110, -110), ln("betmgm", 64.5, -105, -115),
             ln("draftkings", 4.5, -120, 100, "player_receptions"), ln("fanduel", 5.5, 130, -160, "player_receptions"),
             ln("draftkings", 1.5, 120, -150, "player_pass_tds", "QB One"), ln("fanduel", 1.5, 110, -140, "player_pass_tds", "QB One"),
             {"player": "Jaylen Warren", "market": "player_anytime_td", "book": "draftkings", "point": None, "prices": {"Yes": 140}, "game_id": "g1"},
             {"player": "Jaylen Warren", "market": "player_anytime_td", "book": "fanduel", "point": None, "prices": {"Yes": 130, "No": -170}, "game_id": "g1"}]
    ps = props.build_props(lines, C.SIGMA, C.MAX_LINE_DISTANCE, C.ALT_LINE_DISTANCE, C.ANYTIME_TD_VIG)
    gl = [{"g": "g1", "market": "h2h", "book": "dk", "point": None, "prices": [-300, 240]},
          {"g": "g1", "market": "spreads", "book": "dk", "point": -6.5, "prices": [-110, -110]},
          {"g": "g1", "market": "spreads", "book": "fd", "point": -7.0, "prices": [-105, -115]},
          {"g": "g1", "market": "totals", "book": "dk", "point": 48.5, "prices": [-110, -110]},
          {"g": "g1", "market": "totals", "book": "fd", "point": 47.5, "prices": [-115, -105]}]
    gp = games.build_game_props(gl, C.MARGIN_SD, C.TOTAL_SD)
    D = run.site_data([], {}, [], ps, {"g1": {"a": "New England Patriots", "h": "Buffalo Bills", "t": "x"}}, {}, None, gp)
    D = json.loads(json.dumps(D))

    def py_player(stat, line, player="Jaylen Warren"):
        mains = [l for l in lines if l["market"] == stat and l["player"] == player]
        thr = 1.0 if stat == "player_anytime_td" else float(int(line) + 1)
        p, _ = model.fair_probability(stat, thr, mains, C.SIGMA, C.KALSHI_LINE_DISTANCE, C.ANYTIME_TD_VIG)
        return p
    cases, want = [], []
    for line in (40.5, 52.5, 65.5, 66.5, 80.5, 95.5):
        cases.append({"kind": "player", "player": "Jaylen Warren", "stat": "player_rush_yds", "side": "Over", "line": line})
        want.append(py_player("player_rush_yds", line))
        cases.append({"kind": "player", "player": "Jaylen Warren", "stat": "player_rush_yds", "side": "Under", "line": line})
        want.append(1 - py_player("player_rush_yds", line))
    for line in (3.5, 4.5, 5.5, 6.5):
        cases.append({"kind": "player", "player": "Jaylen Warren", "stat": "player_receptions", "side": "Over", "line": line})
        want.append(py_player("player_receptions", line))
    for line in (0.5, 1.5, 2.5):
        cases.append({"kind": "player", "player": "QB One", "stat": "player_pass_tds", "side": "Over", "line": line})
        want.append(py_player("player_pass_tds", line, "QB One"))
    cases.append({"kind": "player", "player": "Jaylen Warren", "stat": "player_anytime_td", "side": "Yes", "line": None})
    want.append(py_player("player_anytime_td", None))
    for team, line, kind in (("Buffalo Bills", -3.5, "game_spread"), ("New England Patriots", 10.5, "game_spread"),
                             ("Buffalo Bills", None, "game_ml"), (None, 44.5, "game_total"), (None, 51.5, "game_total")):
        side = "Over" if kind == "game_total" else team
        cases.append({"kind": "game", "g": "g1", "stat": kind, "team": team, "side": side, "line": line})
        if kind == "game_ml":
            want.append(games.fair("h2h", gl, None, C.MARGIN_SD, C.TOTAL_SD)[0])
        elif kind == "game_total":
            want.append(games.fair("totals", gl, line, C.MARGIN_SD, C.TOTAL_SD)[0])
        else:
            home = team == "Buffalo Bills"
            p, _ = games.fair("spreads", gl, line if home else -line, C.MARGIN_SD, C.TOTAL_SD)
            want.append(p if home else 1 - p)
    f = tmp_path / "cases.json"
    f.write_text(json.dumps({"D": D, "cases": cases}))
    out = subprocess.run(["node", str(Path(__file__).with_name("model_parity.js")), str(f)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    for c, g, w in zip(cases, got, want):
        assert w is not None and g is not None and abs(g - w) < 1e-5, (c, g, w)
