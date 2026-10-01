import math
from src import model, kalshi, run


def test_devig_even():
    assert abs(model.devig_two_way(-110, -110) - 0.5) < 1e-9


def test_lognormal_anchors_to_line():
    # threshold = line + 0.5 must reproduce the book's over probability
    p = model.lognormal_p_at_least(66, 65.5, 0.52, 0.6)
    assert abs(p - 0.52) < 1e-6


def test_lower_threshold_is_more_likely():
    hi = model.lognormal_p_at_least(70, 65.5, 0.5, 0.6)
    lo = model.lognormal_p_at_least(55, 65.5, 0.5, 0.6)
    assert lo > 0.5 > hi


def test_parse_contract():
    m = {"title": "Jaylen Warren: 60+ rushing yards"}
    assert kalshi.parse_contract(m) == {"stat": "player_rush_yds", "threshold": 60.0}
    assert kalshi.parse_contract({"title": "Will X score a touchdown?"})["stat"] == "player_anytime_td"
    assert kalshi.parse_contract({"title": "X 70+ rushing and receiving yards"}) is None


def test_end_to_end_flags_underpriced_contract():
    lines = [
        {"player": "Jaylen Warren", "market": "player_rush_yds", "book": b, "point": 65.5,
         "prices": {"Over": -115, "Under": -105}, "game": "PIT @ CLE"}
        for b in ("draftkings", "fanduel")
    ]
    cheap = {"ticker": "T1", "title": "Jaylen Warren: 60+ rushing yards", "yes_bid": 40, "yes_ask": 43}
    fair = {"ticker": "T2", "title": "Jaylen Warren: 60+ rushing yards", "yes_bid": 60, "yes_ask": 62}
    picks, stats = run.evaluate(lines, [cheap, fair])
    assert [p["ticker"] for p in picks] == ["T1"] and picks[0]["side"] == "YES"
    assert stats["scored"] == 2


def test_universe_has_fair_uncertainty_and_game():
    lines = [
        {"player": "Jaylen Warren", "market": "player_rush_yds", "book": b, "point": 65.5,
         "prices": {"Over": -115, "Under": -105}, "game": "PIT @ CLE", "game_id": "g1"}
        for b in ("draftkings", "fanduel")
    ]
    u = []
    run.evaluate(lines, [{"ticker": "T1", "title": "Jaylen Warren: 60+ rushing yards", "yes_bid": 40, "yes_ask": 43}], u)
    assert u[0]["books"] == 2 and 0.02 <= u[0]["unc"] <= 0.08
    assert u[0]["ask"] == 43 and u[0]["g"] == "g1"


def test_season_long_kalshi_markets_are_skipped():
    # a real false match from an early scan: season rushing-TD leader read as an anytime-TD contract
    leader = {"ticker": "KXLEADERNFLRUSHTDS-27-CMCCAFFREY23",
              "title": "Will Christian McCaffrey have the most rushing touchdowns?"}
    assert kalshi.parse_contract(leader) is None
    assert kalshi.parse_contract({"ticker": "KXNFLSEASON-X", "title": "Bijan Robinson 1,500+ rushing yards this season"}) is None
    assert kalshi.parse_contract({"ticker": "KXNFLTD-26OCT01PITCLE-CLEQJUDKINS10-1",
                                  "title": "Will Quinshon Judkins score a touchdown?"})["stat"] == "player_anytime_td"


def test_only_player_prop_series_are_fetched():
    # 350+ NFL series exist; fetching them all got the scan rate-limited before the yardage series loaded
    assert kalshi.is_prop_series("KXNFLRECYDS", "Pro Football Receiving Yards")
    assert kalshi.is_prop_series("KXNFLREC", "Pro Football Player Receptions")
    assert kalshi.is_prop_series("KXNFLNEWPROP", "Pro Football Passing Yards")      # new ticker, known title
    assert not kalshi.is_prop_series("KXNFLSEASONRECYDS", "Receiving Yards")         # season-long
    assert not kalshi.is_prop_series("KXNFLWINS-NO", "Pro football wins New Orleans")
    assert not kalshi.is_prop_series("KXNFLMOSTRECYDS", "Pro Football Most Receiving Yards")
