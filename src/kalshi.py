"""Kalshi public market data (no login or API key needed for reads).

Kalshi's market titles aren't a fixed format, so instead of parsing the player name out of the
title we look for the sportsbook players' names inside the title text (see run.py)."""
import math
import re

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"

NFL_SERIES_HINTS = re.compile(
    r"nfl|football|rushing|receiving|receptions|touchdown|passing|interception", re.I
)

# order matters: first match wins
STAT_PATTERNS = [
    ("player_pass_tds", re.compile(r"passing touchdown|pass(?:ing)? td", re.I)),
    ("player_pass_yds", re.compile(r"passing yards|pass yards", re.I)),
    ("player_rush_yds", re.compile(r"rushing yards|rush yards", re.I)),
    ("player_reception_yds", re.compile(r"receiving yards|rec yards", re.I)),
    ("player_receptions", re.compile(r"receptions|catches", re.I)),
    ("player_anytime_td", re.compile(r"touchdown", re.I)),
]
# markets we can't price from single-stat lines, plus season-long markets (stat leaders, season totals,
# awards) whose titles mention the same stats but aren't single-game props
SKIP = re.compile(
    r"rushing\s*(?:and|\+|&)\s*receiving|scrimmage|combined|longest|first touchdown|last touchdown"
    r"|first td|last td|first scorer"
    r"|leader|\bmost\b|season|mvp|award|career|all-pro|pro bowl",
    re.I,
)
SKIP_TICKER = re.compile(r"LEADER|SEASON|MVP|AWARD|ROTY|OPOY|DPOY", re.I)
PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*\+")
OVER = re.compile(r"(?:over|at least)\s+(\d+(?:\.\d+)?)", re.I)


def _get(path, params=None):
    r = requests.get(f"{BASE}{path}", params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def discover_nfl_series():
    """Find NFL-related series tickers in the Sports category. Returns [] if the call fails."""
    try:
        data = _get("/series", {"category": "Sports"})
    except Exception as e:  # noqa: BLE001
        print(f"[kalshi] series discovery failed: {e}")
        return []
    out = []
    for s in data.get("series", []):
        ticker = s.get("ticker", "")
        if ticker.upper().startswith("KXNFL") or NFL_SERIES_HINTS.search(s.get("title", "")):
            out.append(ticker)
    return out


def fetch_open_markets(series_tickers, max_pages=20):
    markets = []
    for series in series_tickers:
        cursor = None
        for _ in range(max_pages):
            params = {"status": "open", "with_nested_markets": "true", "limit": 200, "series_ticker": series}
            if cursor:
                params["cursor"] = cursor
            try:
                data = _get("/events", params)
            except Exception as e:  # noqa: BLE001
                print(f"[kalshi] {series}: {e}")
                break
            for ev in data.get("events", []):
                for m in ev.get("markets") or []:
                    m["_event_title"] = ev.get("title", "")
                    markets.append(m)
            cursor = data.get("cursor")
            if not cursor:
                break
    return markets


def _cents(m, field):
    v = m.get(field)
    if v is not None:
        return float(v)
    d = m.get(field + "_dollars")
    if d is not None:
        return round(float(d) * 100, 1)
    return None


def market_text(m):
    parts = [m.get("title"), m.get("yes_sub_title"), m.get("subtitle"), m.get("_event_title")]
    return " | ".join(p for p in parts if p)


def prices(m):
    """(yes_bid, yes_ask) in cents, either may be None/0 if there's no book on that side."""
    return _cents(m, "yes_bid"), _cents(m, "yes_ask")


def parse_contract(m):
    """Return {'stat', 'threshold'} for single-stat player contracts, else None."""
    text = market_text(m)
    if SKIP.search(text) or SKIP_TICKER.search(m.get("ticker", "") or "") \
            or SKIP_TICKER.search(m.get("event_ticker", "") or ""):
        return None
    stat = next((s for s, pat in STAT_PATTERNS if pat.search(text)), None)
    if not stat:
        return None
    threshold = None
    mp = PLUS.search(text)
    if mp:
        threshold = float(mp.group(1))
    else:
        mo = OVER.search(text)
        if mo:
            x = float(mo.group(1))
            threshold = math.floor(x) + 1 if x != int(x) else x
    if threshold is None:
        if stat == "player_anytime_td":
            threshold = 1.0
        else:
            return None
    if stat == "player_anytime_td" and threshold != 1:
        return None  # multi-TD contracts: not priced in v1
    return {"stat": stat, "threshold": threshold}
