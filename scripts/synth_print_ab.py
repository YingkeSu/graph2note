#!/usr/bin/env python3
"""生成合成印刷样本（issue 08 印刷维度补充，方法写进报告），并可对它们跑 Route B。

评估集无真实印刷页。Route A 在印刷维如实标注无样本（不新增视觉调用）；Route B 用合成
清印刷样本展示其在纯文本印刷上的表现。

用法（source .env 后）：
  python scripts/synth_print_ab.py            # 仅生成样本，不调用模型
  python scripts/synth_print_ab.py --route-b   # 生成 + 对样本跑 Route B（文本 LLM 调用）
样本/gold 落到 reports/route-b/scripts/data/synth_print/。
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))

FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
OUT = REPO / ".scratch" / "manuscript-compiler-mvp" / "reports" / "route-b" / "scripts" / "data" / "synth_print"

SAMPLES = {
    "SYN-P1": (
        "卷积神经网络（CNN）是深度学习中最常用的图像识别模型。\n"
        "它由卷积层、池化层和全连接层组成。\n"
        "卷积层通过滤波器提取局部特征，池化层降低特征维度。\n"
        "反向传播算法用于更新网络参数。\n"
        "模型在训练集上的损失函数定义为 L = -Σ y log(p)。\n"
        "本文讨论其在手写数字识别 MNIST 数据集上的应用。"
    ),
    "SYN-P2": (
        "设 X 为随机变量，E[X] 表示其期望，Var(X) 表示方差。\n"
        "中心极限定理：大量独立同分布随机变量之和近似服从正态分布。\n"
        "样本均值 X̄ 的标准误为 σ/√n。\n"
        "95% 置信区间估计：X̄ ± 1.96·σ/√n。\n"
        "假设检验中，p 值小于显著性水平 0.05 时拒绝原假设。"
    ),
}


def generate() -> dict[str, dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(FONT, 28)
    results = {}
    for pid, text in SAMPLES.items():
        lines = text.split("\n")
        img = Image.new("RGB", (900, len(lines) * 40 + 120), "white")
        d = ImageDraw.Draw(img)
        y = 60
        for ln in lines:
            d.text((40, y), ln, font=font, fill="black")
            y += 40
        img.save(OUT / f"{pid}.jpg", "JPEG", quality=92)
        (OUT / f"{pid}.gold.txt").write_text(text, encoding="utf-8")
        results[pid] = {"text": text}
    return results


def run_route_b() -> None:
    from graph2note.ocr import ocr_mean_confidence
    from graph2note.route_b import route_b_chain
    from eval import editerate

    out = []
    for pid in SAMPLES:
        img = str(OUT / f"{pid}.jpg")
        gold = (OUT / f"{pid}.gold.txt").read_text(encoding="utf-8").strip()
        conf = ocr_mean_confidence(img)
        res = route_b_chain(img, max_retries=0)
        md = res.raw_content or ""
        er = editerate.compute_edit_distance(gold, md).edits / max(len(gold), 1)
        out.append({
            "id": pid, "ocr_mean_conf": conf["mean_conf"], "route_b_edit_rate": round(er, 4),
            "route_b_chars": len(md), "blocks": len(res.document.blocks), "warnings": res.warnings,
        })
        print(f"{pid}: conf={conf['mean_conf']} edit_rate={er:.4f} blocks={len(res.document.blocks)}")
    (OUT / "synth_print_summary.json").write_text(json.dumps({
        "method": "PIL 渲染合成印刷样本（Hiragino Sans GB）。Route A 印刷维无真实样本、不新增视觉调用，故 N/A；Route B 跑 OCR+文本 LLM。",
        "n": len(out), "samples": out,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT / 'synth_print_summary.json'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--route-b", action="store_true", help="对合成样本跑 Route B（live 文本 LLM）")
    args = ap.parse_args()
    generate()
    print("generated:", list(SAMPLES))
    if args.route_b:
        run_route_b()