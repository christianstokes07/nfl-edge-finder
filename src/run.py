"""python -m src.run            -> scan and send results
python -m src.run --dump-kalshi -> print raw Kalshi NFL market titles (for debugging matching)
python -m src.run --no-send     -> scan and print only (no Discord, no log, no data.json)
python -m src.run --estimate    -> print what a scan would cost in Odds API credits (uses 0 credits)"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests

from . import config as C
from . import kalshi, model, odds, props, verdict

STAT_LABEL = {
    "player_rush_yds": "rushing yds",
    "player_reception_yds": "receiving yds",
    "player_pass_yds": "passing yds",
    "player_pass_tds": "passing TDs",
    "player_receptions": "receptions",
    "player_anytime_td": "anytime TD",
}


def collect_lines():
    """Returns (lines, games, credits_used). Only the per-game odds calls cost credits."""
    if not C.ODDS_API_KEY:
        sys.exit("ODDS_API_KEY is not set.")
    events, remaining = odds.upcoming_events(C.ODDS_API_KEY, C.WINDOW_HOURS)
    start = remaining
    print(f"[odds] {len(events)} games in the next {C.WINDOW_HOURS:.0f}h, markets: {','.join(C.ODDS_MARKETS)}")
    all_lines, games = [], {}
    for e in events:
        if remaining is not None and remaining <= C.CREDIT_RESERVE:
            print(f"[odds] only {remaining:.0f} credits left, stopping to protect the reserve")
            break
        try:
            lines, remaining = odds.event_props(C.ODDS_API_KEY, e["id"], C.ODDS_MARKETS, C.BOOKMAKERS)
        except odds.OddsAPIError as err:
            print(f"[odds] {e.get('away_team')} @ {e.get('home_team')}: {err}")
            continue
        games[e["id"]] = {"a": e.get("away_team", ""), "h": e.get("home_team", ""), "t": e.get("commence_time")}
        for ln in lines:
            ln["game"] = f"{e.get('away_team')} @ {e.get('home_team')}"
            ln["game_id"] = e["id"]
            ln["kick"] = e.get("commence_time")
        all_lines.extend(lines)
    used = (start - remaining) if (start is not None and remaining is not None) else None
    print(f"[odds] {len(all_lines)} book lines, credits used this run: {used}, remaining: {remaining}")
    return all_lines, games, used


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


def evaluate(lines, markets, universe=None):
    """Pure function: book lines + Kalshi markets -> (picks, stats)."""
    idx, names = index_lines([ln for ln in lines if props.is_main(ln)])
    stats = {"markets": len(markets), "parsed": 0, "matched": 0, "scored": 0}
    picks = []
    for m in markets:
        c = kalshi.parse_contract(m)
        if not c:
            continue
        stats["parsed"] += 1
        player = find_player(kalshi.market_text(m), names)
        if not player:
            continue
        book_lines = idx.get((player, c["stat"]))
        if not book_lines:
            continue
        stats["matched"] += 1
        fair, n = model.fair_probability(
            c["stat"], c["threshold"], book_lines, C.SIGMA, C.MAX_LINE_DISTANCE, C.ANYTIME_TD_VIG
        )
        if fair is None or n < C.MIN_BOOKS:
            continue
        bid, ask = kalshi.prices(m)
        if universe is not None and 0.03 < fair < 0.97:
            universe.append({"ticker": m.get("ticker", ""), "player": book_lines[0]["player"],
                             "g": props.game_id(book_lines[0]), "stat": c["stat"],
                             "label": STAT_LABEL[c["stat"]], "threshold": c["threshold"],
                             "fair": round(fair, 3), "books": n,
                             "unc": round(model.uncertainty(c["stat"], c["threshold"], book_lines, C.MAX_LINE_DISTANCE), 3),
                             "bid": bid, "ask": ask})
        if not bid or not ask or ask >= 99 or (ask - bid) > C.MAX_SPREAD_CENTS:
            continue
        stats["scored"] += 1
        by = stats.setdefault("by_stat", {})
        by[STAT_LABEL[c["stat"]]] = by.get(STAT_LABEL[c["stat"]], 0) + 1
        yes_cost = ask / 100
        no_cost = 1 - bid / 100
        edge_yes = fair - yes_cost - model.kalshi_fee(yes_cost, C.KALSHI_FEE_RATE)
        edge_no = (1 - fair) - no_cost - model.kalshi_fee(no_cost, C.KALSHI_FEE_RATE)
        side, edge, cost, p_win = ("YES", edge_yes, yes_cost, fair)
        if edge_no > edge_yes:
            side, edge, cost, p_win = ("NO", edge_no, no_cost, 1 - fair)
        if edge < (C.MIN_EDGE_TD if c["stat"] == "player_anytime_td" else C.MIN_EDGE):
            continue
        picks.append(
            {
                "player": book_lines[0]["player"],
                "game": book_lines[0].get("game", ""),
                "stat": c["stat"],
                "threshold": c["threshold"],
                "side": side,
                "price": round(cost * 100),
                "fair": p_win,
                "edge": edge,
                "books": n,
                "ticker": m.get("ticker", ""),
            }
        )
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


def site_data(picks, stats, universe=(), prop_list=(), games=None, markets_updated=None, now=None):
    """Everything site/index.html needs. Kept compact: per-book prices are [over/yes, under/no] pairs."""
    now = now or datetime.now(timezone.utc)
    games = games or {}
    counts = defaultdict(int)
    for p in prop_list:
        for b in p["b"]:
            counts[b] += 1
    configured = [b.strip() for b in C.BOOKMAKERS.split(",") if b.strip()]
    books = [{"k": b, "name": C.BOOK_NAMES.get(b, b), "n": counts.get(b, 0), "paid": b in C.PAID_ONLY_BOOKS}
             for b in configured + sorted(set(counts) - set(configured))]
    used = {p["g"] for p in prop_list} | {u.get("g") for u in universe}
    kalshi_rows = sorted(universe, key=_spread)[: C.KALSHI_MAX_ROWS]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-kalshi", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    args = ap.parse_args()

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

    lines, games, used = collect_lines()
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
    universe = []
    picks, stats = evaluate(lines, markets, universe)
    stats["credits_used"] = used
    msg = build_message(picks, stats)
    print(msg)
    if not args.no_send:
        write_site(site_data(picks, stats, universe, prop_list, games, markets_updated, now))
        send_discord(msg)
        log_picks(picks, book_log_rows(prop_list, games), load_analytics())


if __name__ == "__main__":
    main()
