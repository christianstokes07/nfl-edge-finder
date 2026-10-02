"""Current injury statuses from ESPN's public NFL feed (free, no key). Fresher than nflverse's weekly
injury file: it carries Friday's game designations (Out / Doubtful / Questionable) as soon as they're
posted, with a timestamp and the latest news note. The analytics job uses it first and falls back to
nflverse; the page also reads it live through functions/api/injuries.js."""
import requests

from . import teams as T
from .model import norm_name

URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
# statuses that mean "won't play": their usage gets handed to teammates in the projections
OUT = {"Out", "Doubtful", "Injured Reserve", "Suspension", "Physically Unable to Perform", "Reserve/PUP", "IR"}


def parse(d):
    """ESPN feed -> {team abbr: [{n, pos, s, d, i, c}]} (Active entries dropped)."""
    out = {}
    for t in d.get("injuries", []):
        abbr = T.abbr(t.get("displayName"))
        if not abbr:
            continue
        rows = []
        for i in t.get("injuries", []):
            if not i.get("status") or i["status"] == "Active":
                continue
            a = i.get("athlete") or {}
            rows.append({"n": a.get("displayName"), "pos": (a.get("position") or {}).get("abbreviation") or "",
                         "s": i["status"], "d": i.get("date"), "i": (i.get("details") or {}).get("type"),
                         "c": (i.get("shortComment") or "")[:160]})
        out[abbr] = rows
    return out


def fetch(session=None):
    """Returns ({team: [...]}, None) or ({}, reason)."""
    try:
        r = (session or requests).get(URL, timeout=20)
        r.raise_for_status()
        return parse(r.json()), None
    except Exception as e:  # noqa: BLE001
        return {}, f"ESPN injuries unavailable ({type(e).__name__})"


def by_name(espn):
    """(team, normalized name) -> entry."""
    return {(t, norm_name(x["n"] or "")): x for t, xs in espn.items() for x in xs}
