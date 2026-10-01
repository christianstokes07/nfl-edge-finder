# Prop Sheet: NFL player-prop picks for building parlays

Twice a week, GitHub Actions pulls player-prop lines from up to 10 US sportsbooks, removes each book's
cut (the "vig"), and averages them into a **hit chance** for every prop. It also matches Kalshi contracts
to those lines. Results go to a private phone-friendly page where you:

- pick **where you bet** (DraftKings, FanDuel, BetMGM, Caesars, theScore Bet, BetRivers, Hard Rock Bet, …,
  or Kalshi) and see that book's actual line and odds for each prop,
- sort by **most likely to hit** or **best value**,
- tap **+ Parlay** to build a slip, or let **Auto-build** pick 2 to 6 legs.

Everything runs in the cloud. Nothing runs on your computer.

**It does not predict games.** It treats the sportsbooks' combined prices as the true odds. A high hit
chance doesn't make a bet profitable: the price still matters, and the page shows both.

## Stats layer: "Why this pick"

Every pick now carries a one-line **"Why 58%"** explanation, a **confidence tag**, a **stats verdict**
(agree / neutral / disagree), warnings, and a **Why this pick** panel with four sections: Usage,
Efficiency, Matchup and Game context. Each section has 3 to 5 lines with real numbers, ranks and sample sizes.
Every stat name is tappable for a plain-English definition and a note on whether higher is better for that pick.

**The hit chance does not change.** It is still the sportsbook consensus. The stats only check it:

- A transparent projection per prop: **usage × opponent-adjusted efficiency × game script**.
  - Rushing yards: expected team carries × carry share × yards per carry × opponent's yards-per-carry factor.
  - Receiving yards and catches: team pass attempts × target share × yards per target (or catch rate) ×
    the opponent's factor against that position (WR / TE / RB).
  - Passing yards: team attempts × yards per attempt × the opponent's yards-per-attempt factor.
  - Anytime TD: expected team TDs (implied team total × league TDs per point), split into rushing and
    receiving by the league mix, then credited by the player's red-zone and overall carry and target shares.
    The chance of at least one TD is 1 − e^(−expected TDs).
  - Team volume: plays per game × expected pass rate. The expected pass rate is a least-squares fit of pass
    rate vs. point spread over two seasons of nflverse games, plus the team's pass rate over expected.
  - Yardage is compared at the **typical game** (median), not the average. Big games pull the average up,
    and lines sit near the typical game. The average-to-typical ratio per stat is measured from last
    season's player-games (rushing 0.86, receiving 0.84, catches 0.91, passing 1.01).
- **Verdict:** "agree" when the typical-game projection is at least 7% past the line in the pick's
  direction (0.5 for catches, 0.25 for passing TDs, 5 points of probability for anytime TD). "Disagree"
  is the same test the other way. Anything closer is "neutral". These thresholds are judgment calls
  (`src/verdict.py`, mirrored in `site/analytics.js`).
- **Confidence tag:** Medium with 3+ books (Low with fewer). Up one level if stats agree, down one if they
  disagree, and down one for a serious warning. Disagreeing picks also show a visible warning, and
  auto-build skips them when there are enough other legs.
- **Warnings:**
  - the player's own injury designation or a missed practice
  - key teammates out (QB, 15%+ target share or 30%+ carry share)
  - opposing defensive regulars out (60%+ of defensive snaps)
  - wind over 15 mph on passing and receiving picks
  - big line moves since the previous scan

**Early-season handling.** Recent games count more: each week back is worth 0.8× the next. Player and team
rates are blended with last season (`blended = (n × this season + 3 × last season) / (n + 3)`, n = games),
and the panel says "Small sample" under 4 games. Efficiency (yards per carry, per target, per attempt) is
opponent-adjusted: scaled by league average ÷ the average of the defenses faced. Defensive numbers are
adjusted the same way for the offenses faced, and their ranks use the adjusted value.

**Every number is loaded, never invented.** If something can't be computed, the page says "n/a" and
why (e.g. "Next Gen Stats only lists runners with enough carries", "not found in nflverse snap counts",
"forecast not out yet"). The footer lists every data source with ✓ or ✕ and the reason.

