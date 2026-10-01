"""Fake-but-realistic data for previewing the page without spending Odds API credits.

python -m src.demo                      -> writes site/demo-data.json (open the page with ?demo)
python -m src.demo --out some/path.json

DraftKings and FanDuel get alternate yardage lines in the demo so you can see what they look like.
Real scans only include them if you add *_alternate markets to ODDS_MARKETS (they cost extra credits).

The numbers are made up. Nothing here calls any API. Runs the same pipeline as a real scan."""
import argparse
import json
import os
import random
import shutil
from datetime import datetime, timedelta, timezone

from . import config as C
from . import model, props, run

ALT_BOOKS = {"draftkings", "fanduel"}
BOOKS = ["draftkings", "fanduel", "betmgm", "espnbet", "betrivers", "hardrockbet", "betparx", "ballybet"]

# (away, home, hours from now, players: (name, team side, rush, rec, pass, td_yes_odds))
GAMES = [
    ("Pittsburgh Steelers", "Cleveland Browns", 30, [
        ("Jaylen Warren", "a", 58.5, 22.5, None, 140), ("Aaron Rodgers", "a", None, None, 221.5, 900),
        ("DK Metcalf", "a", None, 61.5, None, 165), ("Pat Freiermuth", "a", None, 28.5, None, 320),
        ("Quinshon Judkins", "h", 71.5, 12.5, None, 105), ("Jerry Jeudy", "h", None, 48.5, None, 260),
        ("Harold Fannin Jr.", "h", None, 34.5, None, 290), ("Deshaun Watson", "h", 14.5, None, 198.5, 450)]),
    ("Kansas City Chiefs", "Las Vegas Raiders", 52, [
        ("Patrick Mahomes", "a", 21.5, None, 264.5, 500), ("Isiah Pacheco", "a", 52.5, 11.5, None, 120),
        ("Rashee Rice", "a", None, 66.5, None, 150), ("Travis Kelce", "a", None, 44.5, None, 210),
        ("Ashton Jeanty", "h", 78.5, 19.5, None, -105), ("Brock Bowers", "h", None, 64.5, None, 170),
        ("Geno Smith", "h", 8.5, None, 231.5, 1100), ("Jakobi Meyers", "h", None, 49.5, None, 280)]),
    ("Detroit Lions", "Green Bay Packers", 56, [
        ("Jahmyr Gibbs", "a", 74.5, 31.5, None, -150), ("Amon-Ra St. Brown", "a", None, 78.5, None, 125),
        ("Jared Goff", "a", None, None, 248.5, 1400), ("Sam LaPorta", "a", None, 39.5, None, 230),
        ("Josh Jacobs", "h", 81.5, 17.5, None, -130), ("Jordan Love", "h", 12.5, None, 239.5, 800),
        ("Tucker Kraft", "h", None, 41.5, None, 240), ("Jayden Reed", "h", None, 45.5, None, 250)]),
    ("Buffalo Bills", "New England Patriots", 101, [
        ("Josh Allen", "a", 33.5, None, 236.5, 135), ("James Cook", "a", 69.5, 14.5, None, 100),
        ("Khalil Shakir", "a", None, 51.5, None, 260), ("Dalton Kincaid", "a", None, 36.5, None, 270),
        ("Drake Maye", "h", 24.5, None, 227.5, 400), ("Rhamondre Stevenson", "h", 49.5, 16.5, None, 165),
        ("Stefon Diggs", "h", None, 54.5, None, 210), ("Hunter Henry", "h", None, 33.5, None, 300)]),
]
# receptions for some pass catchers (discrete market; demo also exercises it)
RECEPTIONS = {"Amon-Ra St. Brown": 6.5, "Brock Bowers": 5.5, "Travis Kelce": 4.5, "Rashee Rice": 5.5,
              "Jahmyr Gibbs": 3.5, "Jerry Jeudy": 4.5}


