"""Odds stage — model price vs the bookmakers, across as many markets as possible.

For every upcoming game we pull each book's market board, map each book's
market/selection naming to a canonical model market (moneyline, point spread,
total points, team totals) and price it from the sim's game distribution — so any
book line (-6.5, Over 219.5, …) is priced exactly. Dabble's Pick'em (a multiplier
player-prop game) is captured separately for the Pick'em page, with the model's
over-probability from each player's rate profile.

Books: Sportsbet + Ladbrokes (urllib / curl_cffi, no auth); PointsBet + TAB +
Dabble (curl_cffi; TAB OAuth creds, Dabble bearer). Each is wrapped so one failing
never breaks the rest. The AU books geo-restrict to AU IPs, so this runs from a
local AU cron (scripts/odds-cron.sh); off-season there are no markets and it writes
an empty board. No public output reveals how the boards are fetched.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from . import ratings, sim, util

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
NUM = re.compile(r"([+-]?\d+(?:\.\d+)?)")

MARKET_LABEL = {"ml": "Moneyline", "spread": "Point spread", "total": "Total points",
                "team_total": "Team total"}
MARKET_ORDER = ["ml", "spread", "total", "team_total"]


# --------------------------------------------------------------------------- #
# HTTP + name helpers
# --------------------------------------------------------------------------- #
def _get(url, headers=UA, retries=2, timeout=30):
    last = None
    for i in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.5 * (i + 1))
    return None


def _cffi():
    try:
        from curl_cffi import requests as creq
        return creq
    except Exception:  # noqa: BLE001
        return None


def _cget(url, headers, impersonate="chrome", timeout=25):
    creq = _cffi()
    if creq is None:
        return None
    try:
        r = creq.get(url, headers=headers, impersonate=impersonate, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


def norm(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def _team_match(name, team):
    """Does a book team name refer to this model team? Match on full/nick/abbr."""
    n = norm(name)
    full, abbr = norm(team.get("name", "")), norm(team.get("abbr", ""))
    nick = norm((team.get("name", "").split() or [""])[-1])   # last word (e.g. "Thunder")
    return bool(n) and (n == full or full in n or n in full or (len(nick) >= 4 and nick in n) or n == abbr)


def _find_fixture(fixtures, league, b1, b2):
    for f in fixtures:
        if f["league"] != league:
            continue
        h, a = f["_home"], f["_away"]
        if (_team_match(b1, h) and _team_match(b2, a)):
            return f, False        # b1=home, b2=away
        if (_team_match(b1, a) and _team_match(b2, h)):
            return f, True         # swapped
    return None, False


# --------------------------------------------------------------------------- #
# Canonical market parsing — book market name + selections -> (sel_id, label, price)
# selections = [(name, price)]; `home`/`away` are the model team dicts; `swap` flips sides
# --------------------------------------------------------------------------- #
def parse_market(name, selections, home, away, swap):
    low = (name or "").lower()
    out = []

    def emit(sid, label, price):
        if price and float(price) > 1:
            out.append((sid, label, float(price)))

    def side_of(sel_name):
        if _team_match(sel_name, home):
            return "home"
        if _team_match(sel_name, away):
            return "away"
        return None

    if any(k in low for k in ("head to head", "match betting", "moneyline", "money line", "match result")) \
            and "quarter" not in low and "half" not in low:
        for sn, pr in selections:
            s = side_of(sn)
            if s:
                emit(f"ml|{s}", (home if s == "home" else away)["name"], pr)
    elif any(k in low for k in ("line", "handicap", "point spread", "spread")) \
            and "quarter" not in low and "half" not in low:
        for sn, pr in selections:
            s, m = side_of(sn), NUM.search(sn)
            if s and m:
                line = float(m.group(1))
                # canonical spread line is the home margin handicap
                hl = -line if s == "home" else line
                emit(f"spread|{s}|{hl}", f"{(home if s=='home' else away)['name']} {line:+g}", pr)
    elif ("total" in low or "over/under" in low or "points" in low) and "team" not in low \
            and "quarter" not in low and "half" not in low:
        for sn, pr in selections:
            m = NUM.search(sn)
            sd = "over" if "over" in sn.lower() else "under" if "under" in sn.lower() else None
            if sd and m:
                line = abs(float(m.group(1)))
                emit(f"total|{sd}|{line}", f"{'Over' if sd=='over' else 'Under'} {line}", pr)
    elif "team total" in low or ("total" in low and "team" in low):
        for sn, pr in selections:
            s, m = side_of(sn), NUM.search(sn)
            sd = "over" if "over" in sn.lower() else "under" if "under" in sn.lower() else None
            if s and sd and m:
                line = abs(float(m.group(1)))
                emit(f"team_total|{s}|{sd}|{line}", f"{(home if s=='home' else away)['name']} {'O' if sd=='over' else 'U'}{line}", pr)
    return out


def model_price(sel_id, params):
    """Model probability for a canonical selection id, from the game distribution."""
    p = sel_id.split("|")
    k = p[0]
    if k == "ml":
        return params["head_home"] if p[1] == "home" else params["head_away"]
    if k == "spread":
        line = float(p[2])
        return sim._sf(line, params["mu_margin"], params["sigma_margin"]) if p[1] == "home" \
            else sim._cdf(line, params["mu_margin"], params["sigma_margin"])
    if k == "total":
        line = float(p[2])
        return sim._sf(line, params["mu_total"], params["sigma_total"]) if p[1] == "over" \
            else sim._cdf(line, params["mu_total"], params["sigma_total"])
    if k == "team_total":
        side, sd, line = p[1], p[2], float(p[3])
        mu = params["mu_home"] if side == "home" else params["mu_away"]
        over = sim._sf(line, mu, params["sd_team"])
        return over if sd == "over" else 1 - over
    return None


# --------------------------------------------------------------------------- #
# Books — list_events() -> [{league,id,p1,p2,(raw)}] ; markets(ev) -> [(name,[(sel,price)])]
# Each resolves the NBA + NBL competitions by name; missing ids just yield [].
# --------------------------------------------------------------------------- #
_COMP_NAMES = {"nba": ("nba",), "nbl": ("nbl",)}


def _league_of(comp_name):
    low = (comp_name or "").lower()
    if "nbl" in low:
        return "nbl"
    if "nba" in low:
        return "nba"
    return None


SB = "https://www.sportsbet.com.au/apigw/sportsbook-sports/Sportsbook/Sports"


def sb_events():
    # discover the basketball class, then its NBA/NBL competitions
    nav = _get(f"{SB}?displayType=default") or []
    bball = next((s for s in nav if isinstance(s, dict) and "basketball" in str(s.get("name", "")).lower()), None)
    sid = bball.get("id") if bball else os.environ.get("SB_BASKETBALL_ID", "")
    if not sid:
        return []
    comps = _get(f"{SB}/{sid}/Competitions") or []
    out = []
    for c in comps:
        lg = _league_of(c.get("name"))
        if not lg:
            continue
        d = _get(f"{SB}/Competitions/{c.get('id')}?displayType=default&eventFilter=matches")
        for e in (d or {}).get("events", []):
            if e.get("participant1") and e.get("participant2"):
                out.append({"league": lg, "id": e["id"], "p1": e["participant1"], "p2": e["participant2"]})
    return out


def sb_markets(ev):
    d = _get(f"{SB}/Events/{ev['id']}/Markets")
    return [(m.get("name", ""), [(s.get("name", ""), (s.get("price") or {}).get("winPrice"))
            for s in m.get("selections", [])]) for m in (d if isinstance(d, list) else [])]


LAD = "https://api.ladbrokes.com.au"
LAD_HDR = {"User-Agent": "Mozilla/5.0", "Origin": "https://www.ladbrokes.com.au",
           "Referer": "https://www.ladbrokes.com.au/", "Content-Type": "application/json"}
# Ladbrokes/Entain basketball category UUID (env-overridable).
LAD_CATS = [c for c in os.environ.get("LAD_BASKETBALL_CATS", "3c34d075-dc14-436d-bfc4-9272a49c2b39").split(",") if c]


def lad_events():
    if not LAD_CATS:
        return []
    q = urllib.parse.quote(json.dumps(LAD_CATS))
    d = _cget(f"{LAD}/v2/sport/event-request?category_ids={q}", LAD_HDR)
    out = []
    for eid, e in ((d or {}).get("events", {}) or {}).items():
        nm, comp = e.get("name", ""), e.get("competition_name", "")
        lg = _league_of(comp) or _league_of(nm)
        for sep in (" vs ", " v ", " @ "):
            if sep in nm and lg:
                a, b = nm.split(sep, 1)
                out.append({"league": lg, "id": eid, "p1": a.strip(), "p2": b.strip()})
                break
    return out


def lad_markets(ev):
    d = _cget(f"{LAD}/v2/sport/event-card?id={ev['id']}", LAD_HDR)
    if not d:
        return []
    prices = d.get("prices", {})

    def price(ent_id):
        for kk, v in prices.items():
            if kk.startswith(ent_id + ":"):
                o = (v or {}).get("odds") or {}
                if "decimal" in o:
                    return round(float(o["decimal"]), 2)
        return None

    by_market = {}
    for ent in d.get("entrants", {}).values():
        by_market.setdefault(ent.get("market_id"), []).append(ent)
    return [((d.get("markets", {}).get(mid) or {}).get("name", ""),
             [(e.get("name", ""), price(e["id"])) for e in ents]) for mid, ents in by_market.items()]


PB = "https://api.au.pointsbet.com/api/mes/v3"
PB_V2 = "https://api.au.pointsbet.com/api/v2"
PB_HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Origin": "https://pointsbet.com.au"}


def pb_events():
    d = _cget(f"{PB_V2}/sports/list/", PB_HDR)
    if not d:
        return []
    sports = d.get("sports", d) if isinstance(d, dict) else d
    keys = [(c.get("key"), c.get("name")) for s in sports if str(s.get("name", "")).strip().lower() == "basketball"
            for c in s.get("competitions", []) if c.get("key") and _league_of(c.get("name"))]
    out = []
    for key, cname in keys:
        lg = _league_of(cname)
        feat = _cget(f"{PB}/events/featured/competition/{key}", PB_HDR)
        for ev in (feat.get("events", []) if isinstance(feat, dict) else feat) or []:
            if ev.get("homeTeam") and ev.get("awayTeam"):
                out.append({"league": lg, "id": ev.get("key") or ev.get("eventId") or ev.get("id"),
                            "p1": ev["homeTeam"], "p2": ev["awayTeam"]})
    return out


def pb_markets(ev):
    det = _cget(f"{PB}/events/{ev['id']}", PB_HDR)
    if not det:
        return []
    return [(m.get("name", ""), [(o.get("name", ""), o.get("price")) for o in (m.get("outcomes") or [])])
            for m in (det.get("fixedOddsMarkets") or det.get("markets") or [])]


TAB = "https://api.beta.tab.com.au/v1/tab-info-service"


def _tab_token():
    cid, csec = os.environ.get("TAB_CLIENT_ID", "").strip(), os.environ.get("TAB_CLIENT_SECRET", "").strip()
    creq = _cffi()
    if cid and csec and creq:
        try:
            r = creq.post("https://api.beta.tab.com.au/oauth/token",
                          data={"grant_type": "client_credentials", "client_id": cid, "client_secret": csec},
                          headers={"Accept": "application/json"}, impersonate="chrome", timeout=15)
            if r.status_code == 200 and r.json().get("access_token"):
                return r.json()["access_token"]
        except Exception:  # noqa: BLE001
            pass
    return os.environ.get("TAB_ACCESS_TOKEN", "").strip() or None


def tab_events():
    tok = _tab_token()
    if not tok:
        return []
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    lst = _cget(f"{TAB}/sports/Basketball/competitions?jurisdiction=NSW&homeState=NSW", hdr)
    out = []
    for comp in (lst or {}).get("competitions", []):
        lg = _league_of(comp.get("name"))
        if not lg:
            continue
        for t in comp.get("tournaments", []):
            link = (t.get("_links") or {}).get("self") or (t.get("_links") or {}).get("matches")
            if not link:
                continue
            d = _cget(link, hdr)
            for m in (d or {}).get("matches", []):
                cons = m.get("contestants") or []
                if len(cons) != 2:
                    continue
                raw = [(mk.get("betOption", ""), [(pp.get("name", ""), pp.get("returnWin")) for pp in mk.get("propositions", [])])
                       for mk in m.get("markets", [])]
                out.append({"league": lg, "id": m.get("id"), "p1": cons[0].get("name"), "p2": cons[1].get("name"), "raw": raw})
    return out


DAB = "https://api.dabble.com.au"
_PICKEM = []


def _dab_headers():
    h = {"accept": "application/json",
         "x-device-id": os.environ.get("DABBLE_DEVICE_ID", "00000000-0000-0000-0000-000000000000"),
         "user-agent": os.environ.get("DABBLE_UA", "Dabble/1000041710 CFNetwork/3826.600.41.2.1 Darwin/24.6.0"),
         "x-app-version": os.environ.get("DABBLE_APP_VERSION", "4.17.10+019ededb"), "accept-language": "en-AU,en;q=0.9"}
    auth = os.environ.get("DABBLE_AUTH", "").strip()
    if auth:
        h["authorization"] = auth if auth.lower().startswith("bearer ") else "Bearer " + auth
    if os.environ.get("DABBLE_COOKIE", "").strip():
        h["cookie"] = os.environ["DABBLE_COOKIE"].strip()
    return h


def _dab_get(path):
    creq = _cffi()
    if creq is None:
        return None
    try:
        r = creq.get(DAB + path, headers=_dab_headers(), impersonate="safari_ios", timeout=25)
        return r.json() if r.status_code == 200 else None
    except Exception:  # noqa: BLE001
        return None


# Dabble basketball sport id (env-overridable).
DAB_BASKETBALL_SPORT = os.environ.get("DAB_BASKETBALL_SPORT", "01408294-cb34-4cc0-8ab1-504f5c4c6e1f")


def _dab_comps():
    if not DAB_BASKETBALL_SPORT:
        return []
    d = _dab_get(f"/competitions/active?sportId={DAB_BASKETBALL_SPORT}")
    data = d.get("data", d) if isinstance(d, dict) else d
    if isinstance(data, dict):
        return data.get("competitions") or next((v for v in data.values() if isinstance(v, list)), [])
    return data or []


def _dab_fixtures(comp_id):
    fx = _dab_get(f"/frontend-api/competitions/{comp_id}/sport-fixtures?includeInPlay=false&exclude%5B%5D=none")
    return (fx.get("data", fx) if isinstance(fx, dict) else fx) or []


def dab_events():
    out = []
    for comp in _dab_comps():
        if "pick" in (comp.get("name") or "").lower():
            continue
        lg = _league_of(comp.get("name"))
        for f in _dab_fixtures(comp["id"]):
            name = f.get("name", "")
            for sep in (" v ", " @ "):
                if f.get("id") and sep in name:
                    p1, p2 = [x.strip() for x in name.split(sep, 1)]
                    out.append({"league": lg, "id": f["id"], "p1": p1, "p2": p2, "name": name})
                    break
    return out


# Dabble Pick'em (the multiplier game) — player-prop over lines per fixture.
DAB_PICKEM_STAT = {"points": "points", "rebounds": "rebounds", "assists": "assists",
                   "three-pointers-made": "threes", "threes": "threes", "pra": "pra",
                   "points-rebounds-assists": "pra", "steals": "steals", "blocks": "blocks"}


def dab_pickem(profiles, cfg):
    for comp in _dab_comps():
        if "pick" not in (comp.get("name") or "").lower():
            continue
        lg = _league_of(comp.get("name")) or ("nbl" if "nbl" in comp.get("name", "").lower() else "nba")
        for f in _dab_fixtures(comp["id"]):
            detail = _dab_get(f"/frontend-api/sport-fixtures/details/{f['id']}")
            sfd = (detail or {}).get("sportFixtureDetail") or (detail or {}).get("data", {}).get("sportFixtureDetail") or {}
            for pp in sfd.get("playerProps", []):
                if pp.get("value") is None or not pp.get("playerName"):
                    continue
                stat = next((DAB_PICKEM_STAT[s] for s in (pp.get("stats") or []) if s in DAB_PICKEM_STAT), None)
                if not stat:
                    continue
                line = float(pp["value"])
                over = _pickem_model(profiles, lg, pp["playerName"], stat, line, cfg)
                row = {"league": lg, "event": f.get("name", ""), "player": pp["playerName"],
                       "stat": stat, "line": line, "proj": None, "over": over}
                if over is not None:
                    proj, _ = _player_stat(profiles, lg, pp["playerName"], stat)
                    row["proj"] = round(proj, 1) if proj is not None else None
                if row not in _PICKEM:
                    _PICKEM.append(row)


def _player_stat(profiles, league, player_name, stat):
    players = profiles.get(league, {}).get("players", {})
    pn = norm(player_name)
    best = None
    for p in players.values():
        if norm(p["name"]) == pn or pn in norm(p["name"]):
            best = p
            break
    if not best:
        return None, None
    pg = best["pg"]
    if stat == "pra":
        return pg["pts"] + pg["reb"] + pg["ast"], "pra"
    key = {"points": "pts", "rebounds": "reb", "assists": "ast", "threes": "fg3m",
           "steals": "stl", "blocks": "blk"}.get(stat)
    return (pg.get(key), key) if key else (None, None)


def _pickem_model(profiles, league, player_name, stat, line, cfg):
    mean, key = _player_stat(profiles, league, player_name, stat)
    if mean is None or mean <= 0:
        return None
    if stat in ("threes", "steals", "blocks"):
        return round(sim._clip(sim._poisson_sf(line, mean)), 4)
    sd = sim._prop_sd("pts" if stat in ("points", "pra") else key, mean) if stat != "pra" \
        else (sim._prop_sd("pts", mean) * 1.2)
    return round(sim._clip(sim._sf(line, mean, sd)), 4)


def dab_markets(ev):
    detail = _dab_get(f"/frontend-api/sport-fixtures/details/{ev['id']}")
    sfd = (detail or {}).get("sportFixtureDetail") or (detail or {}).get("data", {}).get("sportFixtureDetail") or {}
    if not sfd:
        return []
    sel_name = {s["id"]: s.get("name", "") for s in sfd.get("selections", [])}
    by_mkt = {}
    for p in sfd.get("prices", []):
        by_mkt.setdefault(p.get("marketId"), []).append((sel_name.get(p.get("selectionId")), p.get("price")))
    raw = []
    for m in sfd.get("markets", []):
        rt = (m.get("resultingType") or "").lower()
        if "pickem" in rt or (m.get("isSgmAllowed") and not m.get("isSingleAllowed")):
            continue
        raw.append((m.get("name", ""), by_mkt.get(m.get("id"), [])))
    return raw


BOOKS = {
    "sportsbet": (sb_events, sb_markets),
    "ladbrokes": (lad_events, lad_markets),
    "pointsbet": (pb_events, pb_markets),
    "tab": (tab_events, lambda ev: ev.get("raw", [])),
    "dabble": (dab_events, dab_markets),
}


# --------------------------------------------------------------------------- #
def run(cfg: dict) -> dict:
    dd = cfg["paths"]["docs_data_dir"]
    md = cfg["paths"]["models_dir"]
    util.load_env()
    preds = util.read_json(util.abspath(os.path.join(dd, "predictions.json")))
    profiles = util.read_json(util.abspath(os.path.join(md, "profiles.json")))
    elos = util.read_json(util.abspath(os.path.join(md, "elo.json"))) \
        if os.path.exists(util.abspath(os.path.join(md, "elo.json"))) else {}

    # resolve each predicted fixture's team profiles + a cached game params
    fixtures = []
    for f in (preds or {}).get("fixtures", []):
        lg = f["league"]
        teams = profiles.get(lg, {}).get("teams", {})
        home, away = teams.get(f.get("homeId")), teams.get(f.get("awayId"))
        if home and away:
            fixtures.append({**f, "_home": home, "_away": away})

    def params_for(f):
        elo = elos.get(f["league"])
        ewp = ratings.elo_win_prob(elo, f["_home"]["id"], f["_away"]["id"]) if elo else None
        return sim.game_params(f["_home"], f["_away"], profiles[f["league"]]["league"], cfg["sim"], ewp)

    book_events = {}
    for name, (lister, _) in BOOKS.items():
        book_events[name] = _safe(lister) or []
        util.log(f"  [{name}] {len(book_events[name])} events")

    books_present, out_games = set(), []
    for f in fixtures:
        params = None
        sel_books, sel_label = {}, {}
        for book, (_, get_markets) in BOOKS.items():
            ev = _match_event(book_events[book], f)
            if not ev:
                continue
            swap = ev.get("_swap", False)
            for mname, sels in _safe(get_markets, ev) or []:
                for sid, label, price in parse_market(mname, sels, f["_home"], f["_away"], swap):
                    sel_books.setdefault(sid, {})[book] = round(price, 2)
                    sel_label[sid] = label
                    books_present.add(book)
        if not sel_books:
            continue
        if params is None:
            params = params_for(f)
        markets = {}
        for sid, books in sel_books.items():
            mp = model_price(sid, params)
            if mp is None or mp <= 0:
                continue
            mp = sim._clip(mp)
            best_price = max(books.values())
            best_book = max(books, key=books.get)
            mk = sid.split("|")[0]
            markets.setdefault(mk, {"key": mk, "label": MARKET_LABEL[mk], "selections": []})
            markets[mk]["selections"].append({
                "id": sid, "label": sel_label[sid], "model": round(mp, 4), "fair": round(1 / mp, 2),
                "books": books, "best": {"price": best_price, "book": best_book},
                "ev": round(mp * best_price - 1, 4), "edge": round(mp - 1 / best_price, 4)})
        ordered = [markets[k] for k in MARKET_ORDER if k in markets]
        if ordered:
            out_games.append({"league": f["league"], "homeAbbr": f["_home"].get("abbr", ""),
                              "awayAbbr": f["_away"].get("abbr", ""), "home": f["_home"]["name"],
                              "away": f["_away"]["name"], "markets": ordered})

    util.write_json(util.abspath(os.path.join(dd, "odds.json")),
                    {"generated": _now(), "books": sorted(books_present), "count": len(out_games), "games": out_games})
    util.log(f"odds: {len(out_games)} games priced across {sorted(books_present) or 'no books (off-season)'}")

    # Dabble Pick'em
    _PICKEM.clear()
    _safe(dab_pickem, profiles, cfg)
    util.write_json(util.abspath(os.path.join(dd, "pickem-lines.json")),
                    {"generated": _now(), "count": len(_PICKEM), "lines": _PICKEM})
    if _PICKEM:
        util.log(f"odds: {len(_PICKEM)} Dabble pick'em lines")
    return {"games": len(out_games), "books": sorted(books_present), "pickem": len(_PICKEM)}


# --------------------------------------------------------------------------- #
# Futures (outright) odds — open year-round, so the value page works off-season.
# Sportsbet now (direct apigw, AU-geo); structured for more books later.
# --------------------------------------------------------------------------- #
def _is_title_market(name: str) -> bool:
    n = (name or "").lower()
    return ("winner" in n or "outright" in n or "champion" in n or "to win" in n) \
        and not any(k in n for k in ("conference", "division", "east", "west", "mvp", "scoring",
                                     "rookie", "player", "coach", "defensive", "regular season"))


_SB_FUTURES_CLASS = {"nba": 16, "nbl": 63}   # Basketball - US / Basketball - Aus-Other


def _sb_championship(league: str) -> list[tuple]:
    cls = _SB_FUTURES_CLASS.get(league)
    if not cls:
        return []
    comps = _get(f"{SB}/{cls}/Competitions") or []
    comp = next((c for c in comps if "future" in str(c.get("name", "")).lower()
                 and _league_of(c.get("name")) == league), None)
    if not comp:
        return []
    d = _get(f"{SB}/Competitions/{comp['id']}?displayType=default&eventFilter=outrights") or {}
    out = []
    for ev in d.get("events", []) if isinstance(d, dict) else []:
        for m in (_get(f"{SB}/Events/{ev['id']}/Markets") or []):
            if _is_title_market(m.get("name")):
                for s in m.get("selections", []):
                    price = util.num((s.get("price") or {}).get("winPrice"))
                    if price > 1:
                        out.append((s.get("name", ""), round(price, 2)))
    return out


def _pb_championship(league: str) -> list[tuple]:
    d = _cget(f"{PB_V2}/sports/list/", PB_HDR)
    if not d:
        return []
    sports = d.get("sports", d) if isinstance(d, dict) else d
    keys = [c.get("key") for s in sports if str(s.get("name", "")).strip().lower() == "basketball"
            for c in s.get("competitions", [])
            if "future" in str(c.get("name", "")).lower() and _league_of(c.get("name")) == league]
    out = []
    for key in keys:
        feat = _cget(f"{PB}/events/featured/competition/{key}", PB_HDR)
        for ev in (feat.get("events", []) if isinstance(feat, dict) else feat) or []:
            for m in (ev.get("fixedOddsMarkets") or ev.get("markets") or []):
                if _is_title_market(m.get("name")):
                    for o in (m.get("outcomes") or []):
                        price = util.num(o.get("price"))
                        if price > 1:
                            out.append((o.get("name", ""), round(price, 2)))
    return out


def _lad_championship(league: str) -> list[tuple]:
    if not LAD_CATS:                          # set LAD_BASKETBALL_CATS env to enable
        return []
    q = urllib.parse.quote(json.dumps(LAD_CATS))
    d = _cget(f"{LAD}/v2/sport/event-request?category_ids={q}", LAD_HDR)
    out = []
    for eid, e in ((d or {}).get("events", {}) or {}).items():
        if _league_of(e.get("competition_name", "")) != league and _league_of(e.get("name", "")) != league:
            continue
        card = _cget(f"{LAD}/v2/sport/event-card?id={eid}", LAD_HDR)
        if not card:
            continue
        prices = card.get("prices", {})

        def price(ent_id):
            for kk, v in prices.items():
                if kk.startswith(ent_id + ":"):
                    o = (v or {}).get("odds") or {}
                    return round(float(o["decimal"]), 2) if "decimal" in o else None
            return None
        by_m = {}
        for ent in card.get("entrants", {}).values():
            by_m.setdefault(ent.get("market_id"), []).append(ent)
        for mid, ents in by_m.items():
            if _is_title_market((card.get("markets", {}).get(mid) or {}).get("name", "")):
                for ent in ents:
                    p = price(ent["id"])
                    if p and p > 1:
                        out.append((ent.get("name", ""), p))
    return out


def _tab_championship(league: str) -> list[tuple]:
    tok = _tab_token()
    if not tok:
        return []
    hdr = {"Authorization": f"Bearer {tok}", "Accept": "application/json", "User-Agent": "Mozilla/5.0"}
    lst = _cget(f"{TAB}/sports/Basketball/competitions?jurisdiction=NSW&homeState=NSW", hdr)
    out = []
    for comp in (lst or {}).get("competitions", []):
        # the futures comp (e.g. "NBA Futures") holds matches, each carrying the outright markets
        if "future" not in str(comp.get("name", "")).lower() or _league_of(comp.get("name")) != league:
            continue
        matches_link = (comp.get("_links") or {}).get("matches")
        ml = _cget(matches_link, hdr) if matches_link else None
        for mt in (ml or {}).get("matches", []) if isinstance(ml, dict) else []:
            self_link = (mt.get("_links") or {}).get("self")
            d = _cget(self_link, hdr) if self_link else None
            for m in (d or {}).get("markets", []) if isinstance(d, dict) else []:
                if _is_title_market(m.get("betOption") or m.get("name")):
                    for pp in m.get("propositions", []):
                        p = util.num(pp.get("returnWin"))
                        if p > 1:
                            out.append((pp.get("name", ""), round(p, 2)))
    return out


def _dab_championship(league: str) -> list[tuple]:
    out = []
    for comp in _dab_comps():
        if _league_of(comp.get("name")) != league or "future" not in (comp.get("name") or "").lower():
            continue
        for f in _dab_fixtures(comp["id"]):
            detail = _dab_get(f"/frontend-api/sport-fixtures/details/{f['id']}")
            sfd = (detail or {}).get("sportFixtureDetail") or (detail or {}).get("data", {}).get("sportFixtureDetail") or {}
            sel_name = {s["id"]: s.get("name", "") for s in sfd.get("selections", [])}
            by_m = {}
            for p in sfd.get("prices", []):
                by_m.setdefault(p.get("marketId"), []).append((sel_name.get(p.get("selectionId")), p.get("price")))
            for m in sfd.get("markets", []):
                if _is_title_market(m.get("name")):
                    for nm, price in by_m.get(m.get("id"), []):
                        if util.num(price) > 1:
                            out.append((nm, round(util.num(price), 2)))
    return out


FUTURES_BOOKS = {
    "sportsbet": _sb_championship, "pointsbet": _pb_championship,
    "ladbrokes": _lad_championship, "tab": _tab_championship, "dabble": _dab_championship,
}


def futures_odds(cfg: dict) -> dict:
    md = cfg["paths"]["models_dir"]
    dd = cfg["paths"]["docs_data_dir"]
    fut = util.read_json(util.abspath(os.path.join(dd, "futures.json"))) \
        if os.path.exists(util.abspath(os.path.join(dd, "futures.json"))) else {}
    profiles = util.read_json(util.abspath(os.path.join(md, "profiles.json"))) \
        if os.path.exists(util.abspath(os.path.join(md, "profiles.json"))) else {}
    books_present, out = set(), {}
    for league in cfg["leagues"]:
        teams = (fut.get("leagues", {}).get(league, {}) or {}).get("teams", [])
        if not teams:
            continue
        tmeta = profiles.get(league, {}).get("teams", {})
        # each book's championship board -> map selections to model teams by name
        priced = {}
        for book, fn in FUTURES_BOOKS.items():
            for name, price in (_safe(fn, league) or []):
                tid = next((tid for tid, tm in tmeta.items() if _team_match(name, tm)), None)
                if tid:
                    priced.setdefault(tid, {})[book] = price
                    books_present.add(book)
        rows = []
        for t in teams:
            books = priced.get(t["teamId"], {})
            mp = t.get("title_pct") or 0
            row = {"team": t["name"], "abbr": t["abbr"], "model_pct": mp,
                   "model_fair": t.get("title_fair"), "books": books}
            if books and mp > 0:
                best_price = max(books.values()); best_book = max(books, key=books.get)
                row.update({"best": {"price": best_price, "book": best_book},
                            "ev": round(mp * best_price - 1, 4), "edge": round(mp - 1 / best_price, 4)})
            rows.append(row)
        out[league] = {"championship": rows}
    util.write_json(util.abspath(os.path.join(dd, "futures-odds.json")),
                    {"generated": _now(), "books": sorted(books_present), "leagues": out})
    n = sum(1 for lg in out.values() for r in lg["championship"] if r.get("books"))
    util.log(f"odds: futures — {n} championship selections priced across {sorted(books_present) or 'no books'}")
    return {"priced": n, "books": sorted(books_present)}


def _match_event(events, f):
    for e in events:
        if e.get("league") and e["league"] != f["league"]:
            continue
        fx, swap = _find_fixture([f], f["league"], e.get("p1", ""), e.get("p2", ""))
        if fx:
            e["_swap"] = swap
            return e
    return None


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as exc:  # noqa: BLE001
        util.log(f"  [odds] {getattr(fn, '__name__', fn)} failed: {exc}")
        return None


def _now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def main(argv: list[str]) -> int:
    run(util.load_config())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
