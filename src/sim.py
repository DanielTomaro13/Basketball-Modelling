"""Sim — clean-room basketball scoring & market engine. Pure-Python, no I/O.

Each team's expected points come from its opponent-adjusted offensive rating
versus the opponent's defence, scaled by the game's pace, plus a home-court edge.
The game **margin** and **total** are modelled as Normals (basketball scores are
high-count, so a Normal is the natural choice); per-team points, quarters and
halves are scaled Normals. Every market is read off these distributions. Player
props come from each player's rate profile and projected minutes, with low-count
stats (threes, steals, blocks, milestones) priced from Poisson tails.

This is a clean-room implementation built for the published site; it shares no
code with any private pricing engine.
"""
from __future__ import annotations

import math

SQRT2 = math.sqrt(2.0)
_2PI = math.sqrt(2.0 * math.pi)


# --------------------------------------------------------------------------- #
# Normal / Poisson primitives
# --------------------------------------------------------------------------- #
def _cdf(x: float, mu: float, sd: float) -> float:
    if sd <= 0:
        return 1.0 if x >= mu else 0.0
    return 0.5 * (1.0 + math.erf((x - mu) / (sd * SQRT2)))


def _sf(x: float, mu: float, sd: float) -> float:
    return 1.0 - _cdf(x, mu, sd)


def _pdf(x: float, mu: float, sd: float) -> float:
    if sd <= 0:
        return 0.0
    return math.exp(-((x - mu) ** 2) / (2 * sd * sd)) / (sd * _2PI)


def _band(lo: float, hi: float, mu: float, sd: float) -> float:
    return max(0.0, _cdf(hi, mu, sd) - _cdf(lo, mu, sd))


def _poisson_sf(line: float, mean: float) -> float:
    """P(X > line) for X ~ Poisson(mean); line is a half-integer (e.g. 2.5)."""
    if mean <= 0:
        return 0.0
    k = int(math.floor(line))                      # P(X >= k+1) = 1 - sum_{i=0..k}
    cum, term = 0.0, math.exp(-mean)
    for i in range(0, k + 1):
        cum += term
        term *= mean / (i + 1)
    return max(0.0, min(1.0, 1.0 - cum))


def _logit(p: float) -> float:
    p = min(max(p, 1e-9), 1 - 1e-9)
    return math.log(p / (1 - p))


def _sig(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-z))


def fair(p) -> float | None:
    return round(1.0 / p, 2) if p and p > 1e-6 else None


