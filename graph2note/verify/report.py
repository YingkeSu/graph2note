"""Render a cross-validation report to JSON and a readable Markdown (issue 10).

The Markdown form is the "按块聚合、不逐条刷屏" human reading: top summary
counters, then each divergence class aggregated into a table.  The JSON form is
the machine shape that issue 06's reserved verification display slot (and
notes-organizer traceability) consume.
"""

from __future__ import annotations

import json
from typing import Optional

from . import text
from .model import (
    CrossValidationReport,
    DiffBlock,
    BlockDiff,
    CONSISTENT,
    ONE_SIDE,
    CONFLICT,
)

_TAG_LABEL = {
    CONSISTENT: "双侧一致 (高置信)",
    ONE_SIDE: "单侧出现 (疑似漏识别)",
    CONFLICT: "不一致 (内容冲突)",
}
_SIDE_LABEL = {
    "a": "A",
    "b": "B",
    "both": "两",
}


def to_json(report: CrossValidationReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def to_markdown(
    report: CrossValidationReport,
    *,
    include_raw: bool = False,
) -> str:
    L: list[str] = []
    L.append("# 交叉验证分歧报告")
    L.append("")
    L.append(f"- 来源: `{report.source}`")
    L.append(f"- 模型 A: `{report.model_a}`　模型 B: `{report.model_b}`")
    L.append(f"- 验证状态: {'✅ 双模型完成' if report.verified else '⚠️ 未验证（降级单模型）'}")
    if report.note:
        L.append(f"- 说明: {report.note}")
    L.append("")

    c = report.diff.counts
    L.append("## 汇总")
    L.append("")
    L.append("| 类别 | 块数 |")
    L.append("|---|---|")
    L.append(f"| 双侧一致 (高置信) | {c[CONSISTENT]} |")
    L.append(f"| 单侧出现 (疑似漏识别) | {c[ONE_SIDE]} |")
    L.append(f"| 不一致 (内容冲突) | {c[CONFLICT]} |")
    L.append(f"| 顺序差异 | {'是' if report.diff.order_changed else '否'} |")
    L.append("")

    _section(L, "双侧一致（高置信）", report.diff.consistent, "//★")
    _section(L, "单侧出现（疑似漏识别）", report.diff.one_side, "⚠未")
    _section(L, "不一致（内容冲突）", report.diff.conflict, "✕", include_raw=include_raw)

    if report.duplicates_a or report.duplicates_b:
        L.append("## 文档内近重复块")
        L.append("")
        for group in report.duplicates_a + report.duplicates_b:
            side = "A" if group in report.duplicates_a else "B"
            L.append(f"- [{side}] `{group.block_type}` 块 {group.indexes} "
                     f"（相似度 {group.similarity}）：`{group.representative_text[:60]}`")
        L.append("")
    return "\n".join(L)


def _section(L: list, title: str, items: list[DiffBlock], mark: str,
             include_raw: bool = False):
    if not items:
        L.append(f"## {title}")
        L.append("")
        L.append("（无）")
        L.append("")
        return
    L.append(f"## {title}")
    L.append("")
    L.append("| # | 块类型 | 位置 | 文本 |")
    L.append("|---|--------|------|------|")
    for i, d in enumerate(items, 1):
        pos = f"A:{(d.index_a + 1) if d.index_a is not None else '-'} / " \
              f"B:{(d.index_b + 1) if d.index_b is not None else '-'}"
        show = (d.text_a or d.text_b or "").replace("|", "\\|")
        show = show[:80] + ("…" if len(show) > 80 else "")
        sim = f" (sim={d.similarity})" if d.similarity is not None else ""
        L.append(f"| {i} | `{d.block_type}` | {pos} | {show}{sim} |")
    L.append("")
    if include_raw and any(
            d.similarity is not None and d.similarity < 1.0 for d in items):
        L.append("### 冲突对（A 原文 / B 原文）")
        L.append("")
        for d in items:
            if d.similarity is not None and d.similarity < 1.0:
                a = (d.text_a or "").replace("\n", " ")[:200]
                b = (d.text_b or "").replace("\n", " ")[:200]
                L.append(f"- A: `{a}`")
                L.append(f"  B: `{b}`")
        L.append("")


__all__ = ["to_json", "to_markdown"]