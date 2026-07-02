"""Predict stage — price every upcoming fixture's full market book + player props.

For each fixture: blend the sim with the team-Elo baseline (inside sim), attach the
full market book, and project props for each side's rotation. Off-season, the model's
featured matchups are priced too so the site always has content. Writes
``reports/predictions.csv`` (flat headline) and ``docs/data/predictions.json``.
"""
from __future__ import annotations

import csv
import datetime
import os
import sys

from . import fixtures as fixmod, ratings, sim, util


def _rotation(profiles: dict, league: str, team: dict, cfg: dict) -> list[dict]:
    players = profiles[league]["players"]
    mine = [p for p in players.values()
            if p.get("teamAbbr") and p["teamAbbr"] == team.get("abbr")]
    mine.sort(key=lambda p: -p.get("min", 0.0))
    floor = cfg["features"]["min_player_minutes"]
    return [p for p in mine if p.get("min", 0) >= floor][:9]


def _team_scale(exp_pts: float, team: dict) -> float:
    base = team.get("pf") or exp_pts
    if not base:
        return 1.0
    return max(0.85, min(1.15, exp_pts / base))


def _clip_f(f, lo=0.92, hi=1.08) -> float:
    return max(lo, min(hi, f or 1.0))


def _stat_scales(team_scale: float, opponent: dict) -> dict:
    """Per-stat matchup scales. Scoring stats keep the team scale (the game
    projection already prices this matchup's scoring environment); rebounds /
    assists / threes also lean on what the OPPONENT'S defence allows for that
    stat (features.build_opponent_factors, from the game logs)."""
    al = (opponent or {}).get("opp_allow") or {}
    root = team_scale ** 0.5
    return {"pts": team_scale, "fgm": team_scale, "fg2m": team_scale, "ftm": team_scale,
            "fg3m": team_scale * _clip_f(al.get("fg3m")),
            "reb": _clip_f(al.get("reb")),
            "ast": root * _clip_f(al.get("ast")),
            "stl": 1.0, "blk": 1.0, "tov": 1.0}


def project_fixture(cfg: dict, fx: dict, profiles: dict, elos: dict, agg_cache: dict) -> dict:
    league = fx["league"]
    home, away = fx["home"], fx["away"]
    agg = profiles[league]["league"]
    elo = elos.get(league)
    elo_wp = ratings.elo_win_prob(elo, home["id"], away["id"]) if elo else None
    g = sim.project_game(home, away, agg, cfg["sim"], elo_wp)

    sh = _team_scale(g["mu_home"], home)
    sa = _team_scale(g["mu_away"], away)
    ssh = _stat_scales(sh, away)   # home players face the away defence
    ssa = _stat_scales(sa, home)
    props = {
        "home": [sim.player_props(p, sh, agg, cfg["sim"], stat_scales=ssh)
                 for p in _rotation(profiles, league, home, cfg)],
        "away": [sim.player_props(p, sa, agg, cfg["sim"], stat_scales=ssa)
                 for p in _rotation(profiles, league, away, cfg)],
    }
    return {
        "league": league, "gameId": fx.get("gameId"), "date": fx.get("date"),
        "featured": bool(fx.get("featured")),
        "home": home["name"], "away": away["name"],
        "homeAbbr": home.get("abbr", ""), "awayAbbr": away.get("abbr", ""),
        "homeId": home["id"], "awayId": away["id"],
        "win_home": g["win_home"], "win_away": g["win_away"],
        "fair_home": g["fair_home"], "fair_away": g["fair_away"],
        "proj_home": g["mu_home"], "proj_away": g["mu_away"],
        "mu_total": g["mu_total"], "mu_margin": g["mu_margin"],
        "markets": g["markets"], "props": props,
    }


