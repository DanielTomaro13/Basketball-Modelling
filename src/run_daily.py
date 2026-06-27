"""Orchestrator — run the full NBA + NBL pipeline end to end.

    python -m src.run_daily          # full rebuild (results + backtest + odds)
    python -m src.run_daily --quick  # skip results derivation + backtest (faster)

Stages: ingest -> features -> ratings -> (evaluate) -> scrape -> predict ->
players -> build_site -> (odds). Everything is sourced from cloud-reachable public
APIs (ESPN for the NBA, nbl.com.au for the NBL), so the whole thing runs on
GitHub Actions.
"""
from __future__ import annotations

import sys
import time

from . import (build_site, evaluate, features, fixtures, futures, ingest, leaders,
               odds, players, predict, ratings, scrape_schedule, supercoach, util)


def run(quick: bool = False) -> int:
    cfg = util.load_config()
    util.load_env()
    t0 = time.time()

    util.log("=== 1/8 ingest ===")
    ingest.download_core(cfg)
    if not quick:
        ingest.derive_results(cfg)

    util.log("=== 2/8 features ===")
    features.build(cfg)
    util.log("=== 3/8 ratings ===")
    try:
        ratings.build(cfg)
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: ratings skipped ({exc})")

    if not quick:
        util.log("=== 4/8 evaluate (backtest) ===")
        try:
            evaluate.build(cfg)
        except Exception as exc:  # noqa: BLE001
            util.log(f"run_daily: backtest skipped ({exc})")

    util.log("=== 5/8 scrape schedule ===")
    try:
        scrape_schedule.write_csv(util.abspath("data/fixtures.csv"), scrape_schedule.scrape(cfg))
    except Exception as exc:  # noqa: BLE001
        util.log(f"run_daily: scrape failed ({exc})")

    util.log("=== 6/8 predict ===")
    predict.main([])

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
    raise SystemExit(run(quick="--quick" in sys.argv[1:]))
