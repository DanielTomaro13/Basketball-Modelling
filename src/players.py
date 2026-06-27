"""Players stage — per-player season cards + a lightweight search index for the site."""
from __future__ import annotations

import os
import sys

from . import util


def build(cfg: dict) -> tuple[dict, list[dict]]:
    profiles = util.read_json(util.abspath(os.path.join(cfg["paths"]["models_dir"], "profiles.json")))
    cards: dict = {}
    index: list[dict] = []
    for league in cfg["leagues"]:
        lp = profiles.get(league)
        if not lp:
            continue
        cards[league] = {}
        for pid, p in lp["players"].items():
            pg = p["pg"]
            cards[league][pid] = {
                "id": pid, "name": p["name"], "team": p.get("teamAbbr", ""),
                "gp": p["gp"], "min": p["min"],
                "pts": pg["pts"], "reb": pg["reb"], "ast": pg["ast"], "fg3m": pg["fg3m"],
                "stl": pg["stl"], "blk": pg["blk"], "tov": pg["tov"],
                "fgm": pg["fgm"], "ftm": pg["ftm"],
                "dd_rate": p.get("dd_rate", 0), "td_rate": p.get("td_rate", 0),
            }
            index.append({"id": pid, "name": p["name"], "team": p.get("teamAbbr", ""), "league": league})
    dd = cfg["paths"]["docs_data_dir"]
    util.write_json(util.abspath(os.path.join(dd, "players.json")), cards)
    util.write_json(util.abspath(os.path.join(dd, "players-index.json")), index)
    util.log(f"players: {sum(len(c) for c in cards.values())} cards across {len(cards)} leagues")
    return cards, index


def main(argv: list[str]) -> int:
    build(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
