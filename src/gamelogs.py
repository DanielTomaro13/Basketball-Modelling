"""Game logs — per-player box-score lines for every completed game (ESPN leagues).

The season-stats feeds give only season aggregates, so player props were priced
off season averages: no recency weighting, no minutes trend, no matchup factor.
This stage accumulates real per-game lines incrementally: each run fetches the
box scores of games that are in the results file but not yet in the cache
(``data/raw/gamelogs-{league}-{season}.json``), so the first run backfills the
season and every later run only touches the new games.

Cache shape: {gameId: {"date": d, "teams": {teamId: [{player line}, ...]}}}
Line keys: id, name, pos, min, pts, reb, ast, fg3m, fgm, ftm, stl, blk, tov.

NBL note: the rosetta API 403s every per-match stats route we probed, so the
NBL keeps season-average props until a box-score source exists for it.
"""
from __future__ import annotations

import csv
import os
import sys

from . import util


def _made(s: str) -> float:
    """'10-21' -> 10.0"""
    try:
        return float(str(s).split("-")[0])
    except (ValueError, IndexError):
        return 0.0


def _num(s) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def _parse_box(data: dict) -> dict:
    """ESPN summary payload -> {teamId: [player lines]}."""
    out: dict[str, list] = {}
    for tblock in (data.get("boxscore", {}) or {}).get("players", []):
        tid = str((tblock.get("team") or {}).get("id", ""))
        stats = (tblock.get("statistics") or [{}])[0]
        labels = stats.get("labels") or []
        idx = {lab: i for i, lab in enumerate(labels)}
        lines = []
        for a in stats.get("athletes", []):
            ath = a.get("athlete") or {}
            vals = a.get("stats") or []
            if not vals or len(vals) < len(labels):
                continue  # DNP rows come through with empty stats

            def v(lab):
                return vals[idx[lab]] if lab in idx else ""

            mins = _num(v("MIN"))
            if mins <= 0:
                continue
            lines.append({
                "id": str(ath.get("id", "")),
                "name": ath.get("displayName", ""),
                "pos": (ath.get("position") or {}).get("abbreviation", ""),
                "min": mins,
                "pts": _num(v("PTS")), "reb": _num(v("REB")), "ast": _num(v("AST")),
                "fg3m": _made(v("3PT")), "fgm": _made(v("FG")), "ftm": _made(v("FT")),
                "stl": _num(v("STL")), "blk": _num(v("BLK")), "tov": _num(v("TO")),
            })
        if tid and lines:
            out[tid] = lines
    return out


def _results_rows(cfg: dict, league: str, season) -> list[dict]:
    path = util.abspath(f"data/processed/results-{league}-{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def cache_path(league: str, season) -> str:
    return util.abspath(f"data/raw/gamelogs-{league}-{season}.json")


def load(cfg: dict, league: str, season=None) -> dict:
    season = season or cfg[league]["season"]
    path = cache_path(league, season)
    return util.read_json(path) if os.path.exists(path) else {}


def sync_league(cfg: dict, league: str, max_new: int | None = None) -> int:
    """Fetch box scores for completed games missing from the cache. Returns
    the number of new games fetched."""
    if cfg[league].get("source") != "espn":
        util.log(f"gamelogs[{league}]: no box-score source — skipping")
        return 0
    season = cfg[league]["season"]
    site = cfg[league]["espn_site"]
    rows = _results_rows(cfg, league, season)
    if not rows:
        return 0
    cache = load(cfg, league, season)
    missing = [r for r in rows if r["gameId"] not in cache]
    if max_new is not None:
        missing = missing[:max_new]
    fetched = 0
    for r in missing:
        gid = r["gameId"]
        data = util.http_get_json(f"{site}/summary?event={gid}", pause=0.05)
        if not data:
            continue
        teams = _parse_box(data)
        if teams:
            cache[gid] = {"date": r.get("date", ""), "teams": teams}
            fetched += 1
    if fetched:
        util.write_json(cache_path(league, season), cache)
    util.log(f"gamelogs[{league}]: {len(cache)} games cached (+{fetched} new)")
    return fetched


def sync(cfg: dict) -> None:
    for league in cfg["leagues"]:
        try:
            sync_league(cfg, league)
        except Exception as exc:  # noqa: BLE001
            util.log(f"gamelogs[{league}]: sync failed ({exc})")


def main(argv: list[str]) -> int:
    sync(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
