"""Sportsbook player-prop lines from The Odds API (https://the-odds-api.com)."""
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl"


class OddsAPIError(Exception):
    pass


def region_units(bookmakers):
    """The Odds API bills every group of up to 10 bookmakers as one region."""
    n = len([b for b in bookmakers.split(",") if b.strip()])
    return max(1, -(-n // 10))


def run_cost(n_games, markets, bookmakers):
    """Upper bound on credits for one scan: games x markets x regions (empty markets are free)."""
    return n_games * len(markets) * region_units(bookmakers)


def _get(path, params):
    r = requests.get(f"{BASE}{path}", params=params, timeout=30)
    if r.status_code != 200:
        raise OddsAPIError(f"{r.status_code}: {r.text[:200]}")
    remaining = r.headers.get("x-requests-remaining")
    return r.json(), (float(remaining) if remaining is not None else None)


def upcoming_events(api_key, window_hours):
    """Games kicking off within the window. The /events endpoint doesn't use credits."""
    data, remaining = _get("/events", {"apiKey": api_key})
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=window_hours)
    out = []
    for e in data:
        t = datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00"))
        if now <= t <= end:
            out.append(e)
    return out, remaining


def event_props(api_key, event_id, markets, bookmakers):
    """Returns (lines, credits_remaining). Each line:
    {player, market, book, point, prices: {'Over': -115, 'Under': -105} or {'Yes': 120}}"""
    data, remaining = _get(
        f"/events/{event_id}/odds",
        {
            "apiKey": api_key,
            "markets": ",".join(markets),
            "bookmakers": bookmakers,
            "oddsFormat": "american",
        },
    )
    grouped = {}
    for b in data.get("bookmakers", []):
        for m in b.get("markets", []):
            for o in m.get("outcomes", []):
                player = o.get("description")
                if not player:
                    continue
                key = (player, m["key"], b["key"], o.get("point"))
                grouped.setdefault(key, {})[o["name"]] = o["price"]
    lines = [
        {"player": k[0], "market": k[1], "book": k[2], "point": k[3], "prices": v}
        for k, v in grouped.items()
    ]
    return lines, remaining
