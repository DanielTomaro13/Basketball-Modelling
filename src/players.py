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
            r1 = lambda k: round(pg[k], 1)
            cards[league][pid] = {
                "id": pid, "name": p["name"], "team": p.get("teamAbbr", ""),
                "gp": p["gp"], "min": round(p["min"], 1),
                "pts": r1("pts"), "reb": r1("reb"), "ast": r1("ast"), "fg3m": r1("fg3m"),
                "stl": r1("stl"), "blk": r1("blk"), "tov": r1("tov"),
                "fgm": r1("fgm"), "ftm": r1("ftm"),
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
