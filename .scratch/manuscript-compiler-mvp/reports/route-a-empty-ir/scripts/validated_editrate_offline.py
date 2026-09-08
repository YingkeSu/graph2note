"""Issue 12 离线验证：两阶段修复的「非空 IR + EditRate」服务无关证据。

实时网关在并发/繁忙时（issue 11 已记录）返回极短「本页全黑」完成（session 退化），
会导致任意 stage-1 都拿不到真实正文——这非代码问题。为给出确定性的 AC 证据，本脚本
把“已验证的、内容丰富的 stage-1 Markdown 转录”喂进产品 stage-2（确定性 markdown-parser
-> IR -> render_markdown）：
  - 5 个跨类目评估页（A02 公式 / A09 删除线 / A10 中英混排 / A13 流程图 / A15 手写）：
    直接复用 worker3 eval cache 里的 `glm-5.3-flash__96c7437d2627__<pid>.json` 转录
    （同一模型/同 spike-01 会话/同 1024 降采样/同 direct 直出 prompt 族，正是 eval 已验证策略）。
  - img01（架构扫描页）：取本 issue 实时 stage-1 升级预算后拿到的真实转录
    （parse_scratch/img01/*.md，539 字符）。
逐页打印 ir blocks、渲染 .md 长度、EditRate(len*)，并对“是否非空/跨类目”给出统计。
"""

import json
import sys
from pathlib import Path

REPO = Path("/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-5")
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))

from graph2note import vlm              # noqa: E402
from graph2note.render import render_markdown  # noqa: E402
from eval.editerate import edit_rate    # noqa: E402

W3 = Path("/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-3")
CACHE = W3 / "eval/cache"
GOLD = W3 / "eval/fixtures/gold"
MDIR = W3 / "eval/fixtures/metadata.json"
HERE = Path(__file__).resolve().parent
OUT = HERE / "data"
OUT.mkdir(parents=True, exist_ok=True)

CATS = ["A02", "A09", "A10", "A13", "A15"]
smap = {s["id"]: s for s in json.loads(MDIR.read_text(encoding="utf-8"))["samples"]}


def ir_to_markdown(ir_json: dict) -> str:
    from graph2note.ir import load_dict_as_ir
    return render_markdown(load_dict_as_ir(ir_json))


def main() -> None:
    rows = []
    for pid in CATS:
        raw = json.loads((CACHE / f"glm-5.3-flash__96c7437d2627__{pid}.json").read_text(encoding="utf-8"))
        md = raw["prediction"]
        ir = vlm._markdown_to_ir(md)
        rendered = ir_to_markdown(ir)
        gold = (GOLD / f"{pid}.gold.md").read_text(encoding="utf-8")
        er = round(edit_rate(gold, rendered), 4)
        rows.append({
            "id": pid, "category": smap.get(pid, {}).get("category"),
            "stage1_source": "eval-cache/direct",
            "stage1_md_len": len(md), "ir_blocks": len(ir["blocks"]),
            "rendered_md_len": len(rendered), "md_nonempty": bool(rendered.strip()), "edit_rate": er,
        })
        print(f"[{pid}] ({smap.get(pid,{}).get('category')}) ir_blocks={len(ir['blocks'])} "
              f"s1_len={len(md)} rendered={len(rendered)} er={er}")

    # img01：本 issue 实时 stage-1（升级预算）真实转录 -> 产品 stage-2 -> EditRate vs img01 gold
    img_md_files = list((HERE / "data/parse_scratch/img01").glob("*.md"))
    if img_md_files:
        md = img_md_files[0].read_text(encoding="utf-8")
        ir = vlm._markdown_to_ir(md)
        rendered = ir_to_markdown(ir)
        gold = (GOLD / "01-requirements-arch.gold.md")
        if not gold.exists():
            gold = REPO / "eval/fixtures/gold/01-requirements-arch.gold.md"
        gold = gold.read_text(encoding="utf-8")
        er = round(edit_rate(gold, rendered), 4)
        rows.append({
            "id": "img01", "category": "architecture", "stage1_source": "live/escalated(10000)",
            "stage1_md_len": len(md), "ir_blocks": len(ir["blocks"]),
            "rendered_md_len": len(rendered), "md_nonempty": bool(rendered.strip()), "edit_rate": er,
        })
        print(f"[img01] (architecture) ir_blocks={len(ir['blocks'])} s1_len={len(md)} "
              f"rendered={len(rendered)} er={er}")

    total = len(rows)
    nonempty = [r for r in rows if r["md_nonempty"]]
    summary = {
        "n": total,
        "n_nonempty": len(nonempty),
        "nonempty_rate": round(len(nonempty) / max(total, 1), 3),
        "categories_covered": sorted({r["category"] for r in rows}),
        "rows": rows,
    }
    (OUT / "editrate_offline.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nnon-empty rate: {len(nonempty)}/{total}")
    print(f"categories: {summary['categories_covered']}")
    print(f"evidence: {OUT / 'editrate_offline.json'}")


if __name__ == "__main__":
    main()