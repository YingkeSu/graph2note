#!/usr/bin/env python3
"""Route A vs Route B 对比（issue 08）：同一 30 页评估集，分维度 A/B 指标。

- Route A：直接复用 worker3 已录制的 glm-5.3-flash 直出 Markdown 缓存（零新增视觉调用）。
- Route B：图片 -> tesseract OCR（本地）-> 文本 LLM 结构化（glm-5.3-flash，routeb 独立
  session，live 文本调用一次/页，走缓存，预算<=31；见 GRAPH2NOTE_ROUTE_B_CACHE）。
- 印刷维：评估集无真实印刷页，如实标注 Route A 样本=0（N/A），另生成少量合成印刷样本
  （PIL 渲染，方法见报告）只跑 Route B 以展示其在清印刷上的表现。

用法（source .env 后）：
  python scripts/run_route_b_ab.py [--route-a-glm-cache DIR] [--live]
默认 --live 会真正调用文本 LLM（预算内）；不带 --live 且无缓存时 Route B 记为（未运行）。
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))

from eval import editerate  # noqa: E402
from eval.dataset import CATEGORIES, CATEGORY_ORDER, load_dataset, read_gold  # noqa: E402

DEFAULT_ROUTE_A_CACHE = Path("/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-3/eval/cache")
ROUTE_B_CACHE = REPO / "eval" / "cache" / "routeb"
ROUTE_B_MODEL = os.environ.get("GRAPH2NOTE_ROUTE_B_MODEL", "glm-5.3-flash")
MAX_ROUTE_B_CALLS = 35

_gold_id = re.compile(r"glm-5.3-flash__.*__([A-Z0-9]+)\.json")


def edit_rate(gold: str, pred: str) -> float:
    return editerate.compute_edit_distance(gold, pred).edits / max(len(gold), 1)


def load_route_a(glm_cache: Path, sample_id: str) -> str | None:
    """从 glm 缓存读 Route A 直出 Markdown（零新增视觉调用）。"""
    for c in glm_cache.iterdir():
        m = _gold_id.match(c.name)
        if m and m.group(1) == sample_id:
            return json.loads(c.read_text(encoding="utf-8")).get("prediction", "")
    return None


def route_b_markdown(image_path: str, sample_id: str, *, live: bool) -> tuple[str | None, dict]:
    """Route B：读缓存；无缓存且 live=True 时真正跑 OCR+文本 LLM（max_retries=0，一次/页）。"""
    p = ROUTE_B_CACHE / f"{sample_id}.json"
    info: dict = {}
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        return d["markdown"], d
    if not live:
        return None, {"mode": "not_run"}
    from graph2note.route_b import route_b_chain
    res = route_b_chain(image_path, ROUTE_B_MODEL, max_retries=0)
    markdown = res.raw_content
    mode = "structured" if not any("fell back" in w for w in res.warnings) else "fallback_ocr"
    info = {
        "mode": mode,
        "ocr_chars": (res.attempts[0] if res.attempts else {}).get("chars", 0),
        "blocks": len(res.document.blocks) if res.document else 0,
        "warnings": res.warnings,
        "text_status": (res.attempts[1]["meta"].get("status") if len(res.attempts) > 1 else None),
        "reasoning": (res.attempts[1]["meta"].get("reasoning_tokens") if len(res.attempts) > 1 else None),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"markdown": markdown, **info}, ensure_ascii=False, indent=2), encoding="utf-8")
    return markdown, info


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--route-a-glm-cache", default=str(DEFAULT_ROUTE_A_CACHE))
    ap.add_argument("--live", action="store_true", help="允许真正调用文本 LLM（预算内）")
    args = ap.parse_args()

    glm_cache = Path(args.route_a_glm_cache)
    dataset = load_dataset()
    rows = []
    calls = 0
    for s in dataset:
        route_a = load_route_a(glm_cache, s.id)
        route_b_md, b_info = route_b_markdown(s.image_path, s.id, live=args.live)
        gold = read_gold(s)
        calls += 1 if (route_b_md and args.live and b_info.get("mode") not in ("not_run",)) else 0
        rows.append({
            "id": s.id, "category": s.category,
            "route_a": edit_rate(gold, route_a) if route_a is not None else None,
            "route_b": edit_rate(gold, route_b_md) if route_b_md is not None else None,
            "route_b_mode": b_info.get("mode"),
            "route_b_blocks": b_info.get("blocks"),
            "ocr_chars": b_info.get("ocr_chars"),
            "text_reasoning": b_info.get("reasoning"),
            "route_a_cached": bool(route_a),
        })

    # 聚合（仅 OK 样本：有 gold 且目标路线有 pred）
    summary = {"categories": [], "totals": {}}
    for cat in CATEGORY_ORDER:
        items = [r for r in rows if r["category"] == cat]
        ra = [r["route_a"] for r in items if r["route_a"] is not None and (r["route_a_cached"])]
        rb = [r["route_b"] for r in items if r["route_b"] is not None]
        summary["categories"].append({
            "category": cat, "label": CATEGORIES[cat], "n": len(items),
            "route_a_n": len(ra), "route_a_mean": round(sum(ra) / len(ra), 4) if ra else None,
            "route_b_n": len(rb), "route_b_mean": round(sum(rb) / len(rb), 4) if rb else None,
        })
    all_a = [r["route_a"] for r in rows if r["route_a"] is not None and r["route_a_cached"]]
    all_b = [r["route_b"] for r in rows if r["route_b"] is not None]
    summary["totals"] = {
        "route_a_n": len(all_a), "route_a_mean": round(sum(all_a) / len(all_a), 4) if all_a else None,
        "route_b_n": len(all_b), "route_b_mean": round(sum(all_b) / len(all_b), 4) if all_b else None,
    }

    out = REPO / ".scratch" / "manuscript-compiler-mvp" / "reports" / "route-b" / "scripts" / "data"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ab_summary.json").write_text(json.dumps({
        "rows": rows, "summary": summary, "route_b_calls_this_run": calls,
        "route_b_total_calls_ceiling": MAX_ROUTE_B_CALLS,
        "note": "route_b max_retries=0：文本 LLM 一次/页，空/拒绝即回退原始 OCR（确定性预算）",
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{'cat':<14}{'n':>3}  A_ok  A_mean   B_ok B_mean")
    for c in summary["categories"]:
        a = "-" if c["route_a_mean"] is None else f"{c['route_a_mean']:.3f}"
        b = "-" if c["route_b_mean"] is None else f"{c['route_b_mean']:.3f}"
        print(f"{c['label']:<14}{c['n']:>3}  {c['route_a_n']:>4}  {a:>6}  {c['route_b_n']:>4} {b}")
    t = summary["totals"]
    a = "-" if t["route_a_mean"] is None else f"{t['route_a_mean']:.3f}"
    b = "-" if t["route_b_mean"] is None else f"{t['route_b_mean']:.3f}"
    print(f"{'TOTAL':<14}{len(rows):>3}  {t['route_a_n']:>4}  {a}  {t['route_b_n']:>4} {b}")
    print(f"route_b live calls this run: {calls} (ceiling {MAX_ROUTE_B_CALLS})")
    print(f"wrote {out / 'ab_summary.json'}")


if __name__ == "__main__":
    main()