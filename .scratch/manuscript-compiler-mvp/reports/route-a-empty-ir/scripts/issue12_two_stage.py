"""Issue 12 实时验证：Route A 两阶段解析修复在真实扫描页的非空 IR 产出。

对比口径：
- BEFORE（旧产品 IR-JSON 直出）：issue 11 基线显示评估集 5 页渲染全部为空 IR
  （editerate_after_subset.json 全 1.0），且 test-images/01 的 golden 也为空
  （tests/golden/real-img01-empty.golden.json）。
- AFTER（本修复）：VLM Markdown 直出 -> 文本 LLM 结构化 IR。

对每页跑完整 `pipeline.parse_document`，记录：stage1 markdown 长度、stage2
reasoning / 非空 IR block 数、渲染 .md 长度、EditRate（对 gold md）、empty 标记、
重试标记。写证据到 reports/route-a-empty-ir/data/。

实时调用预算：img01 + 5 评估页 各 2 次（VLM+文本）= 12。

用法（需 .env 密钥 + GRAPH2NOTE_OPENCODE_SESSION 由环境控制）：
    source <repo>/.env
    python scripts/issue12_two_stage.py <worker3_repo>
"""

import argparse
import json
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

from graph2note import pipeline, vlm  # noqa: E402
from graph2note import preprocess as pp  # noqa: E402
from eval.editerate import edit_rate  # noqa: E402

MODEL = "glm-5.3-flash"
HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
OUT.mkdir(parents=True, exist_ok=True)

PAGES = ["A02", "A09", "A10", "A13", "A15"]  # formula/strikethrough/mixed/flowchart/handwriting


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("worker3_root")
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.worker3_root)))

    data_dir = Path(args.worker3_root) / "eval" / "fixtures" / "data"
    gold_dir = Path(args.worker3_root) / "eval" / "fixtures" / "gold"
    meta = json.loads(
        (Path(args.worker3_root) / "eval" / "fixtures" / "metadata.json").read_text(encoding="utf-8")
    )
    smap = {s["id"]: s for s in meta["samples"]}

    targets = [("01-requirements-arch.jpg", "img01", "architecture")]
    for pid in PAGES:
        targets.append((f"{pid}.jpg", pid, smap.get(pid, {}).get("category")))

    print(f"IR_MODEL={vlm.IR_MODEL}  session={vlm.resolve_session(MODEL)}  targets={len(targets)}")
    rows = []
    scratch = OUT / "parse_scratch"
    for fname, pid, cat in targets:
        if fname.startswith("A"):
            img = data_dir / fname
        else:
            img = Path(REPO) / "test-images" / fname
        if not img.exists():
            print(f"[skip] missing {fname}")
            continue
        t0 = time.monotonic()
        try:
            res = pipeline.parse_document(str(img), str(scratch / pid), model=MODEL)
        except Exception as exc:  # live router could raise RecognitionError
            rows.append({"id": pid, "category": cat, "error": str(exc), "e2e": round(time.monotonic() - t0, 2)})
            print(f"[{pid}] ERROR {exc}")
            continue
        e2e = time.monotonic() - t0
        tj = res.timing_json.get("llm", {})
        md = ""
        try:
            md = Path(res.markdown_path).read_text(encoding="utf-8")
        except Exception:
            pass
        ir_blocks = len(res.ir.blocks) if res.ir else 0
        # real content vs router's empty placeholder (“本页无”)
        real_md = bool(md.strip()) and not md.strip().startswith(("（本页", "（本图"))
        meta = (res.route.attempts or [{}])[0].get("meta") or {}
        ms1 = meta.get("markdown_stage") or {}
        ms2 = meta.get("ir_stage") or {}
        # EditRate vs gold md (evaluation pages have .gold.md; img01 has one too)
        gold_md = (gold_dir / f"{pid}.gold.md")
        er = None
        if gold_md.exists():
            er = round(edit_rate(gold_md.read_text(encoding="utf-8"), md), 4)
        rows.append({
            "id": pid,
            "category": cat,
            "e2e_seconds": round(e2e, 3),
            "stage1_retried": ms1.get("retried_stage1", False),
            "stage1_markdown_len": meta.get("markdown_len") or 0,
            "stage1_reasoning": ms1.get("reasoning_tokens") if ms1 else None,
            "stage2_mode": ms2.get("mode"),
            "ir_blocks": ir_blocks,
            "md_len": len(md),
            "md_nonempty": bool(md.strip()),
            "real_md": real_md,
            "edit_rate": er,
            "warnings": list(res.route.warnings),
        })
        print(f"[{pid}] ({cat}) ir_blocks={ir_blocks} md_len={len(md)} nonempty={bool(md.strip())} "
              f"reasoning2={tj.get('reasoning_tokens')} edit_rate={er} e2e={e2e:.2f}s")

    real = [r for r in rows if r.get("real_md")]
    summary = {
        "model": MODEL,
        "ir_model": vlm.IR_MODEL,
        "session": vlm.resolve_session(MODEL),
        "n": len(rows),
        "n_real_nonempty": len(real),
        "real_nonempty_rate_after": round(len(real) / max(len(rows), 1), 3),
        "rows": rows,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreal non-empty .md rate (after): {summary['n_real_nonempty']}/{len(rows)} = {summary['real_nonempty_rate_after']}")
    print(f"evidence: {OUT / 'summary.json'}")


if __name__ == "__main__":
    main()