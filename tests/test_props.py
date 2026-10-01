import json
from datetime import datetime, timedelta, timezone

from src import config as C
from src import demo, model, odds, props, run


def _ln(book, point, over, under, player="Jaylen Warren", market="player_rush_yds"):
    return {"player": player, "market": market, "book": book, "point": point,
            "prices": {"Over": over, "Under": under}, "game": "PIT @ CLE", "game_id": "g1"}


def _build(lines):
    return props.build_props(lines, C.SIGMA, C.MAX_LINE_DISTANCE, C.ALT_LINE_DISTANCE, C.ANYTIME_TD_VIG)


def test_each_book_keeps_its_own_line_and_prices():
    lines = [_ln("draftkings", 65.5, -115, -105), _ln("fanduel", 65.5, -110, -110), _ln("betmgm", 66.5, -105, -115)]
    ps = {p["pt"]: p for p in _build(lines)}
    assert set(ps) == {65.5, 66.5}
    assert ps[65.5]["b"] == {"draftkings": [-115, -105], "fanduel": [-110, -110]}
    assert ps[66.5]["b"] == {"betmgm": [-105, -115]}
    # hit chance comes from all three books, even for the prop only BetMGM hangs
    assert ps[65.5]["n"] == 3 and ps[66.5]["n"] == 3
    # a higher line is harder to go over
    assert ps[66.5]["p"] < ps[65.5]["p"]


def test_consensus_is_no_vig_average():
    lines = [_ln("draftkings", 65.5, -115, -105), _ln("fanduel", 65.5, -110, -110)]
    (p,) = _build(lines)
    want = (model.devig_two_way(-115, -105) + 0.5) / 2
    assert abs(p["p"] - want) < 0.001


def test_anytime_td_yes_only_and_two_way():
    lines = [
        {"player": "Quinshon Judkins", "market": "player_anytime_td", "book": "draftkings", "point": None,
         "prices": {"Yes": 105}, "game_id": "g1"},
        {"player": "Quinshon Judkins", "market": "player_anytime_td", "book": "fanduel", "point": None,
         "prices": {"Yes": 100, "No": -130}, "game_id": "g1"},
    ]
    (p,) = _build(lines)
    assert p["pt"] is None and p["b"] == {"draftkings": [105, None], "fanduel": [100, -130]}
    yes_only = model.american_to_prob(105) / (1 + C.ANYTIME_TD_VIG)
    assert abs(p["p"] - (yes_only + model.devig_two_way(100, -130)) / 2) < 0.001


def test_alternate_lines_priced_off_main_consensus():
    lines = [_ln("draftkings", 65.5, -110, -110), _ln("fanduel", 65.5, -110, -110),
             {"player": "Jaylen Warren", "market": "player_rush_yds_alternate", "book": "draftkings",
              "point": 44.5, "prices": {"Over": -300}, "game_id": "g1"},
             {"player": "Jaylen Warren", "market": "player_rush_yds_alternate", "book": "draftkings",
              "point": 65.5, "prices": {"Over": -110}, "game_id": "g1"}]
    ps = _build(lines)
    alt = [p for p in ps if p["m"] == "player_rush_yds_alternate"]
    assert [p["pt"] for p in alt] == [44.5]          # the 65.5 alt duplicates the main line and is dropped
    assert alt[0]["p"] > 0.7 and alt[0]["b"] == {"draftkings": [-300, None]}
    # main-line consensus ignores alternate prices
    main = [p for p in ps if p["m"] == "player_rush_yds"][0]
    assert abs(main["p"] - 0.5) < 1e-6


def test_receptions_need_matching_points():
    lines = [_ln("draftkings", 4.5, -120, 100, market="player_receptions"),
             _ln("fanduel", 4.5, -115, -105, market="player_receptions"),
             _ln("betmgm", 5.5, 130, -160, market="player_receptions")]
    ps = {p["pt"]: p for p in _build(lines)}
    assert ps[4.5]["n"] == 2 and ps[5.5]["n"] == 1


def test_lines_from_props_round_trip():
    lines = [_ln("draftkings", 65.5, -115, -105), _ln("fanduel", 65.5, -110, -110)]
    ps = _build(lines)
    games = {"g1": {"a": "Pittsburgh Steelers", "h": "Cleveland Browns", "t": "2030-01-01T18:00:00Z"}}
    back = props.lines_from_props(ps, games)
    assert _build(back) == ps


