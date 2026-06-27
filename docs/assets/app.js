// app.js — Basketball-Modelling. Static SPA over the pipeline's JSON contracts (NBA + NBL).

/* ---------- helpers ---------- */
const fmtPct = (p) => (p == null ? "—" : (p * 100).toFixed(0) + "%");
const odds = (v) => (v && v > 0 ? (+v).toFixed(2) : "—");
const getJSON = (p) => fetch(p).then((r) => (r.ok ? r.json() : null)).catch(() => null);
const LEAGUES = [["nba", "NBA"], ["nbl", "NBL"]];

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on") && typeof v === "function") e[k] = v;
    else e.setAttribute(k, v);
  }
  kids.flat().forEach((c) => e.append(c?.nodeType ? c : document.createTextNode(c ?? "")));
  return e;
}
function bar(p) { const b = el("div", { class: "bar" }); const s = el("span"); s.style.width = ((p || 0) * 100).toFixed(1) + "%"; b.append(s); return b; }
const money = (v) => (v == null ? "—" : "$" + (v / 1000).toFixed(0) + "k");
const signed = (v) => (v == null ? "—" : (v > 0 ? "+" : "") + (Math.abs(v) >= 1000 ? (v / 1000).toFixed(0) + "k" : v));
function deltaCell(v) { return el("td", { class: "num " + (v > 0 ? "pos" : v < 0 ? "neg" : "mut") }, signed(v)); }
function badge(txt, cls) { return txt ? el("span", { class: "pill " + (cls || "") }, txt) : ""; }

// Sortable table: cols = [{key,label,cls,get,cell}]; renders, clicking a header re-sorts.
function sortableTable(rows, cols, state, host) {
  function draw() {
    const sorted = state.sort ? [...rows].sort((a, b) => {
      const ga = state._get(a), gb = state._get(b);
      if (ga == null) return 1; if (gb == null) return -1;
      return typeof ga === "string" ? state.dir * ga.localeCompare(gb) : state.dir * (gb - ga);
    }) : rows;
    const head = el("tr", {}, ...cols.map((c) => {
      const on = state.sort === c.key;
      const th = el("th", { class: (c.cls || "") + " so" + (on ? " on" : "") }, c.label + (on ? (state.dir > 0 ? " ▾" : " ▴") : ""));
      th.onclick = () => { if (state.sort === c.key) state.dir = -state.dir; else { state.sort = c.key; state.dir = 1; } state._get = c.get; draw(); };
      return th;
    }));
    host.replaceChildren(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, head),
      el("tbody", {}, ...sorted.slice(0, state.limit || 200).map((r) => el("tr", {}, ...cols.map((c) => c.cell(r))))))));
  }
  state._get = state._get || ((r) => 0);
  draw();
  return draw;
}

let LEAGUE = localStorage.getItem("bb_league") || "nba";

/* ---------- chrome ---------- */
const NAV = [
  ["home", "Home", "index.html"], ["games", "Games", "games.html"],
  ["compare", "Compare", "compare.html"], ["value", "Value", "value.html"],
  ["pickem", "Pick'em", "pickem.html"], ["fantasy", "Fantasy", "fantasy.html"],
  ["futures", "Futures", "futures.html"], ["rankings", "Rankings", "rankings.html"],
  ["players", "Players", "players.html"], ["backtest", "Backtest", "backtest.html"],
  ["about", "About", "about.html"],
];
const SISTER_SITES = [
  ["AFL 23-0", "https://afl23-0.com"], ["NRL 24-0", "https://nrl24-0.com"],
  ["NBA 82-0", "https://nba82-0.com"], ["NBL 33-0", "https://nbl33-0.com"],
  ["MLB 162-0", "https://mlb162-0.com"],
  ["Tennis Slam", "https://danieltomaro13.github.io/Tennis-Modelling/"],
  ["Football Invincibles", "https://footballinvincibles.com"], ["F1 Slam", "https://f1slam.com"],
];

function sisterBar() {
  return el("div", { class: "sister-bar", role: "navigation", "aria-label": "Sister sites" },
    el("span", { class: "lead" }, "THE 0 SERIES ·"),
    ...SISTER_SITES.map(([label, href]) => el("a", { class: "sister-link", href }, label)));
}
function chrome(page) {
  const header = el("header", {}, el("div", { class: "wrap" },
    el("a", { class: "brand", href: "index.html" },
      el("img", { class: "ball", src: "assets/ball.svg", alt: "", "aria-hidden": "true" }),
      el("span", {}, "Basketball "), el("span", { class: "acc" }, "Models")),
    el("nav", {}, ...NAV.map(([id, label, href]) => el("a", { class: id === page ? "on" : "", href }, label)))));
  const footer = el("footer", {}, el("div", { class: "wrap" },
    el("nav", { class: "foot-links" }, el("a", { href: "about.html" }, "How it works"),
      el("span", { class: "sep" }, "·"), el("a", { href: "backtest.html" }, "Backtest")),
    el("p", { html: "NBA modelled from public ESPN data; NBL from the public nbl.com.au stats API. For research and entertainment only — not betting advice." }),
    el("p", { class: "series" }, "Part of the 0 Series · ",
      ...SISTER_SITES.flatMap(([label, href], i) => [i ? " · " : "", el("a", { href }, label)])),
    el("a", { class: "kofi", href: "https://ko-fi.com/danieltomaro", target: "_blank", rel: "noopener" }, "☕ Support on Ko-fi")));
  document.getElementById("app-header")?.replaceWith(sisterBar(), header);
  document.getElementById("app-footer")?.replaceWith(footer);
}

