"""Turn sportsbook lines into a fair probability for a Kalshi-style 'X or more' contract."""
import math
import re
from statistics import NormalDist

_N = NormalDist()

# Yards and larger counts: lognormal anchored to each book's line (spread = SIGMA per stat).
YARDS = {"player_pass_yds", "player_rush_yds", "player_reception_yds", "player_rush_reception_yds"}
COUNTS = {"player_receptions", "player_pass_completions", "player_pass_attempts", "player_rush_attempts"}
SPREAD_STATS = YARDS | COUNTS
# Small counts (0, 1, 2, 3...): Poisson with its rate solved from each book's line.
POISSON = {"player_pass_tds", "player_pass_interceptions"}
DISCRETE = POISSON  # kept for older imports


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


def poisson_rate(line: float, p_over: float) -> float:
    """Rate λ with P(X > line) = p_over for X ~ Poisson(λ) (bisection; line like 1.5)."""
    k = int(math.floor(line))
    target = min(max(p_over, 1e-4), 1 - 1e-4)
    def p_gt(lam):
        term, cdf = math.exp(-lam), 0.0
        for i in range(k + 1):
            cdf += term
            term *= lam / (i + 1)
        return 1 - cdf
    lo, hi = 1e-6, 30.0
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if p_gt(mid) < target else (lo, mid)
    return (lo + hi) / 2


def poisson_p_at_least(threshold: float, line: float, p_over: float) -> float:
    lam = poisson_rate(line, p_over)
    n = int(math.ceil(threshold - 1e-9))
    term, cdf = math.exp(-lam), 0.0
    for i in range(n):
        cdf += term
        term *= lam / (i + 1)
    return 1 - cdf


def normal_p_over(line: float, book_line: float, p_over: float, sd: float) -> float:
    """Game margins and totals: a book says P(X > book_line) = p_over. Assume X is normal with spread sd,
    anchor it to that, and return P(X > line)."""
    p = min(max(p_over, 1e-4), 1 - 1e-4)
    mu = book_line + sd * _N.inv_cdf(p)
    return 1 - _N.cdf((line - mu) / sd)


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
        elif stat in POISSON:
            # Kalshi '2+' vs book Over 1.5: exact; other thresholds via the book's Poisson rate
            if pt is not None and "Over" in pr and "Under" in pr and abs(threshold - (pt + 0.5)) <= 2:
                p_over = devig_two_way(pr["Over"], pr["Under"])
                if abs(pt - (threshold - 0.5)) < 1e-6:
                    probs.append(p_over)
                else:
                    probs.append(poisson_p_at_least(threshold, pt, p_over))
        elif stat in SPREAD_STATS:
            # counts like receptions are small numbers: allow 2 units away even when that's > max_dist
            near = abs(threshold - pt) / pt <= max_dist if pt else False
            if stat in COUNTS and pt:
                near = near or abs(threshold - (pt + 0.5)) <= 2
            if pt and "Over" in pr and "Under" in pr and near and stat in sigma_map:
                p_over = devig_two_way(pr["Over"], pr["Under"])
                probs.append(lognormal_p_at_least(threshold, pt, p_over, sigma_map[stat]))
    if not probs:
        return None, 0
    return sum(probs) / len(probs), len(probs)


def uncertainty(stat, threshold, lines, max_dist):
    """Haircut (in probability points) for how much we trust the fair value. Bigger for the rougher
    anytime-TD math and for yardage thresholds far from the book line. Rough heuristics, not science."""
    if stat == "player_anytime_td":
        return 0.04
    if stat in POISSON:
        return 0.03
    pts = [l["point"] for l in lines if l.get("point")]
    d = min((abs(threshold - x) / x for x in pts), default=max_dist)
    return 0.02 + 0.06 * min(1.0, d / max_dist)
