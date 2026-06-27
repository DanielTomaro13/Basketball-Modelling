"""Ratings stage — results-based, margin-aware team Elo per league.

Chronological replay of every game across the history seasons: home-court bonus,
a margin-of-victory multiplier (so blowouts move ratings more, damped for big
favourites), and regression toward the mean between seasons. Output:
``models/elo.json`` (state for the sim) and ``models/ratings.json`` (leaderboard).
"""
from __future__ import annotations

import math
import os
import sys

from . import ingest, util


def _expected(elo_home: float, elo_away: float, home_field: float) -> float:
    return 1.0 / (1.0 + 10 ** ((elo_away - (elo_home + home_field)) / 400.0))


def _mov_mult(margin: float, elo_diff_winner: float, mov: bool) -> float:
    if not mov:
        return 1.0
    return math.log(abs(margin) + 1.0) * (2.2 / (elo_diff_winner * 0.001 + 2.2))


def elo_win_prob(elo: dict, home_id: str, away_id: str, home_field: float | None = None) -> float:
    meta = elo.get("_meta", {})
    hf = home_field if home_field is not None else meta.get("home_field", 60.0)
    init = meta.get("initial", 1500.0)
    rh = (elo.get(home_id) or {}).get("elo", init)
    ra = (elo.get(away_id) or {}).get("elo", init)
    return _expected(rh, ra, hf)


def compute_elo(cfg: dict, league: str) -> dict:
    e = cfg["elo"]
    init, k, hf = e["initial"], e["k"], e["home_field"]
    regress, mov = e["season_regression"], e["mov_mult"]
    rating: dict[str, float] = {}
    played: dict[str, int] = {}

    seasons = sorted(set(cfg[league]["history_seasons"] + [cfg[league]["season"]]))
    for si, season in enumerate(seasons):
        rows = ingest.load_results(cfg, league, season)
        if not rows:
            continue
        if si > 0 and regress:  # regress toward the mean between seasons
            for t in rating:
                rating[t] = init + (1 - regress) * (rating[t] - init)
        rows.sort(key=lambda r: (r.get("date") or "", r.get("gameId") or ""))
        for r in rows:
            h, a = r["homeId"], r["awayId"]
            hp, ap = util.num(r["homePts"]), util.num(r["awayPts"])
            if hp <= 0 or ap <= 0:
                continue
            rh = rating.get(h, init)
            ra = rating.get(a, init)
            exp_h = _expected(rh, ra, hf)
            home_win = hp > ap
            actual = 1.0 if home_win else 0.0
            elo_diff_winner = (rh + hf - ra) if home_win else (ra - rh - hf)
            mult = _mov_mult(hp - ap, elo_diff_winner, mov)
            delta = k * mult * (actual - exp_h)
            rating[h] = rh + delta
            rating[a] = ra - delta
            played[h] = played.get(h, 0) + 1
            played[a] = played.get(a, 0) + 1

    out = {t: {"elo": round(rating[t], 1), "played": played.get(t, 0)} for t in rating}
    out["_meta"] = {"home_field": hf, "initial": init, "seasons": seasons}
    return out


def build_leaderboard(cfg: dict, league: str, elo: dict, profiles: dict | None = None) -> list[dict]:
    teams_meta = {}
    if profiles and league in profiles:
        teams_meta = profiles[league]["teams"]
    rows = []
    for tid, v in elo.items():
        if tid == "_meta":
            continue
        if teams_meta and tid not in teams_meta:   # drop teams not in the current season
            continue
        meta = teams_meta.get(tid, {})
        rows.append({"teamId": tid, "abbr": meta.get("abbr", ""),
                     "name": meta.get("name", tid), "elo": v["elo"], "played": v["played"],
                     "off": meta.get("off"), "def": meta.get("def"), "pace": meta.get("pace")})
    rows.sort(key=lambda r: -r["elo"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def build(cfg: dict) -> tuple[dict, dict]:
    models = cfg["paths"]["models_dir"]
    profiles_path = util.abspath(os.path.join(models, "profiles.json"))
    profiles = util.read_json(profiles_path) if os.path.exists(profiles_path) else {}
    elos, boards = {}, {}
    for league in cfg["leagues"]:
        if not ingest.load_results(cfg, league, cfg[league]["season"]) and \
           not any(ingest.load_results(cfg, league, s) for s in cfg[league]["history_seasons"]):
            continue
        elo = compute_elo(cfg, league)
        elos[league] = elo
        boards[league] = build_leaderboard(cfg, league, elo, profiles)
        top = boards[league][0] if boards[league] else {}
        util.log(f"ratings[{league}]: {len(boards[league])} teams, top {top.get('name')} "
                 f"{top.get('elo')}")
    util.write_json(util.abspath(os.path.join(models, "elo.json")), elos)
    util.write_json(util.abspath(os.path.join(models, "ratings.json")), boards)
    return elos, boards


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    build(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
