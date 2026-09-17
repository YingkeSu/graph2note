#!/bin/bash
# Reproducible browser evidence for the research weekly report (issue 01, F7).
#
# Seeds a throwaway store, pre-generates one research report OFFLINE (injected
# stub planner, never a live model), then serves the real app on loopback so the
# reviewer can drive the same reading view in the AO Browser panel.  The
# injected planner also guards the app: even clicking 生成 cannot reach a live
# model.
#
# Usage:
#   bash scripts/rw01_browser_evidence.sh            # port 8799
#   PORT=8811 bash scripts/rw01_browser_evidence.sh
#
# Then run the printed `ao browser ...` commands.  Ctrl-C stops the server and
# removes the throwaway store.  The user's real library / main checkout are never
# touched.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-$ROOT/.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
PORT="${PORT:-8799}"
STORAGE="$(mktemp -d "${TMPDIR:-/tmp}/rw01-browser.XXXXXX")"
export PYTHONPATH="$ROOT"

echo "== seeding throwaway store: $STORAGE =="
GRAPH2NOTE_STORAGE="$STORAGE" "$PY" - "$STORAGE" <<'PY'
import json, os, sys
from graph2note.store import FileDocumentStore
from graph2note import research_report as rr

storage = sys.argv[1]

def slot(value, source="none"):
    return {"value": value, "source": source, "confidence": None, "evidence": None}

store = FileDocumentStore(storage)
seed = [
    ("doc-a", "信道编码推导", "2026-09-02", "# 信道编码\n香农编码步骤与容量推导。", ["数学"]),
    ("doc-b", "实验备忘", "2026-09-05", "# 备忘\n本周复现实验记录与踩坑。", ["重点"]),
    ("doc-c", "方法笔记", "2026-09-06", "# 方法\n对比两种估计方法。", []),
]
for did, title, date, md, topics in seed:
    store.save_document(
        document_id=did, title=title, source_job_id=f"job-{did}", model="fixture",
        markdown=md, ir_json=json.dumps({"blocks": []}), original_path="",
        original_ext=".jpg", preprocessed_path="", preprocessed_raw_path="",
        assets_dir="", timing_json={},
        metadata={"document_time": slot(date, "manual")})

reply = json.dumps({"sections": {
    "overview": {"markdown": "主线：信道编码容量推导。\n副线：估计方法对比。",
                 "source_document_ids": ["doc-a", "doc-c"]},
    "progress": {"markdown": "（一）信道编码\n- 已知：完成香农编码步骤\n- 待验证：容量数值\n（二）实验\n- 计划：下周复现",
                 "source_document_ids": ["doc-a", "doc-b"]},
    "issues": {"markdown": "", "source_document_ids": []},
    "process": {"markdown": "- 踩坑：环境依赖版本不一致。", "source_document_ids": ["doc-b"]},
}}, ensure_ascii=False)

def planner(prompt, model):
    return {"text": reply, "usage": {}, "model": "stub-text", "provider": "stub"}

records = [store.get_document(s[0]) for s in seed]
rspec = {"kind": "custom", "from": "2026-09-01", "to": "2026-09-07",
         "label": "自定义（2026-09-01 ~ 2026-09-07）"}
result = rr.generate_report(
    records, rspec, storage_dir=storage, planner=planner,
    modules=[{"key": "process", "enabled": True}, {"key": "experiments", "enabled": True}],
    reporter="张三", report_date="2026-09-13")
print("offline report:", result["report"]["report_id"],
      "| sections:", [s["title"] for s in result["sections"]])
PY

# Factory with an injected stub planner so the served app can never call a live model.
cat > "$STORAGE/app_factory.py" <<'PY'
import os
from graph2note.webapp import create_app as _create_app


def _stub(prompt, model):
    return {"text": '{"sections": {}}', "usage": {}, "model": "stub", "provider": "stub"}


def create_app():
    return _create_app(storage_dir=os.environ["GRAPH2NOTE_STORAGE"], digest_planner=_stub)
PY

echo "== serving http://127.0.0.1:$PORT (stub planner; Ctrl-C to stop) =="
GRAPH2NOTE_STORAGE="$STORAGE" PYTHONPATH="$STORAGE:$ROOT" \
  "$PY" -m uvicorn app_factory:create_app --factory --host 127.0.0.1 --port "$PORT" &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true; rm -rf "$STORAGE"' EXIT

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/api/digests" >/dev/null 2>&1; then break; fi
  sleep 0.25
done

cat <<EOF

== reproducible browser evidence ==
export AO=/Applications/Agent Orchestrator.app/Contents/Resources/daemon/ao
"\$AO" browser open "http://127.0.0.1:$PORT/#reports"
"\$AO" browser wait --selector "#report-section-overview" --timeout 15000
"\$AO" browser get text "#report-viewer-content"      # sections / sources / stats / budget
"\$AO" browser get text "#report-viewer-meta"          # template · range · reporter · date · llm mode
"\$AO" browser errors                                  # expect: no console errors
"\$AO" browser screenshot /tmp/rw01-report.png          # if the screenshot service is available

Expected text: "1、本周概览", "2、本周进展", "3、过程记录", "4、问题与求助",
"附录：来源材料", "汇报人：张三", "材料预算", and source chips for 信道编码推导/实验备忘/方法笔记.
The enabled 实验结果 module has no evidence in this fixture, so it is intentionally absent.

Press Ctrl-C to stop the server and delete the throwaway store.
EOF

wait "$SERVER"
