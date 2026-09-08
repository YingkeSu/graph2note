"""评估 harness 主逻辑：对指定模型在评估集上直转 Markdown 并计算 EditRate。

流程：图片 -> VLM -> Markdown 直出（本 spike 是直转对比，无 IR）
     -> 与 gold 做字符级 diff -> EditRate + 分类目指标 -> 报告。

缓存：同图同模型的结果落盘缓存（pred + meta），不重复调用 LLM。
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime, timezone

from . import editerate
from .dataset import CATEGORIES, CATEGORY_ORDER, REPO_ROOT, Sample, load_dataset, read_gold
from .gateway import cache_namespace, transcribe_with_policy

# 缓存目录：eval/cache/。报告落盘：eval/reports/。
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")


class EvalRun:
    def __init__(self, model: str, dataset: list[Sample] | None = None):
        self.model = model
        self.samples = dataset or load_dataset()
        self.results = []  # dict per sample

    def run(self, *, use_cache: bool = True) -> list[dict]:
        os.makedirs(CACHE_DIR, exist_ok=True)
        for sample in self.samples:
            self.results.append(self._run_one(sample, use_cache=use_cache))
        return self.results

    def _cache_path(self, sample: Sample) -> str:
        safe = self.model.replace("/", "_")
        # 缓存指纹：prompt/预算/降采样参数变化时旧缓存失效（img+model+prompt 指纹）。
        ns = cache_namespace()
        return os.path.join(CACHE_DIR, f"{safe}__{ns}__{sample.id}.json")

    def _run_one(self, sample: Sample, *, use_cache: bool) -> dict:
        cache_path = self._cache_path(sample)
        if use_cache and os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as fh:
                cached = json.load(fh)
            pred = cached["prediction"]
            meta = cached["meta"]
            meta["cached"] = True
        else:
            try:
                pred, meta = transcribe_with_policy(sample.image_path, self.model)
                meta["cached"] = False
                meta["retried"] = bool(meta.get("retried"))
            except Exception as exc:  # 配置/解析异常 surfaced into the report
                pred = ""
                meta = {"status": "error", "error": str(exc), "cached": False}
            if pred:
                with open(cache_path, "w", encoding="utf-8") as fh:
                    json.dump({"prediction": pred, "meta": meta}, fh, ensure_ascii=False, indent=2)

        gold = read_gold(sample) if sample.gold else ""
        result = {
            "id": sample.id,
            "category": sample.category,
            "gold_proofed": sample.gold_proofed,
            "image": sample.image,
            "prediction": pred,
            "gold": gold,
            "meta": meta,
            **self._metrics(gold, pred),
        }
        return result

    @staticmethod
    def _metrics(gold: str, pred: str) -> dict:
        ed = editerate.compute_edit_distance(gold, pred)
        return {
            "edits": ed.edits,
            "insertions": ed.insertions,
            "deletions": ed.deletions,
            "substitutions": ed.substitutions,
            "gold_chars": len(gold),
            "pred_chars": len(pred),
            "edit_rate": ed.edits / max(len(gold), 1),
        }

    def category_summary(self) -> list[dict]:
        by_cat: dict[str, list[dict]] = defaultdict(list)
        for r in self.results:
            by_cat[r["category"]].append(r)
        rows = []
        for cat in CATEGORY_ORDER:
            items = by_cat.get(cat, [])
            if not items:
                rows.append(
                    {
                        "category": cat,
                        "label": CATEGORIES[cat],
                        "count": 0,
                        "mean_edit_rate": None,
                        "min_edit_rate": None,
                        "max_edit_rate": None,
                        "unproofed_gold": 0,
                    }
                )
                continue
            rates = [r["edit_rate"] for r in items]
            rows.append(
                {
                    "category": cat,
                    "label": CATEGORIES[cat],
                    "count": len(items),
                    "mean_edit_rate": round(sum(rates) / len(rates), 4),
                    "min_edit_rate": round(min(rates), 4),
                    "max_edit_rate": round(max(rates), 4),
                    "unproofed_gold": sum(0 if r["gold_proofed"] else 1 for r in items),
                }
            )
        return rows


# ---------- 报告渲染 ----------

def format_markdown_table(rows: list[dict]) -> str:
    if not rows:
        return "_(空)_"
    headers = list(rows[0].keys())
    lines = ["| " + " | ".join(str(h) for h in headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for row in rows:
        cells = []
        for h in headers:
            v = row[h]
            if isinstance(v, float):
                cells.append(f"{v:.4f}")
            elif v is None or v == "":
                cells.append("—")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build_report(run: EvalRun, model: str) -> str:
    lines = []
    lines.append(f"# 视觉模型评估报告（Spike 1 — {model}）")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"- 模型: `{model}`")
    lines.append(f"- 样本数: {len(run.samples)}")
    n_unproofed = sum(0 if r["gold_proofed"] else 1 for r in run.results)
    if n_unproofed:
        lines.append(
            f"- ⚠️ **{n_unproofed} 份 gold 为 AI 草拟、未经人工校对（HITL 待维护者）**"
        )
    lines.append("")

    real = [r for r in run.results if r["meta"].get("status", "ok") != "error"]
    if real:
        overall = sum(r["edit_rate"] for r in real) / len(real)
        total_edits = sum(r["edits"] for r in real)
        total_chars = sum(r["gold_chars"] for r in real)
    else:
        overall, total_edits, total_chars = 0.0, 0, 0
    lines.append("## 总体 EditRate")
    lines.append("")
    lines.append(f"- 样本均值 EditRate: **{overall:.4f}** ({overall*100:.2f}%)")
    lines.append(f"- 聚合 EditRate（Σ编辑字符 / Σgold 字符）: {total_edits / max(total_chars, 1):.4f} | Σ编辑字符 {total_edits} / Σgold 字符 {total_chars}")
    lines.append(f"- 目标: < 5.0% (SC-001)")
    lines.append("")

    lines.append("## 分类目指标")
    lines.append("")
    lines.append(format_markdown_table(run.category_summary()))
    lines.append("")

    lines.append("## 样本明细")
    lines.append("")
    detail = []
    for r in run.results:
        m = r["meta"]
        detail.append(
            {
                "id": r["id"],
                "category": CATEGORIES.get(r["category"], r["category"]),
                "edit_rate": r["edit_rate"],
                "edits": r["edits"],
                "ins": r["insertions"],
                "del": r["deletions"],
                "sub": r["substitutions"],
                "gold_chars": r["gold_chars"],
                "pred_chars": r["pred_chars"],
                "gold_proofed": "是" if r["gold_proofed"] else "否",
                "status": m.get("status", "ok"),
                "latency_s": m.get("latency_seconds"),
                "total_tokens": m.get("total_tokens"),
                "cost": m.get("cost"),
                "cached": "是" if m.get("cached") else "否",
            }
        )
    lines.append(format_markdown_table(detail))
    lines.append("")

    # 涂改类目专项记录
    strike = [r for r in run.results if r["category"] == "strikethrough"]
    lines.append("## 涂改样本（语义化删除）专项")
    lines.append("")
    if not strike:
        lines.append(
            "当前评估集 **无真实涂改样本**（留空）。harness 已为该类目预留记录字段 "
            "（`deletion_note`），扩充样本后在此专项追踪："
            "明确划掉/涂抹的内容是否不输出（不误删）、模糊划线是否保守保留。"
        )
    else:
        for r in strike:
            lines.append(f"- **{r['id']}**: EditRate {r['edit_rate']:.4f}；{r.get('deletion_note', '')}")
    lines.append("")
    return "\n".join(lines)


def write_report(run: EvalRun, model: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    text = build_report(run, model)
    path = os.path.join(REPORTS_DIR, f"report-{model}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def save_predictions(run: EvalRun, model: str) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    payload = [
        {
            "id": r["id"],
            "model": model,
            "category": r["category"],
            "gold_proofed": r["gold_proofed"],
            "meta": r["meta"],
            "metrics": {k: r[k] for k in ("edits", "insertions", "deletions", "substitutions", "edit_rate")},
            "gold": r["gold"],
            "prediction": r["prediction"],
        }
        for r in run.results
    ]
    path = os.path.join(REPORTS_DIR, f"detail-{model}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"model": model, "samples": payload}, fh, ensure_ascii=False, indent=2)
    return path