def _two_way(rng, p_over):
    """American odds for a two-way line with ~4.5% vig around a true over chance."""
    p_over = min(max(p_over + rng.uniform(-0.03, 0.03), 0.2), 0.8)
    over, under = p_over * 1.045, (1 - p_over) * 1.045
    return _american(over), _american(under)


def _american(implied):
    implied = min(max(implied, 0.02), 0.98)
    if implied >= 0.5:
        return -int(round(100 * implied / (1 - implied) / 5) * 5)
    return int(round(100 * (1 - implied) / implied / 5) * 5)


def games_from_analytics(a, rng, n_games=4):
    """Real matchups and players from analytics.json (the odds are still made up): for each team, its
    main QB, top runner and top two pass catchers, with fake lines near the stats projection."""
    out, seen = [], set()
    by_team = {}
    for p in a.get("players", []):
        by_team.setdefault(p["t"], []).append(p)
    for team, g in sorted(a.get("games", {}).items(), key=lambda kv: (kv[1].get("kick") or "", kv[0])):
        if not g.get("home") or team in seen or len(out) >= n_games:
            continue
        seen |= {team, g["opp"]}
        players = []
        for t in (g["opp"], team):
            roster = by_team.get(t, [])
            def top(pos, stat, k):
                c = [p for p in roster if p["pos"] in pos and stat in (p.get("pj") or {})]
                return sorted(c, key=lambda p: -(p["pj"][stat].get("med") or 0))[:k]
            picks = top(("QB",), "player_pass_yds", 1) + top(("RB",), "player_rush_yds", 1) + top(("WR", "TE"), "player_reception_yds", 2)
            for p in picks:
                pj = p["pj"]
                jig = lambda x: None if x is None else max(0.5, round(x * rng.uniform(0.9, 1.1)) + 0.5)
                rush = jig((pj.get("player_rush_yds") or {}).get("med"))
                rec = jig((pj.get("player_reception_yds") or {}).get("med"))
                pas = jig((pj.get("player_pass_yds") or {}).get("med"))
                tdp = (pj.get("player_anytime_td") or {}).get("p")
                td = _american(min(max(tdp * rng.uniform(0.85, 1.15) * 1.08, 0.04), 0.8)) if tdp else 400
                players.append((p["n"], "a" if t == g["opp"] else "h", rush if p["pos"] in ("RB", "QB") else None, rec, pas, td))
        kick = datetime.fromisoformat(g["kick"]) if g.get("kick") else None
        out.append((a["teams"][g["opp"]]["name"], a["teams"][team]["name"], kick, players))
    return out


def fake_lines(now, rng, games_spec=None):
    lines, games = [], {}
    for gi, (away, home, hrs, players) in enumerate(games_spec or GAMES):
        gid = f"demo{gi}"
        kick = hrs if isinstance(hrs, datetime) else (now + timedelta(hours=hrs)).replace(minute=0, second=0, microsecond=0)
        games[gid] = {"a": away, "h": home, "t": kick.isoformat().replace("+00:00", "Z")}
        name = f"{away} @ {home}"
        for player, _side, rush, rec, pas, td in players:
            stats = [("player_rush_yds", rush), ("player_reception_yds", rec), ("player_pass_yds", pas),
                     ("player_receptions", RECEPTIONS.get(player))]
            for book in BOOKS:
                if rng.random() < 0.12:
                    continue  # not every book posts every player
                for market, line in stats:
                    if line is None:
                        continue
                    pt = line + (rng.choice([-1, 0, 0, 0, 1]) if market != "player_receptions" else 0)
                    o, u = _two_way(rng, 0.5)
                    lines.append({"player": player, "market": market, "book": book, "point": pt,
                                  "prices": {"Over": o, "Under": u}, "game": name, "game_id": gid,
                                  "kick": games[gid]["t"]})
                    # alternate lines (off by default in real scans: they cost extra credits)
                    if book in ALT_BOOKS and market in ("player_rush_yds", "player_reception_yds") and line >= 30:
                        for frac in (0.7, 0.85):
                            apt = int(line * frac) + 0.5
                            fair = model.lognormal_p_at_least(apt + 0.5, line, 0.5, C.SIGMA[market])
                            lines.append({"player": player, "market": market + "_alternate", "book": book,
                                          "point": apt, "prices": {"Over": _american(fair * 1.06)},
                                          "game": name, "game_id": gid, "kick": games[gid]["t"]})
                yes = td + rng.choice([-20, -10, 0, 0, 10, 20]) if td > 0 else td - rng.choice([0, 10, 20])
                lines.append({"player": player, "market": "player_anytime_td", "book": book, "point": None,
                              "prices": {"Yes": yes if abs(yes) >= 100 else 100}, "game": name,
                              "game_id": gid, "kick": games[gid]["t"]})
    return lines, games


