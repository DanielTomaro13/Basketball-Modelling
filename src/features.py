"""Features stage — opponent-adjusted team profiles + player rate profiles.

Team offense/defense are derived from final scores with a few rounds of
opponent adjustment (SRS-style, in points-per-game space), so a team that piled
up points against weak defences is discounted. Pace comes from the season stats
feed. Player profiles are per-game rates with a per-minute view for projecting
props at non-average minutes. Everything is shrunk toward the league mean by
sample size. Output: ``models/profiles.json`` keyed by league.
"""
from __future__ import annotations

import os
import sys

from . import ingest, util


def _season_results(cfg: dict, league: str) -> list[dict]:
    """Current-season final scores (the rating window); fall back to the latest available."""
    seasons = [cfg[league]["season"]] + list(reversed(cfg[league]["history_seasons"]))
    for s in seasons:
        rows = ingest.load_results(cfg, league, s)
        if rows:
            return rows
    return []


def opponent_adjust(games: dict, lg_ppg: float, he: float, iterations: int = 12) -> tuple[dict, dict]:
    """SRS-style iterative opponent adjustment in points-per-game space.

    ``games`` = {team: [(pts_for, pts_against, opponent, is_home), ...]}.
    Returns (adj_offense, adj_defense) per team, unshrunk. Also used by the
    walk-forward backtest (profiles rebuilt from prior games only).
    """
    ids = list(games.keys())
    adj_o = {t: lg_ppg for t in ids}
    adj_d = {t: lg_ppg for t in ids}
    for _ in range(iterations):
        new_o, new_d = {}, {}
        for t in ids:
            so = sd = 0.0
            for pf, pa, opp, is_home in games[t]:
                edge = he / 2 if is_home else -he / 2
                so += (pf - edge) - (adj_d.get(opp, lg_ppg) - lg_ppg)
                sd += (pa + edge) - (adj_o.get(opp, lg_ppg) - lg_ppg)
            g = len(games[t])
            new_o[t] = so / g
            new_d[t] = sd / g
        adj_o, adj_d = new_o, new_d
    return adj_o, adj_d


def build_team_profiles(cfg: dict, league: str) -> tuple[dict, dict]:
    """Return (teams dict keyed by id, league aggregates). Adjusted o/d in points/game."""
    teams_path = util.abspath(f"data/raw/teams-{league}.json")
    tstats_path = util.abspath(f"data/raw/teamstats-{league}.json")
    teams_meta = util.read_json(teams_path) if os.path.exists(teams_path) else {}
    tstats = util.read_json(tstats_path) if os.path.exists(tstats_path) else {}
    rows = _season_results(cfg, league)

    # collect each team's games as (pts_for, pts_against, opponent, is_home)
    games: dict[str, list] = {}
    pf_tot = n_tot = 0.0
    for r in rows:
        h, a = r["homeId"], r["awayId"]
        hp, ap = util.num(r["homePts"]), util.num(r["awayPts"])
        if hp <= 0 or ap <= 0:
            continue
        games.setdefault(h, []).append((hp, ap, a, True))
        games.setdefault(a, []).append((ap, hp, h, False))
        pf_tot += hp + ap
        n_tot += 2
    lg_ppg = (pf_tot / n_tot) if n_tot else cfg[league]["league_ppg"]
    he = cfg[league]["home_edge_pts"]

    adj_o, adj_d = opponent_adjust(games, lg_ppg, he)

    # shrink toward league mean by games played
    prior = cfg["features"]["team_prior_games"]
    ids = list(games.keys())
    out = {}
    paces = []
    for t in ids:
        g = len(games[t])
        w = g / (g + prior)
        o = lg_ppg + w * (adj_o[t] - lg_ppg)
        d = lg_ppg + w * (adj_d[t] - lg_ppg)
        ts = tstats.get(t, {})
        pace = util.num((ts.get("paceFactor") or {}).get("value")) or \
            util.num((ts.get("avgEstimatedPossessions") or {}).get("value")) or cfg[league]["league_pace"]
        paces.append(pace)
        meta = teams_meta.get(t, {})
        out[t] = {"id": t, "abbr": meta.get("abbr", ""), "name": meta.get("name", t),
                  "gp": g, "off": round(o, 2), "def": round(d, 2), "pace": round(pace, 2),
                  "pf": round(sum(x[0] for x in games[t]) / g, 1),
                  "pa": round(sum(x[1] for x in games[t]) / g, 1)}
    lg_pace = (sum(paces) / len(paces)) if paces else cfg[league]["league_pace"]
    for t in out:
        out[t]["pace_factor"] = round(out[t]["pace"] / lg_pace, 4) if lg_pace else 1.0
    aggregates = {"ppg": round(lg_ppg, 2), "pace": round(lg_pace, 2),
                  "quarter_minutes": cfg[league]["quarter_minutes"],
                  "quarters": cfg[league]["quarters"],
                  "home_edge_pts": he,
                  "sigma_margin": cfg[league]["sigma_margin"],
                  "sigma_total": cfg[league]["sigma_total"],
                  "ot_push": cfg[league]["ot_push"]}
    # Overlay the empirically calibrated sigmas / home edge from the walk-forward
    # backtest (models/calibration.json, written by evaluate) — the config values
    # are seed guesses and run narrow (NBA margin SD is ~13, config said 11.6),
    # which made every spread/total probability overconfident.
    cal_path = util.abspath(os.path.join(cfg["paths"]["models_dir"], "calibration.json"))
    cal = (util.read_json(cal_path) if os.path.exists(cal_path) else {}).get(league, {})
    if cal.get("n", 0) >= 100:
        for k in ("sigma_margin", "sigma_total", "home_edge_pts"):
            if cal.get(k):
                aggregates[k] = round(float(cal[k]), 2)
        aggregates["calibrated"] = True
    return out, aggregates


