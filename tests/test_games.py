import math

import pytest

from src import config as C
from src import games, kalshi, model, run, teams

EV = [{"id": "e1", "home_team": "Buffalo Bills", "away_team": "New England Patriots", "bookmakers": [
    {"key": "draftkings", "markets": [
        {"key": "h2h", "outcomes": [{"name": "Buffalo Bills", "price": -300}, {"name": "New England Patriots", "price": 240}]},
        {"key": "spreads", "outcomes": [{"name": "Buffalo Bills", "price": -110, "point": -6.5},
                                        {"name": "New England Patriots", "price": -110, "point": 6.5}]},
        {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 48.5}, {"name": "Under", "price": -110, "point": 48.5}]}]},
    {"key": "fanduel", "markets": [
        {"key": "spreads", "outcomes": [{"name": "Buffalo Bills", "price": -105, "point": -7.0},
                                        {"name": "New England Patriots", "price": -115, "point": 7.0}]}]}]}]


def test_parse_and_build_game_props():
    gl = games.parse_events(EV)
    assert {(l["market"], l["book"], l["point"]) for l in gl} == {
        ("h2h", "draftkings", None), ("spreads", "draftkings", -6.5), ("totals", "draftkings", 48.5), ("spreads", "fanduel", -7.0)}
    ps = {(p["m"], p["pt"]): p for p in games.build_game_props(gl, 12.7, 13.0)}
    assert ps[("h2h", None)]["p"] == pytest.approx(model.devig_two_way(-300, 240), abs=1e-3)
    assert ps[("totals", 48.5)]["p"] == pytest.approx(0.5, abs=1e-3)
    # both spread points get a hit chance from both books; -7 is harder to cover than -6.5
    assert ps[("spreads", -6.5)]["n"] == 2 and ps[("spreads", -7.0)]["n"] == 2
    assert ps[("spreads", -7.0)]["p"] < ps[("spreads", -6.5)]["p"]
    assert ps[("spreads", -6.5)]["b"] == {"draftkings": [-110, -110]}


def test_normal_model_anchors_to_book():
    assert model.normal_p_over(48.5, 48.5, 0.5, 13.0) == pytest.approx(0.5)
    assert model.normal_p_over(41.5, 48.5, 0.5, 13.0) > 0.65
    # home -6.5 at 50% means the expected home margin is 6.5
    assert model.normal_p_over(-(-6.5), -(-6.5), 0.5, 12.7) == pytest.approx(0.5)


def test_poisson_rate_round_trip():
    lam = model.poisson_rate(1.5, 0.45)
    assert 1 - math.exp(-lam) * (1 + lam) == pytest.approx(0.45, abs=1e-6)
    assert model.poisson_p_at_least(2, 1.5, 0.45) == pytest.approx(0.45, abs=1e-6)
    assert model.poisson_p_at_least(3, 1.5, 0.45) < 0.2


def test_kalshi_game_contracts_priced_from_game_lines():
    gl = games.parse_events(EV, {"e1": "g1"})
    gm = {"g1": {"a": "New England Patriots", "h": "Buffalo Bills", "t": "2030-01-01T18:00:00Z"}}
    mk = [{"ticker": "KXNFLGAME-26OCT04NEBUF-BUF", "title": "Buffalo wins", "_sub_title": "NE vs BUF (Oct 4)", "yes_bid": 70, "yes_ask": 72},
          {"ticker": "KXNFLGAME-26OCT04NEBUF-NE", "title": "New England wins", "_sub_title": "NE vs BUF (Oct 4)", "yes_bid": 27, "yes_ask": 29},
          {"ticker": "KXNFLSPREAD-26OCT04NEBUF-BUF7", "title": "BUF Bills wins by over 6.5 points?", "_sub_title": "NE vs BUF (Oct 4)", "yes_bid": 48, "yes_ask": 50},
          {"ticker": "KXNFLSPREAD-26OCT04NEBUF-NE4", "title": "NE Patriots wins by over 3.5 points?", "_sub_title": "NE vs BUF (Oct 4)", "yes_bid": 10, "yes_ask": 12},
          {"ticker": "KXNFLTOTAL-26OCT04NEBUF-45", "title": "Full Game: over 44.5 points scored?", "_sub_title": "NE vs BUF (Oct 4)", "yes_bid": 60, "yes_ask": 62}]
    u = []
    run.evaluate([], mk, u, gl, gm)
    by = {r["ticker"]: r for r in u}
    p_home = model.devig_two_way(-300, 240)
    assert by["KXNFLGAME-26OCT04NEBUF-BUF"]["fair"] == pytest.approx(p_home, abs=1e-3)
    assert by["KXNFLGAME-26OCT04NEBUF-NE"]["fair"] == pytest.approx(1 - p_home, abs=1e-3)
    assert by["KXNFLGAME-26OCT04NEBUF-BUF"]["team"] == "Buffalo Bills" and by["KXNFLGAME-26OCT04NEBUF-BUF"]["g"] == "g1"
    assert 0.45 < by["KXNFLSPREAD-26OCT04NEBUF-BUF7"]["fair"] < 0.52     # books: ~50% at -6.5/-7
    # underdog wins by 4+: home margin < -3.5. Averaged over the two books' spreads (-6.5 at 50%, -7 at ~51%)
    want = sum(model._N.cdf((-3.5 - mu) / 12.7) for mu in (6.5, 7.0 + 12.7 * model._N.inv_cdf(model.devig_two_way(-105, -115)))) / 2
    assert by["KXNFLSPREAD-26OCT04NEBUF-NE4"]["fair"] == pytest.approx(want, abs=2e-3)
    assert by["KXNFLTOTAL-26OCT04NEBUF-45"]["fair"] > 0.55                 # total 48.5 -> over 44.5 likely


def test_kalshi_only_stats_use_kalshi_price():
    lines = [{"player": "Deshaun Watson", "market": "player_pass_yds", "book": b, "point": 199.5,
              "prices": {"Over": -110, "Under": -110}, "game": "PIT @ CLE", "game_id": "g1"} for b in ("draftkings", "fanduel")]
    u = []
    run.evaluate(lines, [{"ticker": "A29", "title": "Deshaun Watson: 29+ passing attempts", "yes_bid": 53, "yes_ask": 54}], u)
    assert u == [{"ticker": "A29", "player": "Deshaun Watson", "g": "g1", "stat": "player_pass_attempts", "threshold": 29.0,
                  "fair": 0.535, "books": 0, "km": 1, "unc": 0.0, "bid": 53, "ask": 54}]


def test_team_names():
    assert teams.abbr("Jacksonville Jaguars") == "JAX" == teams.abbr("JAC")
    assert teams.abbr("LAR") == "LA" and teams.abbr("Nope") is None
    assert teams.by_text("Los Angeles C wins", ["Los Angeles Rams", "Los Angeles Chargers"]) is None   # ambiguous city
    assert teams.by_text("LAC Chargers", ["Los Angeles Rams", "Los Angeles Chargers"]) == "Los Angeles Chargers"


def test_kalshi_game_contract_without_book_lines_uses_kalshi_price():
    gm = {"g1": {"a": "New England Patriots", "h": "Buffalo Bills", "t": "2030-01-01T18:00:00Z"}}
    u = []
    run.evaluate([], [{"ticker": "KXNFLGAME-X-NE", "title": "New England wins", "_sub_title": "NE vs BUF (Oct 4)",
                       "yes_bid": 27, "yes_ask": 29}], u, [], gm)
    assert u[0]["km"] == 1 and u[0]["fair"] == 0.28 and u[0]["team"] == "New England Patriots" and u[0]["books"] == 0
