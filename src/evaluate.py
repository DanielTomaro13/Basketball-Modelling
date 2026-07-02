"""Evaluate stage — walk-forward backtest of the PRODUCTION blend per league.

Replays every game chronologically. At each holdout-season game the model is
rebuilt exactly as production would have seen it that morning:
  - Elo state from all earlier results (margin-aware, season-regressed);
  - opponent-adjusted team profiles from THIS season's earlier games only
    (shrunk toward the league mean, so early-season games lean on the prior);
  - headline win prob = the same logit blend (sim, Elo, elo_weight) predict uses.

Scores log-loss / Brier / accuracy / calibration (ECE) for the blend and for
each leg alone (Elo-only, sim-only) plus the fixed home-court baseline — the
previous backtest scored ONLY the Elo leg, so the published number was never
validated. Also collects margin / total residuals and writes their empirical
SDs + fitted home edge to ``models/calibration.json``; features overlays those
onto the league aggregates so the whole market book prices with measured
widths instead of the config seed guesses.

Output: ``reports/backtest.json`` + ``models/calibration.json``.
"""
from __future__ import annotations

import math
import os
import sys

from . import features, ingest, ratings, sim, util


def _safe(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


def _ece(pairs: list[tuple[float, float]], bins: int = 10) -> float:
    """Expected calibration error over (prob, outcome) pairs."""
    tot = len(pairs)
    if not tot:
        return 0.0
    buckets: dict[int, list[tuple[float, float]]] = {}
    for p, y in pairs:
        buckets.setdefault(min(int(p * bins), bins - 1), []).append((p, y))
    err = 0.0
    for vals in buckets.values():
        if len(vals) < 25:
            continue
        pm = sum(v[0] for v in vals) / len(vals)
        ym = sum(v[1] for v in vals) / len(vals)
        err += (len(vals) / tot) * abs(pm - ym)
    return err


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _profiles_from(games: dict, lg_ppg: float, he: float, prior: float) -> dict:
    """Shrunk opponent-adjusted profiles from an accumulated game log."""
    if not games:
        return {}
    adj_o, adj_d = features.opponent_adjust(games, lg_ppg, he)
    out = {}
    for t, gs in games.items():
        g = len(gs)
        w = g / (g + prior)
        out[t] = {"off": lg_ppg + w * (adj_o[t] - lg_ppg),
                  "def": lg_ppg + w * (adj_d[t] - lg_ppg),
                  "pace_factor": 1.0}
    return out


def evaluate_league(cfg: dict, league: str) -> dict:
    e = cfg["elo"]
    init, k, hf = e["initial"], e["k"], e["home_field"]
    regress, mov = e["season_regression"], e["mov_mult"]
    holdout = int(cfg["backtest"].get(f"{league}_holdout_season", cfg[league]["season"]))
    lg_ppg = cfg[league]["league_ppg"]
    he = cfg[league]["home_edge_pts"]
    prior = cfg["features"]["team_prior_games"]
    sigma_m = cfg[league]["sigma_margin"]
    elo_w = cfg["sim"]["elo_weight"]
    rating: dict[str, float] = {}

    seasons = sorted(set(cfg[league]["history_seasons"] + [cfg[league]["season"]]))
    n = correct = base_correct = home_wins = 0
    ll = brier = base_ll = ll_elo = ll_sim = 0.0
    pairs: list[tuple[float, float]] = []
    resid_m: list[float] = []
    resid_t: list[float] = []
    home_base = _safe(0.60)   # fixed home-court baseline prob

    for si, season in enumerate(seasons):
        rows = ingest.load_results(cfg, league, season)
        if not rows:
            continue
        if si > 0 and regress:
            for t in rating:
                rating[t] = init + (1 - regress) * (rating[t] - init)
        rows.sort(key=lambda r: (r.get("date") or "", r.get("gameId") or ""))
        season_games: dict[str, list] = {}
        profiles: dict = {}
        profiles_date = None
        for r in rows:
            h, a = r["homeId"], r["awayId"]
            hp, ap = util.num(r["homePts"]), util.num(r["awayPts"])
            if hp <= 0 or ap <= 0:
                continue
            rh, ra = rating.get(h, init), rating.get(a, init)
            elo_p = ratings._expected(rh, ra, hf)
            home_win = hp > ap
            if int(season) == holdout:
                # rebuild profiles from prior games once per date (cheap + honest)
                d = r.get("date") or ""
                if d != profiles_date:
                    profiles = _profiles_from(season_games, lg_ppg, he, prior)
                    profiles_date = d
                lg_prof = {"off": lg_ppg, "def": lg_ppg, "pace_factor": 1.0}
                ph = profiles.get(h, lg_prof)
                pa_ = profiles.get(a, lg_prof)
                agg = {"ppg": lg_ppg, "home_edge_pts": he}
                mu_h, mu_a = sim.team_means(ph, pa_, agg)
                sim_p = _safe(sim._sf(0.0, mu_h - mu_a, sigma_m))
                p = _safe(sim._sig((1 - elo_w) * sim._logit(sim_p)
                                   + elo_w * sim._logit(_safe(elo_p))))
                y = 1.0 if home_win else 0.0
                n += 1
                ll += -(y * math.log(p) + (1 - y) * math.log(1 - p))
                ll_elo += -(y * math.log(_safe(elo_p)) + (1 - y) * math.log(1 - _safe(elo_p)))
                ll_sim += -(y * math.log(sim_p) + (1 - y) * math.log(1 - sim_p))
                brier += (p - y) ** 2
                correct += 1 if (p > 0.5) == home_win else 0
                base_ll += -(y * math.log(home_base) + (1 - y) * math.log(1 - home_base))
                base_correct += 1 if home_win else 0
                home_wins += 1 if home_win else 0
                pairs.append((p, y))
                resid_m.append((hp - ap) - (mu_h - mu_a))
                resid_t.append((hp + ap) - (mu_h + mu_a))
            # update Elo (always)
            actual = 1.0 if home_win else 0.0
            ediff = (rh + hf - ra) if home_win else (ra - rh - hf)
            mult = ratings._mov_mult(hp - ap, ediff, mov)
            delta = k * mult * (actual - elo_p)
            rating[h], rating[a] = rh + delta, ra - delta
            season_games.setdefault(h, []).append((hp, ap, a, True))
            season_games.setdefault(a, []).append((ap, hp, h, False))

    if n == 0:
        return {"league": league, "n": 0}
    bias_m = sum(resid_m) / n
    return {"league": league, "holdout_season": holdout, "n": n,
            "log_loss": round(ll / n, 4), "brier": round(brier / n, 4),
            "accuracy": round(correct / n, 4),
            "calibration_error": round(_ece(pairs), 4),
            "log_loss_elo_only": round(ll_elo / n, 4),
            "log_loss_sim_only": round(ll_sim / n, 4),
            "home_win_rate": round(home_wins / n, 4),
            "baseline_log_loss": round(base_ll / n, 4),
            "baseline_accuracy": round(base_correct / n, 4),
            "beats_baseline": ll / n < base_ll / n,
            # distribution calibration (what the market book prices with)
            "sigma_margin_config": sigma_m,
            "sigma_margin_empirical": round(_std(resid_m), 2),
            "sigma_total_config": cfg[league]["sigma_total"],
            "sigma_total_empirical": round(_std(resid_t), 2),
            "margin_bias": round(bias_m, 2),
            "margin_mae": round(sum(abs(x) for x in resid_m) / n, 2),
            "home_edge_config": he,
            "home_edge_fitted": round(he + bias_m, 2)}


def build(cfg: dict) -> list[dict]:
    out = []
    cal_path = util.abspath(os.path.join(cfg["paths"]["models_dir"], "calibration.json"))
    cal = util.read_json(cal_path) if os.path.exists(cal_path) else {}
    for league in cfg["leagues"]:
        if not any(ingest.load_results(cfg, league, s)
                   for s in cfg[league]["history_seasons"] + [cfg[league]["season"]]):
            continue
        res = evaluate_league(cfg, league)
        out.append(res)
        util.log(f"evaluate[{league}]: {res}")
        if res.get("n", 0) >= 100:
            cal[league] = {"n": res["n"],
                           "sigma_margin": res["sigma_margin_empirical"],
                           "sigma_total": res["sigma_total_empirical"],
                           "home_edge_pts": res["home_edge_fitted"],
                           "holdout_season": res["holdout_season"]}
    util.write_json(cal_path, cal)
    util.write_json(util.abspath(os.path.join(cfg["paths"]["reports_dir"], "backtest.json")), out, indent=2)
    return out


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    build(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
