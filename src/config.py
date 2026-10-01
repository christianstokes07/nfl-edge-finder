"""All settings in one place. Everything can be overridden with environment variables
(GitHub Actions secrets/vars, or a local shell export)."""
import os


def _f(name, default):
    return float(os.environ.get(name, default))


def _i(name, default):
    return int(os.environ.get(name, default))


def _list(name, default):
    return [x.strip() for x in (os.environ.get(name) or default).split(",") if x.strip()]


# --- secrets -----------------------------------------------------------------
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

# --- sportsbook data (The Odds API) -------------------------------------------
# Free tier = 500 credits/month. Cost per game = (markets returned) x (regions), and every group of
# up to 10 bookmakers counts as ONE region. So 10 books cost the same as 1: don't go past 10.
# Adding a market (including an *_alternate one) adds about 1 credit per game.
ODDS_MARKETS = _list("ODDS_MARKETS", "player_rush_yds,player_reception_yds,player_pass_yds,player_anytime_td")
# Odds API keys. Caesars is "williamhill_us". Caesars and Fanatics only return data on paid Odds API
# plans; they're listed so they show up if you upgrade, and they cost nothing extra while <= 10 books.
BOOKMAKERS = os.environ.get(
    "BOOKMAKERS",
    "draftkings,fanduel,betmgm,williamhill_us,espnbet,fanatics,betrivers,hardrockbet,betparx,ballybet",
)
BOOK_NAMES = {
    "draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM", "williamhill_us": "Caesars",
    "espnbet": "theScore Bet", "fanatics": "Fanatics", "betrivers": "BetRivers", "hardrockbet": "Hard Rock Bet",
    "betparx": "betPARX", "ballybet": "Bally Bet", "bovada": "Bovada", "betonlineag": "BetOnline",
    "mybookieag": "MyBookie", "lowvig": "LowVig", "betus": "BetUS", "fliff": "Fliff",
}
PAID_ONLY_BOOKS = {"williamhill_us", "fanatics"}
WINDOW_HOURS = _f("WINDOW_HOURS", 110)   # only look at games kicking off within this many hours
CREDIT_RESERVE = _i("CREDIT_RESERVE", 15)  # stop calling the API if credits drop below this

# --- model assumptions --------------------------------------------------------
MIN_BOOKS = _i("MIN_BOOKS", 2)             # books that must agree before a contract is scored
MAX_LINE_DISTANCE = _f("MAX_LINE_DISTANCE", 0.25)  # ignore Kalshi thresholds >25% away from the book line
ALT_LINE_DISTANCE = _f("ALT_LINE_DISTANCE", 0.5)   # alternate sportsbook lines may sit further from the main line
PROP_MIN_BOOKS = _i("PROP_MIN_BOOKS", 1)   # sportsbook picks: books needed for a hit chance (count is shown)
ANYTIME_TD_VIG = _f("ANYTIME_TD_VIG", 0.12)  # rough vig removed from one-sided anytime-TD prices
# Spread of a player's yardage (lognormal sigma). Rough guesses: tune after you have results logged.
SIGMA = {
    "player_rush_yds": _f("SIGMA_RUSH", 0.60),
    "player_reception_yds": _f("SIGMA_REC", 0.65),
    "player_pass_yds": _f("SIGMA_PASS", 0.28),
}

# --- Kalshi / output ----------------------------------------------------------
KALSHI_FEE_RATE = _f("KALSHI_FEE_RATE", 0.07)  # taker fee ~ rate * p * (1-p) per contract; verify on Kalshi
MIN_EDGE = _f("MIN_EDGE", 0.05)                # 5 points after fees
MIN_EDGE_TD = _f("MIN_EDGE_TD", 0.08)          # anytime-TD fair values are rougher, so demand more
MAX_SPREAD_CENTS = _i("MAX_SPREAD_CENTS", 8)   # skip illiquid contracts
TOP_N = _i("TOP_N", 10)
KALSHI_MAX_ROWS = _i("KALSHI_MAX_ROWS", 300)   # Kalshi contracts written to the page (live-priced there)
LOG_PATH = os.environ.get("LOG_PATH", "data/picks_log.csv")
SITE_DATA_PATH = os.environ.get("SITE_DATA_PATH", "site/data.json")
ANALYTICS_PATH = os.environ.get("ANALYTICS_PATH", "site/analytics.json")

# Kalshi names that differ from sportsbook names. normalized kalshi name -> normalized book name
NAME_ALIASES = {
    "patrick freiermuth": "pat freiermuth",
}
