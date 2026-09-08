#!/usr/bin/env python3
"""Issue 10 — manual cross-validation driver over the eval-sample images.

Runs ``cross_validate`` on each document image with a reply cache under
``out/10/cache`` so the *model calls happen once* (2 images x 2 models = 4
live calls, within the issue's sanctioned budget) and every subsequent run is
offline.  Writes, per image, ``verify.<stem>.{json,md}`` plus an aggregated
``out/10/report.json`` covering the divergence-rate AC metric.

Usage:
    ./.venv-spike3/bin/python scripts/verify_manual.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from graph2note.verify import cross_validate  # noqa: E402
from graph2note.verify import report as _report  # noqa: E402
from graph2note.verify import model as _model  # noqa: E402
from graph2note import vlm  # noqa: E402

SAMPLES = [
    ROOT / "test-images" / "01-requirements-arch.jpg",
    ROOT / "test-images" / "02-digitize-pipeline.jpg",
]
MODEL_A = "glm-5.3-flash"
MODEL_B = "deepseek-v4-flash-vision-exp"
OUT = ROOT / "out" / "10"
CACHE = OUT / "cache"


def divergence_rate(rep) -> float:
    total = sum(rep.diff.counts.values())
    if not total:
        return 0.0
    return round((1 - rep.diff.counts[_model.CONSISTENT] / total) * 100, 2)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = vlm.VlmCache(str(CACHE))
    rows = []
    for img in SAMPLES:
        print(f"[verify] {img.name} ...", file=sys.stderr)
        rep = cross_validate(str(img), model_a=MODEL_A, model_b=MODEL_B,
                             cache=cache)
        stem = img.stem
        (OUT / f"verify.{stem}.md").write_text(
            _report.to_markdown(rep, include_raw=True), encoding="utf-8")
        (OUT / f"verify.{stem}.json").write_text(
            _report.to_json(rep), encoding="utf-8")
        rows.append({
            "image": img.name,
            "verified": rep.verified,
            "note": rep.note,
            "counts": rep.diff.counts,
            "order_changed": rep.diff.order_changed,
            "duplicates_a": len(rep.duplicates_a),
            "duplicates_b": len(rep.duplicates_b),
            "divergence_rate_%": divergence_rate(rep),
            "warnings": rep.warnings,
        })
        print(f"  verified={rep.verified} "
              f"counts={rep.diff.counts} rate={rows[-1]['divergence_rate_%']}%",
              file=sys.stderr)

    summary = {
        "models": {"a": MODEL_A, "b": MODEL_B},
        "cached_offline": [r for r in rows if True],
        "rows": rows,
        "note": (
            "Divergence rate = 非一致块占全部已对齐块的比例（非一致块 = "
            "单侧出现 + 不一致）。仅作选型/调优的横向参考，非绝对准确率。"
        ),
    }
    (OUT / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# Issue 10 交叉验证实跑记录", "",
          f"- 评估集样本: {[r['image'] for r in rows]}",
          f"- 模型 A: {MODEL_A} / 模型 B: {MODEL_B}", "",
          "| 图像 | 验证 | 一致 | 单侧 | 不一致 | 顺序差 | 重复A/B | 分歧率% |",
          "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c = r["counts"]
        md.append(f"| {r['image']} | {'✅' if r['verified'] else '⚠️'} | "
                  f"{c[_model.CONSISTENT]} | {c[_model.ONE_SIDE]} | "
                  f"{c[_model.CONFLICT]} | {r['order_changed']} | "
                  f"{r['duplicates_a']}/{r['duplicates_b']} | "
                  f"{r['divergence_rate_%']} |")
    if not all(r["verified"] for r in rows):
        md += ["", "> 存在降级样本（未验证），请人工复核对应 verify.*.md。"]
    (OUT / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'report.json'} and {OUT / 'summary.md'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())