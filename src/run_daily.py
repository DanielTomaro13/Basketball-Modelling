"""Orchestrator — run the full NBA + NBL + WNBA pipeline end to end.

    python -m src.run_daily                 # full rebuild (results + backtest + odds)
    python -m src.run_daily --quick         # skip results derivation + backtest (faster)
    python -m src.run_daily --league wnba   # rebuild a single league (repeatable)
    python -m src.run_daily --league nba --league nbl

Stages: ingest -> features -> ratings -> (evaluate) -> scrape -> predict ->
players -> build_site -> (odds). NBA is sourced from ESPN and NBL from nbl.com.au
(both cloud-reachable, so they run on GitHub Actions); WNBA is sourced from
stats.wnba.com, which is Akamai-walled for cloud IPs and so runs from a local/AU
networked context (like the AU odds cron).
"""
from __future__ import annotations

import sys
import time

from . import (build_site, evaluate, features, fixtures, futures, ingest, leaders,
               odds, players, predict, ratings, scrape_schedule, supercoach, util)


def _leagues_arg(argv: list[str]) -> list[str]:
    """Parse repeated ``--league X`` flags; empty means all configured leagues."""
    out = []
    for i, a in enumerate(argv):
        if a == "--league" and i + 1 < len(argv):
            out.append(argv[i + 1].lower())
        elif a.startswith("--league="):
            out.append(a.split("=", 1)[1].lower())
    return out


def run(quick: bool = False, leagues: list[str] | None = None) -> int:
    cfg = util.load_config()
    util.load_env()
    cfg["_all_leagues"] = list(cfg["leagues"])
    if leagues:
        unknown = [lg for lg in leagues if lg not in cfg["leagues"]]
        if unknown:
            util.log(f"run_daily: unknown league(s) {unknown}; known: {cfg['leagues']}")
        cfg["leagues"] = [lg for lg in cfg["leagues"] if lg in leagues] or cfg["leagues"]
        util.log(f"run_daily: restricted to leagues {cfg['leagues']}")
    t0 = time.time()

    util.log("=== 1/8 ingest ===")
    ingest.download_core(cfg)
    if not quick:
        ingest.derive_results(cfg)

    # evaluate runs BEFORE features: it writes models/calibration.json (empirical
    # sigma_margin / sigma_total / home edge from the walk-forward backtest) which
    # features overlays onto the league aggregates the whole market book prices with.
    if not quick:
        util.log("=== 2/8 evaluate (backtest + sigma calibration) ===")
        try:
            evaluate.build(cfg)
        except Exception as exc:  # noqa: BLE001
            util.log(f"run_daily: backtest skipped ({exc})")

    util.log("=== 3/8 features ===")
    features.build(cfg)
    util.log("=== 4/8 ratings ===")
    try:
        ratings.build(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: ratings skipped ({exc})")

    util.log("=== 5/8 scrape schedule ===")
    try:
        scrape_schedule.write_csv(util.abspath("data/fixtures.csv"), scrape_schedule.scrape(cfg))
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: scrape failed ({exc})")

    util.log("=== 6/8 predict ===")
    predict.build(cfg)

    util.log("=== 7/9 players + futures + supercoach ===")
    try:
        players.build(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: players skipped ({exc})")
    try:
        futures.build(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: futures skipped ({exc})")
    try:
        leaders.build(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: leaders skipped ({exc})")
    try:
        supercoach.build(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: supercoach skipped ({exc})")

    util.log("=== 8/9 build site ===")
    build_site.build(cfg)

    util.log("=== 9/9 odds (best-effort; AU-geo books) ===")
    try:
        odds.run(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: odds skipped ({exc})")
    try:
        odds.futures_odds(cfg)   # outright/championship futures (open year-round)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: futures odds skipped ({exc})")

    util.log(f"run_daily: done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    _argv = sys.argv[1:]
    raise SystemExit(run(quick="--quick" in _argv, leagues=_leagues_arg(_argv)))
