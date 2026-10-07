"""Polymarket NFL markets (free public API, no key): game lines and per-game player props.

Each Polymarket market is translated into the same shape as a Kalshi contract (a YES side with a bid/ask in
cents and a title like "Name: 46+ receiving yards"), so run.evaluate() prices it against the sportsbook
consensus exactly like Kalshi. Rows are tagged src="poly" with the Polymarket market id for live prices.

Formats (checked 2026-10-06):
  game event "Buccaneers vs. Cowboys" (away vs. home):  "Buccaneers vs. Cowboys" (moneyline, outcomes = teams),
     "Spread: Cowboys (-1.5)" (outcomes [Cowboys, Buccaneers]), "Buccaneers vs. Cowboys: O/U 31.5"
  "<game> - Player Props": "Name: Receiving Yards O/U 45.5" (Over/Under), "Name: Anytime Touchdown" (Yes/No)
Prices: bestBid / bestAsk are for the FIRST outcome (Over, Yes, or the first team)."""
import json
import re

import requests

from . import teams as T

BASE = "https://gamma-api.polymarket.com"
STATS = {"receiving yards": "receiving yards", "receptions": "receptions", "rushing yards": "rushing yards",
         "passing yards": "passing yards", "passing touchdowns": "passing touchdowns",
         "passing attempts": "passing attempts", "passing completions": "passing completions",
         "rushing attempts": "rushing attempts", "interceptions": "passing interceptions",
         "rushing + receiving yards": "rushing and receiving yards"}
OU = re.compile(r"^(.+?):\s*(.+?)\s+O/U\s+(\d+(?:\.\d+)?)$", re.I)
TD = re.compile(r"^(.+?):\s*Anytime Touchdown$", re.I)
SPREAD = re.compile(r"^Spread:\s*(.+?)\s*\(-(\d+(?:\.\d+)?)\)$", re.I)
TOTAL = re.compile(r":\s*O/U\s+(\d+(?:\.\d+)?)$", re.I)
NICK = {full.rsplit(" ", 1)[1].lower(): full for full in T.TEAMS}


def team(nick):
    return NICK.get((nick or "").strip().lower())


def fetch_events(max_pages=10, session=None):
    get = (session or requests).get
    out = []
    for i in range(max_pages):
        try:
            r = get(f"{BASE}/events", params={"tag_slug": "nfl", "closed": "false", "limit": 100, "offset": 100 * i}, timeout=30)
            r.raise_for_status()
            page = r.json()
        except Exception as e:  # noqa: BLE001
            print(f"[poly] events page {i}: {e}")
            break
        out += page
        if len(page) < 100:
            break
    return out


def _cents(x):
    try:
        return round(float(x) * 100, 1)
    except (TypeError, ValueError):
        return None


def _outcomes(m):
    o = m.get("outcomes")
    return json.loads(o) if isinstance(o, str) else (o or [])


def to_contracts(events):
    """Polymarket events -> Kalshi-shaped dicts (title, ticker, _sub_title, yes_bid, yes_ask, pm, pf)."""
    out = []
    for e in events:
        title = e.get("title", "")
        base = title.split(" - ")[0]
        if " vs. " not in base or ":" in base or "Season" in title:
            continue
        a_nick, h_nick = base.split(" vs. ", 1)
        away, home = team(a_nick), team(h_nick)
        if not away or not home:
            continue
        pair = f"{T.abbr(away)} vs {T.abbr(home)} (poly)"
        props = title.endswith("- Player Props")
        if " - " in title and not props:
            continue  # first-TD scorer and other specials
        for m in e.get("markets", []):
            if not m.get("active") or m.get("closed"):
                continue
            q = (m.get("question") or "").strip()
            bid, ask = _cents(m.get("bestBid")), _cents(m.get("bestAsk"))
            if bid is None and ask is None:
                continue
            row = {"_sub_title": pair, "_event_title": title, "pm": str(m.get("id")), "pf": 0, "yes_bid": bid or 0, "yes_ask": ask or 0}
            outs = _outcomes(m)
            if props:
                mo, mt = OU.match(q), TD.match(q)
                if mt and outs[:1] == ["Yes"]:
                    out.append({**row, "ticker": f"PM-{m['id']}", "title": f"Will {mt.group(1).strip()} score a touchdown?"})
                elif mo and outs[:1] == ["Over"]:
                    stat = STATS.get(mo.group(2).strip().lower())
                    line = float(mo.group(3))
                    if stat and line % 1:  # .5 lines only ("Over 45.5" = "46+")
                        out.append({**row, "ticker": f"PM-{m['id']}", "title": f"{mo.group(1).strip()}: {int(line) + 1}+ {stat}"})
                continue
            if q == base and len(outs) == 2:  # moneyline: price is for outs[0]
                t0, t1 = team(outs[0]), team(outs[1])
                if t0 and t1:
                    out.append({**row, "ticker": f"KXNFLGAME-PM{m['id']}-{T.abbr(t0)}", "title": f"{t0} wins"})
                    out.append({**row, "pf": 1, "ticker": f"KXNFLGAME-PM{m['id']}x-{T.abbr(t1)}", "title": f"{t1} wins",
                                "yes_bid": round(100 - (ask or 100), 1), "yes_ask": round(100 - (bid or 0), 1)})
                continue
            ms = SPREAD.match(q)
            if ms and team(ms.group(1)) and team(outs[0] if outs else ""):
                fav = team(ms.group(1))
                out.append({**row, "ticker": f"KXNFLSPREAD-PM{m['id']}",
                            "title": f"{T.abbr(fav)} {fav.rsplit(' ', 1)[1]} wins by over {ms.group(2)} points?"})
                continue
            mt = TOTAL.search(q)
            if mt and q.startswith(base + ":") and "1H" not in q and "1Q" not in q and outs[:1] == ["Over"]:
                out.append({**row, "ticker": f"KXNFLTOTAL-PM{m['id']}", "title": f"Full Game: over {mt.group(1)} points scored?"})
    return out


def fetch_contracts():
    ev = fetch_events()
    seen, c = set(), []
    for x in to_contracts(ev):
        if x["ticker"] not in seen:
            seen.add(x["ticker"]); c.append(x)
    print(f"[poly] {len(ev)} NFL events, {len(c)} game-line and player-prop markets")
    return c