def fake_kalshi(prop_list, rng):
    """Kalshi-style 'X+' contracts around each yardage line, priced near fair with some noise."""
    markets = []
    for p in prop_list:
        if p["m"] not in ("player_rush_yds", "player_reception_yds", "player_anytime_td"):
            continue
        if p["stat"] == "player_anytime_td":
            thresholds = [1]
        else:
            if len(p["b"]) < 4:
                continue  # one prop per player: the consensus point
            base = int(p["pt"] // 10 * 10)
            thresholds = [max(base - 20, 10), base, base + 20]
        for t in thresholds:
            label = "rushing yards" if p["stat"] == "player_rush_yds" else "receiving yards"
            title = (f"Will {p['player']} score a touchdown?" if p["stat"] == "player_anytime_td"
                     else f"{p['player']}: {t}+ {label}")
            ticker = f"KXDEMO-{p['player'].upper().replace(' ', '').replace('.', '')}-{p['stat'][7:10].upper()}{t:g}"
            if any(m["ticker"] == ticker for m in markets):
                continue
            mid = rng.uniform(15, 85) if p["stat"] != "player_anytime_td" else p["p"] * 100 + rng.uniform(-6, 6)
            mid = min(max(mid, 4), 95)
            markets.append({"ticker": ticker, "title": title, "yes_bid": round(mid - 1), "yes_ask": round(mid + 2)})
    return markets


def build(now=None, seed=7, analytics=None):
    now = now or datetime.now(timezone.utc)
    rng = random.Random(seed)
    spec = games_from_analytics(analytics, rng) if analytics else None
    lines, games = fake_lines(now, rng, spec or None)
    prop_list = props.build_props(lines, C.SIGMA, C.MAX_LINE_DISTANCE, C.ALT_LINE_DISTANCE,
                                  C.ANYTIME_TD_VIG, C.PROP_MIN_BOOKS)
    universe = []
    picks, stats = run.evaluate(lines, fake_kalshi(prop_list, rng), universe)
    stamp = (now - timedelta(hours=3)).isoformat(timespec="seconds")
    data = run.site_data(picks, stats, universe, prop_list, games,
                         {m: stamp for m in ("player_rush_yds", "player_reception_yds", "player_pass_yds",
                                             "player_anytime_td", "player_receptions")},
                         now - timedelta(hours=3))
    data["demo"] = True
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/demo-data.json")
    ap.add_argument("--analytics", default="site/analytics.json",
                    help="use real matchups/players from this analytics.json if it exists (odds stay fake)")
    args = ap.parse_args()
    a = None
    if args.analytics and os.path.exists(args.analytics):
        with open(args.analytics) as f:
            a = json.load(f)
        demo_a = os.path.join(os.path.dirname(args.out) or ".", "demo-analytics.json")
        shutil.copyfile(args.analytics, demo_a)
        print(f"using players and matchups from {args.analytics} (copied to {demo_a})")
    data = build(analytics=a)
    run.write_site(data, args.out)
    print(f"wrote {args.out}: {len(data['props'])} sportsbook props, {len(data['kalshi'])} Kalshi contracts")


if __name__ == "__main__":
    main()