_STAT_KEYS = ("pts", "reb", "ast", "fg3m", "fgm", "ftm", "stl", "blk", "tov")


def _player_logs(cfg: dict, league: str) -> dict[str, list[dict]]:
    """{playerId: [game lines, chronological]} from the game-log cache."""
    from . import gamelogs
    cache = gamelogs.load(cfg, league)
    by_player: dict[str, list] = {}
    for gid, g in cache.items():
        for tid, lines in (g.get("teams") or {}).items():
            for ln in lines:
                by_player.setdefault(ln["id"], []).append({**ln, "date": g.get("date", "")})
    for pid in by_player:
        by_player[pid].sort(key=lambda x: x["date"])
    return by_player


def _recency_rates(logs: list[dict], halflife: float) -> tuple[dict, float, float]:
    """Recency-weighted per-game rates + minutes over a player's game log.
    Weight halves every ``halflife`` games (most recent game = weight 1)."""
    n = len(logs)
    wsum = 0.0
    acc = {k: 0.0 for k in _STAT_KEYS}
    macc = 0.0
    for i, ln in enumerate(logs):
        w = 0.5 ** ((n - 1 - i) / halflife)
        wsum += w
        macc += w * ln["min"]
        for k in _STAT_KEYS:
            acc[k] += w * ln.get(k, 0.0)
    rates = {k: acc[k] / wsum for k in _STAT_KEYS}
    return rates, macc / wsum, wsum


