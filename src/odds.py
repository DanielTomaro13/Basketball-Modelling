"""Odds stage — overlay bookmaker prices on the model book (best-effort).

Fetches public AU bookmaker basketball boards (Sportsbet for v1), maps each book's
head-to-head / line / total selections to the model markets, and writes
``docs/data/odds.json`` with model price, fair price, best book price, EV and edge.

This is best-effort and geo-sensitive: out of season there are simply no markets,
so it writes an empty (but valid) board and the Value page shows nothing. No public
output reveals how the boards are fetched.
"""
from __future__ import annotations

import os
import sys

from . import ratings, sim, util

# Sportsbet public API — basketball competitions (apigw). class/competition ids
# are resolved live; the fetch is wrapped so an off-season empty board is fine.
_SB = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"
_SB_COMP = {"nba": "NBA Matches", "nbl": "NBL Matches"}


def _sb_events(comp_name: str) -> list[dict]:
    # Best-effort: resolve the basketball class, find the competition, list events.
    nav = util.http_get_json(f"{_SB}/Competitions?tagName=basketball", timeout=25)
    if not isinstance(nav, list):
        return []
    out = []
    for comp in nav:
        if comp.get("name") != comp_name:
            continue
        cid = comp.get("id")
        events = util.http_get_json(f"{_SB}/Competitions/{cid}/Events", timeout=25) or []
        for ev in events if isinstance(events, list) else []:
            out.append(ev)
    return out


def _norm(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _model_params(cfg: dict, league: str, home: dict, away: dict, elos: dict):
    elo = elos.get(league)
    ewp = ratings.elo_win_prob(elo, home["id"], away["id"]) if elo else None
    return sim.game_params(home, away, profile_league(cfg, league), cfg["sim"], ewp)


def profile_league(cfg, league):
    return _PROFILES[league]["league"]


_PROFILES: dict = {}


def _price_selection(params: dict, market: str, side: str, line):
    """Model probability for a canonical (market, side, line)."""
    if market == "ml":
        return params["head_home"] if side == "home" else params["head_away"]
    if market == "spread":
        mu, sd = params["mu_margin"], params["sigma_margin"]
        return sim._sf(line, mu, sd) if side == "home" else sim._cdf(line, mu, sd)
    if market == "total":
        mu, sd = params["mu_total"], params["sigma_total"]
        return sim._sf(line, mu, sd) if side == "over" else sim._cdf(line, mu, sd)
    return None


def run(cfg: dict) -> dict:
    global _PROFILES
    dd = cfg["paths"]["docs_data_dir"]
    models = cfg["paths"]["models_dir"]
    _PROFILES = util.read_json(util.abspath(os.path.join(models, "profiles.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "profiles.json"))) else {}
    elos = util.read_json(util.abspath(os.path.join(models, "elo.json"))) \
        if os.path.exists(util.abspath(os.path.join(models, "elo.json"))) else {}

    games, books_present = [], set()
    for league in cfg["leagues"]:
        if league not in _PROFILES:
            continue
        teams = _PROFILES[league]["teams"]
        by_norm = {_norm(t["name"]): t for t in teams.values()}
        try:
            events = _sb_events(_SB_COMP.get(league, ""))
        except Exception as exc:  # noqa: BLE001
            util.log(f"odds[{league}]: sportsbet fetch failed ({exc})")
            events = []
        for ev in events:
            home = by_norm.get(_norm(ev.get("homeTeam") or ev.get("name", "").split(" v ")[-1]))
            away = by_norm.get(_norm(ev.get("awayTeam") or ev.get("name", "").split(" v ")[0]))
            if not home or not away:
                continue
            params = _model_params(cfg, league, home, away, elos)
            markets = _map_book_markets(ev, params, home, away)
            if markets:
                books_present.add("sportsbet")
                games.append({"league": league, "homeAbbr": home.get("abbr", ""),
                              "awayAbbr": away.get("abbr", ""), "home": home["name"],
                              "away": away["name"], "markets": markets})

    util.write_json(util.abspath(os.path.join(dd, "odds.json")),
                    {"generated": _now(), "books": sorted(books_present),
                     "count": len(games), "games": games})
    util.log(f"odds: {len(games)} games priced across {sorted(books_present) or 'no books (off-season)'}")
    return {"games": len(games), "books": sorted(books_present)}


def _map_book_markets(ev: dict, params: dict, home: dict, away: dict) -> list[dict]:
    """Map a Sportsbet event's markets to the canonical model markets with EV."""
    out = []
    for mk in ev.get("markets", []) if isinstance(ev.get("markets"), list) else []:
        name = (mk.get("name") or "").lower()
        canon = "ml" if "head to head" in name or "match" in name else \
            ("spread" if "line" in name or "handicap" in name else
             ("total" if "total" in name or "over/under" in name else None))
        if not canon:
            continue
        sels = []
        for s in mk.get("selections", []):
            price = util.num(s.get("price", {}).get("winValue") if isinstance(s.get("price"), dict) else s.get("odds"))
            if price <= 1:
                continue
            side, line = _classify(canon, s, home, away)
            if side is None:
                continue
            model = _price_selection(params, canon, side, line)
            if not model or model <= 0:
                continue
            sels.append({"label": s.get("name", ""), "model": round(model, 4),
                         "fair": round(1 / model, 2), "books": {"sportsbet": round(price, 2)},
                         "best": {"price": round(price, 2), "book": "sportsbet"},
                         "ev": round(model * price - 1, 4), "edge": round(model - 1 / price, 4)})
        if sels:
            out.append({"key": canon, "label": mk.get("name", canon), "selections": sels})
    return out


def _classify(canon: str, sel: dict, home: dict, away: dict):
    nm = _norm(sel.get("name", ""))
    if canon == "ml":
        return ("home", None) if _norm(home["name"]) in nm else (("away", None) if _norm(away["name"]) in nm else (None, None))
    handicap = util.num(sel.get("handicap") or sel.get("points"))
    if canon == "spread":
        side = "home" if _norm(home["name"]) in nm else ("away" if _norm(away["name"]) in nm else None)
        return (side, -handicap if side == "home" else handicap) if side else (None, None)
    if canon == "total":
        if "over" in nm:
            return "over", handicap
        if "under" in nm:
            return "under", handicap
    return None, None


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str]) -> int:
    run(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
