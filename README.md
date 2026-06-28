# Basketball-Modelling

Predictive models for **NBA**, **NBL** and **WNBA** basketball — match win probabilities, the full
betting market book (spreads, totals, team totals, quarters, halves, margins, double results) and
player props (points, rebounds, assists, threes, combos, double/triple-doubles) — published as a
static dashboard.

Part of the **0 Series** network of sports models.

## How it works

A standard-library Python pipeline rebuilt automatically by GitHub Actions:

1. **ingest** — pull public stats for each league (ESPN for the NBA, the nbl.com.au data API for the
   NBL, the stats.wnba.com API for the WNBA): team season stats, player season stats, and final
   scores for the rating history.
2. **features** — opponent-adjusted, sample-shrunk team offense / defense / pace profiles and
   per-player scoring/rebounding/assist rate profiles.
3. **ratings** — a results-based, margin-aware Elo per league (overall strength baseline).
4. **sim** — a clean-room possession/efficiency engine: each team's expected points come from its
   offensive rating versus the opponent's defence and the game's pace, plus home-court edge. The
   margin and total are modelled as Normals and every market is read off the resulting
   distributions. Player props come from each player's rate profile and projected minutes.
5. **evaluate** — a walk-forward backtest (log-loss / Brier / accuracy) versus the home-court and
   Elo baselines.
6. **predict / build_site** — price every upcoming fixture and publish the JSON the site reads.

The headline win probability blends the simulation with the Elo baseline; all derived markets stay
consistent with it.

## Data

- **NBA** — ESPN's public JSON API (anonymous, cloud-reachable; runs in CI).
- **NBL** — the public nbl.com.au statistics API (Genius Sports data; referer-gated, cloud-reachable).
- **WNBA** — the stats.wnba.com API (the stats.nba.com family with `LeagueID=10` and single
  calendar-year seasons). This host is Akamai-walled for cloud IPs, so the WNBA league is best run
  from a local or AU-networked context (the same place the bookmaker-odds cron runs), not GitHub
  Actions.

For research and entertainment only — not betting advice.

## Leagues

Leagues are configured in `config.yaml` under the `leagues:` list, each with its own block (data
`source`, game length, pace/scoring baselines, season length, playoff size). The model code is
shared and reads the active league's block:

- `nba`  — `source: espn`,    82-game season.
- `nbl`  — `source: rosetta`, 28-game season.
- `wnba` — `source: stats`,   44-game season (LeagueID 10, single-year seasons).

## Local run

```bash
pip install -r requirements.txt
python -m src.run_daily                 # full rebuild (all three leagues)
python -m src.run_daily --quick         # skip history derivation + backtest
python -m src.run_daily --league wnba   # rebuild just one league (repeatable; merges into the
                                        # published files, leaving the other leagues untouched)
python -m http.server -d docs 8000      # preview the site
```

The WNBA stats host is geo/IP-walled for cloud runners — run `--league wnba` from a local/AU
machine to populate real WNBA team/player/results data. SuperCoach has no WNBA competition, so
`fantasy-wnba.json` is emitted empty-but-valid (the site renders a graceful empty state); the
bookmaker `odds.json` / `futures-odds.json` WNBA sections fill in when a book offers those markets.
