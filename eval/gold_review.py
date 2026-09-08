"""维护者 gold 人工抽检复核材料包生成器（纯离线，不调用网络）。

用法（工作区根目录）：
    python -m eval.gold_review

产出：eval/reports/gold-review/
    index.md            复核总目录（每页一节）
    thumbnails/<id>.jpg  页图缩略图（base64 内嵌于 index.md，同时保留文件）
    gold/<id>.gold.md    gold 副本（维护者可直接在副本上修改后回同步）

输入全部来自缓存与 fixtures（metadata.json + eval/fixtures/gold/*.gold.md +
eval/reports/detail-glm-5.3-flash.json + eval/fixtures/data/*.jpg），不触网。
本脚本把 30 页按「热区优先」（涂改 > 公式 > 其余）排序便于优先抽检。
"""

from __future__ import annotations

import base64
import io
import json
import os

from PIL import Image

from .dataset import CATEGORIES, FIXTURES_DIR, REPO_ROOT, load_dataset

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "gold-review")
THUMB_DIR = os.path.join(OUT_DIR, "thumbnails")
GOLD_COPY_DIR = os.path.join(OUT_DIR, "gold")
DATA_DIR = os.path.join(FIXTURES_DIR, "data")
GOLD_DIR = os.path.join(FIXTURES_DIR, "gold")
DETAIL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "detail-glm-5.3-flash.json")

THUMB_MAX_DIM = 320
THUMB_QUALITY = 70

# 抽检优先级：涂改（最依赖人眼）> 公式 > 其余
PRIORITY = {"strikethrough": 0, "formula": 1}

CATEGORY_DIFF_HINTS = {
    "strikethrough": (
        "语义化删除类：gold 按逐字忠实口径保留了被划线/涂改段并打 `<<划掉>>/<<涂改>>` 标记；"
        "glm 预测按语义化删除口径不输出明确划掉的内容。因此该页差异会偏大，请重点核对删除线归属。"
    ),
    "formula": (
        "数学公式类：差异多来自 LaTeX 写法（$…$ 与 $$…$$、`\frac`/`\sum`/下标排版）与空行/分段，"
        "请核对公式内容与推导步骤是否一致。"
    ),
    "flowchart": (
        "流程图/架构图类：gold 与 glm 对节点文字、箭头方向的 Markdown 描述方式可能不同，"
        "请以原图核对节点与连线是否完备、方向是否正确。"
    ),
    "mixed": "中英混排类：核对中英文词与全角/半角、标点是否与图一致。",
    "handwriting": "手写类：核对字形易混字、数字/单位、行内缩写是否与图一致。",
}


def _diff_points(m: dict) -> str:
    edits, ins, dele, sub = m["edits"], m["insertions"], m["deletions"], m["substitutions"]
    gl, pr = m["gold_chars"], m["pred_chars"]
    parts = []
    if pr > gl:
        parts.append(f"glm 预测比 gold 长 {pr - gl} 字符（可能多抄或补了细节）")
    elif gl > pr:
        parts.append(f"glm 预测比 gold 短 {gl - pr} 字符（可能漏抄/截断，或按语义化删除删除了删除段）")
    if ins and ins / max(edits, 1) >= 0.4:
        parts.append(f"插入占比高（{ins}/{edits}）——glm 出现了 gold 没有的内容")
    if dele and dele / max(edits, 1) >= 0.4:
        parts.append(f"删除占比高（{dele}/{edits}）——glm 未输出 gold 中内容（涂改类多为删除线，其余类请核漏抄）")
    if sub and sub / max(edits, 1) >= 0.4:
        parts.append(f"替换占比高（{sub}/{edits}）——多为措辞/LaTeX 记号/分段差异")
    return "；".join(parts) if parts else "差异分布在字符级，未见明显单向偏差（以人眼核对内容为准）。"


def _thumb_b64(path: str) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        s = THUMB_MAX_DIM / float(max(w, h))
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=THUMB_QUALITY)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        # 同时存缩略图文件，方便直接查看
        im.save(os.path.join(THUMB_DIR, os.path.basename(path)), format="JPEG", quality=THUMB_QUALITY)
    return b64


