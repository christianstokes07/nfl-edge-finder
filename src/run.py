"""python -m src.run            -> scan and send results
python -m src.run --dump-kalshi -> print raw Kalshi NFL market titles (for debugging matching)
python -m src.run --no-send     -> scan and print only (no Discord, no log, no data.json)
python -m src.run --estimate    -> print what a scan would cost in Odds API credits (uses 0 credits)
python -m src.run --kalshi-only -> re-price Kalshi from the last scan's sportsbook lines (uses 0 credits)"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests

from . import config as C
from . import games as games_mod
from . import kalshi, model, odds, props, teams, verdict

STAT_LABEL = {
    "game_ml": "moneyline", "game_spread": "spread", "game_total": "game total",
    "player_rush_reception_yds": "rush + rec yds", "player_pass_attempts": "pass attempts",
    "player_pass_completions": "completions", "player_rush_attempts": "rush attempts",
    "player_pass_interceptions": "interceptions",
    "player_rush_yds": "rushing yds",
    "player_reception_yds": "receiving yds",
    "player_pass_yds": "passing yds",
    "player_pass_tds": "passing TDs",
    "player_receptions": "receptions",
    "player_anytime_td": "anytime TD",
}


def collect_lines():
    """Returns (lines, games, game_lines, credits_used). /events is free; each game's player-prop call costs
    (markets returned); the one bulk game-lines call costs 3 (moneyline, spread, total)."""
    if not C.ODDS_API_KEY:
        sys.exit("ODDS_API_KEY is not set.")
    events, remaining = odds.upcoming_events(C.ODDS_API_KEY, C.WINDOW_HOURS)
    start = remaining
    print(f"[odds] {len(events)} games in the next {C.WINDOW_HOURS:.0f}h, player markets: "
          f"{','.join(C.ODDS_MARKETS) or 'none (carried over)'}; game lines: {'yes' if C.GAME_LINES else 'no'}")
    all_lines, games = [], {}
    for e in events:
        games[e["id"]] = {"a": e.get("away_team", ""), "h": e.get("home_team", ""), "t": e.get("commence_time")}
    for e in events if C.ODDS_MARKETS else ():
        if remaining is not None and remaining <= C.CREDIT_RESERVE:
            print(f"[odds] only {remaining:.0f} credits left, stopping to protect the reserve")
            break
        try:
            lines, remaining = odds.event_props(C.ODDS_API_KEY, e["id"], C.ODDS_MARKETS, C.BOOKMAKERS)
        except odds.OddsAPIError as err:
            print(f"[odds] {e.get('away_team')} @ {e.get('home_team')}: {err}")
            continue
        for ln in lines:
            ln["game"] = f"{e.get('away_team')} @ {e.get('home_team')}"
            ln["game_id"] = e["id"]
            ln["kick"] = e.get("commence_time")
        all_lines.extend(lines)
    game_lines = []
    if C.GAME_LINES and (remaining is None or remaining > C.CREDIT_RESERVE):
        try:
            evs, remaining = odds.game_odds(C.ODDS_API_KEY, C.BOOKMAKERS)
            ids = {e["id"] for e in events}
            game_lines = games_mod.parse_events([e for e in evs if e["id"] in ids])
        except odds.OddsAPIError as err:
            print(f"[odds] game lines: {err}")
    used = (start - remaining) if (start is not None and remaining is not None) else None
    print(f"[odds] {len(all_lines)} player lines, {len(game_lines)} game lines, credits used this run: {used}, "
          f"remaining: {remaining}")
    return all_lines, games, game_lines, used


def load_previous(path=None):
    try:
        with open(path or C.SITE_DATA_PATH) as f:
            d = json.load(f)
        return d if d.get("version") == 2 else None
    except (OSError, ValueError):
        return None


def carry_forward(prev, fetched_markets, now=None):
    """Markets this run didn't fetch (e.g. passing yards on the cheaper Sunday run) are copied from
    the previous scan for games that haven't kicked off. Returns (lines, games, markets_updated)."""
    if not prev:
        return [], {}, {}
    now = now or datetime.now(timezone.utc)
    games = {}
    for gid, g in (prev.get("games") or {}).items():
        try:
            kick = datetime.fromisoformat(str(g.get("t")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if kick > now:
            games[gid] = g
    keep = [p for p in prev.get("props", []) if p.get("m") not in fetched_markets and p.get("g") in games]
    lines = props.lines_from_props(keep, games)
    old = prev.get("markets_updated") or {}
    updated = {m: old.get(m, prev.get("updated")) for m in {p["m"] for p in keep}}
    if keep:
        print(f"[carry] kept {len(keep)} props from the {prev.get('updated')} scan: {', '.join(sorted(updated))}")
    return lines, {g: games[g] for g in {p["g"] for p in keep}}, updated


def index_lines(lines):
    idx = defaultdict(list)  # (norm player, market) -> lines
    for ln in lines:
        idx[(model.norm_name(ln["player"]), ln["market"])].append(ln)
    names = sorted({k[0] for k in idx}, key=len, reverse=True)
    return idx, names


def find_player(text, names):
    t = " " + model.norm_name(text) + " "
    for alias, real in C.NAME_ALIASES.items():
        if f" {alias} " in t:
            t = t.replace(f" {alias} ", f" {real} ")
    for n in names:
        if f" {n} " in t:
            return n
    return None


def _edge_pick(fair, bid, ask, stat):
    """Best side (YES/NO) and its edge after fees, or None if the market is too thin to trade."""
    if not bid or not ask or ask >= 99 or (ask - bid) > C.MAX_SPREAD_CENTS:
        return None
    yes_cost, no_cost = ask / 100, 1 - bid / 100
    edge_yes = fair - yes_cost - model.kalshi_fee(yes_cost, C.KALSHI_FEE_RATE)
    edge_no = (1 - fair) - no_cost - model.kalshi_fee(no_cost, C.KALSHI_FEE_RATE)
    if edge_no > edge_yes:
        return "NO", edge_no, no_cost, 1 - fair
    return "YES", edge_yes, yes_cost, fair


def _game_for_pair(pair, games):
    """Kalshi 'PIT vs CLE' -> our game id (either order)."""
    if not pair:
        return None
    want = {teams.abbr(pair[0]), teams.abbr(pair[1])}
    for gid, g in games.items():
        if {teams.abbr(g.get("a")), teams.abbr(g.get("h"))} == want:
            return gid
    return None


def evaluate(lines, markets, universe=None, game_lines=(), games=None):
    """Pure function: book lines + Kalshi markets -> (picks, stats).

    Player contracts are priced from the sportsbook consensus. Kalshi player contracts with no sportsbook
    line at all (e.g. passing attempts when that market wasn't bought) are kept for the page with Kalshi's
    own mid price as the chance (books = 0, km = 1): no value judgment possible, stats check still works.
    Game contracts (winner / wins by over X / total over X) are priced from the game-line consensus."""
    idx, names = index_lines([ln for ln in lines if props.is_main(ln)])
    player_game = {}
    for (name, _), lns in idx.items():
        player_game.setdefault(name, (lns[0]["player"], props.game_id(lns[0]), lns[0].get("game", "")))
    games = games or {}
    gl_by_game = defaultdict(list)
    for gl in game_lines or ():
        gl_by_game[gl["g"]].append(gl)
    stats = {"markets": len(markets), "parsed": 0, "matched": 0, "scored": 0}
    picks = []

    def record(row, fair, n, unc, bid, ask, label, game_name, stat_key):
        if universe is not None and 0.03 < fair < 0.97:
            universe.append({**row, "fair": round(fair, 3), "books": n, "unc": round(unc, 3), "bid": bid, "ask": ask})
        if n == 0:
            return
        ep = _edge_pick(fair, bid, ask, stat_key)
        if not ep:
            return
        stats["scored"] += 1
        by = stats.setdefault("by_stat", {})
        by[label] = by.get(label, 0) + 1
        side, edge, cost, p_win = ep
        if edge >= (C.MIN_EDGE_TD if stat_key == "player_anytime_td" else C.MIN_EDGE):
            picks.append({"player": row["player"], "game": game_name, "stat": stat_key,
                          "threshold": row["threshold"] if row["threshold"] is not None else 0.5,
                          "side": side, "price": round(cost * 100), "fair": p_win, "edge": edge, "books": n,
                          "ticker": row["ticker"]})

    for m in markets:
        bid, ask = kalshi.prices(m)
        gc = kalshi.parse_game_contract(m)
        if gc:
            stats["parsed"] += 1
            gid = _game_for_pair(gc["pair"], games)
            if not gid:
                continue
            g = games[gid]
            home_is_team = gc["team"] is not None and teams.abbr(gc["team"]) == teams.abbr(g["h"])
            if not gl_by_game.get(gid):
                # no sportsbook game lines yet: show it at Kalshi's own price (no value judgment)
                if bid and ask and ask < 99 and (ask - bid) <= C.MAX_SPREAD_CENTS and universe is not None and 3 < (bid + ask) / 2 < 97:
                    team = (g["h"] if home_is_team else g["a"]) if gc["team"] else None
                    universe.append({"ticker": m.get("ticker", ""), "player": team or "Game total", "g": gid, "stat": gc["kind"],
                                     "threshold": gc["threshold"], "team": team, "fair": round((bid + ask) / 200, 3),
                                     "books": 0, "km": 1, "unc": 0.0, "bid": bid, "ask": ask})
                continue
            fair, n = games_mod.kalshi_fair(gc, gl_by_game[gid], home_is_team, C.MARGIN_SD, C.TOTAL_SD)
            if fair is None:
                continue
            stats["matched"] += 1
            team = (g["h"] if home_is_team else g["a"]) if gc["team"] else None
            row = {"ticker": m.get("ticker", ""), "player": team or "Game total", "g": gid, "stat": gc["kind"],
                   "threshold": gc["threshold"], "team": team}
            record(row, fair, n, 0.02 if gc["kind"] == "game_ml" else 0.03, bid, ask, STAT_LABEL[gc["kind"]],
                   f"{g['a']} @ {g['h']}", gc["kind"])
            continue
        c = kalshi.parse_contract(m)
        if not c:
            continue
        stats["parsed"] += 1
        player = find_player(kalshi.market_text(m), names)
        if not player:
            continue
        book_lines = idx.get((player, c["stat"]))
        display, gid, gname = player_game[player]
        row = {"ticker": m.get("ticker", ""), "player": display, "g": gid, "stat": c["stat"], "threshold": c["threshold"]}
        if not book_lines:
            # no sportsbook line for this stat: Kalshi's own price is the only market
            if bid and ask and ask < 99 and (ask - bid) <= C.MAX_SPREAD_CENTS and universe is not None:
                mid = (bid + ask) / 200
                if 0.03 < mid < 0.97:
                    universe.append({**row, "fair": round(mid, 3), "books": 0, "km": 1, "unc": 0.0, "bid": bid, "ask": ask})
            continue
        stats["matched"] += 1
        fair, n = model.fair_probability(
            c["stat"], c["threshold"], book_lines, C.SIGMA, C.KALSHI_LINE_DISTANCE, C.ANYTIME_TD_VIG
        )
        if fair is None or n < C.MIN_BOOKS:
            continue
        unc = model.uncertainty(c["stat"], c["threshold"], book_lines, C.KALSHI_LINE_DISTANCE)
        record(row, fair, n, unc, bid, ask, STAT_LABEL[c["stat"]], gname, c["stat"])
    picks.sort(key=lambda p: p["edge"], reverse=True)
    return picks, stats


def fmt_pick(p):
    thr = "" if p["stat"] == "player_anytime_td" else f"{p['threshold']:g}+ "
    return (
        f"**{p['player']}** {thr}{STAT_LABEL[p['stat']]}\n"
        f"Buy **{p['side']}** at {p['price']}¢ | fair {p['fair']:.0%} | edge {p['edge']:+.1%} "
        f"| {p['books']} books | `{p['ticker']}`"
    )


def build_message(picks, stats):
    head = f"**NFL edge scan** ({datetime.now(timezone.utc):%a %b %d %H:%M} UTC)"
    if not picks:
        return (
            f"{head}\nNo contracts cleared the {C.MIN_EDGE:.0%} edge bar. "
            f"(Kalshi markets {stats['markets']}, parsed {stats['parsed']}, "
            f"matched to a book line {stats['matched']}, scored {stats['scored']})"
        )
    body = "\n\n".join(fmt_pick(p) for p in picks[: C.TOP_N])
    foot = "\nEdges use sportsbook consensus as fair value. Check the live price and inactives before buying."
    return f"{head}\n\n{body}\n{foot}"


def send_discord(msg):
    if not C.DISCORD_WEBHOOK_URL:
        print("[discord] no webhook set, skipping")
        return
    # Discord caps messages at 2000 chars
    chunks, cur = [], ""
    for para in msg.split("\n\n"):
        if len(cur) + len(para) + 2 > 1900:
            chunks.append(cur)
            cur = ""
        cur += para + "\n\n"
    chunks.append(cur)
    for ch in chunks:
        r = requests.post(C.DISCORD_WEBHOOK_URL, json={"content": ch.strip()}, timeout=30)
        if r.status_code >= 300:
            print(f"[discord] error {r.status_code}: {r.text[:200]}")


LOG_HEADER = ["ts_utc", "source", "game", "player", "stat", "line", "side", "price", "hit_chance", "value",
              "books", "where", "analytics", "projection"]


def load_analytics(path=None):
    try:
        with open(path or C.ANALYTICS_PATH) as f:
            a = json.load(f)
        return a if a.get("version") == 1 else None
    except (OSError, ValueError):
        return None


def analytics_check(a, player, team_names, stat, side, line, market_p):
    """(verdict, projection) for one pick from analytics.json, or ('n/a', '')."""
    if not a:
        return "n/a", ""
    hits = [p for p in a.get("players", []) if model.norm_name(p.get("n") or "") == model.norm_name(player)]
    if len(hits) > 1:
        abbrs = {k for k, t in a.get("teams", {}).items() if t.get("name") in team_names}
        hits = [p for p in hits if p["t"] in abbrs] or hits
    if not hits:
        return "n/a", ""
    p = hits[0]
    g = a.get("games", {}).get(p["t"])
    if not g or a.get("teams", {}).get(g["opp"], {}).get("name") not in team_names:
        return "n/a", ""  # analytics are for a different week than this game
    proj = (p.get("pj") or {}).get(stat)
    v = verdict.verdict(stat, side, line, proj, market_p)
    shown = "" if not proj else (f"{proj['p']:.3f}" if stat == "player_anytime_td" else f"{proj['med']:.1f}")
    return v, shown


def book_log_rows(prop_list, games):
    """One row per main-line prop at the consensus point: the side the market favors (Yes for anytime
    TD), at the best price across books. This is what lets you check later whether 'agree' hits more."""
    best = {}
    for p in prop_list:
        if p["m"] != p["stat"]:
            continue
        k = (model.norm_name(p["player"]), p["m"])
        if k not in best or len(p["b"]) > len(best[k]["b"]):
            best[k] = p
    rows = []
    for p in best.values():
        td = p["stat"] == "player_anytime_td"
        s = 0 if (td or p["p"] >= 0.5) else 1
        side = ("Yes" if s == 0 else "No") if td else ("Over" if s == 0 else "Under")
        prices = [(v[s], b) for b, v in p["b"].items() if v[s] is not None]
        if not prices:
            continue
        price, book = min(prices, key=lambda x: model.american_to_prob(x[0]))  # best payout
        g = games.get(p["g"], {})
        rows.append({"source": "book", "game": f"{g.get('a', '')} @ {g.get('h', '')}", "team_names": {g.get("a"), g.get("h")},
                     "player": p["player"], "stat": p["stat"], "line": p["pt"], "side": side, "price": price,
                     "hit": p["p"] if s == 0 else 1 - p["p"], "value": None, "books": p["n"], "where": book,
                     "market_p": p["p"]})
    return rows


def game_log_rows(gprops, games):
    """One row per game market at its most-quoted line: the side the market favors."""
    best = {}
    for p in gprops:
        k = (p["g"], p["m"])
        if k not in best or len(p["b"]) > len(best[k]["b"]):
            best[k] = p
    rows = []
    for p in best.values():
        g = games.get(p["g"], {})
        s = 0 if p["p"] >= 0.5 else 1
        if p["m"] == "totals":
            side = "Over" if s == 0 else "Under"
        else:
            side = g.get("h") if s == 0 else g.get("a")
        prices = [(v[s], b) for b, v in p["b"].items() if v[s] is not None]
        if not prices:
            continue
        price, book = min(prices, key=lambda x: model.american_to_prob(x[0]))
        line = p["pt"] if p["m"] != "spreads" or s == 0 else -p["pt"]
        rows.append({"source": "game", "game": f"{g.get('a', '')} @ {g.get('h', '')}", "team_names": set(),
                     "player": "", "stat": games_mod.STAT[p["m"]], "line": "" if line is None else line, "side": side,
                     "price": price, "hit": p["p"] if s == 0 else 1 - p["p"], "value": None, "books": p["n"],
                     "where": book, "market_p": None})
    return rows


def log_picks(picks, book_rows=(), analytics=None):
    """Append Kalshi picks (those clearing the edge bar) and every sportsbook main-line prop, each with
    the stats verdict, to data/picks_log.csv."""
    rows = []
    for p in picks:
        team_names = set(p.get("game", "").split(" @ "))
        line = None if p["stat"] == "player_anytime_td" else p["threshold"] - 0.5
        rows.append({"source": "kalshi", "game": p["game"], "team_names": team_names, "player": p["player"],
                     "stat": p["stat"], "line": line if line is not None else "", "side": p["side"],
                     "price": p["price"], "hit": p["fair"], "value": p["edge"], "books": p["books"],
                     "where": p["ticker"], "market_p": p["fair"] if p["side"] == "YES" else 1 - p["fair"]})
    rows += list(book_rows)
    if not rows:
        return
    os.makedirs(os.path.dirname(C.LOG_PATH) or ".", exist_ok=True)
    if os.path.exists(C.LOG_PATH):
        with open(C.LOG_PATH) as f:
            head = f.readline().strip().split(",")
        if head != LOG_HEADER:  # older log format: keep it, start a new one
            os.replace(C.LOG_PATH, C.LOG_PATH.replace(".csv", "_v1.csv"))
    new = not os.path.exists(C.LOG_PATH)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(C.LOG_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(LOG_HEADER)
        for r in rows:
            line = r["line"] if r["line"] != "" else None
            v, proj = analytics_check(analytics, r["player"], r["team_names"], r["stat"], r["side"], line, r["market_p"])
            w.writerow([ts, r["source"], r["game"], r["player"], r["stat"], r["line"] if r["line"] is not None else "",
                        r["side"], r["price"], f"{r['hit']:.3f}", "" if r["value"] is None else f"{r['value']:.3f}",
                        r["books"], r["where"], v, proj])


def _spread(u):
    return (u["ask"] - u["bid"]) if u.get("bid") and u.get("ask") else 99


def site_data(picks, stats, universe=(), prop_list=(), games=None, markets_updated=None, now=None, game_props=()):
    """Everything site/index.html needs. Kept compact: per-book prices are [over/yes, under/no] pairs."""
    now = now or datetime.now(timezone.utc)
    games = games or {}
    counts = defaultdict(int)
    for p in list(prop_list) + list(game_props):
        for b in p["b"]:
            counts[b] += 1
    configured = [b.strip() for b in C.BOOKMAKERS.split(",") if b.strip()]
    books = [{"k": b, "name": C.BOOK_NAMES.get(b, b), "n": counts.get(b, 0), "paid": b in C.PAID_ONLY_BOOKS}
             for b in configured + sorted(set(counts) - set(configured))]
    used = {p["g"] for p in prop_list} | {u.get("g") for u in universe} | {p["g"] for p in game_props}
    # cap per prop type (tightest markets first) so anytime-TD contracts can't crowd out yardage ones
    by_stat = defaultdict(list)
    for u in sorted(universe, key=_spread):
        by_stat[u["stat"]].append(u)
    kalshi_rows = [u for rows in by_stat.values() for u in rows[: C.KALSHI_ROWS_PER_STAT]]
    return {
        "version": 2,
        "updated": now.isoformat(timespec="seconds"),
        "markets_updated": markets_updated or {},
        "min_edge": C.MIN_EDGE,
        "stats": stats,
        "params": {"fee": C.KALSHI_FEE_RATE, "max_spread": C.MAX_SPREAD_CENTS,
                   "min_edge": C.MIN_EDGE, "min_edge_td": C.MIN_EDGE_TD, "top_n": C.TOP_N},
        "books": books,
        "games": {k: v for k, v in games.items() if k in used},
        "props": [{"id": f"p{i}", **p} for i, p in enumerate(prop_list)],
        "lines": [{"id": f"q{i}", **p} for i, p in enumerate(game_props)],   # moneyline / spread / total
        "game_sd": {"margin": C.MARGIN_SD, "total": C.TOTAL_SD},
        "kalshi": kalshi_rows,  # the page re-prices these live
        "picks": [
            {**p, "label": STAT_LABEL[p["stat"]], "fair": round(p["fair"], 3), "edge": round(p["edge"], 3)}
            for p in picks[: C.TOP_N]
        ],
    }


def write_site(data, path=None):
    """Data file read by site/index.html (the phone page). Compact JSON keeps it small."""
    path = path or C.SITE_DATA_PATH
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))


def get_kalshi_markets():
    series = kalshi.discover_nfl_series()
    print(f"[kalshi] NFL-ish series found: {len(series)}")
    return kalshi.fetch_open_markets(series)


def apply_measured_spreads(a):
    """Use the analytics job's measurements (from nflverse games) for the distribution spreads."""
    if not a:
        return
    for stat, v in (a.get("sigma") or {}).items():
        if v:
            C.SIGMA[stat] = v
    sd = a.get("game_sd") or {}
    C.MARGIN_SD = sd.get("margin") or C.MARGIN_SD
    C.TOTAL_SD = sd.get("total") or C.TOTAL_SD


def kalshi_refresh(path=None, markets=None, now=None):
    """Rebuild the Kalshi section of data.json from fresh Kalshi markets and the sportsbook lines already
    stored there. Free: no Odds API call. The sportsbook numbers and their timestamp stay as they were."""
    prev = load_previous(path)
    if not prev:
        print("[kalshi-only] no version-2 data.json to work from; run a full scan first")
        return None
    now = now or datetime.now(timezone.utc)
    apply_measured_spreads(load_analytics())
    lines = props.lines_from_props(prev.get("props", []), prev.get("games", {}))
    gprops = [{k: v for k, v in p.items() if k != "id"} for p in prev.get("lines", [])]
    markets = markets if markets is not None else get_kalshi_markets()
    universe = []
    picks, stats = evaluate(lines, markets, universe, games_mod.lines_from_props(gprops), prev.get("games"))
    stats["credits_used"] = 0
    prop_list = [{k: v for k, v in p.items() if k != "id"} for p in prev.get("props", [])]
    data = site_data(picks, stats, universe, prop_list, prev.get("games"), prev.get("markets_updated"),
                     datetime.fromisoformat(prev["updated"]), gprops)
    data["kalshi_updated"] = now.isoformat(timespec="seconds")
    write_site(data, path)
    by = defaultdict(int)
    for u in data["kalshi"]:
        by[u["stat"]] += 1
    print(f"[kalshi-only] {len(data['kalshi'])} Kalshi contracts from {len(lines)} stored book lines: {dict(by)}")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-kalshi", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--kalshi-only", action="store_true")
    args = ap.parse_args()

    if args.kalshi_only:
        kalshi_refresh()
        return

    if args.estimate:
        if not C.ODDS_API_KEY:
            sys.exit("ODDS_API_KEY is not set.")
        events, remaining = odds.upcoming_events(C.ODDS_API_KEY, C.WINDOW_HOURS)  # free endpoint
        print(f"{len(events)} games x {len(C.ODDS_MARKETS)} markets x {odds.region_units(C.BOOKMAKERS)} region(s) "
              f"= at most {odds.run_cost(len(events), C.ODDS_MARKETS, C.BOOKMAKERS)} credits "
              f"(markets a book hasn't posted yet are free). Credits remaining: {remaining}")
        return

    if args.dump_kalshi:
        for m in get_kalshi_markets()[:60]:
            print(m.get("ticker"), "|", kalshi.market_text(m), "|", kalshi.prices(m))
        return

    lines, games, game_lines, used = collect_lines()
    apply_measured_spreads(load_analytics())
    now = datetime.now(timezone.utc)
    prev = load_previous()
    carried, carried_games, markets_updated = carry_forward(prev, set(C.ODDS_MARKETS), now)
    stamp = now.isoformat(timespec="seconds")
    markets_updated.update({m: stamp for m in C.ODDS_MARKETS})
    lines += carried
    games = {**carried_games, **games}
    prop_list = props.build_props(lines, C.SIGMA, C.MAX_LINE_DISTANCE, C.ALT_LINE_DISTANCE,
                                  C.ANYTIME_TD_VIG, C.PROP_MIN_BOOKS)
    props.add_line_moves(prop_list, (prev or {}).get("props"))
    print(f"[props] {len(prop_list)} sportsbook props across {len(games)} games")
    markets = get_kalshi_markets()
    gprops = games_mod.build_game_props(game_lines, C.MARGIN_SD, C.TOTAL_SD)
    print(f"[games] {len(gprops)} game-line props (moneyline / spread / total)")
    universe = []
    picks, stats = evaluate(lines, markets, universe, game_lines, games)
    stats["credits_used"] = used
    msg = build_message(picks, stats)
    print(msg)
    if not args.no_send:
        write_site(site_data(picks, stats, universe, prop_list, games, markets_updated, now, gprops))
        send_discord(msg)
        log_picks(picks, book_log_rows(prop_list, games) + game_log_rows(gprops, games), load_analytics())


if __name__ == "__main__":
    main()
