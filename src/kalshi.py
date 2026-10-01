"""Kalshi public market data (no login or API key needed for reads).

Kalshi's market titles aren't a fixed format, so instead of parsing the player name out of the
title we look for the sportsbook players' names inside the title text (see run.py)."""
import math
import re
import time

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"

NFL_SERIES_HINTS = re.compile(
    r"nfl|football|rushing|receiving|receptions|touchdown|passing|interception", re.I
)

# order matters: first match wins
STAT_PATTERNS = [
    ("player_rush_reception_yds", re.compile(r"rushing\s*(?:and|\+|&)\s*receiving yards|rush\s*\+\s*rec", re.I)),
    ("player_pass_tds", re.compile(r"passing touchdown|pass(?:ing)? td", re.I)),
    ("player_pass_interceptions", re.compile(r"passing interception|interceptions thrown", re.I)),
    ("player_pass_attempts", re.compile(r"passing attempts|pass attempts", re.I)),
    ("player_pass_completions", re.compile(r"passing completions|completions", re.I)),
    ("player_pass_yds", re.compile(r"passing yards|pass yards", re.I)),
    ("player_rush_attempts", re.compile(r"rushing attempts|rush attempts", re.I)),
    ("player_rush_yds", re.compile(r"rushing yards|rush yards", re.I)),
    ("player_reception_yds", re.compile(r"receiving yards|rec yards", re.I)),
    ("player_receptions", re.compile(r"receptions|catches", re.I)),
    ("player_anytime_td", re.compile(r"touchdown", re.I)),
]
# markets we can't price from single-stat lines, plus season-long markets (stat leaders, season totals,
# awards) whose titles mention the same stats but aren't single-game props
SKIP = re.compile(
    r"scrimmage|longest|first touchdown|last touchdown"
    r"|first td|last td|first scorer"
    r"|leader|\bmost\b|season|mvp|award|career|all-pro|pro bowl",
    re.I,
)
SKIP_TICKER = re.compile(r"LEADER|SEASON|MVP|AWARD|ROTY|OPOY|DPOY", re.I)
PLUS = re.compile(r"(\d+(?:\.\d+)?)\s*\+")
OVER = re.compile(r"(?:over|at least)\s+(\d+(?:\.\d+)?)", re.I)


def _get(path, params=None, tries=5):
    """GET with polite retries: Kalshi answers 429 (Too Many Requests) if we go too fast."""
    for i in range(tries):
        r = requests.get(f"{BASE}{path}", params=params or {}, timeout=30)
        if r.status_code == 429 and i < tries - 1:
            time.sleep(float(r.headers.get("Retry-After") or 0) or 1.5 * (2 ** i))
            continue
        r.raise_for_status()
        return r.json()


# Single-game player-prop series we can price from sportsbook lines. Kalshi lists 350+ NFL series
# (season wins, drafts, awards...); downloading all of them gets us rate-limited before the prop series
# load, so only these are fetched. New prop series are picked up by title (PROP_SERIES_TITLE).
PROP_SERIES = ("KXNFLRSHYDS", "KXNFLRECYDS", "KXNFLPASSYDS", "KXNFLREC", "KXNFLPASSTDS", "KXNFLTD", "KXNFLANYTD",
               "KXNFLPASSATT", "KXNFLPASSCOMP", "KXNFLRSHATT", "KXNFLPASSINT", "KXNFLRRYDS")
GAME_SERIES = ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL")
PROP_SERIES_TITLE = re.compile(r"^pro football (player )?(rushing yards|receiving yards|passing yards|receptions|"
                               r"player receptions|passing touchdowns|touchdowns|anytime touchdown|passing attempts|"
                               r"passing completions|rushing attempts|passing interceptions|rush and receiving yards)$", re.I)


def is_prop_series(ticker, title):
    t = (ticker or "").upper()
    if SKIP_TICKER.search(t) or not t.startswith("KXNFL"):
        return False
    return t in PROP_SERIES or t in GAME_SERIES or bool(PROP_SERIES_TITLE.match((title or "").strip()))


def discover_nfl_series():
    """NFL player-prop series tickers in the Sports category. Falls back to the known list if the call fails."""
    try:
        data = _get("/series", {"category": "Sports"})
    except Exception as e:  # noqa: BLE001
        print(f"[kalshi] series discovery failed ({e}); using the known prop series")
        return list(PROP_SERIES + GAME_SERIES)
    out = [s["ticker"] for s in data.get("series", []) if is_prop_series(s.get("ticker"), s.get("title"))]
    return out or list(PROP_SERIES + GAME_SERIES)


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
                    m["_event_ticker"] = ev.get("event_ticker", "")
                    m["_sub_title"] = ev.get("sub_title", "")
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


GAME_ML = re.compile(r"^KXNFLGAME-", re.I)
GAME_SPREAD = re.compile(r"^(.+?) wins by over (\d+(?:\.\d+)?) points", re.I)
GAME_TOTAL = re.compile(r"over (\d+(?:\.\d+)?) points scored", re.I)
PAIR = re.compile(r"^([A-Z]{2,3}) vs ([A-Z]{2,3})")


def parse_game_contract(m):
    """Game contracts -> {kind, team (abbr or None), threshold, pair: (abbr, abbr)} or None.
    KXNFLGAME 'Cleveland wins' (ticker ends -CLE); KXNFLSPREAD 'PIT Steelers wins by over 20.5 points?';
    KXNFLTOTAL 'Full Game: over 17.5 points scored?'. Quarter/half markets live in other series."""
    t = m.get("ticker", "") or ""
    pair = PAIR.match(m.get("_sub_title", "") or "")
    pair = (pair.group(1), pair.group(2)) if pair else None
    title = m.get("title", "") or ""
    if GAME_ML.match(t):
        return {"kind": "game_ml", "team": t.rsplit("-", 1)[-1], "threshold": None, "pair": pair}
    if t.upper().startswith("KXNFLSPREAD-"):
        mm = GAME_SPREAD.search(title)
        if mm:
            return {"kind": "game_spread", "team": mm.group(1).split()[0].upper(), "threshold": float(mm.group(2)), "pair": pair}
    if t.upper().startswith("KXNFLTOTAL-") and title.lower().startswith("full game"):
        mm = GAME_TOTAL.search(title)
        if mm:
            return {"kind": "game_total", "team": None, "threshold": float(mm.group(1)), "pair": pair}
    return None


def parse_contract(m):
    """Return {'stat', 'threshold'} for single-stat player contracts, else None."""
    if (m.get("ticker") or "").upper().startswith(GAME_SERIES):
        return None  # game contracts: parse_game_contract
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
