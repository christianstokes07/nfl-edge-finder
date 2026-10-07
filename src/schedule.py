"""The upcoming slate, for free: The Odds API's /events list (0 credits) when a key is set, else ESPN's
public scoreboard. Used by the Kalshi refresh so the page rolls to the new week's games as soon as last
week's are over, without waiting for Thursday's paid scan."""
from datetime import datetime, timedelta, timezone

import requests

from . import odds

ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


def _ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def from_espn(now, days, session=None):
    """{espn:<id>: {a, h, t}} for games kicking off from now to now + days. Reads this week and the next."""
    get = (session or requests).get
    out = {}
    try:
        cur = get(ESPN, timeout=20).json()
        week, stype = (cur.get("week") or {}).get("number"), ((cur.get("season") or {}).get("type") or 2)
        pages = [cur] + ([get(ESPN, params={"seasontype": stype, "week": week + 1}, timeout=20).json()] if week else [])
    except Exception as e:  # noqa: BLE001
        print(f"[schedule] ESPN unavailable ({type(e).__name__})")
        return out
    for d in pages:
        for e in d.get("events", []):
            c = (e.get("competitions") or [{}])[0]
            teams = {x["homeAway"]: x["team"]["displayName"] for x in c.get("competitors", [])}
            t = _ts(e["date"])
            if "home" in teams and "away" in teams and now <= t <= now + timedelta(days=days):
                out["espn:" + e["id"]] = {"a": teams["away"], "h": teams["home"], "t": e["date"]}
    return out


def week_end(kicks, now):
    """End of the current NFL week: the first Tuesday 10:00 UTC (after Monday night's game) following the
    earliest kickoff still to come. Games after it belong to next week's slate."""
    future = sorted(k for k in kicks if k > now)
    if not future:
        return now
    t = future[0]
    days = (1 - t.weekday()) % 7 or 7          # weekday 1 = Tuesday
    end = (t + timedelta(days=days)).replace(hour=10, minute=0, second=0, microsecond=0)
    return end


def this_week(games, now=None):
    """Only the games of the current NFL week (drops next week's Thursday game, etc.)."""
    now = now or datetime.now(timezone.utc)
    kicks = {g: _ts(v["t"]) for g, v in games.items() if v.get("t")}
    start = now - timedelta(hours=4)             # a game that kicked off 4+ hours ago is over
    end = week_end(kicks.values(), start)
    return {g: v for g, v in games.items() if g in kicks and start < kicks[g] < end}


def upcoming(api_key=None, now=None, days=9):
    """{game id: {a, h, t}} for the next `days` days. Odds API ids when a key is set (so Thursday's scan
    lines up with them); ESPN otherwise or if that call fails."""
    now = now or datetime.now(timezone.utc)
    if api_key:
        try:
            evs, _ = odds.upcoming_events(api_key, days * 24)
            return this_week({e["id"]: {"a": e["away_team"], "h": e["home_team"], "t": e["commence_time"]} for e in evs}, now)
        except Exception as e:  # noqa: BLE001
            print(f"[schedule] Odds API /events failed ({e}); using ESPN")
    return this_week(from_espn(now, days), now)
