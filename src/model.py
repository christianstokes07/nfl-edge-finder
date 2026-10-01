"""Turn sportsbook lines into a fair probability for a Kalshi-style 'X or more' contract."""
import math
import re
from statistics import NormalDist

_N = NormalDist()

DISCRETE = {"player_pass_tds", "player_receptions", "player_pass_interceptions"}
YARDS = {"player_pass_yds", "player_rush_yds", "player_reception_yds"}


def norm_name(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", s.lower())
    toks = [t for t in s.split() if t not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(toks)


def american_to_prob(odds) -> float:
    odds = float(odds)
    return 100 / (odds + 100) if odds > 0 else -odds / (-odds + 100)


def devig_two_way(over_odds, under_odds) -> float:
    """No-vig probability of the first side."""
    a, b = american_to_prob(over_odds), american_to_prob(under_odds)
    return a / (a + b)


def lognormal_p_at_least(threshold: float, line: float, p_over: float, sigma: float) -> float:
    """Book says P(X > line) = p_over. Assume X is lognormal with spread sigma, anchor it to
    that, and return P(X >= threshold). Yardage lines end in .5 so 'X+' means X > X-0.5."""
    p = min(max(p_over, 1e-4), 1 - 1e-4)
    cut = max(threshold - 0.5, 0.5)
    z = _N.inv_cdf(1 - p)
    mu = math.log(line) - sigma * z
    return 1 - _N.cdf((math.log(cut) - mu) / sigma)


def kalshi_fee(price: float, rate: float) -> float:
    """Approximate taker fee per contract, in dollars, for a contract bought at `price` dollars."""
    return rate * price * (1 - price)


def fair_probability(stat, threshold, lines, sigma_map, max_dist, td_vig):
    """Average the fair probability implied by every book. Returns (prob, n_books) or (None, 0)."""
    probs = []
    for ln in lines:
        pr, pt = ln["prices"], ln["point"]
        if stat == "player_anytime_td":
            if "Yes" in pr and "No" in pr:
                probs.append(devig_two_way(pr["Yes"], pr["No"]))
            elif "Yes" in pr:
                probs.append(min(american_to_prob(pr["Yes"]) / (1 + td_vig), 0.99))
        elif stat in DISCRETE:
            # exact match only: Kalshi '2+' <-> book Over 1.5
            if pt is not None and "Over" in pr and "Under" in pr and abs(pt - (threshold - 0.5)) < 1e-6:
                probs.append(devig_two_way(pr["Over"], pr["Under"]))
        elif stat in YARDS:
            if pt and "Over" in pr and "Under" in pr and abs(threshold - pt) / pt <= max_dist:
                p_over = devig_two_way(pr["Over"], pr["Under"])
                probs.append(lognormal_p_at_least(threshold, pt, p_over, sigma_map[stat]))
    if not probs:
        return None, 0
    return sum(probs) / len(probs), len(probs)
