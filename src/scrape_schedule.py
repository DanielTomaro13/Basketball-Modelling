"""Scrape stage — upcoming fixtures per league into ``data/fixtures.csv``.

NBA: the ESPN scoreboard for today .. today+days_ahead. NBL: the rosetta match
feed (wired in the NBL branch). Off-season both simply return nothing — the
pipeline then prices the model's featured matchups instead.
"""
from __future__ import annotations

import csv
import datetime
import os
import sys

from . import util


def _dates(days_ahead: int) -> list[str]:
    today = datetime.date.today()
    return [(today + datetime.timedelta(days=d)).strftime("%Y%m%d") for d in range(days_ahead + 1)]


def _espn_upcoming(cfg: dict, league: str) -> list[dict]:
    site = cfg[league]["espn_site"]
    out, seen = [], set()
    for ymd in _dates(cfg["fixtures"]["days_ahead"]):
        data = util.http_get_json(f"{site}/scoreboard?dates={ymd}", pause=0.05)
        for ev in (data or {}).get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            state = comp.get("status", {}).get("type", {}).get("state")
            if state not in ("pre", "in"):          # only un-played games
                continue
            gid = str(ev.get("id"))
            if gid in seen:
                continue
            home = away = None
            for c in comp.get("competitors", []):
                rec = {"id": str(c["team"]["id"]), "abbr": c["team"].get("abbreviation", "")}
                if c.get("homeAway") == "home":
                    home = rec
                else:
                    away = rec
            if not home or not away:
                continue
            seen.add(gid)
            out.append({"league": league, "gameId": gid, "date": (ev.get("date") or "")[:10],
                        "homeId": home["id"], "awayId": away["id"],
                        "homeAbbr": home["abbr"], "awayAbbr": away["abbr"]})
    return out


def _rosetta_upcoming(cfg: dict, league: str) -> list[dict]:
    base = cfg[league]["rosetta_base"]
    hdrs = {"Origin": "https://nbl.com.au", "Referer": "https://nbl.com.au/"}
    today = datetime.date.today().isoformat()
    out, seen = [], set()
    for season in (cfg[league]["season"], int(cfg[league]["season"]) + 1):
        data = util.http_get_json(f"{base}/nbl/matches/in/season/{season}/{cfg[league]['season_type']}",
                                  headers=hdrs, pause=0.05)
        for m in (data or {}).get("data", []) if isinstance(data, dict) else []:
            if str(m.get("match_status", "")).lower() == "complete":
                continue
            date = (m.get("start_time") or "")[:10]
            if date < today:
                continue
            ht, at = m.get("home_team") or {}, m.get("away_team") or {}
            gid = str(m.get("id"))
            if not ht.get("id") or not at.get("id") or gid in seen:
                continue
            seen.add(gid)
            out.append({"league": league, "gameId": gid, "date": date,
                        "homeId": ht["id"], "awayId": at["id"],
                        "homeAbbr": ht.get("team_code", ""), "awayAbbr": at.get("team_code", "")})
    return out


def scrape(cfg: dict) -> list[dict]:
    rows = []
    for league in cfg["leagues"]:
        src = cfg[league]["source"]
        try:
            if src == "espn":
                got = _espn_upcoming(cfg, league)
            elif src == "rosetta":
                got = _rosetta_upcoming(cfg, league)
            else:
                got = []
            util.log(f"scrape[{league}]: {len(got)} upcoming")
            rows.extend(got)
        except Exception as exc:  # noqa: BLE001
            util.log(f"scrape[{league}]: failed ({exc})")
    return rows


def write_csv(path: str, rows: list[dict]) -> None:
    cols = ["league", "gameId", "date", "homeId", "awayId", "homeAbbr", "awayAbbr"]
    util.ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    rows = scrape(cfg)
    write_csv(util.abspath("data/fixtures.csv"), rows)
    util.log(f"scrape: wrote {len(rows)} fixtures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
