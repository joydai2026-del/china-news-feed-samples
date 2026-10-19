#!/usr/bin/env bash
# Rebuild docs/ ("Deleted today / 今日被删" GitHub Pages site) from the live pipeline output and push it.
# Usage: tools/publish_deleted_today.sh   (env: CMF_OUTPUT, PAGES_REPO_DIR, WINDOW_HOURS)
set -euo pipefail
OUT="${CMF_OUTPUT:-/workspace/china-feed-run/output}"
REPO="${PAGES_REPO_DIR:-/workspace/cmf-growth/pages-repo}"
HOURS="${WINDOW_HOURS:-24}"
if [ ! -d "$REPO/.git" ]; then gh repo clone joydai2026-del/china-news-feed-samples "$REPO" -- -q; fi
cd "$REPO"
git fetch -q origin main && git checkout -q main && git reset -q --hard origin/main
python3 tools/build_deleted_today.py "$OUT/censored.json" docs --hours "$HOURS" --feed-en "$OUT/feed_en.json"
git add docs
if git diff --cached --quiet; then echo "no change"; exit 0; fi
git commit -q -m "Deleted today: rebuild $(TZ=America/New_York date '+%Y-%m-%d %H:%M ET')"
git push -q origin main
echo "pushed: https://joydai2026-del.github.io/china-news-feed-samples/"
