"""Does the stats projection agree with a pick? Pure Python (the scan job uses it for the pick log).
site/analytics.js has the same rules for the page; tests/test_verdict.py and tests/analytics.test.js
check both against the same cases."""

# How far the projection must sit from the line before we call it a lean. Below this: neutral.
YARDS_REL = 0.07        # 7% of the line, e.g. 70.1+ vs a 65.5 line
RECEPTIONS_ABS = 0.5    # half a catch
PASS_TDS_ABS = 0.25
TD_PROB_ABS = 0.05      # 5 percentage points vs the market's anytime-TD chance

YARDS = {"player_rush_yds", "player_reception_yds", "player_pass_yds"}
OVER_SIDES = {"Over", "Yes", "YES"}


def lean(stat, line, proj, market_p=None):
    """'over' / 'under' / 'neutral' / None (no projection). For anytime TD, 'over' means score."""
    if not proj:
        return None
    if stat == "player_anytime_td":
        if proj.get("p") is None or market_p is None:
            return None
        d = proj["p"] - market_p
        return "neutral" if abs(d) < TD_PROB_ABS else ("over" if d > 0 else "under")
    med = proj.get("med")
    if med is None or line is None:
        return None
    d = med - line
    if stat in YARDS:
        big = abs(d) >= YARDS_REL * max(line, 1)
    elif stat == "player_receptions":
        big = abs(d) >= RECEPTIONS_ABS
    else:
        big = abs(d) >= PASS_TDS_ABS
    return "neutral" if not big else ("over" if d > 0 else "under")


def verdict(stat, side, line, proj, market_p=None):
    """'agree' / 'neutral' / 'disagree' / 'n/a' for one side of a prop.

    line: the Over/Under point (a Kalshi 'X+' contract is line X - 0.5). market_p: market chance the
    Over/Yes side hits (needed for anytime TD)."""
    l = lean(stat, line, proj, market_p)
    if l is None:
        return "n/a"
    if l == "neutral":
        return "neutral"
    return "agree" if (l == "over") == (side in OVER_SIDES) else "disagree"