def run(cfg: dict) -> list[dict]:
    models = cfg["paths"]["models_dir"]
    profiles = util.read_json(util.abspath(os.path.join(models, "profiles.json")))
    elos = util.read_json(util.abspath(os.path.join(models, "elo.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "elo.json"))) else {}
    boards = util.read_json(util.abspath(os.path.join(models, "ratings.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "ratings.json"))) else {}

    fx = fixmod.load_fixtures(cfg, profiles)
    have = {f["league"] for f in fx}
    # any league without real upcoming games gets featured matchups so it's never empty
    missing = [lg for lg in cfg["leagues"] if lg not in have and lg in profiles]
    if missing:
        fx += fixmod.featured_matchups(cfg, profiles, boards, leagues=missing)
    preds = []
    for f in fx:
        try:
            preds.append(project_fixture(cfg, f, profiles, elos, {}))
        except Exception as exc:  # noqa: BLE001
            util.log(f"predict: skipped {f.get('home',{}).get('abbr')} v "
                     f"{f.get('away',{}).get('abbr')} ({exc})")
    preds.sort(key=lambda p: (p["league"], p.get("date") or "9999", -max(p["win_home"], p["win_away"])))
    return preds


_INDEX_KEYS = ("league", "gameId", "date", "featured", "home", "away", "homeAbbr",
               "awayAbbr", "homeId", "awayId", "win_home", "win_away", "fair_home",
               "fair_away", "proj_home", "proj_away", "mu_total", "mu_margin")


def build(cfg: dict) -> list[dict]:
    preds = run(cfg)
    dd = cfg["paths"]["docs_data_dir"]
    reports = util.ensure_dir(util.abspath(cfg["paths"]["reports_dir"]))
    # Leagues actually priced this run. A configured league missing here (a partial
    # --league run, or a full run where a geo-walled league like WNBA had no data)
    # keeps its previously published fixtures + per-game detail files.
    built_leagues = {p["league"] for p in preds}
    merge = util.should_merge(cfg, {lg: 1 for lg in built_leagues})
    cols = ["league", "date", "home", "away", "win_home", "win_away", "fair_home",
            "fair_away", "proj_home", "proj_away", "mu_total", "featured"]
    with open(f"{reports}/predictions.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(preds)

    # slim index (list views) + one detail file per game (loaded on demand by the modal).
    # When merging, only the rebuilt leagues' detail files are refreshed; others stay put.
    games_dir = util.ensure_dir(util.abspath(os.path.join(dd, "games")))
    for f in os.listdir(games_dir):
        if not f.endswith(".json"):
            continue
        if merge and not any(f.startswith(f"{lg}-") for lg in built_leagues):
            continue
        os.remove(os.path.join(games_dir, f))
    index = []
    for p in preds:
        index.append({k: p.get(k) for k in _INDEX_KEYS})
        util.write_json(os.path.join(games_dir, f"{p['league']}-{p['gameId']}.json"),
                        {"markets": p["markets"], "props": p["props"]})

    pred_path = util.abspath(os.path.join(dd, "predictions.json"))
    if merge and os.path.exists(pred_path):
        prev = util.read_json(pred_path) or {}
        kept = [fx for fx in prev.get("fixtures", []) if fx.get("league") not in built_leagues]
        index = kept + index
    util.write_json(pred_path,
                    {"generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                     "count": len(index), "fixtures": index})
    util.log(f"predict: wrote {len(preds)} predictions")
    for p in preds[:8]:
        util.log(f"  [{p['league']}] {p['awayAbbr']} @ {p['homeAbbr']}  "
                 f"{p['win_home']:.0%}/{p['win_away']:.0%}  {p['proj_home']}-{p['proj_away']}")
    return preds


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    leagues = []
    for i, a in enumerate(argv):
        if a == "--league" and i + 1 < len(argv):
            leagues.append(argv[i + 1].lower())
        elif a.startswith("--league="):
            leagues.append(a.split("=", 1)[1].lower())
    if leagues:
        cfg["_all_leagues"] = list(cfg["leagues"])
        cfg["leagues"] = [lg for lg in cfg["leagues"] if lg in leagues] or cfg["leagues"]
    build(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
