"""Futures stage — season win totals, playoff odds and title odds from Elo.

Off-season there are no games to price, so this projects the season ahead. Each
team's expected win % comes from its Elo against the rest of the field; a Monte
Carlo then samples season records, seeds a playoff bracket and crowns a champion
many times over to estimate playoff and title probabilities. Output:
``docs/data/futures.json``. Deterministic (fixed seed) so it doesn't churn.
"""
from __future__ import annotations

import math
import os
import random
import sys

from . import ratings, util

SIMS = 5000
SEED = 17


def _seed_order(n: int) -> list[int]:
    order = [1]
    while len(order) < n:
        m = len(order) * 2
        order = [x for o in order for x in (o, m + 1 - o)]
    return order


def _bracket_size(k: int) -> int:
    s = 1
    while s < k:
        s *= 2
    return s


def _win_prob(elo: dict, a: str, b: str, hf: float) -> float:
    return ratings.elo_win_prob(elo, a, b, hf)


def build_league(cfg: dict, league: str, elo: dict, teams_meta: dict) -> dict:
    ids = [t for t in elo if t != "_meta" and t in teams_meta]
    if len(ids) < 2:
        return {}
    G = int(cfg[league].get("games_per_season", 82))
    K = min(int(cfg[league].get("playoff_teams", 8)), len(ids))
    hf = (elo.get("_meta", {}).get("home_field", 60.0)) * 0.5   # playoff home edge

    # deterministic expected win % vs the field (neutral court)
    wp = {}
    for t in ids:
        ps = [_win_prob(elo, t, o, 0.0) for o in ids if o != t]
        wp[t] = sum(ps) / len(ps)

    rng = random.Random(SEED)
    playoff = {t: 0 for t in ids}
    title = {t: 0 for t in ids}
    size = _bracket_size(K)
    order = _seed_order(size)

    for _ in range(SIMS):
        # sample a season record for each team (Normal approx of a Binomial)
        wins = {}
        for t in ids:
            mu = G * wp[t]
            sd = math.sqrt(max(G * wp[t] * (1 - wp[t]), 0.5))
            wins[t] = min(G, max(0, rng.gauss(mu, sd)))
        seeds = sorted(ids, key=lambda t: (-wins[t], -elo[t]["elo"], rng.random()))[:K]
        for t in seeds:
            playoff[t] += 1
        bracket = [seeds[i - 1] if i - 1 < K else None for i in order]
        while len(bracket) > 1:
            nxt = []
            for i in range(0, len(bracket), 2):
                a, b = bracket[i], bracket[i + 1]
                if a is None:
                    nxt.append(b)
                elif b is None:
                    nxt.append(a)
                else:
                    nxt.append(a if rng.random() < _win_prob(elo, a, b, hf) else b)
            bracket = nxt
        if bracket and bracket[0]:
            title[bracket[0]] += 1

    rows = []
    for t in ids:
        meta = teams_meta.get(t, {})
        pwins = round(wp[t] * G, 1)
        rows.append({
            "teamId": t, "abbr": meta.get("abbr", ""), "name": meta.get("name", t),
            "elo": elo[t]["elo"], "proj_wins": pwins, "proj_losses": round(G - pwins, 1),
            "win_pct": round(wp[t], 3),
            "playoff_pct": round(playoff[t] / SIMS, 4), "playoff_fair": _fair(playoff[t] / SIMS),
            "title_pct": round(title[t] / SIMS, 4), "title_fair": _fair(title[t] / SIMS),
        })
    rows.sort(key=lambda r: -r["title_pct"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {"games": G, "playoff_teams": K, "sims": SIMS, "teams": rows}


def _fair(p: float):
    return round(1.0 / p, 2) if p and p > 1e-4 else None


def build(cfg: dict) -> dict:
    models = cfg["paths"]["models_dir"]
    elos = util.read_json(util.abspath(os.path.join(models, "elo.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "elo.json"))) else {}
    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "profiles.json"))) else {}
    out = {}
    for league in cfg["leagues"]:
        elo = elos.get(league)
        teams_meta = profiles.get(league, {}).get("teams", {})
        if not elo or not teams_meta:
            continue
        res = build_league(cfg, league, elo, teams_meta)
        if res:
            out[league] = res
            top = res["teams"][0]
            util.log(f"futures[{league}]: title favourite {top['name']} {top['title_pct']:.1%} "
                     f"({res['games']}-game season, top-{res['playoff_teams']} playoff)")
    path = util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], "futures.json"))
    payload = {"generated": _now(), "leagues": out}
    fresh = [lg for lg in (cfg.get("_all_leagues") or cfg["leagues"]) if lg in out]
    if util.should_merge(cfg, out):
        payload = util.merge_existing(path, payload, fresh, container_key="leagues")
    util.write_json(path, payload)
    return out


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str]) -> int:
    build(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
