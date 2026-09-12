#!/usr/bin/env bash
# U4 evidence capture (offline, local only).
#
# Seeds a 43-document library, serves the local app, then captures before/after
# screenshots + DOM measurements of the knowledge graph:
#   before = `main` graph.js (pre-U4 single-pass layout)
#   after  = this branch (force layout, zoom/pan, filters, clusters, focus)
#
# Usage: bash scripts/u4_capture_evidence.sh [port] [workdir]
# Requires: uv, node, Google Chrome (macOS path below).
set -euo pipefail

PORT="${1:-8791}"
WORKDIR="${2:-/tmp/u4-evidence}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
CHROME="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
STORAGE="$WORKDIR/storage"

cd "$REPO"
mkdir -p "$WORKDIR"

# 1) seed a deterministic 43-document library
uv run python scripts/seed_u4_evidence.py "$STORAGE"

# 2) serve it
GRAPH2NOTE_STORAGE="$STORAGE" uv run uvicorn graph2note.webapp:create_app \
  --factory --port "$PORT" --host 127.0.0.1 > "$WORKDIR/server.log" 2>&1 &
SERVER_PID=$!
trap 'kill "$SERVER_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT/api/graph" > /dev/null && break
  sleep 0.25
done

# 3) after (this branch): CDP metrics + `visual-qa capture` screenshot
node scripts/u4_graph_probe.mjs "$CHROME" "http://127.0.0.1:$PORT/#graph" \
  "$WORKDIR/graph-after.png" "$WORKDIR/graph-after.json"
uv run graph2note visual-qa capture "http://127.0.0.1:$PORT/#graph" \
  -o "$WORKDIR/graph-after.png" --viewport 1440x1000 --chrome-bin "$CHROME"

# 4) before (main's graph.js) — swap in the pre-U4 view without touching the test suite
cp graph2note/webstatic/js/views/graph.js "$WORKDIR/graph-after.js"
git show "main:graph2note/webstatic/js/views/graph.js" > graph2note/webstatic/js/views/graph.js
node scripts/u4_graph_probe.mjs "$CHROME" "http://127.0.0.1:$PORT/#graph" \
  "$WORKDIR/graph-before.png" "$WORKDIR/graph-before.json"
uv run graph2note visual-qa capture "http://127.0.0.1:$PORT/#graph" \
  -o "$WORKDIR/graph-before.png" --viewport 1440x1000 --chrome-bin "$CHROME"
cp "$WORKDIR/graph-after.js" graph2note/webstatic/js/views/graph.js
rm -f "$WORKDIR/graph-after.js"

# 5) summarise
uv run python scripts/u4_evidence_metrics.py "$WORKDIR"
echo "evidence written to $WORKDIR"