let META = null;
function leagueBar(onChange) {
  const lm = META?.leagues?.[LEAGUE];
  const meta = lm ? `Season ${lm.season} · ${lm.n_teams} teams · ${lm.n_players} players · updated ${META.generated}` : "";
  const seg = el("div", { class: "seg" }, ...LEAGUES.map(([id, label]) =>
    el("button", { class: id === LEAGUE ? "on" : "", onclick: () => { if (id === LEAGUE) return; LEAGUE = id; localStorage.setItem("bb_league", id); onChange(); } }, label)));
  return el("div", { class: "leaguebar" }, seg, el("span", { class: "lmeta" }, meta));
}

/* ---------- pages ---------- */
function tile(h, big, p) { return el("div", { class: "tile" }, el("h3", {}, h), el("div", { class: "big" }, big), el("p", {}, p)); }

async function pageHome(content) {
  const [preds, odds_] = await Promise.all([getJSON("data/predictions.json"), getJSON("data/odds.json")]);
  function render() {
    content.replaceChildren(leagueBar(render));
    const lm = META?.leagues?.[LEAGUE] || {}; const bt = lm.backtest || {};
    const games = (preds?.fixtures || []).filter((f) => f.league === LEAGUE);
    content.append(el("div", { class: "cards" },
      tile("Games priced", games.length + "", games[0]?.featured ? "featured matchups (off-season)" : "across the full market book"),
      tile("Backtest accuracy", bt.accuracy != null ? fmtPct(bt.accuracy) : "—", `vs ${bt.home_win_rate != null ? fmtPct(bt.home_win_rate) : "—"} home base rate`),
      tile("Log loss", bt.log_loss ?? "—", bt.beats_baseline ? "beats baseline ✓" : "baseline " + (bt.baseline_log_loss ?? "—")),
      tile("Players profiled", lm.n_players ?? "—", `${LEAGUE.toUpperCase()} · ${lm.ppg ?? "—"} lg ppg`)));
    const picks = valuePicks(odds_, LEAGUE).slice(0, 6);
    if (picks.length) {
      content.append(el("div", { class: "group-head" }, el("h2", {}, "Top value"), el("a", { href: "value.html", class: "muted" }, "all value →")));
      content.append(valueTable(picks));
    }
    if (games.length) {
      content.append(el("div", { class: "group-head" }, el("h2", {}, games[0]?.featured ? "Featured matchups" : "Upcoming"), el("span", { class: "muted" }, "tap for the full book")));
      games.slice(0, 6).forEach((g) => content.append(gameCard(g)));
    }
    content.append(el("a", { class: "banner", href: "games.html" }, "Every game's full market book on the Games page →"));
  }
  render();
}

async function pageGames(content) {
  const preds = await getJSON("data/predictions.json");
  function render() {
    content.replaceChildren(leagueBar(render));
    const games = (preds?.fixtures || []).filter((f) => f.league === LEAGUE);
    if (!games.length) return content.append(el("p", { class: "loading" }, "No games to price right now — check back when the season tips off."));
    const byDate = {};
    games.forEach((g) => (byDate[g.featured ? "Featured matchups" : g.date] ||= []).push(g));
    for (const date of Object.keys(byDate).sort()) {
      content.append(el("div", { class: "group-head" }, el("h2", {}, date), el("span", { class: "muted" }, byDate[date].length + " games")));
      byDate[date].forEach((g) => content.append(gameCard(g)));
    }
  }
  render();
}

function gameCard(g) {
  const card = el("div", { class: "match click" },
    el("h3", { onclick: () => openModal(g) },
      el("span", {}, `${g.awayAbbr} @ ${g.homeAbbr}`),
      el("span", { class: "ko" }, `${g.proj_away}–${g.proj_home} · total ${g.mu_total}`)),
    el("div", { class: "tablewrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { class: "pl" }, "Team"), el("th", {}, "Win"), el("th", {}, "Prob"), el("th", {}, "Fair"), el("th", {}, "Proj"))),
      el("tbody", {},
        teamRow(g.away, g.awayAbbr, g.win_away, g.fair_away, g.proj_away),
        teamRow(g.home, g.homeAbbr, g.win_home, g.fair_home, g.proj_home)))));
  return card;
}
function teamRow(name, abbr, wp, fair, proj) {
  return el("tr", {},
    el("td", { class: "pl" }, el("b", {}, name), " ", el("span", { class: "pill" }, abbr)),
    el("td", {}, bar(wp)), el("td", {}, fmtPct(wp)), el("td", {}, odds(fair)), el("td", {}, proj));
}

