"""python -m src.run            -> scan and send results
python -m src.run --dump-kalshi -> print raw Kalshi NFL market titles (for debugging matching)
python -m src.run --no-send     -> scan and print only (no Discord, no log)"""
import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

import requests

from . import config as C
from . import kalshi, model, odds

STAT_LABEL = {
    "player_rush_yds": "rushing yds",
    "player_reception_yds": "receiving yds",
    "player_pass_yds": "passing yds",
    "player_pass_tds": "passing TDs",
    "player_receptions": "receptions",
    "player_anytime_td": "anytime TD",
}


def collect_lines():
    if not C.ODDS_API_KEY:
        sys.exit("ODDS_API_KEY is not set.")
    events, remaining = odds.upcoming_events(C.ODDS_API_KEY, C.WINDOW_HOURS)
    print(f"[odds] {len(events)} games in the next {C.WINDOW_HOURS:.0f}h")
    all_lines = []
    for e in events:
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
        all_lines.extend(lines)
    print(f"[odds] {len(all_lines)} book lines, credits remaining: {remaining}")
    return all_lines


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
    idx, names = index_lines(lines)
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
        if universe is not None and 0.05 < fair < 0.95:
            universe.append({"ticker": m.get("ticker", ""), "player": book_lines[0]["player"],
                             "game": book_lines[0].get("game", ""), "stat": c["stat"],
                             "label": STAT_LABEL[c["stat"]], "threshold": c["threshold"],
                             "fair": round(fair, 3), "books": n})
        bid, ask = kalshi.prices(m)
        if not bid or not ask or ask >= 99 or (ask - bid) > C.MAX_SPREAD_CENTS:
            continue
        stats["scored"] += 1
        yes_cost = ask / 100
        no_cost = 1 - bid / 100
        edge_yes = fair - yes_cost - model.kalshi_fee(yes_cost, C.KALSHI_FEE_RATE)
        edge_no = (1 - fair) - no_cost - model.kalshi_fee(no_cost, C.KALSHI_FEE_RATE)
        side, edge, cost, p_win = ("YES", edge_yes, yes_cost, fair)
        if edge_no > edge_yes:
            side, edge, cost, p_win = ("NO", edge_no, no_cost, 1 - fair)
        if edge < C.MIN_EDGE:
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


def log_picks(picks):
    if not picks:
        return
    os.makedirs(os.path.dirname(C.LOG_PATH) or ".", exist_ok=True)
    new = not os.path.exists(C.LOG_PATH)
    with open(C.LOG_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["ts_utc", "game", "player", "stat", "threshold", "side", "price_c", "fair", "edge", "ticker"])
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for p in picks:
            w.writerow([ts, p["game"], p["player"], p["stat"], p["threshold"], p["side"], p["price"],
                        f"{p['fair']:.3f}", f"{p['edge']:.3f}", p["ticker"]])


def write_site(picks, stats, universe=()):
    """Data file read by site/index.html (the phone page)."""
    os.makedirs(os.path.dirname(C.SITE_DATA_PATH) or ".", exist_ok=True)
    data = {
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_edge": C.MIN_EDGE,
        "stats": stats,
        "params": {"fee": C.KALSHI_FEE_RATE, "max_spread": C.MAX_SPREAD_CENTS,
                   "min_edge": C.MIN_EDGE, "top_n": C.TOP_N},
        "universe": list(universe)[:80],  # every scored contract; the page re-prices these live
        "picks": [
            {**p, "label": STAT_LABEL[p["stat"]], "fair": round(p["fair"], 3), "edge": round(p["edge"], 3)}
            for p in picks[: C.TOP_N]
        ],
    }
    with open(C.SITE_DATA_PATH, "w") as f:
        json.dump(data, f, indent=1)


def get_kalshi_markets():
    series = kalshi.discover_nfl_series()
    print(f"[kalshi] NFL-ish series found: {len(series)}")
    return kalshi.fetch_open_markets(series)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump-kalshi", action="store_true")
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()

    if args.dump_kalshi:
        for m in get_kalshi_markets()[:60]:
            print(m.get("ticker"), "|", kalshi.market_text(m), "|", kalshi.prices(m))
        return

    lines = collect_lines()
    markets = get_kalshi_markets()
    universe = []
    picks, stats = evaluate(lines, markets, universe)
    msg = build_message(picks, stats)
    print(msg)
    if not args.no_send:
        write_site(picks, stats, universe)
        send_discord(msg)
        log_picks(picks)


if __name__ == "__main__":
    main()