def test_carry_forward_keeps_unfetched_markets_for_future_games():
    now = datetime(2026, 10, 4, 16, tzinfo=timezone.utc)
    prev = {"version": 2, "updated": "2026-10-01T16:00:00+00:00",
            "markets_updated": {"player_pass_yds": "2026-10-01T16:00:00+00:00"},
            "games": {"future": {"a": "A", "h": "B", "t": "2026-10-04T17:00:00Z"},
                      "past": {"a": "C", "h": "D", "t": "2026-10-02T00:15:00Z"}},
            "props": [{"player": "QB One", "g": "future", "stat": "player_pass_yds", "m": "player_pass_yds",
                       "pt": 230.5, "b": {"draftkings": [-110, -110]}},
                      {"player": "QB Two", "g": "past", "stat": "player_pass_yds", "m": "player_pass_yds",
                       "pt": 240.5, "b": {"draftkings": [-110, -110]}},
                      {"player": "RB", "g": "future", "stat": "player_rush_yds", "m": "player_rush_yds",
                       "pt": 60.5, "b": {"draftkings": [-110, -110]}}]}
    lines, games, updated = run.carry_forward(prev, {"player_rush_yds"}, now)
    assert [l["player"] for l in lines] == ["QB One"]   # rush yds re-fetched; past game dropped
    assert set(games) == {"future"} and updated == {"player_pass_yds": "2026-10-01T16:00:00+00:00"}


def test_site_data_lists_books_with_counts_and_stays_small():
    data = demo.build(now=datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
    books = {b["k"]: b for b in data["books"]}
    assert books["williamhill_us"]["name"] == "Caesars" and books["williamhill_us"]["paid"]
    assert books["williamhill_us"]["n"] == 0 and books["draftkings"]["n"] > 0
    assert all(p["g"] in data["games"] for p in data["props"])
    assert all(u["g"] in data["games"] for u in data["kalshi"])
    size = len(json.dumps(data, separators=(",", ":")))
    per_prop = size / len(data["props"])
    assert per_prop < 400, per_prop  # ~600 props on a full Sunday slate stays well under 300 KB


def test_bookmakers_fit_in_one_region():
    assert odds.region_units(C.BOOKMAKERS) == 1
    assert odds.region_units(",".join(f"b{i}" for i in range(11))) == 2
    assert odds.run_cost(16, C.ODDS_MARKETS, C.BOOKMAKERS) == 64


def test_line_moves_since_previous_scan():
    old = _build([_ln("draftkings", 60.5, -110, -110), _ln("fanduel", 60.5, -110, -110)])
    new = _build([_ln("draftkings", 65.5, -110, -110), _ln("fanduel", 65.5, -110, -110), _ln("betmgm", 64.5, -110, -110)])
    props.add_line_moves(new, old)
    assert {p["pt"]: p.get("mv") for p in new} == {64.5: [60.5, 65.5], 65.5: [60.5, 65.5]}
    same = _build([_ln("draftkings", 60.5, -110, -110)])
    assert "mv" not in props.add_line_moves(same, old)[0]


def test_pick_log_records_analytics_verdict(tmp_path, monkeypatch):
    log = tmp_path / "picks_log.csv"
    monkeypatch.setattr(C, "LOG_PATH", str(log))
    log.write_text("ts_utc,game,player,old,format\nx,y,z,1,2\n")            # old format gets rotated, not mixed
    a = json.loads((__import__("pathlib").Path(__file__).parent / "fixtures" / "analytics_mock.json").read_text())
    ps = _build([_ln("draftkings", 60.5, -110, -110), _ln("fanduel", 60.5, -115, -105)])  # Over favored
    games = {"g1": {"a": "Pittsburgh Steelers", "h": "Cleveland Browns", "t": "2030-01-01T18:00:00Z"}}
    rows = run.book_log_rows(ps, games)
    assert rows[0]["side"] == "Over" and rows[0]["price"] == -110 and rows[0]["where"] == "draftkings"  # best price
    run.log_picks([], rows, a)
    lines = log.read_text().splitlines()
    assert lines[0].split(",") == run.LOG_HEADER
    row = dict(zip(run.LOG_HEADER, lines[1].split(",")))
    # mock projection 68.4 vs line 60.5 -> 13% over: agree
    assert row["source"] == "book" and row["analytics"] == "agree" and row["projection"] == "68.4"
    assert (tmp_path / "picks_log_v1.csv").exists()
    # a game the analytics file doesn't cover -> n/a, not a guess
    v, proj = run.analytics_check(a, "Jaylen Warren", {"Detroit Lions", "Green Bay Packers"}, "player_rush_yds", "Over", 60.5, None)
    assert (v, proj) == ("n/a", "")