/* ---------- full market modal ---------- */
const GROUPS = [
  ["Main", ["ml", "spread", "total", "team_total", "margin_band", "total_band", "race20", "overtime", "odd_even"]],
  ["Halves", ["h1_ml", "h1_spread", "h1_total", "h1_team_total", "h2_ml", "h2_spread", "h2_total", "h2_team_total", "htft", "half_combo"]],
  ["Quarters", ["q1_ml", "q1_spread", "q1_total", "q1_team_total", "q2_ml", "q2_spread", "q2_total", "q2_team_total", "q3_ml", "q3_spread", "q3_total", "q3_team_total", "q4_ml", "q4_spread", "q4_total", "q4_team_total"]],
];
function chip(label, prob, fair) {
  return el("div", { class: "chip" }, el("b", {}, label), el("span", { class: "o" }, `${fmtPct(prob)} · ${odds(fair)}`));
}
function renderMarket(m) {
  const head = el("div", { class: "mk" }, el("h4", {}, m.label));
  const wrap = el("div", {});
  wrap.append(head);
  if (m.selections) {
    wrap.append(el("div", { class: "selrow" }, ...m.selections.map((s) => chip(s.label, s.prob, s.fair))));
  } else if (m.lines && m.lines[0] && "home" in m.lines[0]) { // spread
    wrap.append(el("div", { class: "selrow" }, ...m.lines.map((l) =>
      el("div", { class: "chip" }, el("b", {}, l.home_label), el("span", { class: "o" }, `${fmtPct(l.home)} · ${odds(l.home_fair)}`)))));
    wrap.append(el("div", { class: "selrow" }, ...m.lines.map((l) =>
      el("div", { class: "chip" }, el("b", {}, l.away_label), el("span", { class: "o" }, `${fmtPct(l.away)} · ${odds(l.away_fair)}`)))));
  } else if (m.lines) { // over/under
    wrap.append(el("div", { class: "selrow" }, ...m.lines.map((l) => {
      const pre = l.team ? `${l.team} ` : "";
      return el("div", { class: "chip" }, el("b", {}, `${pre}${l.line}`),
        el("span", { class: "o" }, `O ${fmtPct(l.over)} / U ${fmtPct(l.under)}`));
    })));
  }
  return wrap;
}
function propCard(pp) {
  const lines = (s) => (s.lines || []).map((l) => `${l.line} (O ${fmtPct(l.over)})`).join("  ");
  const body = [];
  pp.singles?.forEach((s) => body.push(el("div", {}, el("span", { class: "mn" }, `${s.label} ${s.proj}: `), lines(s))));
  pp.combos?.forEach((s) => body.push(el("div", {}, el("span", { class: "mn" }, `${s.label} ${s.proj}: `), lines(s))));
  pp.discrete?.forEach((s) => body.push(el("div", {}, el("span", { class: "mn" }, `${s.label}: `), `${fmtPct(s.prob)} · ${odds(s.fair)}`)));
  pp.periods?.forEach((s) => body.push(el("div", {}, el("span", { class: "mn" }, `${s.label} ${s.proj}: `), lines(s))));
  return el("div", { class: "propcard" },
    el("div", { class: "pn" }, el("span", {}, pp.name), el("span", { class: "mn" }, `${pp.min} min`)),
    ...body.map((b) => { b.style.fontSize = "12.5px"; b.style.color = "var(--mut)"; b.style.margin = "3px 0"; return b; }));
}
async function openModal(g) {
  const detail = await getJSON(`data/games/${g.league}-${g.gameId}.json`);
  g = { ...g, markets: detail?.markets || [], props: detail?.props || {} };
  let tab = "Main";
  const body = el("div", { class: "modal-body" });
  const tabs = el("div", { class: "subtabs" });
  function draw() {
    tabs.replaceChildren(...[...GROUPS.map((x) => x[0]), "Players"].map((name) =>
      el("button", { class: name === tab ? "on" : "", onclick: () => { tab = name; draw(); } }, name)));
    body.replaceChildren(tabs);
    if (tab === "Players") {
      [["away", g.awayAbbr], ["home", g.homeAbbr]].forEach(([side, abbr]) => {
        const list = g.props?.[side] || [];
        body.append(el("div", { class: "mk" }, el("h4", {}, `${abbr} props`), el("span", { class: "sub" }, `${list.length} players`)));
        list.forEach((pp) => body.append(propCard(pp)));
      });
    } else {
      const keys = GROUPS.find((x) => x[0] === tab)[1];
      const mk = Object.fromEntries(g.markets.map((m) => [m.key, m]));
      keys.forEach((k) => { if (mk[k]) body.append(renderMarket(mk[k])); });
    }
  }
  draw();
  const box = el("div", { class: "modal-box" },
    el("div", { class: "modal-head" },
      el("h2", {}, `${g.away} @ ${g.home}`),
      el("button", { class: "x", "aria-label": "Close", onclick: () => overlay.remove() }, "✕")),
    body);
  const overlay = el("div", { class: "modal", onclick: (e) => { if (e.target === overlay) overlay.remove(); } }, box);
  document.body.append(overlay);
}

