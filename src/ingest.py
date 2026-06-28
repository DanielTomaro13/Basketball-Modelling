"""Ingest stage — download + cache public basketball stats per league.

NBA is sourced from the ESPN public JSON API (anonymous, cloud-reachable). NBL is
sourced from the nbl.com.au "rosetta" data API (added in the NBL branch). WNBA is
sourced from the WNBA stats API (stats.wnba.com — the stats.nba.com family with
LeagueID=10 and single-calendar-year seasons). Outputs:

* ``data/raw/teams-{league}.json``        team id -> {abbr, name}
* ``data/raw/teamstats-{league}.json``    team id -> season pace/shooting rates
* ``data/raw/players-{league}.json``      player id -> season per-game rate line
* ``data/processed/results-{league}-{season}.csv``   final scores (Elo + backtest)
"""
from __future__ import annotations

import csv
import os
import sys

from . import util


# --------------------------------------------------------------------------- #
# Per-league HTTP headers
# --------------------------------------------------------------------------- #
def _headers(cfg: dict, league: str) -> dict:
    src = cfg[league]["source"]
    if src == "rosetta":
        return {"Origin": "https://nbl.com.au", "Referer": "https://nbl.com.au/"}
    if src == "stats":
        # stats.wnba.com / stats.nba.com need a browser-ish header bundle.
        return {"Referer": "https://www.wnba.com/", "Origin": "https://www.wnba.com",
                "x-nba-stats-origin": "stats", "x-nba-stats-token": "true",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9", "Connection": "keep-alive"}
    return {}


# --------------------------------------------------------------------------- #
# ESPN (NBA)
# --------------------------------------------------------------------------- #
def _espn_teams(cfg: dict, league: str) -> dict:
    site = cfg[league]["espn_site"]
    data = util.http_get_json(f"{site}/teams", pause=0.05) or {}
    out = {}
    try:
        teams = data["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError):
        teams = []
    for t in teams:
        tm = t["team"]
        out[str(tm["id"])] = {"id": str(tm["id"]), "abbr": tm.get("abbreviation", ""),
                              "name": tm.get("displayName", "")}
    return out


def _espn_results(cfg: dict, league: str, season: int, teams: dict) -> list[dict]:
    """Dedup every team's schedule into league-wide final scores for one season."""
    site = cfg[league]["espn_site"]
    stype = cfg[league]["season_type"]
    seen: dict[str, dict] = {}
    for tid in teams:
        url = f"{site}/teams/{tid}/schedule?season={season}&seasontype={stype}"
        data = util.http_get_json(url, pause=0.04)
        for ev in (data or {}).get("events", []):
            comps = ev.get("competitions", [{}])
            comp = comps[0] if comps else {}
            status = comp.get("status", {}).get("type", {})
            if not status.get("completed"):
                continue
            gid = str(ev.get("id"))
            if gid in seen:
                continue
            home = away = None
            for c in comp.get("competitors", []):
                score = c.get("score", {})
                pts = score.get("value") if isinstance(score, dict) else score
                rec = {"id": str(c["team"]["id"]), "abbr": c["team"].get("abbreviation", ""),
                       "pts": util.num(pts)}
                if c.get("homeAway") == "home":
                    home = rec
                else:
                    away = rec
            if not home or not away:
                continue
            seen[gid] = {"gameId": gid, "date": (ev.get("date") or "")[:10], "season": season,
                         "homeId": home["id"], "awayId": away["id"],
                         "homeAbbr": home["abbr"], "awayAbbr": away["abbr"],
                         "homePts": home["pts"], "awayPts": away["pts"]}
    rows = list(seen.values())
    rows.sort(key=lambda r: r["date"])
    return rows


def _espn_team_stats(cfg: dict, league: str, season: int, teams: dict) -> dict:
    """Per-team season pace + shooting rates (per-game) from the core stats endpoint."""
    core = cfg[league]["espn_core"]
    stype = cfg[league]["season_type"]
    want = {"avgPoints", "paceFactor", "avgEstimatedPossessions", "possessions",
            "threePointFieldGoalsAttempted", "freeThrowsAttempted", "fieldGoalsAttempted",
            "turnovers", "offensiveRebounds", "threePointFieldGoalsMade", "avgAssists"}
    out = {}
    for tid in teams:
        url = f"{core}/seasons/{season}/types/{stype}/teams/{tid}/statistics"
        data = util.http_get_json(url, pause=0.04)
        if not data:
            continue
        flat = {}
        for cat in data.get("splits", {}).get("categories", []):
            for s in cat.get("stats", []):
                if s.get("name") in want:
                    flat[s["name"]] = {"value": util.num(s.get("value")),
                                       "per_game": util.num(s.get("perGameValue"))}
        if flat:
            out[tid] = flat
    return out


# offensive/defensive/general label order is provided per category in the payload,
# so we zip names->values to read by stat name.
def _espn_players(cfg: dict, league: str, season: int, abbr2id: dict) -> dict:
    """All players' season per-game rates via the paginated byathlete endpoint."""
    site = cfg[league]["espn_site"]
    stype = cfg[league]["season_type"]
    base = (f"{site.replace('/site/v2/', '/common/v3/')}/statistics/byathlete"
            f"?season={season}&seasontype={stype}&limit=50")
    out: dict[str, dict] = {}
    schema: dict[str, list] = {}   # category name -> ordered stat labels (top-level glossary)
    page, pages = 1, 1
    while page <= pages and page <= 60:
        data = util.http_get_json(f"{base}&page={page}", retries=4, pause=0.05)
        if not data:
            page += 1           # transient page error (ESPN 504s intermittently) — skip, keep going
            continue
        pages = (data.get("pagination") or {}).get("pages", 1)
        if not schema:
            schema = {c.get("name"): (c.get("names") or []) for c in data.get("categories", [])}
        for a in data.get("athletes", []):
            ath = a.get("athlete", {})
            pid = str(ath.get("id"))
            if not pid or pid == "None":
                continue
            flat = {}
            for cat in a.get("categories", []):
                names = schema.get(cat.get("name")) or cat.get("names") or []
                vals = cat.get("values") or []
                for nm, v in zip(names, vals):
                    flat[nm] = v
            abbr = ath.get("teamShortName", "")
            out[pid] = {
                "id": pid, "name": ath.get("displayName", ""),
                "teamAbbr": abbr, "teamId": abbr2id.get(abbr, ""),
                "gp": util.num(flat.get("gamesPlayed")),
                "min": util.num(flat.get("avgMinutes")),
                "pts": util.num(flat.get("avgPoints")),
                "reb": util.num(flat.get("avgRebounds")),
                "ast": util.num(flat.get("avgAssists")),
                "fg3m": util.num(flat.get("avgThreePointFieldGoalsMade")),
                "fgm": util.num(flat.get("avgFieldGoalsMade")),
                "ftm": util.num(flat.get("avgFreeThrowsMade")),
                "stl": util.num(flat.get("avgSteals")),
                "blk": util.num(flat.get("avgBlocks")),
                "tov": util.num(flat.get("avgTurnovers")),
                "dd": util.num(flat.get("doubleDouble")),
                "td": util.num(flat.get("tripleDouble")),
            }
        page += 1
    return out


# --------------------------------------------------------------------------- #
# Rosetta (NBL)
# --------------------------------------------------------------------------- #
def _rosetta_get(cfg: dict, league: str, route: str) -> list:
    base = cfg[league]["rosetta_base"]
    data = util.http_get_json(f"{base}/{route}", headers=_headers(cfg, league), pause=0.05)
    payload = (data or {}).get("data") if isinstance(data, dict) else None
    return payload if isinstance(payload, list) else []


def _nbl_season_uuid(cfg: dict, league: str, year) -> str | None:
    for s in _rosetta_get(cfg, league, "nbl/seasons"):
        if s.get("season_type") == "regular" and str(s.get("year")) == str(year):
            return s.get("id")
    return None


def _rosetta_results(cfg: dict, league: str, season) -> list[dict]:
    stype = cfg[league]["season_type"]
    rows = []
    for m in _rosetta_get(cfg, league, f"nbl/matches/in/season/{season}/{stype}"):
        hp, ap = util.num(m.get("home_score")), util.num(m.get("away_score"))
        if hp <= 0 or ap <= 0:
            continue
        ht, at = m.get("home_team") or {}, m.get("away_team") or {}
        if not ht.get("id") or not at.get("id"):
            continue
        rows.append({"gameId": str(m.get("id")), "date": (m.get("start_time") or "")[:10],
                     "season": season, "homeId": ht["id"], "awayId": at["id"],
                     "homeAbbr": ht.get("team_code", ""), "awayAbbr": at.get("team_code", ""),
                     "homePts": hp, "awayPts": ap})
    rows.sort(key=lambda r: r["date"])
    return rows


def _rosetta_team_stats(cfg: dict, league: str, season) -> tuple[dict, dict]:
    """Return (teams, team-stats) from the full-game (period 0) rows."""
    stype = cfg[league]["season_type"]
    teams, stats = {}, {}
    for r in _rosetta_get(cfg, league, f"nbl/team/stats/for/season/{season}/{stype}"):
        if str(r.get("period")) != "0":
            continue
        tm = r.get("team") or {}
        tid = tm.get("id")
        if not tid:
            continue
        teams[tid] = {"id": tid, "abbr": tm.get("team_code", ""), "name": tm.get("name", "")}
        fga = util.num(r.get("field_goals_attempted_average"))
        fta = util.num(r.get("free_throws_attempted_average"))
        tov = util.num(r.get("turnovers_average"))
        oreb = util.num(r.get("offensive_rebounds_average"))
        poss = fga - oreb + tov + 0.44 * fta
        stats[tid] = {"paceFactor": {"value": round(poss, 2)},
                      "avgPoints": {"value": util.num(r.get("points_average"))}}
    return teams, stats


def _rosetta_players(cfg: dict, league: str, season) -> dict:
    sid = _nbl_season_uuid(cfg, league, season)
    if not sid:
        return {}
    out = {}
    for r in _rosetta_get(cfg, league, f"nbl/stats/leaders/for/season/id/{sid}?limit=500"):
        pl, tm = r.get("player") or {}, r.get("team") or {}
        pid = pl.get("id")
        if not pid:
            continue
        name = f"{pl.get('first_name', '')} {pl.get('last_name', '')}".strip()
        out[pid] = {
            "id": pid, "name": name, "teamAbbr": tm.get("team_code", ""), "teamId": tm.get("id", ""),
            "gp": util.num(r.get("games")), "min": util.num(r.get("minutes_average")),
            "pts": util.num(r.get("points_average")), "reb": util.num(r.get("rebounds_average")),
            "ast": util.num(r.get("assists_average")), "fg3m": util.num(r.get("three_points_made_average")),
            "fgm": util.num(r.get("field_goals_made_average")), "ftm": util.num(r.get("free_throws_made_average")),
            "stl": util.num(r.get("steals_average")), "blk": util.num(r.get("blocks_average")),
            "tov": util.num(r.get("turnovers_average")), "dd": 0.0, "td": 0.0,
        }
    return out


# --------------------------------------------------------------------------- #
# WNBA stats API (stats.wnba.com — the stats.nba.com family, LeagueID=10)
# Endpoints return {"resultSets": [{"name", "headers", "rowSet": [[...]]}]}.
# Seasons are single calendar years ("2025"), not spans.
# --------------------------------------------------------------------------- #
# Static team meta so tricodes are stable even if a feed omits the abbreviation;
# the numeric team ids come from the live feed and are matched in by tricode.
_WNBA_TEAMS = {
    "ATL": "Atlanta Dream", "CHI": "Chicago Sky", "CON": "Connecticut Sun",
    "DAL": "Dallas Wings", "GSV": "Golden State Valkyries", "IND": "Indiana Fever",
    "LVA": "Las Vegas Aces", "LAS": "Los Angeles Sparks", "MIN": "Minnesota Lynx",
    "NYL": "New York Liberty", "PHO": "Phoenix Mercury", "SEA": "Seattle Storm",
    "WAS": "Washington Mystics",
    "TOR": "Toronto Tempo", "PDX": "Portland Fire",  # 2026 expansion
}

# stats.wnba.com (Akamai) throttles ~1 req / 2.5s; hammering faster gets the IP
# black-holed (read timeouts). Tunable via STATS_PAUSE for slower/faster links.
_STATS_PAUSE = float(os.environ.get("STATS_PAUSE", "2.5"))


def _stats_get(cfg: dict, league: str, endpoint: str, params: dict):
    """GET a stats endpoint and return its resultSets list (name -> {headers, rowSet})."""
    base = cfg[league]["stats_base"]
    qs = util_urlencode(params)
    data = util.http_get_json(f"{base}/{endpoint}?{qs}", headers=_headers(cfg, league), pause=_STATS_PAUSE, retries=4)
    sets = {}
    for rs in (data or {}).get("resultSets", []) if isinstance(data, dict) else []:
        sets[rs.get("name", "")] = {"headers": rs.get("headers", []), "rowSet": rs.get("rowSet", [])}
    # some endpoints return a single dict under "resultSet"
    rs = (data or {}).get("resultSet") if isinstance(data, dict) else None
    if isinstance(rs, dict) and rs.get("name"):
        sets[rs["name"]] = {"headers": rs.get("headers", []), "rowSet": rs.get("rowSet", [])}
    return sets


def util_urlencode(params: dict) -> str:
    import urllib.parse
    return urllib.parse.urlencode(params)


def _rows(rset: dict) -> list[dict]:
    """Zip a resultSet's headers with each row into dicts."""
    hdrs = rset.get("headers", [])
    return [dict(zip(hdrs, row)) for row in rset.get("rowSet", [])]


def _abbr_for(name: str, tricode: str) -> str:
    """Resolve a stable tricode for a WNBA team from its feed tricode or full name."""
    if tricode and tricode.upper() in _WNBA_TEAMS:
        return tricode.upper()
    nm = (name or "").lower()
    for ab, full in _WNBA_TEAMS.items():
        last = full.split()[-1].lower()
        if full.lower() in nm or (len(last) >= 4 and last in nm):
            return ab
    return (tricode or "").upper()


def _stats_team_stats(cfg: dict, league: str, season) -> tuple[dict, dict]:
    """Return (teams, team-stats) from leaguedashteamstats (per-game + advanced pace)."""
    base_p = {"LeagueID": cfg[league]["league_id"], "Season": str(season),
              "SeasonType": cfg[league]["season_type"], "PerMode": "PerGame",
              "MeasureType": "Base", "PaceAdjust": "N", "PlusMinus": "N", "Rank": "N",
              "Outcome": "", "Location": "", "Month": "0", "SeasonSegment": "",
              "DateFrom": "", "DateTo": "", "OpponentTeamID": "0", "VsConference": "",
              "VsDivision": "", "GameSegment": "", "Period": "0", "LastNGames": "0",
              "TeamID": "0", "Conference": "", "Division": "", "GameScope": "",
              "PlayerExperience": "", "PlayerPosition": "", "StarterBench": "",
              "TwoWay": "0", "ShotClockRange": ""}
    base = _stats_get(cfg, league, "leaguedashteamstats", base_p)
    adv = _stats_get(cfg, league, "leaguedashteamstats", {**base_p, "MeasureType": "Advanced"})
    teams, stats = {}, {}
    pace_by_id = {r.get("TEAM_ID"): util.num(r.get("PACE")) for r in _rows(adv.get("LeagueDashTeamStats", {}))}
    for r in _rows(base.get("LeagueDashTeamStats", {})):
        tid = r.get("TEAM_ID")
        if tid is None:
            continue
        tid = str(tid)
        name = r.get("TEAM_NAME", "")
        abbr = _abbr_for(name, r.get("TEAM_ABBREVIATION", ""))
        teams[tid] = {"id": tid, "abbr": abbr, "name": _WNBA_TEAMS.get(abbr, name)}
        fga = util.num(r.get("FGA")); fta = util.num(r.get("FTA"))
        tov = util.num(r.get("TOV")); oreb = util.num(r.get("OREB"))
        pace = pace_by_id.get(r.get("TEAM_ID")) or (fga - oreb + tov + 0.44 * fta)
        stats[tid] = {
            "paceFactor": {"value": round(pace, 2)},
            "avgPoints": {"value": util.num(r.get("PTS"))},
            "avgAssists": {"value": util.num(r.get("AST"))},
            "fieldGoalsAttempted": {"per_game": round(fga, 1)},
            "freeThrowsAttempted": {"per_game": round(fta, 1)},
            "offensiveRebounds": {"per_game": round(oreb, 1)},
            "turnovers": {"per_game": round(tov, 1)},
            "threePointFieldGoalsAttempted": {"per_game": round(util.num(r.get("FG3A")), 1)},
            "threePointFieldGoalsMade": {"per_game": round(util.num(r.get("FG3M")), 1)},
        }
    return teams, stats


def _stats_players(cfg: dict, league: str, season, teams: dict) -> dict:
    """All players' season per-game rates via leaguedashplayerstats (PerGame)."""
    p = {"LeagueID": cfg[league]["league_id"], "Season": str(season),
         "SeasonType": cfg[league]["season_type"], "PerMode": "PerGame",
         "MeasureType": "Base", "PaceAdjust": "N", "PlusMinus": "N", "Rank": "N",
         "Outcome": "", "Location": "", "Month": "0", "SeasonSegment": "",
         "DateFrom": "", "DateTo": "", "OpponentTeamID": "0", "VsConference": "",
         "VsDivision": "", "GameSegment": "", "Period": "0", "LastNGames": "0",
         "TeamID": "0", "Conference": "", "Division": "", "GameScope": "",
         "PlayerExperience": "", "PlayerPosition": "", "StarterBench": "",
         "TwoWay": "0", "ShotClockRange": ""}
    sets = _stats_get(cfg, league, "leaguedashplayerstats", p)
    out = {}
    for r in _rows(sets.get("LeagueDashPlayerStats", {})):
        pid = r.get("PLAYER_ID")
        if pid is None:
            continue
        pid = str(pid)
        tid = str(r.get("TEAM_ID")) if r.get("TEAM_ID") is not None else ""
        abbr = (teams.get(tid, {}) or {}).get("abbr") or _abbr_for(r.get("TEAM_ABBREVIATION", ""), r.get("TEAM_ABBREVIATION", ""))
        out[pid] = {
            "id": pid, "name": r.get("PLAYER_NAME", ""), "teamAbbr": abbr, "teamId": tid,
            "gp": util.num(r.get("GP")), "min": util.num(r.get("MIN")),
            "pts": util.num(r.get("PTS")), "reb": util.num(r.get("REB")),
            "ast": util.num(r.get("AST")), "fg3m": util.num(r.get("FG3M")),
            "fgm": util.num(r.get("FGM")), "ftm": util.num(r.get("FTM")),
            "stl": util.num(r.get("STL")), "blk": util.num(r.get("BLK")),
            "tov": util.num(r.get("TOV")), "dd": util.num(r.get("DD2")),
            "td": util.num(r.get("TD3")),
        }
    return out


def _stats_results(cfg: dict, league: str, season, teams: dict) -> list[dict]:
    """League-wide final scores for one season from leaguegamelog (one row per team-game)."""
    p = {"LeagueID": cfg[league]["league_id"], "Season": str(season),
         "SeasonType": cfg[league]["season_type"], "PlayerOrTeam": "T",
         "Counter": "1000", "Sorter": "DATE", "Direction": "ASC", "DateFrom": "", "DateTo": ""}
    sets = _stats_get(cfg, league, "leaguegamelog", p)
    abbr_by_id = {tid: t.get("abbr", "") for tid, t in teams.items()}
    by_game: dict[str, dict] = {}
    for r in _rows(sets.get("LeagueGameLog", {})):
        gid = str(r.get("GAME_ID"))
        tid = str(r.get("TEAM_ID"))
        matchup = r.get("MATCHUP", "") or ""
        is_home = " vs. " in matchup            # "ATL vs. CHI" = home; "ATL @ CHI" = away
        rec = {"id": tid, "abbr": abbr_by_id.get(tid) or _abbr_for(r.get("TEAM_NAME", ""), r.get("TEAM_ABBREVIATION", "")),
               "pts": util.num(r.get("PTS")), "date": (r.get("GAME_DATE") or "")[:10], "home": is_home}
        by_game.setdefault(gid, {})[("home" if is_home else "away")] = rec
    rows = []
    for gid, sides in by_game.items():
        home, away = sides.get("home"), sides.get("away")
        if not home or not away or home["pts"] <= 0 or away["pts"] <= 0:
            continue
        rows.append({"gameId": gid, "date": home["date"] or away["date"], "season": season,
                     "homeId": home["id"], "awayId": away["id"],
                     "homeAbbr": home["abbr"], "awayAbbr": away["abbr"],
                     "homePts": home["pts"], "awayPts": away["pts"]})
    rows.sort(key=lambda r: r["date"])
    return rows


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _raw_path(name: str) -> str:
    return util.abspath(os.path.join("data/raw", name))


def _proc_path(name: str) -> str:
    return util.abspath(os.path.join("data/processed", name))


def download_core(cfg: dict) -> None:
    """Fetch teams, team season stats and player season rates for each league (current season)."""
    for league in cfg["leagues"]:
        src = cfg[league]["source"]
        season = cfg[league]["season"]
        if src == "espn":
            teams = _espn_teams(cfg, league)
            if not teams:
                util.log(f"ingest[{league}]: no teams returned — skipping")
                continue
            abbr2id = {t["abbr"]: t["id"] for t in teams.values()}
            tstats = _espn_team_stats(cfg, league, season, teams)
            players = _espn_players(cfg, league, season, abbr2id)
            util.write_json(_raw_path(f"teams-{league}.json"), teams)
            util.write_json(_raw_path(f"teamstats-{league}.json"), tstats)
            util.write_json(_raw_path(f"players-{league}.json"), players)
            util.log(f"ingest[{league}]: {len(teams)} teams, {len(tstats)} team-stat lines, "
                     f"{len(players)} players")
        elif src == "rosetta":
            teams, tstats = _rosetta_team_stats(cfg, league, season)
            players = _rosetta_players(cfg, league, season)
            if not teams:
                util.log(f"ingest[{league}]: no team stats returned — skipping")
                continue
            util.write_json(_raw_path(f"teams-{league}.json"), teams)
            util.write_json(_raw_path(f"teamstats-{league}.json"), tstats)
            util.write_json(_raw_path(f"players-{league}.json"), players)
            util.log(f"ingest[{league}]: {len(teams)} teams, {len(tstats)} team-stat lines, "
                     f"{len(players)} players")
        elif src == "stats":
            teams, tstats = _stats_team_stats(cfg, league, season)
            if not teams:
                util.log(f"ingest[{league}]: no team stats returned — skipping")
                continue
            players = _stats_players(cfg, league, season, teams)
            util.write_json(_raw_path(f"teams-{league}.json"), teams)
            util.write_json(_raw_path(f"teamstats-{league}.json"), tstats)
            util.write_json(_raw_path(f"players-{league}.json"), players)
            util.log(f"ingest[{league}]: {len(teams)} teams, {len(tstats)} team-stat lines, "
                     f"{len(players)} players")
        else:
            util.log(f"ingest[{league}]: unknown source {src!r}")


def derive_results(cfg: dict) -> None:
    """Write final-score CSVs across each league's history seasons (Elo + backtest)."""
    cols = ["gameId", "date", "season", "homeId", "awayId", "homeAbbr", "awayAbbr",
            "homePts", "awayPts"]
    for league in cfg["leagues"]:
        src = cfg[league]["source"]
        teams = {}
        if src in ("espn", "stats"):
            teams_path = _raw_path(f"teams-{league}.json")
            if os.path.exists(teams_path):
                teams = util.read_json(teams_path)
            elif src == "espn":
                teams = _espn_teams(cfg, league)
            else:  # stats
                teams, _ = _stats_team_stats(cfg, league, cfg[league]["season"])
        for season in cfg[league]["history_seasons"]:
            if src == "espn":
                rows = _espn_results(cfg, league, season, teams)
            elif src == "rosetta":
                rows = _rosetta_results(cfg, league, season)
            elif src == "stats":
                rows = _stats_results(cfg, league, season, teams)
            else:
                rows = []
            if not rows:
                util.log(f"ingest[{league}]: no results for season {season}")
                continue
            path = _proc_path(f"results-{league}-{season}.csv")
            util.ensure_dir(os.path.dirname(path))
            with open(path, "w", encoding="utf-8", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
            util.log(f"ingest[{league}]: season {season} -> {len(rows)} games")


def load_results(cfg: dict, league: str, season: int) -> list[dict]:
    path = _proc_path(f"results-{league}-{season}.csv")
    if not os.path.exists(path):
        return []
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def main(argv: list[str]) -> int:
    cfg = util.load_config()
    util.load_env()
    download_core(cfg)
    if "--no-results" not in argv:
        derive_results(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