def build_player_profiles(cfg: dict, league: str) -> dict:
    """Per-game rate profiles. With game logs available the rates and the
    projected minutes are RECENCY-WEIGHTED (halflife features.log_halflife_games
    games) and shrunk toward the season averages — a player's role change or
    hot/cold stretch flows into the props instead of being averaged away.
    Falls back to plain season averages where no logs exist (NBL)."""
    players_path = util.abspath(f"data/raw/players-{league}.json")
    players = util.read_json(players_path) if os.path.exists(players_path) else {}
    min_g = cfg["features"]["min_player_games"]
    half = float(cfg["features"].get("log_halflife_games", 10))
    prior = float(cfg["features"].get("log_prior_games", 4))
    logs_by_player = _player_logs(cfg, league)
    out = {}
    for pid, p in players.items():
        gp, mins = p.get("gp", 0), p.get("min", 0.0)
        if gp < min_g or mins < 1.0:
            continue
        season_pg = {k: p.get(k, 0.0) for k in _STAT_KEYS}
        use_min, pg, src = mins, season_pg, "season"
        dd_rate = p.get("dd", 0.0) / gp if gp else 0.0
        td_rate = p.get("td", 0.0) / gp if gp else 0.0
        logs = logs_by_player.get(pid) or []
        if len(logs) >= 3:
            rates, rmin, n_eff = _recency_rates(logs, half)
            w = n_eff / (n_eff + prior)     # shrink recency toward season average
            pg = {k: w * rates[k] + (1 - w) * season_pg[k] for k in _STAT_KEYS}
            use_min = w * rmin + (1 - w) * mins
            src = "logs"
            # double/triple-double rates measured off the logs
            cats = [("pts",), ("reb",), ("ast",), ("stl",), ("blk",)]
            dd_n = td_n = 0
            for ln in logs:
                tens = sum(1 for (k,) in cats if ln.get(k, 0.0) >= 10)
                dd_n += 1 if tens >= 2 else 0
                td_n += 1 if tens >= 3 else 0
            dd_rate = dd_n / len(logs)
            td_rate = td_n / len(logs)
        per_min = {k: (pg[k] / use_min if use_min else 0.0) for k in _STAT_KEYS}
        out[pid] = {
            "id": pid, "name": p.get("name", ""), "teamAbbr": p.get("teamAbbr", ""),
            "teamId": p.get("teamId", ""), "gp": gp, "min": round(use_min, 1),
            "season_min": round(mins, 1), "rates_source": src,
            "pg": {k: round(pg[k], 3) for k in _STAT_KEYS},
            "per_min": {k: round(v, 5) for k, v in per_min.items()},
            "dd_rate": round(dd_rate, 3),
            "td_rate": round(td_rate, 3),
        }
    return out


def build_opponent_factors(cfg: dict, league: str) -> dict:
    """Per-team matchup factors: how much of each stat a defence allows
    relative to the league, from the game logs. factor > 1 = allows more.
    Shrunk toward 1.0 by games played."""
    from . import gamelogs
    cache = gamelogs.load(cfg, league)
    if not cache:
        return {}
    prior = float(cfg["features"].get("opp_factor_prior_games", 12))
    keys = ("pts", "reb", "ast", "fg3m")
    allowed: dict[str, dict] = {}
    for gid, g in cache.items():
        teams = list((g.get("teams") or {}).items())
        if len(teams) != 2:
            continue
        for (tid, _), (opp_tid, opp_lines) in ((teams[0], teams[1]), (teams[1], teams[0])):
            tot = {k: sum(ln.get(k, 0.0) for ln in opp_lines) for k in keys}
            d = allowed.setdefault(tid, {"g": 0, **{k: 0.0 for k in keys}})
            d["g"] += 1
            for k in keys:
                d[k] += tot[k]
    lg = {k: (sum(d[k] for d in allowed.values())
              / max(1, sum(d["g"] for d in allowed.values()))) for k in keys}
    out = {}
    for tid, d in allowed.items():
        g = d["g"]
        w = g / (g + prior)
        out[tid] = {k: round(1.0 + w * ((d[k] / g) / lg[k] - 1.0), 4) if lg[k] else 1.0
                    for k in keys}
    return out


def build(cfg: dict) -> dict:
    profiles = {}
    for league in cfg["leagues"]:
        if not os.path.exists(util.abspath(f"data/raw/teams-{league}.json")):
            util.log(f"features[{league}]: no ingest cache — skipping")
            continue
        teams, agg = build_team_profiles(cfg, league)
        players = build_player_profiles(cfg, league)
        for tid, f in build_opponent_factors(cfg, league).items():
            if tid in teams:
                teams[tid]["opp_allow"] = f
        n_logs = sum(1 for p in players.values() if p.get("rates_source") == "logs")
        profiles[league] = {"league": agg, "teams": teams, "players": players}
        util.log(f"features[{league}]: {len(teams)} teams, {len(players)} players "
                 f"({n_logs} log-based) (lg {agg['ppg']} ppg, pace {agg['pace']})")
    path = util.abspath(os.path.join(cfg["paths"]["models_dir"], "profiles.json"))
    # Preserve any league that wasn't rebuilt this run (a partial --league run, or a
    # full run where a network-walled league — e.g. WNBA from a cloud CI IP — yielded
    # no data) by merging fresh output over the previously published file.
    fresh = [lg for lg in (cfg.get("_all_leagues") or cfg["leagues"]) if lg in profiles]
    if util.should_merge(cfg, profiles):
        profiles = util.merge_existing(path, profiles, fresh)
    util.write_json(path, profiles)
    return profiles


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    build(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