/* ---------- value ---------- */
function valuePicks(data, league) {
  if (!data?.games) return [];
  return data.games.filter((g) => g.league === league)
    .flatMap((g) => (g.markets || []).flatMap((m) => (m.selections || []).map((s) => ({ ...s, g, market: m.label }))))
    .filter((s) => s.ev > 0).sort((a, b) => b.ev - a.ev);
}
function valueTable(rows) {
  return el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", { class: "pl" }, "Game"), el("th", { class: "pl" }, "Selection"),
      el("th", {}, "Model"), el("th", {}, "Fair"), el("th", {}, "Best"), el("th", {}, "Book"), el("th", {}, "EV"))),
    el("tbody", {}, ...rows.map((s) => el("tr", {},
      el("td", { class: "pl mut" }, `${s.g.awayAbbr} @ ${s.g.homeAbbr}`),
      el("td", { class: "pl" }, s.label, el("span", { class: "mut" }, ` · ${s.market || ""}`)),
      el("td", {}, fmtPct(s.model)), el("td", {}, odds(s.fair)),
      el("td", { class: "bestbook" }, odds(s.best?.price)), el("td", { class: "mut" }, s.best?.book || "—"),
      el("td", { class: s.ev > 0 ? "pos" : "neg" }, (s.ev > 0 ? "+" : "") + (s.ev * 100).toFixed(1) + "%")))))));
}
async function pageValue(content) {
  const [data, fodds] = await Promise.all([getJSON("data/odds.json"), getJSON("data/futures-odds.json")]);
  function render() {
    content.replaceChildren(leagueBar(render));
    const picks = valuePicks(data, LEAGUE);
    const fo = fodds?.leagues?.[LEAGUE]?.championship;
    const fval = (fo || []).filter((r) => (r.edge ?? -1) > 0);
    if (data?.games?.length) {
      content.append(el("p", { class: "mut" }, `Books: ${(data.books || []).join(", ") || "—"} · updated ${data.generated}`));
      content.append(el("div", { class: "group-head" }, el("h2", {}, "Positive expected value"), el("span", { class: "muted" }, picks.length + " selections")));
      content.append(picks.length ? valueTable(picks) : el("p", { class: "loading" }, "No positive-EV selections right now."));
    } else {
      content.append(el("p", { class: "mut" }, "Game markets open closer to tip-off. Until then, here's where the model sees value in the championship futures."));
    }
    if (fval.length) {
      content.append(el("div", { class: "group-head" }, el("h2", {}, "Championship futures value"), el("span", { class: "muted" }, fval.length + " teams · " + (fodds.books || []).map(BOOK_LABEL).join(", "))));
      content.append(el("div", { class: "disclaim" }, "Edge = the model's win probability minus the best book's implied probability. Big futures edges usually mean the model rates a team well above the market — disagreement, not a sure thing."));
      content.append(futuresCompare(fo, fodds.books, { valueOnly: true }));
    } else if (!data?.games?.length) {
      content.append(el("p", { class: "loading" }, "No bookmaker odds loaded yet for " + LEAGUE.toUpperCase() + "."));
    }
  }
  render();
}

/* ---------- rankings ---------- */
async function pageRankings(content) {
  const data = await getJSON("data/ratings.json");
  function render() {
    content.replaceChildren(leagueBar(render));
    const board = data?.[LEAGUE];
    if (!board?.length) return content.append(el("p", { class: "loading" }, "Ratings not available."));
    content.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", { class: "pl" }, "Team"), el("th", {}, "Elo"),
        el("th", {}, "Off"), el("th", {}, "Def"), el("th", {}, "Net"), el("th", {}, "Pace"), el("th", {}, "GP"))),
      el("tbody", {}, ...board.map((t) => el("tr", {},
        el("td", { class: "mut" }, t.rank),
        el("td", { class: "pl" }, el("b", {}, t.name), " ", el("span", { class: "pill" }, t.abbr)),
        el("td", { class: "elo" }, t.elo),
        el("td", {}, t.off ?? "—"), el("td", {}, t.def ?? "—"),
        el("td", { class: (t.off && t.def && t.off - t.def > 0) ? "pos" : "neg" }, t.off && t.def ? (t.off - t.def > 0 ? "+" : "") + (t.off - t.def).toFixed(1) : "—"),
        el("td", { class: "mut" }, t.pace ?? "—"), el("td", { class: "mut" }, t.played))))))));
  }
  render();
}

