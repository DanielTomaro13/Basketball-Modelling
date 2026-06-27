# Basketball-Modelling

Predictive models for **NBA** and **NBL** basketball — match win probabilities, the full betting
market book (spreads, totals, team totals, quarters, halves, margins, double results) and player
props (points, rebounds, assists, threes, combos, double/triple-doubles) — published as a static
dashboard.

Part of the **0 Series** network of sports models.

## How it works

A standard-library Python pipeline rebuilt automatically by GitHub Actions:

1. **ingest** — pull public stats for each league (ESPN for the NBA, the nbl.com.au data API for the
   NBL): team season stats, player season stats, and final scores for the rating history.
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

- **NBA** — ESPN's public JSON API.
- **NBL** — the public nbl.com.au statistics API (Genius Sports data).

For research and entertainment only — not betting advice.

## Local run

```bash
pip install -r requirements.txt
python -m src.run_daily          # full rebuild (both leagues)
python -m src.run_daily --quick  # skip history derivation + backtest
python -m http.server -d docs 8000   # preview the site
```
