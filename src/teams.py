"""NFL team names and abbreviations. The Odds API uses full names ("Pittsburgh Steelers"); Kalshi uses
abbreviations (PIT, JAC, LAR) and city names ("Cleveland wins"); nflverse uses LA / JAX-style codes."""

TEAMS = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
# other spellings of the same abbreviation -> the one in TEAMS
ALIASES = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "LVR": "LV", "GNB": "GB", "KAN": "KC", "NOR": "NO",
           "NWE": "NE", "SFO": "SF", "TAM": "TB"}


def abbr(name_or_code):
    """Full name, abbreviation or alias -> canonical abbreviation (None if unknown)."""
    if not name_or_code:
        return None
    s = name_or_code.strip()
    if s in TEAMS:
        return TEAMS[s]
    up = s.upper()
    if up in ALIASES:
        return ALIASES[up]
    if up in TEAMS.values():
        return up
    return None


def by_text(text, candidates):
    """Which of `candidates` (full team names) does `text` mention: abbreviation, city or nickname."""
    t = f" {text.lower()} "
    # abbreviations and nicknames first: cities are ambiguous (two Los Angeles and two New York teams)
    for full in candidates:
        city, nick = full.rsplit(" ", 1)
        code = TEAMS.get(full, "")
        codes = {code.lower()} | {a.lower() for a, c in ALIASES.items() if c == code}
        if f" {nick.lower()}" in t or any(f" {c} " in t for c in codes):
            return full
    hits = [f for f in candidates if f" {f.rsplit(' ', 1)[0].lower()} " in t]
    return hits[0] if len(hits) == 1 else None