/* ---------- players ---------- */
async function pagePlayers(content) {
  const [index, players] = await Promise.all([getJSON("data/players-index.json"), getJSON("data/players.json")]);
  function render() {
    content.replaceChildren(leagueBar(render));
    if (!index) return content.append(el("p", { class: "loading" }, "Players not available."));
    const input = el("input", { class: "search", type: "search", placeholder: "Search players…", autocomplete: "off" });
    const count = el("span", { class: "count" });
    content.append(el("p", { class: "mut", style: "margin:2px 0 8px;font-size:12.5px" }, "Season per-game profiles behind the prop projections. Tap any column to sort."));
    content.append(el("div", { class: "filters" }, input, count));
    const host = el("div", { class: "match" }); content.append(host);
    const num = (k, lab) => ({ key: k, label: lab, get: (r) => r[k], cell: (r) => el("td", { class: "num" }, r[k] ?? "—") });
    const cols = [
      { key: "name", label: "Player", cls: "pl", get: (r) => r.name, cell: (r) => el("td", { class: "pl" }, el("b", {}, r.name)) },
      { key: "team", label: "Team", get: (r) => r.team, cell: (r) => el("td", {}, badge(r.team)) },
      { key: "gp", label: "GP", cls: "mut", get: (r) => r.gp, cell: (r) => el("td", { class: "num mut" }, r.gp) },
      { key: "min", label: "Min", cls: "mut", get: (r) => r.min, cell: (r) => el("td", { class: "num mut" }, r.min) },
      { key: "pts", label: "Pts", get: (r) => r.pts, cell: (r) => el("td", { class: "num elo" }, r.pts) },
      num("reb", "Reb"), num("ast", "Ast"), num("fg3m", "3PM"), num("stl", "Stl"), num("blk", "Blk"),
      num("tov", "TO"), num("fgm", "FGM"), num("ftm", "FTM"),
    ];
    function draw() {
      const q = input.value.trim().toLowerCase();
      const rows = index.filter((p) => p.league === LEAGUE && p.name.toLowerCase().includes(q))
        .map((p) => players?.[LEAGUE]?.[p.id]).filter(Boolean);
      count.textContent = Math.min(rows.length, 160) + " of " + rows.length;
      sortableTable(rows, cols, { sort: "pts", dir: 1, limit: 160, _get: (r) => r.pts }, host);
    }
    input.oninput = draw; draw();
  }
  render();
}

/* ---------- backtest / about ---------- */
async function pageBacktest(content) {
  function render() {
    content.replaceChildren(leagueBar(render));
    const bt = META?.leagues?.[LEAGUE]?.backtest;
    if (!bt || !bt.n) return content.append(el("p", { class: "loading" }, "Backtest not available for " + LEAGUE.toUpperCase() + "."));
    content.append(el("div", { class: "cards" },
      tile("Games scored", (bt.n || 0).toLocaleString(), `holdout season ${bt.holdout_season}`),
      tile("Accuracy", fmtPct(bt.accuracy), `home base rate ${fmtPct(bt.home_win_rate)}`),
      tile("Log loss", bt.log_loss, `baseline ${bt.baseline_log_loss}`),
      tile("Brier", bt.brier, bt.beats_baseline ? "beats baseline ✓" : "below baseline")));
    content.append(el("p", { class: "mut" }, "Walk-forward: every game is predicted from the team-Elo ratings as they stood before tip-off, then scored against the result. Elo updates chronologically, so no future information leaks into a prediction."));
  }
  render();
}
async function pageAbout(content) {
  const steps = [
    ["Ingest", "Cache each league's team season stats, player season rates and every final score — NBA from public ESPN data, NBL from the public nbl.com.au stats API."],
    ["Profiles", "Opponent-adjusted team offense/defense (from final scores) plus pace, and per-player rate profiles — shrunk toward the league mean for small samples."],
    ["Ratings", "Results-based team Elo per league — home-court adjusted, margin-of-victory weighted, regressed between seasons."],
    ["Engine", "A possession/efficiency model: each team's points come from its offense vs the opponent's defense and the game's pace. The margin and total are Normals; every market is read off them."],
    ["Predict", "The sim is blended with Elo (in logit space) for the headline, then the full book is priced — spreads, totals, team totals, quarters, halves, margins, double results — plus player props."],
    ["Backtest", "A leakage-free walk-forward test on the held-out season, scored against the home-court baseline."],
  ];
  content.append(el("p", { class: "mut" }, "A reproducible, dependency-free Python pipeline rebuilt automatically. Everything below comes from public data — it shares no code with any private model."));
  content.append(el("div", { class: "cards" }, ...steps.map(([h, p]) => el("div", { class: "tile" }, el("h3", {}, h), el("p", {}, p)))));
}

