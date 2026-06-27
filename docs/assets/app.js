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

let LEAGUE = localStorage.getItem("bb_league") || "nba";

/* ---------- chrome ---------- */
const NAV = [
  ["home", "Home", "index.html"], ["games", "Games", "games.html"],
  ["value", "Value", "value.html"], ["rankings", "Rankings", "rankings.html"],
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
  const data = await getJSON("data/odds.json");
  function render() {
    content.replaceChildren(leagueBar(render));
    const picks = valuePicks(data, LEAGUE);
    if (!data || !data.games?.length)
      return content.append(el("p", { class: "loading" }, "No bookmaker odds loaded yet — they open closer to game time. Every game still shows the model's fair price on the Games page."));
    content.append(el("p", { class: "mut" }, `Books: ${(data.books || []).join(", ") || "—"} · updated ${data.generated}`));
    content.append(el("div", { class: "group-head" }, el("h2", {}, "Positive expected value"), el("span", { class: "muted" }, picks.length + " selections")));
    if (picks.length) content.append(valueTable(picks));
    else content.append(el("p", { class: "loading" }, "No positive-EV selections for " + LEAGUE.toUpperCase() + " right now."));
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
    content.append(el("div", { class: "filters" }, input, count));
    const host = el("div", { class: "match" }); content.append(host);
    function draw() {
      const q = input.value.trim().toLowerCase();
      const rows = index.filter((p) => p.league === LEAGUE && p.name.toLowerCase().includes(q))
        .map((p) => players?.[LEAGUE]?.[p.id]).filter(Boolean)
        .sort((a, b) => b.pts - a.pts).slice(0, 140);
      count.textContent = rows.length + " shown";
      host.replaceChildren(el("div", { class: "tablewrap" }, el("table", {},
        el("thead", {}, el("tr", {}, el("th", { class: "pl" }, "Player"), el("th", {}, "Team"), el("th", {}, "GP"), el("th", {}, "Min"),
          el("th", {}, "Pts"), el("th", {}, "Reb"), el("th", {}, "Ast"), el("th", {}, "3PM"), el("th", {}, "Stl"), el("th", {}, "Blk"))),
        el("tbody", {}, ...rows.map((p) => el("tr", {},
          el("td", { class: "pl" }, el("b", {}, p.name)), el("td", { class: "mut" }, el("span", { class: "pill" }, p.team)),
          el("td", { class: "mut" }, p.gp), el("td", { class: "mut" }, p.min),
          el("td", {}, p.pts), el("td", {}, p.reb), el("td", {}, p.ast), el("td", {}, p.fg3m),
          el("td", {}, p.stl), el("td", {}, p.blk)))))));
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

/* ---------- boot ---------- */
const PAGES = { home: pageHome, games: pageGames, value: pageValue, rankings: pageRankings, players: pagePlayers, backtest: pageBacktest, about: pageAbout };
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