def main() -> None:
    os.makedirs(THUMB_DIR, exist_ok=True)
    os.makedirs(GOLD_COPY_DIR, exist_ok=True)
    samples = load_dataset()
    detail = json.load(open(DETAIL_PATH, encoding="utf-8"))
    pred_by = {s["id"]: s for s in detail["samples"]}

    ordered = sorted(samples, key=lambda s: (PRIORITY.get(s.category, 9), s.id))

    lines = ["# Gold 人工抽检复核材料包（Spike 1，30 页）", ""]
    lines.append(
        "> 为维护者人工校对 gold 做准备。**数据全部来自本地缓存与 fixtures，离线生成，未调用任何模型。**"
        "gold 为 AI 草拟（glm-5.3-flash）、未经人工校对；类目为 AI 判定。"
    )
    lines.append("")
    lines.append("## 使用说明")
    lines.append("")
    lines.append("1. **建议抽检顺序**：涂改类 6 页优先（语义化删除判断最依赖人眼），其次公式 4 页，再其余。")
    lines.append("2. 每页对照右上/页图缩略图（点开可看原图 `eval/fixtures/data/<id>.jpg`）核对下方两段全文。")
    lines.append("3. 差异要点为系统根据编辑度量粗判 + 类目提示，具体以人眼为准。")
    lines.append("4. **修改方式**：若 gold 需改，直接在 `gold/<id>.gold.md` 副本上修改；")
    lines.append("   勾选「需修改」并把改好的副本放回 `eval/fixtures/gold/<id>.gold.md`、置 `gold_proofed=true`（或交给工单处理）。")
    lines.append("5. 已核对且无误的页勾选「gold 无需修改」。")
    lines.append("")
    lines.append("| 优先 | 类目 | 页数 |")
    lines.append("|---|---|---|")
    from collections import Counter
    cnt = Counter(s.category for s in samples)
    for cat, label in CATEGORIES.items():
        if cnt.get(cat):
            lines.append(f"| {'★★★' if PRIORITY.get(cat, 9) == 0 else ('★★' if PRIORITY.get(cat, 9) == 1 else '☆')} | {label} | {cnt[cat]} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, s in enumerate(ordered, 1):
        gold_path = os.path.join(GOLD_DIR, f"{s.id}.gold.md")
        with open(gold_path, encoding="utf-8") as fh:
            gold = fh.read().strip()
        r = pred_by.get(s.id)
        pred = (r or {}).get("prediction", "") or ""
        m = (r or {}).get("meta", {}) or {}
        metrics = dict((r or {}).get("metrics", {}) or {})
        metrics["gold_chars"] = len(gold)
        metrics["pred_chars"] = len(pred)
        # 复制 gold 副本供维护者直接修改
        with open(os.path.join(GOLD_COPY_DIR, f"{s.id}.gold.md"), "w", encoding="utf-8") as fh:
            fh.write(gold + "\n")

        img_rel = os.path.join("eval", "fixtures", "data", f"{s.id}.jpg")
        thumb_b64 = _thumb_b64(os.path.join(DATA_DIR, f"{s.id}.jpg"))
        latch = m.get("latency_seconds")
        lines.append(f"## {idx:02d}. {s.id}｜{CATEGORIES.get(s.category, s.category)}")
        lines.append("")
        lines.append(f"![页图缩略](./thumbnails/{s.id}.jpg)（原图：`{img_rel}`，点击放大）")
        lines.append("")
        lines.append(f"- 类目：{CATEGORIES.get(s.category, s.category)} | gold 字符 {metrics.get('gold_chars', '')} / glm 预测 {metrics.get('pred_chars', '')} | "
                     f"编辑 {metrics.get('edits', '')}(ins {metrics.get('insertions', 0)}/del {metrics.get('deletions', 0)}/sub {metrics.get('substitutions', 0)}) | "
                     f"EditRate {metrics.get('edit_rate', 0):.4f} | 网关延迟 {latch}s")
        lines.append(f"- 已知差异要点：{_diff_points(metrics)}")
        if s.category in CATEGORY_DIFF_HINTS:
            lines.append(f"  - {CATEGORY_DIFF_HINTS[s.category]}")
        lines.append(f"- 复核副本：`gold/{s.id}.gold.md`")
        lines.append("")
        lines.append("- [ ] gold 无需修改")
        lines.append(f"- [ ] gold 需修改（在 `gold/{s.id}.gold.md` 副本上改后同步回 fixtures）")
        lines.append("")
        lines.append("<details><summary>AI 草拟 gold 全文</summary>")
        lines.append("")
        lines.append("```markdown")
        lines.append(gold)
        lines.append("```")
        lines.append("</details>")
        lines.append("")
        lines.append("<details><summary>glm-5.3-flash 预测全文</summary>")
        lines.append("")
        lines.append("```markdown")
        lines.append(pred)
        lines.append("```")
        lines.append("</details>")
        lines.append("")
        lines.append("---")
        lines.append("")

    index_path = os.path.join(OUT_DIR, "index.md")
    with open(index_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"复核材料包生成：{OUT_DIR}/")
    print(f"  index.md（{os.path.getsize(index_path)//1024}KB）")
    print(f"  thumbnails/{len(os.listdir(THUMB_DIR))} 张缩略图")
    print(f"  gold/{len(os.listdir(GOLD_COPY_DIR))} 份 gold 副本")


if __name__ == "__main__":
    main()