/* ---------- compare (5-book odds) ---------- */
function bookCols(data) { return (data?.books || []); }
async function pageCompare(content) {
  const [data, fodds] = await Promise.all([getJSON("data/odds.json"), getJSON("data/futures-odds.json")]);
  function render() {
    content.replaceChildren(leagueBar(render));
    const games = (data?.games || []).filter((g) => g.league === LEAGUE);
    const fo = fodds?.leagues?.[LEAGUE]?.championship;
    const hasFut = fo && fo.some((r) => r.books && Object.keys(r.books).length);
    if (!games.length) {
      if (hasFut) {
        content.append(el("p", { class: "mut" }, `Game markets open closer to tip-off. Championship futures — model fair price vs ${(fodds.books || []).map(BOOK_LABEL).join(", ")}. Updated ${fodds.generated}.`));
        content.append(futuresCompare(fo, fodds.books));
        return;
      }
      return content.append(el("p", { class: "loading" }, "No bookmaker odds loaded yet — markets open closer to game time, and prices refresh from a local run. Every game still shows the model's fair price on the Games page."));
    }
    const books = bookCols(data);
    content.append(el("p", { class: "mut" }, `Books: ${books.join(", ")} · model fair price vs the market · updated ${data.generated}`));
    const rows = games.flatMap((g) => g.markets.flatMap((m) => m.selections.map((s) => ({ ...s, g, market: m.label }))));
    const head = el("tr", {}, el("th", { class: "pl" }, "Game"), el("th", { class: "pl" }, "Selection"),
      el("th", {}, "Model"), el("th", {}, "Fair"), ...books.map((b) => el("th", {}, BOOK_LABEL(b))), el("th", {}, "Best"), el("th", {}, "EV"));
    content.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
      el("thead", {}, head),
      el("tbody", {}, ...rows.map((s) => el("tr", {},
        el("td", { class: "pl mut" }, `${s.g.awayAbbr} @ ${s.g.homeAbbr}`),
        el("td", { class: "pl" }, s.label, el("span", { class: "mut" }, ` · ${s.market}`)),
        el("td", {}, fmtPct(s.model)), el("td", {}, odds(s.fair)),
        ...books.map((b) => el("td", { class: s.best?.book === b ? "bestbook" : "" }, odds(s.books?.[b]))),
        el("td", { class: "bestbook" }, odds(s.best?.price)),
        el("td", { class: s.ev > 0 ? "pos" : "neg" }, (s.ev > 0 ? "+" : "") + (s.ev * 100).toFixed(1) + "%"))))))));
  }
  render();
}
function BOOK_LABEL(b) { return ({ sportsbet: "Sportsbet", ladbrokes: "Ladbrokes", pointsbet: "PointsBet", tab: "TAB", dabble: "Dabble" })[b] || b; }

/* ---------- pick'em (Dabble) ---------- */
async function pagePickem(content) {
  const data = await getJSON("data/pickem-lines.json");
  function render() {
    content.replaceChildren(leagueBar(render));
    const lines = (data?.lines || []).filter((l) => l.league === LEAGUE);
    content.append(el("p", { class: "mut" }, "Dabble Pick'em — the model's lean on each player line (more/less), with its projection and edge."));
    if (!lines.length)
      return content.append(el("p", { class: "loading" }, "No Pick'em lines loaded yet — Dabble posts them closer to tip-off."));
    content.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", { class: "pl" }, "Player"), el("th", { class: "pl" }, "Stat"),
        el("th", {}, "Line"), el("th", {}, "Proj"), el("th", {}, "Over %"), el("th", {}, "Lean"))),
      el("tbody", {}, ...lines.map((l) => el("tr", {},
        el("td", { class: "pl" }, el("b", {}, l.player)), el("td", { class: "pl mut" }, l.stat),
        el("td", {}, l.line), el("td", {}, l.proj),
        el("td", {}, fmtPct(l.over)),
        el("td", { class: l.over >= 0.5 ? "pos" : "neg" }, l.over >= 0.5 ? "MORE" : "LESS"))))))));
  }
  render();
}

