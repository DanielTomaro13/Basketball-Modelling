#!/bin/bash
# Basketball Models — local odds + site refresh, run from an AU IP every 3h by a
# launchd agent. The Australian books (Sportsbet, TAB, PointsBet, Dabble,
# Ladbrokes) geo-block GitHub's US runners, so the live odds scrape must run
# locally. This re-runs the full pipeline (model is stdlib + fast) including the
# odds step, then commits and pushes; GitHub Pages redeploys from /docs on push.
#
# Model data + fixtures also refresh in CI (.github/workflows/daily.yml) so the
# site stays current when the laptop is asleep — just without live odds.
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
BOT="/Users/danieltomaro/sports-bots"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# curl_cffi (for TAB/PointsBet/Dabble) lives in the shared venv; falls back to system python.
PY="$BOT/nrl-venv/bin/python"; [ -x "$PY" ] || PY="$(command -v python3)"
cd "$REPO" || exit 1
LOG="$REPO/scripts/odds-cron.log"
ts() { date "+%Y-%m-%d %H:%M:%S"; }
exec >>"$LOG" 2>&1
echo "===== $(ts) basketball odds-cron start ($REPO) ====="

# Shared bookmaker creds (TAB_*, DABBLE_*, LAD_*) — same file AFL/NRL/Tennis use.
set -a; [ -f "$BOT/secrets.env" ] && . "$BOT/secrets.env"; set +a

git pull --rebase --autostash origin main || { echo "$(ts) pull failed"; exit 1; }

# Full pipeline incl. the odds step (best-effort per book).
"$PY" -m src.run_daily || { echo "$(ts) run_daily failed"; exit 1; }

git add -A docs reports data/fixtures.csv models
if git diff --cached --quiet; then
  echo "$(ts) no changes — nothing to push"; exit 0
fi
git config user.name  "basketball-odds-bot"
git config user.email "basketball-odds-bot@localhost"
git commit -m "Refresh odds + site (local AU scrape $(date -u +%Y-%m-%dT%H:%MZ))"

for i in 1 2 3 4 5; do
  if git push origin HEAD:main; then echo "$(ts) pushed (attempt $i)"; exit 0; fi
  echo "$(ts) push rejected (attempt $i) — rebasing..."
  git pull --rebase --autostash -X ours origin main || { echo "$(ts) rebase failed"; exit 1; }
done
echo "$(ts) failed to push after 5 attempts"; exit 1
