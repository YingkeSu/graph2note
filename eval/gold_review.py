"""维护者 gold 人工抽检复核材料生成器（纯离线，不调用网络）。

两种输出：
- 默认（--md）：Markdown 复核材料包  → eval/reports/gold-review/index.md + thumbnails/ + gold/
- --pdf    ：PDF 合集（A4 纵向，每样本 1–2 页）→ eval/reports/gold-review/gold-review-pack.pdf
             封面 + 目录（抽检顺序 涂改6→公式4→其余）+ 每页：清晰页图 + gold 全文 + glm 预测全文
             + 差异要点一行 + 复核勾选行。

输入全部来自缓存与 fixtures（metadata.json + eval/fixtures/gold/*.gold.md +
eval/reports/detail-glm-5.3-flash.json + eval/fixtures/data/*.jpg），不触网。

依赖：Pillow（缩略图）、reportlab（PDF，dev extras）。中文用 reportlab 内置 CID 字体 STSong-Light。
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import os

from PIL import Image

from .dataset import CATEGORIES, FIXTURES_DIR, load_dataset

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "gold-review")
THUMB_DIR = os.path.join(OUT_DIR, "thumbnails")
GOLD_COPY_DIR = os.path.join(OUT_DIR, "gold")
DATA_DIR = os.path.join(FIXTURES_DIR, "data")
GOLD_DIR = os.path.join(FIXTURES_DIR, "gold")
DETAIL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports", "detail-glm-5.3-flash.json")
PDF_PATH = os.path.join(OUT_DIR, "gold-review-pack.pdf")

THUMB_MAX_DIM = 320
THUMB_QUALITY = 70

# PDF 用原图（清晰、手写可辨），比 320px 缩略大大得多；JPEG 原样嵌入控体积。
PDF_IMAGE_WIDTH = 4.5 * 72  # pt，约 4.5in

# 抽检优先级：涂改（最依赖人眼）> 公式 > 其余
PRIORITY = {"strikethrough": 0, "formula": 1}
PRIORITY_STAR = {0: "★★★（优先）", 1: "★★", 9: "☆"}

CATEGORY_DIFF_HINTS = {
    "strikethrough": (
        "语义化删除类：gold 按逐字忠实口径保留了被划线/涂改段并打 <<划掉>>/<<涂改>> 标记；"
        "glm 预测按语义化删除口径不输出明确划掉的内容，故该页差异偏大，请重点核对删除线归属。"
    ),
    "formula": (
        "数学公式类：差异多来自 LaTeX 写法（$…$ 与 $$…$$、\\frac/\\sum/下标排版）与空行/分段，"
        "请核对公式内容与推导步骤。"
    ),
    "flowchart": (
        "流程图/架构图类：两模型对节点文字、箭头方向的 Markdown 描述方式可能不同，"
        "请以原图核对节点/连线/方向是否完备。"
    ),
    "mixed": "中英混排类：核对中英文与全角/半角、标点是否与图一致。",
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


def _thumb_b64(path: str, sid: str) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        s = THUMB_MAX_DIM / float(max(w, h))
        im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=THUMB_QUALITY)
        im.save(os.path.join(THUMB_DIR, f"{sid}.jpg"), format="JPEG", quality=THUMB_QUALITY)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def _load(samples) -> list[dict]:
    detail = json.load(open(DETAIL_PATH, encoding="utf-8"))
    pred_by = {s["id"]: s for s in detail["samples"]}
    out = []
    for s in samples:
        with open(os.path.join(GOLD_DIR, f"{s.id}.gold.md"), encoding="utf-8") as fh:
            gold = fh.read().strip()
        r = pred_by.get(s.id) or {}
        pred = r.get("prediction", "") or ""
        m = r.get("meta", {}) or {}
        metrics = dict(r.get("metrics", {}) or {})
        metrics["gold_chars"] = len(gold)
        metrics["pred_chars"] = len(pred)
        s.gold = gold  # 顺手带上，供 PDF 全文字段
        out.append({"sample": s, "gold": gold, "pred": pred, "meta": m, "metrics": metrics})
    return out


def _ordered(samples, data) -> list:
    ordered = sorted(samples, key=lambda s: (PRIORITY.get(s.category, 9), s.id))
    by_id = {d["sample"].id: d for d in data}
    return [by_id[s.id] for s in ordered]


# =============================== Markdown ===============================

def generate_markdown() -> str:
    os.makedirs(THUMB_DIR, exist_ok=True)
    os.makedirs(GOLD_COPY_DIR, exist_ok=True)
    samples = load_dataset()
    data = {d["sample"].id: d for d in _load(samples)}
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
    lines.append("2. 每页对照缩略图（原图 `eval/fixtures/data/<id>.jpg`）核对下方两段全文。")
    lines.append("3. 差异要点为系统根据编辑度量粗判 + 类目提示，具体以人眼为准。")
    lines.append("4. 若 gold 需改，直接在 `gold/<id>.gold.md` 副本上修改并同步回 `eval/fixtures/gold/<id>.gold.md`、置 `gold_proofed=true`。")
    lines.append("5. 已核对且无误的页勾选「gold 无需修改」。")
    lines.append("")
    lines.append("| 优先 | 类目 | 页数 |")
    lines.append("|---|---|---|")
    from collections import Counter
    cnt = Counter(s.category for s in samples)
    for cat, label in CATEGORIES.items():
        if cnt.get(cat):
            lines.append(f"| {PRIORITY_STAR.get(PRIORITY.get(cat, 9), '☆')} | {label} | {cnt[cat]} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx, s in enumerate(ordered, 1):
        d = data[s.id]
        gold, pred, metrics, m = d["gold"], d["pred"], d["metrics"], d["meta"]
        with open(os.path.join(GOLD_COPY_DIR, f"{s.id}.gold.md"), "w", encoding="utf-8") as fh:
            fh.write(gold + "\n")
        _thumb_b64(os.path.join(DATA_DIR, f"{s.id}.jpg"), s.id)
        latch = m.get("latency_seconds")
        lines.append(f"## {idx:02d}. {s.id}｜{CATEGORIES.get(s.category, s.category)}")
        lines.append("")
        lines.append(f"![页图缩略](./thumbnails/{s.id}.jpg)（原图：`eval/fixtures/data/{s.id}.jpg`）")
        lines.append("")
        lines.append(f"- 类目：{CATEGORIES.get(s.category, s.category)} | gold 字符 {metrics.get('gold_chars', '')} / glm 预测 {metrics.get('pred_chars', '')} | "
                     f"编辑 {metrics.get('edits', '')}(ins {metrics.get('insertions', 0)}/del {metrics.get('deletions', 0)}/sub {metrics.get('substitutions', 0)}) | "
                     f"EditRate {metrics.get('edit_rate', 0):.4f} | 网关延迟 {latch}s")
        lines.append(f"- 已知差异要点：{_diff_points(metrics)}")
        if s.category in CATEGORY_DIFF_HINTS:
            lines.append(f"  - {CATEGORY_DIFF_HINTS[s.category]}")
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
    return index_path


# =============================== PDF ===============================

def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _block(text: str, indent: int = 0) -> str:
    pad = "&nbsp;" * (0 if indent == 0 else indent * 2)
    parts = []
    for ln in text.split("\n"):
        parts.append(pad + _esc(ln) if ln else "&nbsp;")
    return "<br/>".join(parts)


def generate_pdf() -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, portrait
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.platypus import (
        BaseDocTemplate, Flowable, Frame, PageBreak, PageTemplate, Paragraph, Spacer,
        Table, TableStyle,
    )
    from reportlab.platypus import Image as ReportImage

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    S = getSampleStyleSheet()
    FONT = "STSong-Light"
    body = ParagraphStyle("Body", parent=S["Normal"], fontName=FONT, fontSize=9.5, leading=13)
    code = ParagraphStyle("Code", parent=body, fontSize=8, leading=10.6)
    h1 = ParagraphStyle("H1", parent=S["Heading1"], fontName=FONT, fontSize=15, leading=19)
    h2 = ParagraphStyle("H2", parent=S["Heading2"], fontName=FONT, fontSize=11.5, leading=15)
    header = ParagraphStyle("SampleHeader", parent=h2, fontSize=12.5, leading=16)
    small = ParagraphStyle("Small", parent=body, fontSize=8, leading=10)

    samples = load_dataset()
    data = _load(samples)
    ordered = _ordered(samples, data)

    class ReviewDoc(BaseDocTemplate):
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and getattr(flowable.style, "name", "") == "SampleHeader":
                text = flowable.getPlainText()
                key = "sample-%s" % self.seq.nextf("sample")
                self.canv.bookmarkPage(key)
                self.notify("TOCEntry", (0, text, self.page, key))

    os.makedirs(OUT_DIR, exist_ok=True)
    doc = ReviewDoc(
        PDF_PATH, pagesize=portrait(A4),
        leftMargin=0.8 * inch, rightMargin=0.8 * inch,
        topMargin=0.75 * inch, bottomMargin=0.7 * inch,
        title="Gold 人工抽检复核材料包（Spike 1，30 页）", author="graph2note eval",
    )
    doc.addPageTemplates([PageTemplate(id="main",
                                      frames=[Frame(doc.leftMargin, doc.bottomMargin,
                                                    doc.width, doc.height, id="frame")])])
    from reportlab.platypus.tableofcontents import TableOfContents
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("TOC0", fontName=FONT, fontSize=9.5, leading=13, leftIndent=6)]

    story: list[Flowable] = []
    # ---- 封面 ----
    story.append(Paragraph("Gold 人工抽检复核材料包（Spike 1，30 页）", h1))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "为维护者人工校对 gold 准备。数据全部来自本地缓存与 fixtures，<b>离线生成，未调用任何模型</b>。"
        "gold 为 AI 草拟（glm-5.3-flash）、未经人工校对；类目为 AI 判定。<br/>"
        "产检顺序建议：<b>涂改类 6 页优先</b>（语义化删除最依赖人眼）→ 公式 4 页 → 其余。", body))
    story.append(Spacer(1, 10))
    story.append(Paragraph("使用说明", h2))
    for t in [
        "1. 每页对照页图（原图 eval/fixtures/data/&lt;id&gt;.jpg）核对下方两段全文。",
        "2. 差异要点为系统按编辑度量粗判 + 类目提示，具体以人眼为准。",
        "3. 若 gold 需修改：直接在副本 gold/&lt;id&gt;.gold.md 上改，并同步回 eval/fixtures/gold/&lt;id&gt;.gold.md、置 gold_proofed=true（或交给工单处理）。",
        "4. 已核对且无误的页勾选「☐ gold 无需修改」。",
    ]:
        story.append(Paragraph(t, small))
        story.append(Spacer(1, 2))
    story.append(Spacer(1, 10))
    story.append(Paragraph("抽检建议顺序", h2))
    from collections import Counter
    cnt = Counter(s.category for s in samples)
    trows = [[Paragraph("优先", small), Paragraph("类目", small), Paragraph("页数", small)]]
    for cat in ("strikethrough", "formula"):
        if cnt.get(cat):
            trows.append([Paragraph(PRIORITY_STAR.get(PRIORITY.get(cat, 9), "☆"), small),
                          Paragraph(CATEGORIES.get(cat, cat), small), Paragraph(str(cnt[cat]), small)])
    for cat, label in CATEGORIES.items():
        if cnt.get(cat) and cat not in ("strikethrough", "formula"):
            trows.append([Paragraph(PRIORITY_STAR.get(PRIORITY.get(cat, 9), "☆"), small),
                          Paragraph(label, small), Paragraph(str(cnt[cat]), small)])
    tt = Table(trows, colWidths=[2.6 * inch, 3.0 * inch, 0.9 * inch])
    tt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.93, 0.93, 0.93)),
                            ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(tt)
    story.append(PageBreak())
    # ---- 目录 ----
    story.append(Paragraph("目录", h1))
    story.append(toc)
    story.append(PageBreak())

    # ---- 每样本 ----
    for idx, d in enumerate(ordered, 1):
        s, gold, pred, m, metrics = d["sample"], d["gold"], d["pred"], d["meta"], d["metrics"]
        latch = m.get("latency_seconds")
        story.append(Paragraph(f"样本 {idx:02d}｜{s.id}｜{CATEGORIES.get(s.category, s.category)}", header))
        story.append(Spacer(1, 4))
        diff = _diff_points(metrics)
        if s.category in CATEGORY_DIFF_HINTS:
            diff += "【" + CATEGORY_DIFF_HINTS[s.category] + "】"
        story.append(Paragraph(
            f"类目 {CATEGORIES.get(s.category, s.category)} | gold {metrics.get('gold_chars', '')} 字符 / "
            f"glm 预测 {metrics.get('pred_chars', '')} | 编辑 {metrics.get('edits', '')} "
            f"(ins {metrics.get('insertions', 0)}/del {metrics.get('deletions', 0)}/sub {metrics.get('substitutions', 0)}) | "
            f"EditRate {(metrics.get('edit_rate') or 0.0):.4f} | 延迟 {latch}s", small))
        story.append(Paragraph(f"已知差异要点：{_esc(diff)}", small))
        story.append(Spacer(1, 3))
        story.append(Paragraph("☐ gold 无需修改　　　☐ 需修改（改 gold/%s.gold.md 后同步回 fixtures）" % s.id, body))
        story.append(Spacer(1, 6))
        # 页图（用原图，清晰手写可辨）
        with Image.open(os.path.join(DATA_DIR, f"{s.id}.jpg")) as imr:
            iw, ih = imr.size
        ratio = ih / float(iw)
        story.append(ReportImage(os.path.join(DATA_DIR, f"{s.id}.jpg"),
                           width=PDF_IMAGE_WIDTH, height=PDF_IMAGE_WIDTH * ratio))
        story.append(Spacer(1, 6))
        story.append(Paragraph("AI 草拟 gold 全文（未经人工校对）", h2))
        story.append(Paragraph(_block(gold), code))
        story.append(Spacer(1, 4))
        story.append(Paragraph("glm-5.3-flash 预测全文", h2))
        story.append(Paragraph(_block(pred), code))
        story.append(PageBreak())

    doc.multiBuild(story)
    return PDF_PATH


# =============================== CLI ===============================

def main() -> None:
    ap = argparse.ArgumentParser(description="gold 复核材料生成（离线）")
    ap.add_argument("--pdf", action="store_true", help="输出 PDF 合集而非 Markdown 材料包")
    args = ap.parse_args()
    if args.pdf:
        p = generate_pdf()
        print(f"PDF 复核材料包生成：{p}（{os.path.getsize(p)//1024}KB）")
    else:
        p = generate_markdown()
        print(f"Markdown 复核材料包生成：eval/reports/gold-review/（index.md {os.path.getsize(p)//1024}KB）")


if __name__ == "__main__":
    main()