/* ---------- fantasy (SuperCoach) ---------- */
const FANTASY_VIEWS = [
  ["premiums", "Premiums", "proj", "Top scorers — your captain and must-have picks."],
  ["value", "Value", "value", "Best points per $1M — the cash-efficient picks."],
  ["movers", "Price movers", "price_change", "Biggest price risers and fallers this round."],
  ["captains", "Captains", "captain", "Highest projected captain scores (score counts double)."],
  ["owned", "Ownership", "owned", "Most-owned players — the template."],
  ["all", "All players", "proj", "The full pool — sort any column."],
];
function valueClass(v) { return v == null ? "mut" : v >= 9 ? "pos" : v >= 5 ? "" : "neg"; }
async function pageFantasy(content) {
  const cache = {};
  async function load() { return (cache[LEAGUE] ||= await getJSON(`data/fantasy-${LEAGUE}.json`)); }
  let view = "premiums", pos = "all";
  async function render() {
    content.replaceChildren(leagueBar(() => render()));
    const data = await load();
    if (!data?.players?.length) return content.append(el("p", { class: "loading" }, "SuperCoach data not available for " + LEAGUE.toUpperCase() + "."));
    const positions = ["all", ...[...new Set(data.players.flatMap((p) => p.pos || []))].sort()];
    content.append(el("p", { class: "mut" }, `SuperCoach ${LEAGUE.toUpperCase()} · ${data.count} players · round ${data.round} · proj = season average · updated ${data.generated}`));
    const viewbar = el("div", { class: "subtabs" }, ...FANTASY_VIEWS.map(([id, label]) =>
      el("button", { class: id === view ? "on" : "", onclick: () => { view = id; render(); } }, label)));
    const input = el("input", { class: "search", type: "search", placeholder: "Search players…", autocomplete: "off" });
    const posSel = el("select", {}, ...positions.map((p) => el("option", { value: p, selected: p === pos ? "" : null }, p === "all" ? "All positions" : p)));
    const count = el("span", { class: "count" });
    const desc = el("p", { class: "mut", style: "margin:2px 0 8px;font-size:12.5px" }, FANTASY_VIEWS.find((v) => v[0] === view)[3]);
    content.append(viewbar, desc, el("div", { class: "filters" }, input, posSel, count));
    const host = el("div", { class: "match" }); content.append(host);

    const cols = [
      { key: "name", label: "Player", cls: "pl", get: (r) => r.name, cell: (r) => { const n = parseInt((r.pos_rank || "").replace(/\D/g, ""), 10); return el("td", { class: "pl" }, el("b", {}, r.name), (r.pos_rank && n <= 30) ? el("span", { class: "rankbadge", title: "Rank at position" }, r.pos_rank) : ""); } },
      { key: "team", label: "Team", cls: "", get: (r) => r.team, cell: (r) => el("td", {}, badge(r.team)) },
      { key: "pos", label: "Pos", cls: "mut", get: (r) => (r.pos || []).join("/"), cell: (r) => el("td", { class: "mut" }, (r.pos || []).join("/")) },
      { key: "price", label: "Price", get: (r) => r.price, cell: (r) => el("td", { class: "num" }, money(r.price)) },
      { key: "price_change", label: "Δ", get: (r) => r.price_change, cell: (r) => deltaCell(r.price_change) },
      { key: "proj", label: "Proj", get: (r) => r.proj, cell: (r) => el("td", { class: "num elo" }, r.proj) },
      { key: "captain", label: "Capt", get: (r) => r.captain, cell: (r) => el("td", { class: "num mut" }, r.captain) },
      { key: "value", label: "Value", get: (r) => r.value, cell: (r) => el("td", { class: "num " + valueClass(r.value) }, r.value ?? "—") },
      { key: "ppm", label: "Pts/min", cls: "mut", get: (r) => r.ppm, cell: (r) => el("td", { class: "num mut" }, r.ppm || "—") },
      { key: "owned", label: "Own", cls: "mut", get: (r) => r.owned, cell: (r) => el("td", { class: "num mut" }, (r.owned ?? 0) + "%") },
      { key: "opp", label: "Next", cls: "mut", get: (r) => r.opp, cell: (r) => el("td", { class: "num mut" }, r.opp || "—") },
    ];
    function draw() {
      const q = input.value.trim().toLowerCase();
      let rows = data.players.filter((p) => p.name.toLowerCase().includes(q) && (pos === "all" || (p.pos || []).includes(pos)));
      if (view === "value") rows = rows.filter((p) => p.price >= (LEAGUE === "nbl" ? 150000 : 5_000_000));
      if (view === "movers") rows = [...rows].sort((a, b) => Math.abs(b.price_change) - Math.abs(a.price_change));
      const sortKey = FANTASY_VIEWS.find((v) => v[0] === view)[2];
      const state = { sort: view === "movers" ? null : sortKey, dir: 1, limit: 180, _get: (r) => r[sortKey] };
      if (view === "movers") { count.textContent = Math.min(rows.length, 180) + " shown"; host.replaceChildren(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, el("tr", {}, ...cols.map((c) => el("th", { class: c.cls || "" }, c.label)))), el("tbody", {}, ...rows.slice(0, 180).map((r) => el("tr", {}, ...cols.map((c) => c.cell(r)))))))); return; }
      const sorted = [...rows];
      count.textContent = Math.min(sorted.length, 180) + " of " + rows.length;
      sortableTable(sorted, cols, state, host);
    }
    input.oninput = draw; posSel.onchange = () => { pos = posSel.value; draw(); }; draw();
  }
  render();
}

/* ---------- futures comparison table (model fair vs books) ---------- */
function futuresCompare(rows, books, opts) {
  opts = opts || {};
  const priced = rows.filter((r) => r.books && Object.keys(r.books).length);
  if (opts.valueOnly) rows = priced.filter((r) => (r.edge ?? -1) > 0).sort((a, b) => b.edge - a.edge);
  const head = el("tr", {}, el("th", { class: "pl" }, "Team"), el("th", {}, "Model %"), el("th", {}, "Model fair"),
    ...books.map((b) => el("th", {}, BOOK_LABEL(b))), el("th", {}, "Best"), el("th", {}, "Edge"));
  return el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
    el("thead", {}, head),
    el("tbody", {}, ...rows.map((r) => el("tr", {},
      el("td", { class: "pl" }, el("b", {}, r.team), " ", badge(r.abbr)),
      el("td", { class: "num elo" }, fmtPct(r.model_pct)),
      el("td", { class: "num mut" }, odds(r.model_fair)),
      ...books.map((b) => el("td", { class: "num " + (r.best?.book === b ? "bestbook" : "mut") }, odds(r.books?.[b]))),
      el("td", { class: "num bestbook" }, odds(r.best?.price)),
      el("td", { class: "num " + (r.edge > 0 ? "pos" : r.edge < 0 ? "neg" : "mut") }, r.edge == null ? "—" : (r.edge > 0 ? "+" : "") + (r.edge * 100).toFixed(1) + "%")))))));
}

