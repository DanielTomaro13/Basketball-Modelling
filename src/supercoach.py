"""SuperCoach stage — fantasy projections, prices and ownership (NBA + NBL).

Pulls the public News Corp / Champion Data SuperCoach feed (anonymous, not
geo-blocked, so it runs in CI) for each league and writes a fantasy card per
player: price, season average (the projection — SuperCoach posts no ``ppts1`` for
basketball), ownership, positions and a value metric (points per $1M). Output:
``docs/data/fantasy-{league}.json``.
"""
from __future__ import annotations

import os
import sys

from . import util

_BASE = "https://www.supercoach.com.au/{year}/api/{sport}/classic/v1/{path}"
_HDRS = {"Accept": "application/json"}


def _get(year, sport: str, path: str):
    return util.http_get_json(_BASE.format(year=year, sport=sport, path=path), headers=_HDRS,
                              timeout=40, pause=0.1)


def build_league(cfg: dict, league: str) -> dict:
    year = cfg[league].get("supercoach_year", cfg[league]["season"])
    settings = _get(year, league, "settings?min=false") or {}
    rnd = (settings.get("competition") or {}).get("current_round")
    data = _get(year, league, "players-cf?embed=positions,player_stats")
    if not isinstance(data, list):
        return {}
    players = []
    for p in data:
        ps = (p.get("player_stats") or [{}])[0]
        price = util.num(ps.get("price"))
        avg = util.num(ps.get("avg"))
        if price <= 0 and avg <= 0:
            continue
        team = p.get("team") or {}
        pos = [x.get("position") for x in (p.get("positions") or []) if x.get("position")]
        value = round(avg / (price / 1_000_000), 2) if price > 0 else None   # pts per $1M
        players.append({
            "id": str(p.get("id")), "name": f"{p.get('first_name','')} {p.get('last_name','')}".strip(),
            "team": team.get("abbrev", ""), "pos": pos,
            "price": int(price), "proj": round(avg, 1), "avg": round(avg, 1),
            "avg3": round(util.num(ps.get("avg3")), 1), "avg5": round(util.num(ps.get("avg5")), 1),
            "owned": round(util.num(ps.get("owned")), 1),
            "value": value, "gp": int(util.num(ps.get("total_games"))),
            "price_change": int(util.num(ps.get("price_change"))),
            "status": (p.get("played_status") or {}).get("status", ""),
        })
    players.sort(key=lambda x: -x["avg"])
    return {"round": rnd, "count": len(players), "players": players}


def build(cfg: dict) -> dict:
    out = {}
    for league in cfg["leagues"]:
        try:
            res = build_league(cfg, league)
        except Exception as exc:  # noqa: BLE001
            util.log(f"supercoach[{league}]: failed ({exc})")
            res = {}
        if res:
            util.write_json(util.abspath(os.path.join(cfg["paths"]["docs_data_dir"], f"fantasy-{league}.json")),
                            {"generated": _now(), **res})
            out[league] = res.get("count", 0)
            util.log(f"supercoach[{league}]: {res.get('count', 0)} players (round {res.get('round')})")
    return out


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str]) -> int:
    build(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