def _clip(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


def _ou(line: float, mu: float, sd: float) -> dict:
    over = _clip(_sf(line, mu, sd))
    return {"line": round(line, 1), "over": round(over, 4), "under": round(1 - over, 4),
            "over_fair": fair(over), "under_fair": fair(1 - over)}


def _half_lines(center: float, n: int, step: float) -> list[float]:
    base = round(center * 2) / 2.0           # nearest 0.5
    return [round(base + (i - n) * step, 1) for i in range(2 * n + 1)]


# --------------------------------------------------------------------------- #
# Expected points
# --------------------------------------------------------------------------- #
def team_means(home: dict, away: dict, agg: dict) -> tuple[float, float]:
    lg = agg["ppg"]
    he = agg["home_edge_pts"]
    raw_h = lg + (home["off"] - lg) + (away["def"] - lg) + he / 2
    raw_a = lg + (away["off"] - lg) + (home["def"] - lg) - he / 2
    pace_mult = home.get("pace_factor", 1.0) * away.get("pace_factor", 1.0)
    return raw_h * pace_mult, raw_a * pace_mult


def _anchor_to_winprob(mu_h: float, mu_a: float, sigma_margin: float, target_p: float) -> tuple[float, float]:
    """Shift the margin to match a target home win prob, keeping the total fixed."""
    total = mu_h + mu_a
    target_margin = sigma_margin * _invnorm(target_p)
    return (total + target_margin) / 2, (total - target_margin) / 2


def _invnorm(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation)."""
    p = min(max(p, 1e-9), 1 - 1e-9)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# --------------------------------------------------------------------------- #
# Game parameters (shared by the market book and the odds pricer)
# --------------------------------------------------------------------------- #
def game_params(home: dict, away: dict, agg: dict, sim_cfg: dict,
                elo_home_wp: float | None = None) -> dict:
    sigma_m = agg["sigma_margin"]
    sigma_t = agg["sigma_total"]
    mu_h, mu_a = team_means(home, away, agg)

    # headline win prob: blend the sim margin-prob with the Elo prob, then anchor
    sim_p = _clip(_sf(0.0, mu_h - mu_a, sigma_m))
    if elo_home_wp is not None:
        w = sim_cfg["elo_weight"]
        head_p = _sig((1 - w) * _logit(sim_p) + w * _logit(_clip(elo_home_wp)))
        mu_h, mu_a = _anchor_to_winprob(mu_h, mu_a, sigma_m, head_p)
    else:
        head_p = sim_p

    mu_margin = mu_h - mu_a
    mu_total = mu_h + mu_a
    sd_team = math.sqrt(sigma_t ** 2 + sigma_m ** 2) / 2.0
    Q = agg["quarters"]
    qvi = sim_cfg["quarter_var_inflation"]
    hvi = sim_cfg["half_var_inflation"]
    return {
        "mu_home": mu_h, "mu_away": mu_a, "mu_margin": mu_margin, "mu_total": mu_total,
        "sigma_margin": sigma_m, "sigma_total": sigma_t, "sd_team": sd_team,
        "head_home": head_p, "head_away": 1 - head_p, "quarters": Q,
        # per-period (quarter / half) margin & total moments
        "q_mu_margin": mu_margin / Q, "q_sd_margin": sigma_m / math.sqrt(Q) * qvi,
        "q_mu_total": mu_total / Q, "q_sd_total": sigma_t / math.sqrt(Q) * qvi,
        "q_mu_home": mu_h / Q, "q_mu_away": mu_a / Q, "q_sd_team": sd_team / math.sqrt(Q) * qvi,
        "h_mu_margin": mu_margin / 2, "h_sd_margin": sigma_m / math.sqrt(2) * hvi,
        "h_mu_total": mu_total / 2, "h_sd_total": sigma_t / math.sqrt(2) * hvi,
        "h_mu_home": mu_h / 2, "h_mu_away": mu_a / 2, "h_sd_team": sd_team / math.sqrt(2) * hvi,
        "ot_push": agg["ot_push"],
    }


# --------------------------------------------------------------------------- #
# Market builders
# --------------------------------------------------------------------------- #
def _moneyline(p: dict, home: str, away: str) -> dict:
    ph = p["head_home"]
    return {"key": "ml", "label": "Moneyline", "selections": [
        {"label": home, "prob": round(ph, 4), "fair": fair(ph)},
        {"label": away, "prob": round(1 - ph, 4), "fair": fair(1 - ph)}]}


def _spread(p: dict, home: str, away: str, sim_cfg: dict) -> dict:
    mu, sd = p["mu_margin"], p["sigma_margin"]
    lines = []
    for L in _half_lines(mu, sim_cfg["spread_ladder"], 1.0):
        # home -L wins if margin > L ; away +L wins if margin < L  (home gives L points)
        ph = _clip(_sf(L, mu, sd))
        lines.append({"line": round(L, 1),
                      "home": round(ph, 4), "away": round(1 - ph, 4),
                      "home_label": f"{home} {-L:+g}", "away_label": f"{away} {L:+g}",
                      "home_fair": fair(ph), "away_fair": fair(1 - ph)})
    return {"key": "spread", "label": "Point spread", "lines": lines}


def _total(p: dict, sim_cfg: dict) -> dict:
    mu, sd = p["mu_total"], p["sigma_total"]
    lines = [_ou(L, mu, sd) for L in _half_lines(mu, sim_cfg["totals_steps"], sim_cfg["totals_step_size"])]
    return {"key": "total", "label": "Total points", "lines": lines}


def _team_totals(p: dict, home: str, away: str, sim_cfg: dict) -> dict:
    sd = p["sd_team"]
    n, step = sim_cfg["team_total_steps"], sim_cfg["totals_step_size"]
    lines = []
    for side, mu, nm in (("home", p["mu_home"], home), ("away", p["mu_away"], away)):
        for L in _half_lines(mu, n, step):
            d = _ou(L, mu, sd)
            d.update({"side": side, "team": nm})
            lines.append(d)
    return {"key": "team_total", "label": "Team totals", "lines": lines}


def _margin_bands(p: dict, home: str, away: str) -> dict:
    mu, sd = p["mu_margin"], p["sigma_margin"]
    bands = [(0.5, 5.5, "1–5"), (5.5, 10.5, "6–10"), (10.5, 15.5, "11–15"),
             (15.5, 20.5, "16–20"), (20.5, 200, "21+")]
    sels = []
    for lo, hi, lab in bands:
        sels.append({"label": f"{home} by {lab}", "prob": round(_clip(_band(lo, hi, mu, sd)), 4),
                     "fair": fair(_band(lo, hi, mu, sd))})
    for lo, hi, lab in bands:
        sels.append({"label": f"{away} by {lab}", "prob": round(_clip(_band(-hi, -lo, mu, sd)), 4),
                     "fair": fair(_band(-hi, -lo, mu, sd))})
    return {"key": "margin_band", "label": "Winning margin", "selections": sels}


def _total_bands(p: dict) -> dict:
    mu, sd = p["mu_total"], p["sigma_total"]
    start = int((mu - 3 * sd) // 10) * 10
    sels = []
    for b in range(start, start + 120, 10):
        prob = _band(b - 0.5, b + 9.5, mu, sd)
        if prob < 0.012:
            continue
        sels.append({"label": f"{b}–{b+9}", "prob": round(prob, 4), "fair": fair(prob)})
    return {"key": "total_band", "label": "Total points band", "selections": sels}


def _overtime(p: dict) -> dict:
    mu, sd = p["mu_margin"], p["sigma_margin"]
    # closeness vs a pick'em, scaled by the league OT baseline
    pot = _clip(p["ot_push"] * (_pdf(0, mu, sd) / _pdf(0, 0, sd)))
    return {"key": "overtime", "label": "Overtime", "selections": [
        {"label": "Yes", "prob": round(pot, 4), "fair": fair(pot)},
        {"label": "No", "prob": round(1 - pot, 4), "fair": fair(1 - pot)}]}


def _odd_even(p: dict) -> dict:
    return {"key": "odd_even", "label": "Total odd / even", "selections": [
        {"label": "Even", "prob": 0.5, "fair": 2.0},
        {"label": "Odd", "prob": 0.5, "fair": 2.0}]}


def _race(p: dict, home: str, away: str) -> dict:
    # race-to-20 winner tracks the scoring-rate gap (de-levered game win prob)
    ph = _clip(0.5 + 0.62 * (p["head_home"] - 0.5))
    return {"key": "race20", "label": "Race to 20 points", "selections": [
        {"label": home, "prob": round(ph, 4), "fair": fair(ph)},
        {"label": away, "prob": round(1 - ph, 4), "fair": fair(1 - ph)}]}


def _period_markets(p: dict, home: str, away: str, sim_cfg: dict) -> list[dict]:
    out = []
    Q = p["quarters"]
    periods = [(f"q{i+1}", f"Q{i+1}", p["q_mu_margin"], p["q_sd_margin"], p["q_mu_total"],
                p["q_sd_total"], p["q_mu_home"], p["q_mu_away"], p["q_sd_team"]) for i in range(Q)]
    periods += [("h1", "1st half", p["h_mu_margin"], p["h_sd_margin"], p["h_mu_total"],
                 p["h_sd_total"], p["h_mu_home"], p["h_mu_away"], p["h_sd_team"]),
                ("h2", "2nd half", p["h_mu_margin"], p["h_sd_margin"], p["h_mu_total"],
                 p["h_sd_total"], p["h_mu_home"], p["h_mu_away"], p["h_sd_team"])]
    for key, lab, mm, sm, mt, st, mh, ma, st_team in periods:
        # 3-way winner (home / tie / away) over a ±0.5 tie window
        p_home = _clip(_sf(0.5, mm, sm))
        p_away = _clip(_cdf(-0.5, mm, sm))
        p_tie = _clip(1 - p_home - p_away)
        out.append({"key": f"{key}_ml", "label": f"{lab} winner", "selections": [
            {"label": home, "prob": round(p_home, 4), "fair": fair(p_home)},
            {"label": "Tie", "prob": round(p_tie, 4), "fair": fair(p_tie)},
            {"label": away, "prob": round(p_away, 4), "fair": fair(p_away)}]})
        # period spread (3 lines), total (3 lines), team totals (main line each)
        sp = [{"line": round(L, 1), "home": round(_clip(_sf(L, mm, sm)), 4),
               "away": round(_clip(_cdf(L, mm, sm)), 4),
               "home_label": f"{home} {-L:+g}", "away_label": f"{away} {L:+g}",
               "home_fair": fair(_sf(L, mm, sm)), "away_fair": fair(_cdf(L, mm, sm))}
              for L in _half_lines(mm, 1, 1.0)]
        out.append({"key": f"{key}_spread", "label": f"{lab} spread", "lines": sp})
        out.append({"key": f"{key}_total", "label": f"{lab} total",
                    "lines": [_ou(L, mt, st) for L in _half_lines(mt, 1, 2.0)]})
        tt = []
        for side, mu, nm in (("home", mh, home), ("away", ma, away)):
            d = _ou(round(mu * 2) / 2 - 0.5, mu, st_team)
            d.update({"side": side, "team": nm})
            tt.append(d)
        out.append({"key": f"{key}_team_total", "label": f"{lab} team totals", "lines": tt})
    return out


def _htft(p: dict, home: str, away: str) -> dict:
    """Half-time/full-time 3x3 from independent first- and second-half margins."""
    m1, s1 = p["h_mu_margin"], p["h_sd_margin"]
    m2, s2 = p["h_mu_margin"], p["h_sd_margin"]
    # discretize both half margins and accumulate the joint
    grid = range(-45, 46)
    w1 = [_pdf(x, m1, s1) for x in grid]
    w2 = [_pdf(x, m2, s2) for x in grid]
    z1, z2 = sum(w1) or 1, sum(w2) or 1
    cells = {}
    for i, x1 in enumerate(grid):
        ht = home if x1 > 0 else (away if x1 < 0 else "Tie")
        for j, x2 in enumerate(grid):
            ft_m = x1 + x2
            ft = home if ft_m > 0 else (away if ft_m < 0 else "Tie")
            cells[(ht, ft)] = cells.get((ht, ft), 0.0) + (w1[i] / z1) * (w2[j] / z2)
    order = [home, "Tie", away]
    sels = []
    for ht in order:
        for ft in order:
            pr = _clip(cells.get((ht, ft), 0.0))
            if pr < 1e-4:
                continue
            sels.append({"label": f"{ht} / {ft}", "prob": round(pr, 4), "fair": fair(pr)})
    return {"key": "htft", "label": "Half-time / full-time", "selections": sels}


def _half_combos(p: dict, home: str, away: str) -> dict:
    m, s = p["h_mu_margin"], p["h_sd_margin"]
    p_h_home = _clip(_sf(0.0, m, s))
    both = _clip(p_h_home * p_h_home)
    either = _clip(1 - (1 - p_h_home) * (1 - p_h_home))
    return {"key": "half_combo", "label": "Halves", "selections": [
        {"label": f"{home} wins both halves", "prob": round(both, 4), "fair": fair(both)},
        {"label": f"{home} wins either half", "prob": round(either, 4), "fair": fair(either)}]}


MARKET_ORDER = ["ml", "spread", "total", "team_total", "margin_band", "total_band",
                "race20", "overtime", "odd_even",
                "h1_ml", "h1_spread", "h1_total", "h1_team_total",
                "h2_ml", "h2_spread", "h2_total", "h2_team_total", "htft", "half_combo",
                "q1_ml", "q1_spread", "q1_total", "q1_team_total",
                "q2_ml", "q2_spread", "q2_total", "q2_team_total",
                "q3_ml", "q3_spread", "q3_total", "q3_team_total",
                "q4_ml", "q4_spread", "q4_total", "q4_team_total"]


def project_game(home: dict, away: dict, agg: dict, sim_cfg: dict,
                 elo_home_wp: float | None = None) -> dict:
    """Full market book for one game. ``home``/``away`` are team profiles."""
    hn, an = home.get("name", "Home"), away.get("name", "Away")
    p = game_params(home, away, agg, sim_cfg, elo_home_wp)
    markets = [
        _moneyline(p, hn, an), _spread(p, hn, an, sim_cfg), _total(p, sim_cfg),
        _team_totals(p, hn, an, sim_cfg), _margin_bands(p, hn, an), _total_bands(p),
        _race(p, hn, an), _overtime(p), _odd_even(p),
    ]
    markets += _period_markets(p, hn, an, sim_cfg)
    markets += [_htft(p, hn, an), _half_combos(p, hn, an)]
    by_key = {m["key"]: m for m in markets}
    ordered = [by_key[k] for k in MARKET_ORDER if k in by_key]
    return {
        "mu_home": round(p["mu_home"], 1), "mu_away": round(p["mu_away"], 1),
        "win_home": round(p["head_home"], 4), "win_away": round(p["head_away"], 4),
        "fair_home": fair(p["head_home"]), "fair_away": fair(p["head_away"]),
        "mu_total": round(p["mu_total"], 1), "mu_margin": round(p["mu_margin"], 1),
        "params": {k: round(v, 4) for k, v in p.items() if isinstance(v, (int, float))},
        "markets": ordered,
    }


# --------------------------------------------------------------------------- #
# Player props
# --------------------------------------------------------------------------- #
# game-to-game SD ≈ factor * sqrt(mean); low-count stats use Poisson tails.
_PROP_SD = {"pts": 1.7, "reb": 1.05, "ast": 1.1, "fgm": 1.15, "ftm": 1.25, "tov": 1.0}
_POISSON_STATS = {"fg3m", "stl", "blk"}
_PROP_LABEL = {"pts": "Points", "reb": "Rebounds", "ast": "Assists", "fg3m": "Threes made",
               "fgm": "Field goals made", "ftm": "Free throws made", "stl": "Steals",
               "blk": "Blocks", "tov": "Turnovers"}
_COMBOS = {"pra": (("pts", "reb", "ast"), "Pts+Reb+Ast"), "pr": (("pts", "reb"), "Pts+Reb"),
           "pa": (("pts", "ast"), "Pts+Ast"), "ra": (("reb", "ast"), "Reb+Ast"),
           "stocks": (("stl", "blk"), "Steals+Blocks")}


def _prop_sd(stat: str, mean: float) -> float:
    return max(0.9, _PROP_SD.get(stat, 1.0) * math.sqrt(max(mean, 0.4)))


def _ou_prop(line: float, mean: float, stat: str) -> dict:
    if stat in _POISSON_STATS:
        over = _poisson_sf(line, mean)
    else:
        over = _sf(line, mean, _prop_sd(stat, mean))
    over = _clip(over)
    return {"line": round(line, 1), "over": round(over, 4), "under": round(1 - over, 4),
            "over_fair": fair(over), "under_fair": fair(1 - over)}


def _prop_lines(mean: float, stat: str, steps: int) -> list[dict]:
    center = round(mean - 0.5) + 0.5 if mean >= 1 else 0.5
    out, seen = [], set()
    for i in range(-steps, steps + 1):
        L = round(center + i, 1)
        if L < 0.5 or L in seen:
            continue
        seen.add(L)
        out.append(_ou_prop(L, mean, stat))
    return out


def player_props(player: dict, scale: float, agg: dict, sim_cfg: dict,
                 minutes: float | None = None) -> dict:
    """Markets for one player. ``scale`` adjusts pace/role for this matchup (≈1.0)."""
    pg = player["pg"]
    mins = minutes if minutes else player.get("min", 0.0)
    base_min = player.get("min", mins) or mins
    mscale = (mins / base_min) if base_min else 1.0
    steps = sim_cfg["prop_steps"]
    means = {k: max(0.0, pg.get(k, 0.0) * scale * mscale) for k in _PROP_LABEL}

    singles = []
    for stat in ("pts", "reb", "ast", "fg3m", "stl", "blk", "fgm", "ftm", "tov"):
        m = means[stat]
        if m < 0.4:
            continue
        singles.append({"stat": stat, "label": _PROP_LABEL[stat], "proj": round(m, 1),
                        "lines": _prop_lines(m, stat, steps)})

    combos = []
    for key, (parts, lab) in _COMBOS.items():
        m = sum(means[s] for s in parts)
        if m < 1.0:
            continue
        var = sum((_prop_sd(s, means[s]) ** 2) for s in parts) * 1.10   # mild positive corr
        sd = math.sqrt(var)
        center = round(m - 0.5) + 0.5
        lines = []
        for i in range(-steps, steps + 1):
            L = center + i * (2.0 if m > 25 else 1.0)
            if L < 0.5:
                continue
            over = _clip(_sf(L, m, sd))
            lines.append({"line": round(L, 1), "over": round(over, 4), "under": round(1 - over, 4),
                          "over_fair": fair(over), "under_fair": fair(1 - over)})
        combos.append({"stat": key, "label": lab, "proj": round(m, 1), "lines": lines})

    # discrete: milestones, 1+ three, double/triple-double
    pts_sd = _prop_sd("pts", means["pts"])
    discrete = []
    for thr in (10, 20, 30):
        pr = _clip(_sf(thr - 0.5, means["pts"], pts_sd))
        discrete.append({"stat": f"pts_{thr}", "label": f"{thr}+ points",
                         "prob": round(pr, 4), "fair": fair(pr)})
    three1 = _clip(_poisson_sf(0.5, means["fg3m"]))
    discrete.append({"stat": "three_1", "label": "1+ three", "prob": round(three1, 4), "fair": fair(three1)})
    dd = _clip(player.get("dd_rate", 0.0)) if player.get("dd_rate") else 0.0
    td = _clip(player.get("td_rate", 0.0)) if player.get("td_rate") else 0.0
    if dd > 1e-4:
        discrete.append({"stat": "dd", "label": "Double-double", "prob": round(dd, 4), "fair": fair(dd)})
    if td > 1e-4:
        discrete.append({"stat": "td", "label": "Triple-double", "prob": round(td, 4), "fair": fair(td)})

    # quarter / half props for the headline counting stats
    Q = agg["quarters"]
    periods = []
    for stat in ("pts", "reb", "ast", "fg3m"):
        m = means[stat]
        if m < 1.0:
            continue
        per_q = m / Q
        per_h = m / 2
        if per_q >= 0.7:
            periods.append({"stat": stat, "label": f"{_PROP_LABEL[stat]} (Q1)", "period": "q1",
                            "proj": round(per_q, 1), "lines": _prop_lines(per_q, stat, 1)})
        if per_h >= 0.7:
            periods.append({"stat": stat, "label": f"{_PROP_LABEL[stat]} (1st half)", "period": "h1",
                            "proj": round(per_h, 1), "lines": _prop_lines(per_h, stat, 1)})
    # PRA quarter/half
    pra = sum(means[s] for s in ("pts", "reb", "ast"))
    if pra >= 4:
        var = sum((_prop_sd(s, means[s]) ** 2) for s in ("pts", "reb", "ast")) * 1.10
        for plab, pkey, div in (("(Q1)", "q1", Q), ("(1st half)", "h1", 2)):
            m = pra / div
            sd = math.sqrt(var) / math.sqrt(div)
            center = round(m - 0.5) + 0.5
            lines = [{"line": round(center + i, 1),
                      "over": round(_clip(_sf(center + i, m, sd)), 4),
                      "under": round(1 - _clip(_sf(center + i, m, sd)), 4),
                      "over_fair": fair(_clip(_sf(center + i, m, sd))),
                      "under_fair": fair(1 - _clip(_sf(center + i, m, sd)))}
                     for i in (-1, 0, 1) if center + i >= 0.5]
            periods.append({"stat": "pra", "label": f"Pts+Reb+Ast {plab}", "period": pkey,
                            "proj": round(m, 1), "lines": lines})

    return {"id": player["id"], "name": player["name"], "team": player.get("teamAbbr", ""),
            "min": round(mins, 1), "singles": singles, "combos": combos,
            "discrete": discrete, "periods": periods}
