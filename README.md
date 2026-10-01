# NFL edge finder (Kalshi vs. sportsbook lines)

Twice a week, GitHub Actions pulls sportsbook player-prop lines, strips the vig, converts them into
a fair probability for each Kalshi "X or more" contract, and publishes the contracts priced below fair
value to a private web page you can open on your phone (Discord alerts are optional). Everything runs in the cloud, nothing on your computer.

**It does not predict games.** It treats the sportsbook consensus as fair value and flags Kalshi
contracts that lag it. Edges are small and prices move, so check the live price before buying.

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
   50 users; Cloudflare may ask for a card on signup but the free plan costs $0.
7. **Add it to your phone:** open your `pages.dev` link, log in with your email, then Share > Add to
   Home Screen. It opens like an app.

After that it runs by itself Thursday around noon ET (whole week's slate) and Sunday around 12:15pm ET
(after inactives, before 1pm kickoffs). The page always shows the latest scan and how old it is.
You can also tap Run workflow from the GitHub mobile app for a fresh scan. For a night game right after
inactives drop, set `window_hours` to `6` so it only scans that game and uses almost no credits.

## Live prices

While the page is open it re-pulls Kalshi prices every 30 seconds through `functions/api/prices.js`
(a free Cloudflare Pages Function, behind the same login) and recomputes the edges. The sportsbook
numbers (fair values) come from the last scan, because refreshing those costs Odds API credits, and
they move slowly. The page shows how old they are. If a player gets ruled out, Kalshi's price drops
but the stored fair value doesn't, which looks like a huge edge. The page flags gaps over 12 points
with "check injury news first". Treat those as a warning, not a buy signal.

Cloudflare picks up the `functions/` folder automatically if it's at the repo root, so keep it there.

## Free-tier limits

The Odds API free tier is 500 credits/month, and a run costs about (games x markets). Thursday's run
scans the whole week's games with 4 markets (rushing, receiving, passing yards, anytime TD), about 64
credits. Sunday's run scans only that day's games with 3 markets, about 42. That's roughly 450 a month,
so there isn't much room to add markets or runs. Add `player_receptions` or `player_pass_tds` through
`ODDS_MARKETS` only if you're willing to drop a run. The script stops itself under `CREDIT_RESERVE`.

## Reading the page

- **Prop type / Fair value from:** filter by prop, and choose whether fair value comes from all books
  combined or one sportsbook's line. Your choices are remembered on your phone.
- **Big number:** edge after a safety margin (bigger for rougher math like anytime TDs, and for
  yardage thresholds far from the book line). Strong is 6+ points, Good is 3+, Thin is under 3.
- **Hit chance:** fair probability that the side you'd buy wins.
- **Sort:** best value (default), most likely to hit, or biggest raw edge.

## First run: check the matching

I wrote the Kalshi side from their public API docs but couldn't test it against live Kalshi markets,
and Kalshi's contract titles aren't a fixed format. If a scan says `matched to a book line 0`:

```
export ODDS_API_KEY=your_key
python -m src.run --dump-kalshi     # prints raw Kalshi NFL market titles and prices
python -m src.run --no-send         # full scan, prints only
```

Then adjust the patterns in `src/kalshi.py`, or add name differences to `NAME_ALIASES` in
`src/config.py` (for example Kalshi says "Patrick", books say "Pat"). Paste me the dump output and I'll fix it.

## Tuning (all env vars, see `src/config.py`)

- `MIN_EDGE` (default 0.05): minimum edge after fees. Lower it and you'll see more noise.
- `MIN_BOOKS` (2): books that must agree before a contract is scored.
- `MAX_SPREAD_CENTS` (8): skips thin contracts.
- `ODDS_MARKETS`: add `player_pass_tds` or `player_receptions` if you have credits to spare.
- `SIGMA_*`: how spread-out player yardage is. These are rough guesses. Thresholds near the book
  line (the default only scores within 25%) barely depend on them.
- `KALSHI_FEE_RATE` (0.07): verify against Kalshi's current fee schedule.

## Tracking whether it works

Every flagged pick is appended to `data/picks_log.csv` and committed back to the repo. After a few
weeks, compare results to the fair probabilities. If the picks don't beat the price they were bought
at, don't trust the edge.

## Not included (v1)

- Polymarket (it mostly has game lines, not player props; can be added).
- Combined rushing + receiving contracts and first/last TD scorer markets.
- Injury/news judgment. Always check inactives before buying.
- Closing-line tracking.

Prediction markets are risky and most bettors lose. Only trade what you can afford to lose.
