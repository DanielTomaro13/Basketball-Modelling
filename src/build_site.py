"""Build-site stage — publish the JSON the static docs/ site reads.

The HTML/CSS/JS under docs/ are committed static files. This stage copies the
ratings leaderboard, slims the team profiles, and writes a per-league meta.json
(counts + backtest summary) used across the pages.
"""
from __future__ import annotations

import datetime
import os
import sys

from . import util


def _slim_profiles(profiles: dict) -> dict:
    out = {}
    for league, lp in profiles.items():
        out[league] = {"league": lp["league"],
                       "teams": {tid: {k: t.get(k) for k in
                                       ("id", "abbr", "name", "off", "def", "pace", "pace_factor",
                                        "pf", "pa", "gp")}
                                 for tid, t in lp["teams"].items()}}
    return out


def build(cfg: dict) -> dict:
    models = cfg["paths"]["models_dir"]
    dd = cfg["paths"]["docs_data_dir"]
    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "profiles.json"))) else {}
    ratings = util.read_json(util.abspath(os.path.join(models, "ratings.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "ratings.json"))) else {}
    backtests = util.read_json(util.abspath(os.path.join(cfg["paths"]["reports_dir"], "backtest.json"))) \
        if os.path.exists(util.abspath(os.path.join(cfg["paths"]["reports_dir"], "backtest.json"))) else []
    bt_by_league = {b["league"]: b for b in backtests}

    util.write_json(util.abspath(os.path.join(dd, "ratings.json")), ratings)
    util.write_json(util.abspath(os.path.join(dd, "profiles.json")), _slim_profiles(profiles))

    # Build meta from the merged profiles (which already preserves any league that
    # wasn't rebuilt this run); skip a configured league with no profile at all so
    # its previously published meta survives the merge below.
    leagues_meta = {}
    for league in (cfg.get("_all_leagues") or cfg["leagues"]):
        lp = profiles.get(league, {})
        if not lp:
            continue
        leagues_meta[league] = {
            "season": cfg[league]["season"],
            "n_teams": len(lp.get("teams", {})),
            "n_players": len(lp.get("players", {})),
            "ppg": lp.get("league", {}).get("ppg"),
            "pace": lp.get("league", {}).get("pace"),
            "backtest": bt_by_league.get(league, {}),
        }
    meta = {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "leagues": leagues_meta}
    meta_path = util.abspath(os.path.join(dd, "meta.json"))
    if util.should_merge(cfg, leagues_meta):
        meta = util.merge_existing(meta_path, meta, list(leagues_meta.keys()), container_key="leagues")
    util.write_json(meta_path, meta)
    util.log(f"build_site: refreshed docs/data ({meta['generated']})")
    return meta


def main(argv: list[str]) -> int:
    build(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
