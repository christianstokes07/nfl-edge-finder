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


def test_universe_has_per_book_fair_and_uncertainty():
    lines = [
        {"player": "Jaylen Warren", "market": "player_rush_yds", "book": b, "point": 65.5,
         "prices": {"Over": -115, "Under": -105}, "game": "PIT @ CLE"}
        for b in ("draftkings", "fanduel")
    ]
    u = []
    run.evaluate(lines, [{"ticker": "T1", "title": "Jaylen Warren: 60+ rushing yards", "yes_bid": 40, "yes_ask": 43}], u)
    assert set(u[0]["by_book"]) == {"draftkings", "fanduel"} and 0.02 <= u[0]["unc"] <= 0.08
    assert u[0]["ask"] == 43
