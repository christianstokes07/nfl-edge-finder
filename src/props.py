"""Sportsbook picks for the page: every book's own line and price for each prop, plus a hit chance
from the no-vig consensus of all books.

A prop is (player, market, point). Books that hang the same player at slightly different points
(65.5 vs 66.5) produce separate props, so whichever book you pick, you see that book's exact line and
a hit chance computed for that exact line. Alternate-line markets (e.g. player_rush_yds_alternate)
are priced off the main-line consensus."""
from collections import defaultdict

from . import model

TD = "player_anytime_td"
STATS = {"player_rush_yds", "player_reception_yds", "player_pass_yds", "player_pass_tds",
         "player_receptions", "player_anytime_td"}


def base_stat(market):
    return market[: -len("_alternate")] if market.endswith("_alternate") else market


def is_main(line):
    return not line["market"].endswith("_alternate")


def book_prices(prices):
    """[over_or_yes, under_or_no] American odds, None for a side the book doesn't offer."""
    first = prices.get("Over", prices.get("Yes"))
    second = prices.get("Under", prices.get("No"))
    return [first, second]


def game_id(line):
    return line.get("game_id") or line.get("game", "")


def build_props(lines, sigma_map, main_dist, alt_dist, td_vig, min_books=1):
    """Pure function: book lines -> list of props (dicts ready for data.json, minus the id).

    Each prop: {player, g, stat, m, pt, p, n, unc, b: {book: [over/yes, under/no]}}
    where p = fair chance the Over (or Yes) side hits at this point and n = books behind that number."""
    consensus = defaultdict(list)  # (norm player, stat) -> main-market lines, used for fair values
    for ln in lines:
        if is_main(ln):
            consensus[(model.norm_name(ln["player"]), ln["market"])].append(ln)

    groups = {}
    for ln in lines:
        stat = base_stat(ln["market"])
        if stat not in STATS:
            continue
        pt = None if stat == TD else ln["point"]
        if stat != TD and pt is None:
            continue
        key = (model.norm_name(ln["player"]), ln["market"], pt)
        g = groups.setdefault(key, {"player": ln["player"], "g": game_id(ln), "stat": stat,
                                    "m": ln["market"], "pt": pt, "b": {}})
        bp = book_prices(ln["prices"])
        if bp[0] is None and bp[1] is None:
            continue
        g["b"][ln["book"]] = bp

    props = []
    for (name, market, pt), g in groups.items():
        stat = g["stat"]
        if not g["b"]:
            continue
        if market != stat and (name, stat, pt) in groups:
            continue  # alternate line duplicates a main line: the main one already has it
        cons = consensus.get((name, stat), [])
        thr = 1.0 if stat == TD else pt + 0.5  # 'Over 65.5' == '66 or more'
        dist = main_dist if market == stat else alt_dist
        fair, n = model.fair_probability(stat, thr, cons, sigma_map, dist, td_vig)
        if fair is None or n < min_books:
            continue
        unc = model.uncertainty(stat, thr, cons, dist)
        props.append({**g, "p": round(fair, 3), "n": n, "unc": round(unc, 3)})
    props.sort(key=lambda p: (p["g"], p["player"], p["stat"], p["pt"] or 0))
    return props


def lines_from_props(props, games):
    """Inverse of build_props, used to carry forward markets a run didn't re-fetch."""
    out = []
    for p in props:
        g = games.get(p["g"], {})
        name = f"{g.get('a', '')} @ {g.get('h', '')}"
        for book, (first, second) in p["b"].items():
            if p["stat"] == TD:
                prices = {k: v for k, v in (("Yes", first), ("No", second)) if v is not None}
            else:
                prices = {k: v for k, v in (("Over", first), ("Under", second)) if v is not None}
            out.append({"player": p["player"], "market": p["m"], "book": book, "point": p["pt"],
                        "prices": prices, "game": name, "game_id": p["g"], "kick": g.get("t")})
    return out


def consensus_points(prop_list):
    """(norm player, market) -> the main-line point most books use (ties: the lower point), or the
    anytime-TD fair chance. Main markets only."""
    groups = defaultdict(list)
    for p in prop_list:
        if p["m"] == p["stat"]:
            groups[(model.norm_name(p["player"]), p["m"])].append(p)
    out = {}
    for k, ps in groups.items():
        if ps[0]["stat"] == TD:
            out[k] = ps[0]["p"]
        else:
            best = max(ps, key=lambda p: (len(p["b"]), -p["pt"]))
            out[k] = best["pt"]
    return out


def add_line_moves(prop_list, prev_props):
    """Mark each main-line prop with mv = [previous consensus, current consensus] when it changed since
    the previous scan (points for yards/catches, fair chance for anytime TD)."""
    if not prev_props:
        return prop_list
    old, new = consensus_points(prev_props), consensus_points(prop_list)
    for p in prop_list:
        k = (model.norm_name(p["player"]), p["m"])
        if p["m"] == p["stat"] and k in old and k in new and old[k] != new[k]:
            p["mv"] = [old[k], new[k]]
    return prop_list