### Data sources (all free)

| Data | Loader (nflreadpy) | Used for |
|---|---|---|
| Play-by-play, this + last season | `load_pbp` | shares, red-zone and goal-line usage, YPC, explosive and stuff rates, aDOT, catch rate over expected (from the `cp` model), EPA, CPOE, pass rate over expected, defense allowed by position, red-zone TD%, game-script fit |
| Snap counts | `load_snap_counts` | snap share, pass-play snaps estimate |
| Next Gen Stats | `load_nextgen_stats` (receiving, passing, rushing) | separation, cushion, time to throw, rush yards over expected |
| PFR advanced stats | `load_pfr_advstats` (def, rush, pass) | pressures generated and faced, yards before contact, team coverage (yards/target, rating), missed tackles |
| Injuries | `load_injuries` | player, teammate and opposing-defense flags |
| Schedules | `load_schedules` | spread, total, implied totals, roof, rest days |
| Rosters, player stats, teams | `load_rosters_weekly`, `load_player_stats`, `load_teams` | IDs, positions, names |
| Weather | Open-Meteo forecast API (free, no key) | kickoff temperature, wind, rain chance for open-air and retractable-roof stadiums |

Checked for the 2026 season on 2026-10-01 (weeks 1–3 played): everything above is published except **participation**.
`load_participation` only covers 2016–2025, so per-play on-field data isn't available.

### What's a proxy, and what's missing

- **YPRR and targets per pass snap are estimates.** Real routes run are paywalled (PFF and similar), and
  participation data isn't out for 2026. Pass-play snaps are estimated as team dropbacks × the player's snap
  share, game by game. The page labels both "(estimate)".
- **Cornerback-vs-receiver matchups are paywalled.** The Matchup section uses team-level numbers instead:
  yards per target, catch rate and passer rating allowed to that position, and PFR coverage totals summed
  across the defense. The page says this on every receiving panel.
- **Weather:** nflverse only fills temperature and wind after a game is played, so upcoming games use the
  Open-Meteo forecast. Forecasts more than 15 days out show "n/a". Stadium coordinates are in `src/context.py`.
- **Next Gen Stats** only lists players above its volume minimums. Others show "n/a" for separation, rush yards
  over expected and time to throw. FTN charting is published but not used.
