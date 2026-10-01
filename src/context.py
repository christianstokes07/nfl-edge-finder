"""Game context for the upcoming week: spread, total, implied team totals, roof, weather, rest.

Sources, in order:
- nflverse schedules: spread_line (home team's expected margin), total_line, roof, rest days.
  nflverse only fills temp/wind after a game is played, so for upcoming games:
- Open-Meteo forecast (free, no key) at the stadium, for the kickoff hour.
- Odds API bulk odds, only if nflverse has no spread/total for a game: ONE call for every game,
  markets spreads+totals on 3 books (one region) = 2 credits."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

ET = ZoneInfo("America/New_York")

# Stadium coordinates (lat, lon) by nflverse stadium_id, for weather lookups. Only open-air and
# retractable-roof venues are needed: fixed domes never get a weather check.
STADIUMS = {
    "BAL00": (39.278, -76.623), "BOS00": (42.091, -71.264), "BUF00": (42.774, -78.787),
    "CAR00": (35.226, -80.853), "CHI98": (41.862, -87.617), "CIN00": (39.095, -84.516),
    "CLE00": (41.506, -81.699), "DEN00": (39.744, -105.020), "GNB00": (44.501, -88.062),
    "JAX00": (30.324, -81.637), "KAN00": (39.049, -94.484), "MIA00": (25.958, -80.239),
    "NAS00": (36.166, -86.771), "NYC01": (40.814, -74.074), "PHI00": (39.901, -75.168),
    "PIT00": (40.447, -80.016), "SEA00": (47.595, -122.332), "SFO01": (37.403, -121.970),
    "TAM00": (27.976, -82.503), "WAS00": (38.908, -76.864), "LON00": (51.556, -0.280),
    "LON02": (51.604, -0.066), "MEX00": (19.303, -99.150), "RIO00": (-22.912, -43.230),
    "MAD01": (40.453, -3.688),
    # retractable roofs: forecast shown, but the roof may be closed
    "ATL97": (33.755, -84.401), "DAL00": (32.748, -97.093), "HOU00": (29.685, -95.411),
    "IND00": (39.760, -86.164), "PHO00": (33.528, -112.263),
}
RETRACTABLE = {"ATL97", "DAL00", "HOU00", "IND00", "PHO00"}


def kickoff_utc(gameday, gametime):
    """nflverse gameday 'YYYY-MM-DD' + gametime 'HH:MM' (US Eastern) -> aware UTC datetime."""
    if not gameday:
        return None
    hh, mm = (gametime or "13:00").split(":")
    local = datetime.strptime(gameday, "%Y-%m-%d").replace(hour=int(hh), minute=int(mm), tzinfo=ET)
    return local.astimezone(timezone.utc)


def implied_totals(spread_line, total_line):
    """nflverse spread_line is the HOME team's expected margin (positive = home favored).
    Returns (home_implied, away_implied) or (None, None)."""
    if spread_line is None or total_line is None:
        return None, None
    return total_line / 2 + spread_line / 2, total_line / 2 - spread_line / 2


def roof_kind(roof, stadium_id):
    if roof in ("dome", "closed"):
        return "indoors"
    if stadium_id in RETRACTABLE and roof not in ("open", "outdoors"):
        return "retractable"
    if roof in ("outdoors", "open"):
        return "outdoors"
    return "unknown"


def forecast(lat, lon, kick, session=None, now=None):
    """Kickoff-hour forecast from Open-Meteo. Returns ({temp_f, wind_mph, precip_pct}, None) or (None, reason)."""
    now = now or datetime.now(timezone.utc)
    if kick - now > timedelta(days=15):
        return None, "forecast not out yet (more than 15 days away)"
    if kick < now - timedelta(hours=3):
        return None, "game already played"
    try:
        r = (session or requests).get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
            "latitude": lat, "longitude": lon, "hourly": "temperature_2m,wind_speed_10m,precipitation_probability",
            "wind_speed_unit": "mph", "temperature_unit": "fahrenheit", "timezone": "UTC",
            "start_date": kick.strftime("%Y-%m-%d"), "end_date": kick.strftime("%Y-%m-%d")})
        r.raise_for_status()
        h = r.json()["hourly"]
    except Exception as e:  # noqa: BLE001
        return None, f"weather service error ({type(e).__name__})"
    want = kick.strftime("%Y-%m-%dT%H:00")
    if want not in h["time"]:
        return None, "kickoff hour missing from forecast"
    i = h["time"].index(want)
    return {"temp": h["temperature_2m"][i], "wind": h["wind_speed_10m"][i],
            "precip": h["precipitation_probability"][i]}, None


def odds_api_lines(api_key, team_abbr_by_name):
    """Fallback: one bulk call for spreads + totals on every upcoming game (2 credits).
    Returns {(home_abbr, away_abbr): (home_spread_line, total)} where home_spread_line follows the
    nflverse convention (positive = home favored)."""
    r = requests.get("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds", timeout=30, params={
        "apiKey": api_key, "markets": "spreads,totals", "bookmakers": "draftkings,fanduel,betmgm",
        "oddsFormat": "american"})
    r.raise_for_status()
    out = {}
    for ev in r.json():
        home, away = team_abbr_by_name.get(ev["home_team"]), team_abbr_by_name.get(ev["away_team"])
        spreads, totals = [], []
        for b in ev.get("bookmakers", []):
            for m in b.get("markets", []):
                for o in m.get("outcomes", []):
                    if m["key"] == "spreads" and o.get("name") == ev["home_team"] and o.get("point") is not None:
                        spreads.append(-o["point"])  # Odds API: home -3.5 means home favored by 3.5
                    if m["key"] == "totals" and o.get("name") == "Over" and o.get("point") is not None:
                        totals.append(o["point"])
        if home and away and spreads and totals:
            out[(home, away)] = (sum(spreads) / len(spreads), sum(totals) / len(totals))
    return out, r.headers.get("x-requests-last")


def upcoming_week(schedules, now=None):
    """First regular-season week that still has an unplayed game kicking off from now on."""
    now = now or datetime.now(timezone.utc)
    weeks = []
    for g in schedules.iter_rows(named=True):
        if g["game_type"] != "REG" or g["home_score"] is not None:
            continue
        k = kickoff_utc(g["gameday"], g["gametime"])
        if k and k > now - timedelta(hours=4):
            weeks.append(g["week"])
    return min(weeks) if weeks else None
