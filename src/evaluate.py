"""Evaluate stage — walk-forward backtest of the team-Elo moneyline per league.

Replays every game chronologically (the Elo state at each game uses only earlier
results — leakage-free), scores the holdout season against log-loss / Brier /
accuracy, and compares to the home-court baseline. Output: ``reports/backtest.json``.
"""
from __future__ import annotations

import math
import os
import sys

from . import ingest, ratings, util


def _safe(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


def evaluate_league(cfg: dict, league: str) -> dict:
    e = cfg["elo"]
    init, k, hf = e["initial"], e["k"], e["home_field"]
    regress, mov = e["season_regression"], e["mov_mult"]
    holdout = cfg["backtest"].get(f"{league}_holdout_season", cfg[league]["season"])
    rating: dict[str, float] = {}

    seasons = sorted(set(cfg[league]["history_seasons"] + [cfg[league]["season"]]))
    n = ll = brier = correct = base_correct = home_wins = 0
    base_ll = 0.0
    home_base = _safe(0.60)   # fixed home-court baseline prob

    for si, season in enumerate(seasons):
        rows = ingest.load_results(cfg, league, season)
        if not rows:
            continue
        if si > 0 and regress:
            for t in rating:
                rating[t] = init + (1 - regress) * (rating[t] - init)
        rows.sort(key=lambda r: (r.get("date") or "", r.get("gameId") or ""))
        for r in rows:
            h, a = r["homeId"], r["awayId"]
            hp, ap = util.num(r["homePts"]), util.num(r["awayPts"])
            if hp <= 0 or ap <= 0:
                continue
            rh, ra = rating.get(h, init), rating.get(a, init)
            exp_h = ratings._expected(rh, ra, hf)
            home_win = hp > ap
            if int(season) == int(holdout):
                p = _safe(exp_h)
                y = 1.0 if home_win else 0.0
                n += 1
                ll += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                brier += (p - y) ** 2
                correct += 1 if (p > 0.5) == home_win else 0
                base_ll += -(y * math.log(home_base) + (1 - y) * math.log(1 - home_base))
                base_correct += 1 if home_win else 0
                home_wins += 1 if home_win else 0
            # update Elo (always)
            actual = 1.0 if home_win else 0.0
            ediff = (rh + hf - ra) if home_win else (ra - rh - hf)
            mult = ratings._mov_mult(hp - ap, ediff, mov)
            delta = k * mult * (actual - exp_h)
            rating[h], rating[a] = rh + delta, ra - delta

    if n == 0:
        return {"league": league, "n": 0}
    return {"league": league, "holdout_season": holdout, "n": n,
            "log_loss": round(ll / n, 4), "brier": round(brier / n, 4),
            "accuracy": round(correct / n, 4),
            "home_win_rate": round(home_wins / n, 4),
            "baseline_log_loss": round(base_ll / n, 4),
            "baseline_accuracy": round(base_correct / n, 4),
            "beats_baseline": ll / n < base_ll / n}


def build(cfg: dict) -> list[dict]:
    out = []
    for league in cfg["leagues"]:
        if not any(ingest.load_results(cfg, league, s)
                   for s in cfg[league]["history_seasons"] + [cfg[league]["season"]]):
            continue
        res = evaluate_league(cfg, league)
        out.append(res)
        util.log(f"evaluate[{league}]: {res}")
    util.write_json(util.abspath(os.path.join(cfg["paths"]["reports_dir"], "backtest.json")), out, indent=2)
    return out


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    build(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
