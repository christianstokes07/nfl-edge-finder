import json
from datetime import datetime, timedelta, timezone

from src import config as C
from src import demo, model, odds, props, run


def _ln(book, point, over, under, player="Jaylen Warren", market="player_rush_yds"):
    return {"player": player, "market": market, "book": book, "point": point,
            "prices": {"Over": over, "Under": under}, "game": "PIT @ CLE", "game_id": "g1"}


def _build(lines):
    return props.build_props(lines, C.SIGMA, C.MAX_LINE_DISTANCE, C.ALT_LINE_DISTANCE, C.TD_CURVE)


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
    yes_only = model.yes_only_fair(105, C.TD_CURVE)
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


def test_receptions_priced_across_points():
    lines = [_ln("draftkings", 4.5, -120, 100, market="player_receptions"),
             _ln("fanduel", 4.5, -115, -105, market="player_receptions"),
             _ln("betmgm", 5.5, 130, -160, market="player_receptions")]
    ps = {p["pt"]: p for p in _build(lines)}
    # receptions are priced like yards now: every book's line moves to each point
    assert ps[4.5]["n"] == 3 and ps[5.5]["n"] == 3 and ps[5.5]["p"] < ps[4.5]["p"]


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
    assert odds.run_cost(16, C.ODDS_MARKETS, C.BOOKMAKERS) == 96   # 16 games x 6 markets x 1 region


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


def test_kalshi_rows_capped_per_game_and_prop_type(monkeypatch):
    # a slate full of tight markets elsewhere must not squeeze a game's category out (SNF receiving was empty);
    # within a game+prop, players take turns so one player's ladder doesn't use up the cap
    monkeypatch.setattr(C, "KALSHI_ROWS_PER_GAME_STAT", 3)
    uni = [{"ticker": f"A{i}", "player": "Star", "stat": "player_reception_yds", "g": "g1", "bid": 40, "ask": 41} for i in range(6)] + \
          [{"ticker": f"B{i}", "player": "Slot", "stat": "player_reception_yds", "g": "g1", "bid": 40, "ask": 43} for i in range(2)] + \
          [{"ticker": f"S{i}", "player": "Late", "stat": "player_reception_yds", "g": "snf", "bid": 30, "ask": 37} for i in range(2)]
    data = run.site_data([], {}, uni, [], {"g1": {}, "snf": {}})
    got = [u["ticker"] for u in data["kalshi"]]
    assert sorted(got) == ["A0", "A1", "B0", "S0", "S1"]


def test_kalshi_ladder_rungs_far_from_line_are_priced():
    # a 30+ rung vs a 55.5 line is 46% away: priced (with a bigger safety margin), not dropped
    lines = [_ln(b, 55.5, -110, -110) for b in ("draftkings", "fanduel")]
    u = []
    run.evaluate(lines, [{"ticker": "R30", "title": "Jaylen Warren: 30+ rushing yards", "yes_bid": 80, "yes_ask": 82}], u)
    assert len(u) == 1 and u[0]["fair"] > 0.8 and u[0]["unc"] > 0.05


def test_kalshi_refresh_reprices_without_odds_api(tmp_path, monkeypatch):
    path = tmp_path / "data.json"
    ps = _build([_ln("draftkings", 55.5, -110, -110), _ln("fanduel", 55.5, -110, -110)])
    games = {"g1": {"a": "Pittsburgh Steelers", "h": "Cleveland Browns", "t": "2030-01-01T18:00:00Z"}}
    old = run.site_data([], {}, [], ps, games, {}, datetime(2026, 10, 1, 13, tzinfo=timezone.utc))
    run.write_site(old, str(path))
    monkeypatch.setattr(run.odds, "event_props", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Odds API called")))
    mk = [{"ticker": "R40", "title": "Jaylen Warren: 40+ rushing yards", "yes_bid": 60, "yes_ask": 62}]
    new = run.kalshi_refresh(str(path), markets=mk)
    assert [u["ticker"] for u in new["kalshi"]] == ["R40"] and new["kalshi"][0]["stat"] == "player_rush_yds"
    assert new["updated"] == old["updated"] and new["props"] == old["props"] and "kalshi_updated" in new


def test_kalshi_refresh_keeps_data_when_kalshi_is_down(tmp_path):
    path = tmp_path / "data.json"
    old = run.site_data([], {}, [{"ticker": "R40", "stat": "player_rush_yds", "g": "g1", "bid": 60, "ask": 62}],
                        [], {"g1": {"a": "A", "h": "B", "t": "2030-01-01T18:00:00Z"}}, {}, datetime(2026, 10, 1, 13, tzinfo=timezone.utc))
    run.write_site(old, str(path))
    before = path.read_text()
    assert run.kalshi_refresh(str(path), markets=[]) is None
    assert path.read_text() == before


def test_td_curve_shades_longshots_more_than_favorites():
    fav, longshot = model.yes_only_fair(-340, C.TD_CURVE), model.yes_only_fair(400, C.TD_CURVE)
    assert abs(fav - model.american_to_prob(-340) * 0.93) < 1e-9          # capped at 93% of the implied chance
    assert abs(longshot - 0.2 * (C.TD_CURVE[0] + C.TD_CURVE[1] * 0.2)) < 1e-9
    assert fav / model.american_to_prob(-340) > longshot / 0.2
    assert abs(model.yes_only_fair(150, 0.12) - 0.4 / 1.12) < 1e-9        # flat cut still available


def test_fit_td_curve_from_kalshi_pairs():
    pairs = [(x, x * (0.8 + 0.2 * x)) for x in [0.05 + 0.02 * i for i in range(35)]]
    a, b, lo, hi, n = model.fit_td_curve(pairs)
    assert n == 35 and abs(a - 0.8) < 1e-9 and abs(b - 0.2) < 1e-9
    assert model.fit_td_curve(pairs[:10]) is None                            # too few to trust


def test_td_refit_ignores_games_in_progress(monkeypatch):
    from datetime import timedelta
    now = datetime(2026, 10, 4, 20, tzinfo=timezone.utc)
    lines, markets = [], []
    for i in range(40):
        live = i < 20                                   # first 20 players' games already started
        kick = (now - timedelta(hours=1) if live else now + timedelta(hours=5)).isoformat()
        for b in ("dk", "fd", "mgm", "cz"):
            lines.append({"player": f"Player {i}", "market": "player_anytime_td", "book": b, "point": None,
                          "prices": {"Yes": 150}, "kick": kick})
        mid = 2 if live else 34                        # live games: Kalshi already near 0
        markets.append({"ticker": f"T{i}", "title": f"Will Player {i} score a touchdown?", "yes_bid": mid, "yes_ask": mid + 1})
    monkeypatch.setattr(C, "TD_CURVE", C.TD_CURVE)
    fit = run.refit_td_curve(lines, markets, now)
    assert fit is None                                   # only 20 not-started players: below the 30 needed
    assert C.TD_CURVE == C.TD_CURVE