/* ---------- futures (championship + stat leaders) ---------- */
async function pageFutures(content) {
  const [data, leaders, fodds] = await Promise.all([getJSON("data/futures.json"), getJSON("data/leaders.json"), getJSON("data/futures-odds.json")]);
  let view = "title", cat = "pts";
  function render() {
    content.replaceChildren(leagueBar(render));
    const lg = data?.leagues?.[LEAGUE];
    const ld = leaders?.leagues?.[LEAGUE];
    content.append(el("div", { class: "subtabs" },
      el("button", { class: view === "title" ? "on" : "", onclick: () => { view = "title"; render(); } }, "Championship"),
      el("button", { class: view === "wins" ? "on" : "", onclick: () => { view = "wins"; render(); } }, "Win totals"),
      el("button", { class: view === "leaders" ? "on" : "", onclick: () => { view = "leaders"; render(); } }, "Stat leaders")));

    if (view === "leaders") {
      if (!ld?.cats) return content.append(el("p", { class: "loading" }, "Leaders not available."));
      content.append(el("p", { class: "mut" }, `Model-projected season leaders — each player's per-game rate over a full ${ld.games}-game season.`));
      const catbar = el("div", { class: "subtabs" }, ...Object.entries(ld.cats).map(([k, c]) =>
        el("button", { class: k === cat ? "on" : "", onclick: () => { cat = k; render(); } }, c.label)));
      content.append(catbar);
      const c = ld.cats[cat] || ld.cats.pts;
      content.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", { class: "pl" }, "Player"), el("th", {}, "Team"), el("th", {}, "Per game"), el("th", {}, "Proj season"))),
        el("tbody", {}, ...c.rows.map((r, i) => el("tr", {},
          el("td", { class: "mut" }, i + 1),
          el("td", { class: "pl" }, el("b", {}, r.name)), el("td", {}, badge(r.team)),
          el("td", { class: "num elo" }, r.per_game), el("td", { class: "num mut" }, r.proj_total.toLocaleString()))))))));
      return;
    }

    if (!lg?.teams?.length) return content.append(el("p", { class: "loading" }, "Futures not available."));
    if (view === "wins") {
      content.append(el("p", { class: "mut" }, `Projected regular-season records over a ${lg.games}-game season, sorted by wins.`));
      const wins = [...lg.teams].sort((a, b) => b.proj_wins - a.proj_wins);
      content.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", { class: "pl" }, "Team"), el("th", {}, "Proj W-L"), el("th", {}, "Win %"), el("th", {}, "Playoffs"))),
        el("tbody", {}, ...wins.map((t, i) => el("tr", {},
          el("td", { class: "mut" }, i + 1),
          el("td", { class: "pl" }, el("b", {}, t.name), " ", badge(t.abbr)),
          el("td", { class: "num elo" }, `${t.proj_wins}-${t.proj_losses}`),
          el("td", { class: "num mut" }, fmtPct(t.win_pct)),
          el("td", { class: "num" }, fmtPct(t.playoff_pct)))))))));
      return;
    }
    const fo = fodds?.leagues?.[LEAGUE]?.championship;
    const fbooks = fodds?.books || [];
    if (fo && fo.some((r) => r.books && Object.keys(r.books).length)) {
      content.append(el("p", { class: "mut" }, `Model championship odds vs the bookmakers (${fbooks.map(BOOK_LABEL).join(", ")}). Edge = model probability − best-price implied. Updated ${fodds.generated}.`));
      content.append(futuresCompare(fo, fbooks));
      return;
    }
    content.append(el("p", { class: "mut" }, `Model title & playoff odds from a ${lg.sims.toLocaleString()}-season Monte Carlo (${lg.games}-game season, top-${lg.playoff_teams} playoff).`));
    content.append(el("div", { class: "match" }, el("div", { class: "tablewrap" }, el("table", {},
      el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", { class: "pl" }, "Team"), el("th", {}, "Elo"),
        el("th", {}, "Proj W-L"), el("th", {}, "Playoffs"), el("th", {}, "Title"), el("th", {}, "Title $"))),
      el("tbody", {}, ...lg.teams.map((t) => el("tr", {},
        el("td", { class: "mut" }, t.rank),
        el("td", { class: "pl" }, el("b", {}, t.name), " ", badge(t.abbr)),
        el("td", { class: "num mut" }, t.elo),
        el("td", { class: "num" }, `${t.proj_wins}-${t.proj_losses}`),
        el("td", { class: "num" }, fmtPct(t.playoff_pct)),
        el("td", { class: "num elo" }, fmtPct(t.title_pct)),
        el("td", { class: "num mut" }, odds(t.title_fair)))))))));
  }
  render();
}

/* ---------- boot ---------- */
const PAGES = { home: pageHome, games: pageGames, compare: pageCompare, value: pageValue, pickem: pagePickem, fantasy: pageFantasy, futures: pageFutures, rankings: pageRankings, players: pagePlayers, backtest: pageBacktest, about: pageAbout };
(async function () {
  const page = document.body.dataset.page || "home";
  chrome(page);
  META = await getJSON("data/meta.json");
  if (META && !META.leagues?.[LEAGUE]) LEAGUE = "nba";
  const content = document.getElementById("content");
  if (content && PAGES[page]) {
    content.replaceChildren();
    try { await PAGES[page](content); }
    catch (e) { content.append(el("p", { class: "loading" }, "Something went wrong loading this page.")); console.error(e); }
  }
})();
