"""Game picks: moneyline, spread and total, from one bulk Odds API call (3 credits for every game).

A game prop is (game, market, point) with every book's prices, like player props:
- h2h:     pt None,  b[book] = [home price, away price],  p = chance the HOME team wins
- spreads: pt = HOME team's spread (e.g. -6.5), b[book] = [home price, away price], p = chance HOME covers
- totals:  pt = total, b[book] = [over price, under price], p = chance the game goes OVER
Hit chances are the no-vig consensus of all books. Books on a different spread/total are moved to this
point with a normal model of final margins/totals (spread measured from nflverse results)."""
from collections import defaultdict

from . import model

KINDS = ("h2h", "spreads", "totals")
STAT = {"h2h": "game_ml", "spreads": "game_spread", "totals": "game_total"}


def parse_events(events, game_ids=None):
    """Odds API /odds response -> flat lines: {g, market, book, point (home spread / total), prices: [a, b]}."""
    out = []
    for ev in events:
        gid = (game_ids or {}).get(ev["id"], ev["id"])
        home, away = ev["home_team"], ev["away_team"]
        for b in ev.get("bookmakers", []):
            for m in b.get("markets", []):
                o = {x["name"]: x for x in m.get("outcomes", [])}
                if m["key"] == "h2h" and home in o and away in o:
                    out.append({"g": gid, "market": "h2h", "book": b["key"], "point": None,
                                "prices": [o[home]["price"], o[away]["price"]]})
                elif m["key"] == "spreads" and home in o and away in o and o[home].get("point") is not None:
                    out.append({"g": gid, "market": "spreads", "book": b["key"], "point": o[home]["point"],
                                "prices": [o[home]["price"], o[away]["price"]]})
                elif m["key"] == "totals" and "Over" in o and "Under" in o and o["Over"].get("point") is not None:
                    out.append({"g": gid, "market": "totals", "book": b["key"], "point": o["Over"]["point"],
                                "prices": [o["Over"]["price"], o["Under"]["price"]]})
    return out


def _p_first(ln):
    return model.devig_two_way(ln["prices"][0], ln["prices"][1])


def fair(kind, lines, line, margin_sd, total_sd):
    """Consensus chance for: h2h -> home wins (line ignored); spreads -> home covers `line` (home spread);
    totals -> over `line`. Returns (p, n_books)."""
    probs = []
    for ln in lines:
        if ln["market"] != kind or None in ln["prices"]:
            continue
        p = _p_first(ln)
        if kind == "h2h":
            probs.append(p)
        elif kind == "spreads":
            # home covers spread s when margin > -s; book: P(margin > -s_b) = p
            probs.append(model.normal_p_over(-line, -ln["point"], p, margin_sd))
        else:
            probs.append(model.normal_p_over(line, ln["point"], p, total_sd))
    if not probs:
        return None, 0
    return sum(probs) / len(probs), len(probs)


def build_game_props(lines, margin_sd, total_sd):
    by_game = defaultdict(list)
    for ln in lines:
        by_game[ln["g"]].append(ln)
    props = []
    for g, gl in by_game.items():
        groups = {}
        for ln in gl:
            key = (ln["market"], ln["point"])
            groups.setdefault(key, {})[ln["book"]] = ln["prices"]
        for (kind, pt), books in groups.items():
            p, n = fair(kind, gl, pt, margin_sd, total_sd)
            if p is None:
                continue
            same = sum(1 for ln in gl if ln["market"] == kind and ln["point"] == pt)
            # moving other books' lines to this point is rougher than an exact match
            unc = 0.02 if kind == "h2h" or same == n else 0.03
            props.append({"g": g, "m": kind, "stat": STAT[kind], "pt": pt, "p": round(p, 3), "n": n,
                          "unc": unc, "b": books})
    props.sort(key=lambda p: (p["g"], KINDS.index(p["m"]), p["pt"] or 0))
    return props


def lines_from_props(gprops):
    """Inverse of build_game_props (carry game lines forward / re-price Kalshi without a new call)."""
    return [{"g": p["g"], "market": p["m"], "book": b, "point": p["pt"], "prices": v}
            for p in gprops for b, v in p["b"].items()]


def kalshi_fair(c, lines, home_is_team, margin_sd, total_sd):
    """Fair chance for a parsed Kalshi game contract c = {kind, team, threshold}.
    home_is_team: is c's team the home team (ignored for totals)."""
    kind = c["kind"]
    if kind == "game_ml":
        p, n = fair("h2h", lines, None, margin_sd, total_sd)
        return (p if home_is_team else (None if p is None else 1 - p)), n
    if kind == "game_spread":
        # "TEAM wins by over X": team margin > X. For the home team that's covering a home spread of -X.
        p, n = fair("spreads", lines, -c["threshold"], margin_sd, total_sd)
        if p is None:
            return None, 0
        if home_is_team:
            return p, n
        # away wins by over X: home margin < -X = 1 - P(home margin > -X) = 1 - P(home covers +X)
        q, n = fair("spreads", lines, c["threshold"], margin_sd, total_sd)
        return 1 - q, n
    if kind == "game_total":
        return fair("totals", lines, c["threshold"], margin_sd, total_sd)
    return None, 0
