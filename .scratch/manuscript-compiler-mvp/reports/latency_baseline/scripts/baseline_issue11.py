"""Issue 11 基线实测：graph2note parse 管线分阶段计时。

数据源：worker 3 的评估集 `eval/fixtures/data/`（30 页，只读）。
- 全 30 页：预处理阶段计时（离线，无 LLM）。
- 子集 5 页（横跨 5 类且均有 gold）：整页 pipeline 分阶段计时（preprocess/llm/render + 
  reasoning_tokens），用 env GRAPH2NOTE_OPENCODE_SESSION 控制会话：
    * before = graph2note-parse-route-a（旧产品会话）
    * after  = 默认（已验证 graph2note-spike-01，收敛后）
写证据到 reports/latency_baseline/data/。含实时 LLM 调用，live 预算内。

用法：
    source <repo>/.env         # 加载 OPENCODE_API_KEY（不从库）
    export GRAPH2NOTE_OPENCODE_SESSION=graph2note-parse-route-a   # before（after 则 unset）
    python baseline_issue11.py <worker3_repo> [--pages-only]
"""

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = None
for _p in Path(__file__).resolve().parents:
    if (_p / "pyproject.toml").exists() and (_p / "graph2note" / "pipeline.py").exists():
        REPO = str(_p)
        break
assert REPO, "cannot locate repo root"
sys.path.insert(0, REPO)

from graph2note import pipeline  # noqa: E402
from graph2note import preprocess as pp  # noqa: E402

MODEL = "glm-5.3-flash"
LIVE_SUBSET = ["A02", "A09", "A10", "A13", "A15"]  # formula/strikethrough/mixed/flowchart/handwriting
HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
OUT.mkdir(parents=True, exist_ok=True)


def list_dataset_n(worker3_root):
    data_dir = Path(worker3_root) / "eval" / "fixtures" / "data"
    return sorted(p for p in data_dir.glob("*.jpg")), data_dir


def measure_preprocess_all(images, data_dir, worker3_root):
    """Stage 0: preprocess timing across all 30 (offline)."""
    meta_path = Path(worker3_root) / "eval" / "fixtures" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    smap = {s["id"]: s for s in meta["samples"]}
    rows = []
    scratch = OUT / "preprocess_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    for img in images:
        pid = img.stem
        t0 = time.monotonic()
        prep = pp.preprocess_image(str(img), str(scratch), save_stages=False)
        sec = time.monotonic() - t0
        rows.append({
            "id": pid,
            "category": smap.get(pid, {}).get("category"),
            "seconds": round(sec, 4),
            "image_bytes": os.path.getsize(img),
        })
    rows.sort(key=lambda r: r["seconds"])
    n = len(rows)
    p50 = statistics.median([r["seconds"] for r in rows])
    p95 = sorted([r["seconds"] for r in rows])[max(0, int(0.95 * n) - 1)]
    summary = {
        "n": n,
        "stage": "preprocess",
        "p50": round(p50, 4),
        "p95": round(p95, 4),
        "max": rows[-1]["seconds"],
        "total": round(sum(r["seconds"] for r in rows), 4),
        "rows": rows,
    }
    (OUT / "preprocess_30pages.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[offline] preprocess over {n} pages: p50={p50:.3f}s p95={p95:.3f}s total={summary['total']:.2f}s")
    return summary


def measure_parse_subset(data_dir, worker3_root, session_label):
    """Live: full parse on the 5-page subset (before/after by session)."""
    meta_path = Path(worker3_root) / "eval" / "fixtures" / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    smap = {s["id"]: s for s in meta["samples"]}
    rows = []
    for pid in LIVE_SUBSET:
        img = data_dir / f"{pid}.jpg"
        if not img.exists():
            print(f"[!] missing {pid}")
            continue
        out = OUT / "parse_scratch" / session_label / pid
        t_start = time.monotonic()
        try:
            res = pipeline.parse_document(str(img), str(out), model=MODEL, preprocess=True,
                                          save_preprocess_stages=False)
        except Exception as exc:
            rows.append({"id": pid, "error": str(exc)})
            print(f"[{session_label}] {pid}: ERROR {exc}")
            continue
        e2e = time.monotonic() - t_start
        tj = res.timing_json
        stage_sec = {s["name"]: s["seconds"] for s in tj.get("stages", [])}
        llm = tj.get("llm", {})
        rows.append({
            "id": pid,
            "category": smap.get(pid, {}).get("category"),
            "e2e_seconds": round(e2e, 3),
            "preprocess_seconds": stage_sec.get("preprocess"),
            "llm_seconds": stage_sec.get("llm"),
            "render_seconds": stage_sec.get("render"),
            "timing_total": tj.get("total_seconds"),
            "llm_retries": llm.get("retries"),
            "llm_sum_latency": llm.get("sum_llm_latency_seconds"),
            "max_reasoning_tokens": llm.get("max_reasoning_tokens"),
            "attempts": llm.get("attempts"),
        })
        print(f"[{session_label}] {pid} ({smap.get(pid,{}).get('category')}): e2e={e2e:.2f}s "
              f"pre={stage_sec.get('preprocess')} llm={stage_sec.get('llm')} render={stage_sec.get('render')} "
              f"reasoning={llm.get('max_reasoning_tokens')} retries={llm.get('retries')}")
    ok = [r for r in rows if "error" not in r]
    if ok:
        p50 = statistics.median([r["e2e_seconds"] for r in ok])
        p95 = sorted([r["e2e_seconds"] for r in ok])[max(0, int(0.95 * len(ok)) - 1)]
        summary = {
            "session": session_label,
            "model": MODEL,
            "n": len(ok),
            "e2e_p50": round(p50, 3),
            "e2e_p95": round(p95, 3),
            "rows": rows,
        }
    else:
        summary = {"session": session_label, "rows": rows}
    (OUT / f"parse_{session_label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{session_label}] e2e p50={p50:.2f}s p95={p95:.2f}s (n={len(ok)})")
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("worker3_root")
    ap.add_argument("--pages-only", action="store_true", help="skip the 30-page preprocess pass")
    args = ap.parse_args()

    images, data_dir = list_dataset_n(args.worker3_root)
    session_label = os.environ.get("GRAPH2NOTE_OPENCODE_SESSION", "after-validated-session")
    print(f"worker3_data={data_dir} ({len(images)} pages); session_label={session_label}")

    if not args.pages_only:
        measure_preprocess_all(images, data_dir, args.worker3_root)
    measure_parse_subset(data_dir, args.worker3_root, session_label)


if __name__ == "__main__":
    main()