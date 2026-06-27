"""Leaders stage — model-projected season statistical leaders (player futures).

From each player's rate profile, project a per-game number and a full-season total
(rate x games), then rank the field per category — the model's "race for the
scoring title / rebounding crown / …". Output: ``docs/data/leaders-{league}.json``.
"""
from __future__ import annotations

import os
import sys

from . import util

CATS = [
    ("pts", "Points", "pts"), ("reb", "Rebounds", "reb"), ("ast", "Assists", "ast"),
    ("fg3m", "Threes made", "fg3m"), ("stl", "Steals", "stl"), ("blk", "Blocks", "blk"),
    ("pra", "Pts+Reb+Ast", None), ("fgm", "Field goals", "fgm"), ("ftm", "Free throws", "ftm"),
]
TOP_N = 25


def build_league(cfg: dict, league: str, profiles: dict) -> dict:
    players = profiles.get(league, {}).get("players", {})
    games = int(cfg[league].get("games_per_season", 82))
    min_games = cfg["features"]["min_player_games"]
    pool = [p for p in players.values() if p.get("gp", 0) >= min_games]
    out = {}
    for key, label, pgkey in CATS:
        rows = []
        for p in pool:
            pg = p["pg"]
            rate = (pg["pts"] + pg["reb"] + pg["ast"]) if key == "pra" else pg.get(pgkey, 0.0)
            if rate <= 0:
                continue
            rows.append({"name": p["name"], "team": p.get("teamAbbr", ""), "id": p["id"],
                         "per_game": round(rate, 1), "proj_total": round(rate * games)})
        rows.sort(key=lambda r: -r["per_game"])
        out[key] = {"label": label, "rows": rows[:TOP_N]}
    return {"games": games, "cats": out}


def build(cfg: dict) -> dict:
    models = cfg["paths"]["models_dir"]
    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "profiles.json"))) else {}
    out = {}
    for league in cfg["leagues"]:
        if league not in profiles:
            continue
        out[league] = build_league(cfg, league, profiles)
        top = out[league]["cats"]["pts"]["rows"][:1]
        util.log(f"leaders[{league}]: scoring leader {top[0]['name'] if top else '—'} "
                 f"{top[0]['per_game'] if top else 0}")
    util.write_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "leaders.json")),
                    {"generated": _now(), "leagues": out})
    return out


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str]) -> int:
    build(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