- **Line moves** need two scans, so they appear from the second scan of the week (the Sunday scan vs Thursday's).

### Schedule and cost

`.github/workflows/analytics.yml` runs Thursday ~11am ET (before the noon scan) and again Sunday ~11:45am ET
to refresh injury designations and forecasts. It uses **0 Odds API credits**. The one exception: if nflverse
hasn't posted a game's spread or total, it makes **one bulk Odds API call for all games** (spreads + totals on 3 books
= **2 credits**). Set `ANALYTICS_ODDS_FALLBACK=0` to turn that off. Downloads are cached (`.cache/nflverse`,
via `actions/cache`): last season's files are kept 30 days and this season's 6 hours. `site/analytics.json`
is about 280 KB for a full 32-team week (about 63 KB gzipped).

Run it locally:

```
pip install -r requirements-analytics.txt      # nflreadpy (needs Python 3.10+)
NFLREADPY_CACHE=filesystem python -m src.analytics
```

### Checking whether "agree" picks hit more

Each scan now writes one row to `data/picks_log.csv` for every sportsbook main-line prop: the side the market favors
(Yes for anytime TD) at the best price. Kalshi edge picks are logged as before. Every row records the stats
`analytics` verdict and the `projection`. Columns: `ts_utc, source, game, player, stat, line, side, price,
hit_chance, value, books, where, analytics, projection`. An older log with different columns is kept as
`picks_log_v1.csv`. After a few weeks, compare hit rates for `agree` vs `neutral` vs `disagree` against `hit_chance`.

## What changed in this version

- **Platform picker ("Where I bet").** Every configured sportsbook plus Kalshi, plus "Best price anywhere",
  which shows each pick at whichever book pays most. On a sportsbook you see its own line and odds
  ("Over 65.5, −115 at DraftKings"). The hit chance is computed for that exact line from all books
  combined. Kalshi works as before: price in cents, refreshed live every 30 seconds.
- **Hit chance is the headline number** on every pick, with a meter and a plain word ("Likely", "Coin flip").
  Value is a separate line in plain words ("Good value: this book pays more than it's worth").
- **Tappable pickers** (bottom sheets on phones) where every option has a one-line explanation, and a
  "How to read this" section.
- **Parlay slip** pinned to the bottom of the screen: combined hit chance, fair odds, warnings for legs from
  the same game or player, auto-build, and a box where you type your book's parlay odds to see if they beat fair.
- **New design:** mobile-first, light and dark modes (follows your phone, or tap the theme button), safe-area aware.
- **Bug fixes:**
  - **Caesars:** it was set as `caesars`, which isn't an Odds API key, so it never returned data. The key is `williamhill_us`.
  - **Kalshi season-long markets:** season leader markets (e.g. `KXLEADERNFLRUSHTDS…`, "most rushing TDs this season") were being
    matched as anytime-TD contracts and showed fake 60% edges. They're now skipped.
  - **Sunday run cost:** this README said Sunday's run used 3 markets, but the workflow never did that. It does now.
- `data.json` now carries every book's line and prices per prop (format below). Old-format files show
  "run a new scan" on the page.

## Setup (about 20 minutes, one time)

1. **Make a private GitHub repo** and upload everything in this folder (keep the folder structure,
   including `.github/workflows/scan.yml`).
2. **Odds API key:** sign up free at https://the-odds-api.com and copy your key.
3. **Add the secret:** repo > Settings > Secrets and variables > Actions > New repository secret:
   `ODDS_API_KEY` = your key. (`DISCORD_WEBHOOK_URL` is optional. Skip it if you don't use Discord.)
4. **Test the scan:** repo > Actions > "NFL edge scan" > Run workflow. When it finishes it commits
   `site/data.json` back to the repo.
5. **Put the page online:** at https://dash.cloudflare.com go to Workers & Pages > Create > Pages >
   Connect to Git, pick your repo. Build command: leave empty. Build output directory: `site`.
   Cloudflare redeploys the page every time the scan commits new data.
6. **Lock it to you:** in the Pages project, Settings > General > Access policy > Enable, then allow
   only your email. (Or Zero Trust > Access > Applications > Add a self-hosted app on your
   `yourproject.pages.dev` domain, plus `*.yourproject.pages.dev` for preview deploys.) Free for up to
   50 users.
7. **Add it to your phone:** open your `pages.dev` link, log in with your email, then Share > Add to
   Home Screen. It opens like an app.

It runs by itself Thursday around noon ET (the whole week's slate) and Sunday around 12:15pm ET
(after inactives, before 1pm kickoffs). The page shows how old the lines are.

## Odds API credits: what each run costs

The free plan is **500 credits a month**. Per The Odds API's docs, one game costs
**(markets returned) × (regions)**, and **every group of up to 10 bookmakers counts as one region**.
So 10 books cost exactly what 1 book costs, and that's why the default list is exactly 10. An 11th
book would double the cost of every run. Markets a book hasn't posted yet are free, and the `/events`
list is free.

| Run | Games | Markets | Credits |
|---|---|---|---|
| Thursday (scheduled, 110h window) | Thu + Sun + Mon, 13–16 games | 4: rushing, receiving, passing yards, anytime TD | **52–64** |
| Sunday (scheduled, 36h window) | Sun + Mon, 12–15 games | 3: rushing, receiving, anytime TD | **36–45** |
| Manual, one night game (`window_hours` = 6) | 1 | 4 | **4** |

On Sunday, passing yards are carried over from Thursday's scan for games that haven't started (QB lines
barely move on inactives), and the page labels them with their age. That's about **90–110 credits a week, or
390–470 a month**. Weeks without byes (early and late season) are the tight ones, so leave room before
running extra manual scans. The script stops itself if credits drop under `CREDIT_RESERVE` (15).

Check before you spend: `python -m src.run --estimate` uses only the free `/events` call and prints what a
scan would cost right now.

**Alternate lines** (the way to get high-hit-chance sportsbook legs, e.g. "Over 39.5 rushing yards at −300")
are supported. Add `player_rush_yds_alternate,player_reception_yds_alternate` to `ODDS_MARKETS`. Each one adds
about 1 credit per game per run, so both on both runs is about +120 credits a month, which doesn't fit with
two runs a week. If you want them, drop to one scan a week (Sunday) with 5–6 markets. You can also add them
to a single manual run with the `markets` box on the Run workflow screen.

## Platforms

- **Sportsbooks** (Odds API keys): `draftkings`, `fanduel`, `betmgm`, `williamhill_us` (Caesars),
  `espnbet` (theScore Bet), `fanatics`, `betrivers`, `hardrockbet`, `betparx`, `ballybet`. Change them with
  the `BOOKMAKERS` env var, and keep it at 10 or fewer.
  **Caesars and Fanatics only return data on paid Odds API plans.** They're still listed (they cost nothing
  extra while there are 10 or fewer books). On the free plan the page shows "No lines: The Odds API only
  sends this book on paid plans" for them.
- **Kalshi:** read from Kalshi's public API (free, no key). It doesn't use Odds API credits.
- **Polymarket: not included.** I checked its public API (gamma-api.polymarket.com) on 2026-10-01.
  Its NFL markets are season-long (MVP, stat leaders, season rushing totals) and team-level game markets
  (spread, totals, team touchdowns). There are no single-game player props to price, so there's nothing to compare.

## Reading the page

- **Hit chance (big %):** how often the pick should win, from all books' prices with their cut removed.
- **Line and odds:** "Over 65.5" wins at 66 or more. −115 means bet $115 to win $100, +140 means bet
  $100 to win $140. On Kalshi a 43¢ YES pays $1 if it happens.
- **Value line:** "Good value" when the price pays more than the hit chance is worth, even after a safety
  margin (bigger for rougher math like anytime TDs and alternate lines far from the main line).
  "Fair price" means about what it's worth after the usual cut. "Poor value" means it pays noticeably less.
- **"Big gap: check injury news first"** shows when a price is more than 12 points away from the
  consensus. It usually means news the scan doesn't know about.
- **Why most sportsbook picks sit near 50%:** books set main lines so both sides are about even. Higher
  hit chances come from alternate lines or Kalshi's lower thresholds, which pay less.
- Picks priced shorter than −1000 (about 91¢ on Kalshi) are hidden, because they barely change a parlay's payout.

## Parlay slip

- **Combined hit chance** = the legs' hit chances multiplied together, then a conservative haircut for
  linked legs: **−10% per pair on the same player, −4% per pair from the same game**. Legs in one game
  move together. That can help or hurt, so the page assumes it hurts and says so.
- **Fair odds** = what the parlay is really worth. If your book's parlay odds are better, it's good value.
  Type your book's odds (+450, −120, or decimal 5.5) and the slip tells you whether they beat fair and by how much.
- **"If your book just multiplies the legs"** shows the payout from multiplying each leg's odds (sportsbook legs
  only). Same-game parlays usually pay less than this.
- **Auto-build** takes the list you're looking at (platform, prop and game filters), then picks the
  highest-hit-chance legs. It uses at most one leg per player and avoids a second leg from the same game
  unless there aren't enough games.
- The slip is saved on your phone (browser storage) and re-priced when new data or live Kalshi prices arrive.

## Live Kalshi prices

While you're on the Kalshi view, or have Kalshi legs in your slip, the page re-pulls Kalshi prices every
30 seconds through `functions/api/prices.js`. That's a free Cloudflare Pages Function behind the same login,
and it splits big ticker lists into batches of 100. Sportsbook numbers come from the last scan, since
refreshing them costs credits. Keep the `functions/` folder at the repo root so Cloudflare picks it up.

## Preview without spending credits

```
python -m src.demo                 # writes site/demo-data.json (+ demo-analytics.json), git-ignored
python3 -m http.server -d site 8000
# open http://localhost:8000/?demo
```

If `site/analytics.json` exists, the demo uses that week's real matchups and players, so the stats panels show
real numbers. The odds are made up around the projections. Without it, the demo falls back to a fixed set of
players. Live Kalshi refresh needs Cloudflare, so locally the page falls back to scan prices.

## Tests

```
pip install -r requirements.txt -r requirements-analytics.txt pytest
python -m pytest
```

Covered:
- probability math, per-book prop data, carry-forward and line moves
- Kalshi parsing, including the season-market fix
- credit math, and the pick log with analytics verdicts
- metric calculations on small hand-built play-by-play: shares, red-zone usage, catch rate over expected,
  recency weights, shrinkage, opponent adjustment, red-zone TD%, the game-script fit, typical-game factors, TD split
- projections, and game context (implied totals, Eastern-time kickoffs, roofs)

The page logic lives in `site/parlay.js` and `site/analytics.js`, tested by `tests/parlay.test.js` and
`tests/analytics.test.js` against a mock `tests/fixtures/analytics_mock.json`. Pytest runs those through Node
(skipped without Node). Python and JS share `tests/fixtures/verdict_cases.json`, so the two verdict
implementations can't drift apart. The metric tests skip when polars isn't installed (nflreadpy needs Python 3.10+).

## data.json format (version 2)

```
games:  {id: {a: away team, h: home team, t: kickoff ISO time}}
books:  [{k: odds-api key, name, n: props in this scan, paid: true if paid-plan only}]
props:  [{id, player, g: game id, stat, m: market key, pt: line, p: fair chance Over/Yes hits at pt,
          n: books behind p, unc: safety margin, b: {book: [over_or_yes_odds, under_or_no_odds]}}]
kalshi: [{ticker, player, g, stat, threshold, fair, books, unc, bid, ask}]   (re-priced live by the page)
markets_updated: {market: ISO time}   (carried-over markets keep their older time)
```

It's written as compact JSON: about 35 KB for 4 games and roughly 150–250 KB for a full Sunday slate
(much less over the wire, since Cloudflare compresses it).

## First run: check the Kalshi matching

Kalshi's contract titles aren't a fixed format. If a scan says `matched to a book line 0`:

```
export ODDS_API_KEY=your_key
python -m src.run --dump-kalshi     # prints raw Kalshi NFL market titles and prices (free)
python -m src.run --no-send         # full scan, prints only (costs credits like a normal run)
```

Then adjust the patterns in `src/kalshi.py`, or add name differences to `NAME_ALIASES` in `src/config.py`.

## Tuning (all env vars, see `src/config.py`)

- `BOOKMAKERS`: up to 10 Odds API bookmaker keys (more doubles the cost).
- `ODDS_MARKETS`: markets per run. Each one is about 1 credit per game.
- `MIN_BOOKS` (2): books that must agree before a Kalshi contract is scored. `PROP_MIN_BOOKS` (1) does
  the same for sportsbook picks, and the page shows how many books are behind each number.
- `MAX_SPREAD_CENTS` (8): skips thin Kalshi contracts.
- `SIGMA_*`: how spread out player yardage is. Rough guesses. They matter for Kalshi thresholds and
  alternate lines far from the main line, and barely at all near the main line.
- `KALSHI_FEE_RATE` (0.07): verify against Kalshi's current fee schedule.
- `MIN_EDGE` / `MIN_EDGE_TD`: bar for the Kalshi picks sent to Discord and logged.

## Tracking whether it works

`data/picks_log.csv` gets a row per sportsbook main-line prop and per Kalshi edge pick on every scan, each
with the stats verdict (see "Checking whether agree picks hit more" above). After a few weeks, compare results
with the hit chances. If picks don't beat their prices, don't trust the value labels. If "agree" doesn't hit more
than "disagree", don't trust the stats verdict.

## Not included

- Polymarket (no single-game player props, see above).
- Combined rushing + receiving and first/last TD scorer markets.
- Injury and news judgment. Always check inactives before betting.
- Closing-line tracking.

Sports betting and prediction markets are risky, and most bettors lose. Only bet what you can afford to lose.
