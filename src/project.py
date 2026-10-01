"""Transparent stats projections: usage x opponent-adjusted efficiency x game script.

The page's hit chance stays the sportsbook consensus. These projections only feed the
"Analytics agree / neutral / disagree" check and the "Why this pick" panel. Every input is returned
next to the result so the page can show how the number was built."""
import math


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def team_volume(team, spread, script):
    """Expected plays, dropbacks, carries and pass attempts for a team in this game.

    team: team profile (off_proj rates); spread: this team's point spread (negative = favored);
    script: {'a', 'b'} from metrics.script_model. Expected pass rate = league fit for this spread
    + this team's pass rate over expected (PROE)."""
    o = team["off_proj"]
    plays = o.get("plays_pg")
    if plays is None:
        return None
    if script.get("a") is not None and spread is not None:
        base = script["a"] + script["b"] * spread
        pr = clamp(base + (o.get("proe") or 0.0), 0.35, 0.8)
    else:
        base, pr = None, o.get("pass_rate")
    if pr is None:
        return None
    dropbacks = plays * pr
    carries = plays * (1 - pr) + dropbacks * (o.get("scramble_rate") or 0.0)
    attempts = dropbacks * (o.get("att_per_db") or 0.9)
    return {"plays": plays, "pass_rate": pr, "script_pass_rate": base, "dropbacks": dropbacks,
            "carries": carries, "attempts": attempts}


def factor(opp_value, league_value):
    return opp_value / league_value if opp_value and league_value else 1.0


def project_player(stat, player, vol, opp_def, opp_pos, league, league_pos, pos, med, td_inputs=None):
    """Returns {'mean', 'med' (typical game), 'in': inputs} or {'p', 'in'} for anytime TD, or None.

    player: metrics.player_profiles entry; vol: team_volume(); opp_def: opponent 'def_proj';
    opp_pos: opponent position_allowed()[pos]; med: median factor for this stat."""
    r = player["proj"]
    if vol is None:
        return None
    mf = (med or {}).get("factor") or 1.0
    if stat == "player_rush_yds":
        share, ypc = r.get("carry_share"), r.get("ypc")
        if not share or ypc is None:
            return None
        carries = share * vol["carries"]
        f = factor(opp_def.get("ypc"), league.get("ypc"))
        mean = carries * ypc * f
        return {"mean": mean, "med": mean * mf, "in": {"carries": carries, "share": share, "ypc": ypc,
                "opp": f, "team_carries": vol["carries"], "mf": mf}}
    if stat in ("player_reception_yds", "player_receptions"):
        share = r.get("target_share")
        if not share:
            return None
        targets = share * vol["attempts"]
        if stat == "player_reception_yds":
            ypt = r.get("ypt")
            if ypt is None:
                return None
            f = factor((opp_pos or {}).get("ypt_proj"), (league_pos or {}).get("ypt"))
            mean = targets * ypt * f
            return {"mean": mean, "med": mean * mf, "in": {"targets": targets, "share": share, "ypt": ypt,
                    "opp": f, "team_att": vol["attempts"], "mf": mf}}
        cr = r.get("catch_rate")
        if cr is None:
            return None
        f = factor((opp_pos or {}).get("comp_proj"), (league_pos or {}).get("comp"))
        mean = targets * min(cr * f, 0.95)
        return {"mean": mean, "med": mean * mf, "in": {"targets": targets, "share": share, "catch": cr,
                "opp": f, "team_att": vol["attempts"], "mf": mf}}
    if stat in ("player_pass_yds", "player_pass_tds"):
        share = r.get("db_share")
        if not share:
            return None
        att = share * vol["attempts"]
        if stat == "player_pass_yds":
            ypa = r.get("ypa")
            if ypa is None:
                return None
            f = factor(opp_def.get("ypa"), league.get("ypa"))
            mean = att * ypa * f
            return {"mean": mean, "med": mean * mf, "in": {"attempts": att, "share": share, "ypa": ypa,
                    "opp": f, "pass_rate": vol["pass_rate"], "mf": mf}}
        rate = r.get("pass_td_rate")
        if rate is None:
            return None
        f = factor(opp_def.get("pass_td_rate"), league.get("pass_td_rate"))
        mean = att * rate * f
        return {"mean": mean, "med": mean, "in": {"attempts": att, "td_rate": rate, "opp": f}}
    if stat == "player_anytime_td":
        # Expected team TDs (implied total x league TDs per point), split into rushing and receiving TDs
        # by the league mix, then credited by the player's share of red-zone and other carries/targets.
        ti = td_inputs or {}
        team_tds, split = ti.get("team_tds"), ti.get("split") or {}
        if team_tds is None or split.get("rush_frac") is None:
            return None
        def share(rz_share, all_share, rz_frac):
            return (rz_frac or 0) * (rz_share or 0) + (1 - (rz_frac or 0)) * (all_share or 0)
        rush_share = share(r.get("rz_carry_share"), r.get("carry_share"), split.get("rush_rz_frac"))
        rec_share = 0.0 if pos == "QB" else share(r.get("rz_target_share"), r.get("target_share"), split.get("rec_rz_frac"))
        lam = team_tds * (split["rush_frac"] * rush_share + (1 - split["rush_frac"]) * rec_share)
        return {"p": 1 - math.exp(-lam), "in": {"team_tds": team_tds, "rush_share": rush_share, "rec_share": rec_share,
                "rush_frac": split["rush_frac"], "implied": ti.get("implied"), "lam": lam}}
    return None
