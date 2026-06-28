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

    ids = list(games.keys())
    adj_o = {t: lg_ppg for t in ids}
    adj_d = {t: lg_ppg for t in ids}
    # iterate opponent adjustment: a team's offense = its scoring minus how much the
    # defences it faced differ from average (and remove home edge); symmetric for defence.
    for _ in range(12):
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

    # shrink toward league mean by games played
    prior = cfg["features"]["team_prior_games"]
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
    return out, aggregates


def build_player_profiles(cfg: dict, league: str) -> dict:
    """Per-game + per-minute rate profiles, shrunk for small samples."""
    players_path = util.abspath(f"data/raw/players-{league}.json")
    players = util.read_json(players_path) if os.path.exists(players_path) else {}
    min_g = cfg["features"]["min_player_games"]
    out = {}
    for pid, p in players.items():
        gp, mins = p.get("gp", 0), p.get("min", 0.0)
        if gp < min_g or mins < 1.0:
            continue
        per_min = {k: (p.get(k, 0.0) / mins if mins else 0.0)
                   for k in ("pts", "reb", "ast", "fg3m", "fgm", "ftm", "stl", "blk", "tov")}
        out[pid] = {
            "id": pid, "name": p.get("name", ""), "teamAbbr": p.get("teamAbbr", ""),
            "teamId": p.get("teamId", ""), "gp": gp, "min": round(mins, 1),
            "pg": {k: round(p.get(k, 0.0), 3) for k in
                   ("pts", "reb", "ast", "fg3m", "fgm", "ftm", "stl", "blk", "tov")},
            "per_min": {k: round(v, 5) for k, v in per_min.items()},
            "dd_rate": round(p.get("dd", 0.0) / gp, 3) if gp else 0.0,
            "td_rate": round(p.get("td", 0.0) / gp, 3) if gp else 0.0,
        }
    return out


def build(cfg: dict) -> dict:
    profiles = {}
    for league in cfg["leagues"]:
        if not os.path.exists(util.abspath(f"data/raw/teams-{league}.json")):
            util.log(f"features[{league}]: no ingest cache — skipping")
            continue
        teams, agg = build_team_profiles(cfg, league)
        players = build_player_profiles(cfg, league)
        profiles[league] = {"league": agg, "teams": teams, "players": players}
        util.log(f"features[{league}]: {len(teams)} teams, {len(players)} players "
                 f"(lg {agg['ppg']} ppg, pace {agg['pace']})")
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
