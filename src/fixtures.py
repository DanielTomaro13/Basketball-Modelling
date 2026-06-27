"""Fixtures stage — load upcoming games and resolve each side to a team profile."""
from __future__ import annotations

import csv
import os
import sys

from . import util


def load_fixtures(cfg: dict, profiles: dict) -> list[dict]:
    path = util.abspath("data/fixtures.csv")
    if not os.path.exists(path):
        path = util.abspath(cfg["fixtures"]["manual_file"])
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        league = r.get("league")
        lp = profiles.get(league)
        if not lp:
            continue
        teams = lp["teams"]
        home = teams.get(r["homeId"]) or _by_abbr(teams, r.get("homeAbbr"))
        away = teams.get(r["awayId"]) or _by_abbr(teams, r.get("awayAbbr"))
        if not home or not away:
            continue
        out.append({"league": league, "gameId": r.get("gameId"), "date": r.get("date"),
                    "home": home, "away": away})
    return out


def _by_abbr(teams: dict, abbr: str | None):
    if not abbr:
        return None
    for t in teams.values():
        if t.get("abbr") == abbr:
            return t
    return None


def featured_matchups(cfg: dict, profiles: dict, ratings_boards: dict,
                      per_league: int = 8, leagues: list | None = None) -> list[dict]:
    """Marquee projected matchups (top teams paired) so the site has content off-season."""
    out = []
    for league in (leagues or cfg["leagues"]):
        lp = profiles.get(league)
        board = (ratings_boards or {}).get(league)
        if not lp or not board:
            continue
        top = [r["teamId"] for r in board[:max(2, 2 * per_league)] if r["teamId"] in lp["teams"]]
        for i in range(0, min(len(top) - 1, 2 * per_league), 2):
            home, away = lp["teams"][top[i + 1]], lp["teams"][top[i]]   # alternate home court
            out.append({"league": league, "gameId": f"feat-{league}-{i}", "date": None,
                        "featured": True, "home": home, "away": away})
    return out


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    profiles = util.read_json(util.abspath(os.path.join(cfg["paths"]["models_dir"], "profiles.json")))
    fx = load_fixtures(cfg, profiles)
    util.log(f"fixtures: {len(fx)} resolved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
