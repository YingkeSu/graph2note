"""Synthesize hand-drawn-style flowchart manuscript samples (Spike 3).

Real flowchart manuscripts are scarce (2 already in test-images/, more being
requested HITL); to reach >=10 experiment samples we synthesize flowchart
sketches here with known ground truth (nodes/edges).  Each image is drawn like
a handwritten note: slightly wobbly boxes, hand-drawn arrows, a small rotation,
ink-on-paper look, so the VLM faces realistic manuscript noise.

All geometry is seeded per-sample so the images are reproducible, and the
ground-truth semantics are written to ground_truth/<name>.json.

Usage:
    python spike3/synthesize_samples.py
"""
from __future__ import annotations

import json
import math
import os
import random

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Rectangle
import numpy as np

from ir_model import Diagram, Node, Edge

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
GT = os.path.join(HERE, "ground_truth")
os.makedirs(SAMPLES, exist_ok=True)
os.makedirs(GT, exist_ok=True)

# Register a CJK-capable font so labels render (and stay non-mojibake).
CJK_FONT = "/Library/Fonts/Arial Unicode.ttf"
try:
    fm.fontManager.addfont(CJK_FONT)
    CJK = fm.FontProperties(fname=CJK_FONT).get_name()
except Exception:
    CJK = "DejaVu Sans"
print("using CJK font:", CJK)


class Hand:
    """Deterministic 'hand-drawn' renderer."""

    def __init__(self, seed: int, w: int = 1200, h: int = 900):
        self.seed = seed
        self.rng = random.Random(seed)
        self.w, self.h = w, h
        fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
        self.ax = fig.add_axes([0, 0, 1, 1])
        self.ax.set_xlim(0, w)
        self.ax.set_ylim(0, h)
        self.ax.axis("off")
        self._paper_bg()
        self.ink = "#151a28"  # dark pen
        self.red = "#a03028"  # red annotation pen

    def _paper_bg(self):
        base = np.full((self.h, self.w, 3), 255, dtype=np.uint8)
        # faint paper grain
        grain = np.random.RandomState(self.seed).normal(0, 4, (self.h, self.w, 1))
        base = np.clip(base + grain, 232, 255).astype(np.uint8)

    def _wobble(self, x0, y0, x1, y1, n=12, amp=2.0):
        xs = np.linspace(x0, x1, n)
        ys = np.linspace(y0, y1, n)
        off = [self.rng.gauss(0, amp) for _ in range(n)]
        # fixed start/end so boxes join arrows cleanly
        off[0] = off[-1] = 0
        return xs, ys + off

    def box(self, cx, cy, w, h, color=None, rot=0.0, lw=3.4, label="", fs=64):
        """Draw a hand-drawn rectangle with a slightly rotated label."""
        rng = self.rng
        color = color or self.ink
        rad = rng.choice([0, 4, 6])
        rx, ry = cx - w / 2, cy - h / 2
        j = rng.uniform(-2, 2)
        rect = Rectangle((rx + j, ry - j), w, h, fill=True,
                         facecolor="#f7f6ee", edgecolor=color, linewidth=lw,
                         capstyle="round", zorder=4)
        self.ax.add_patch(rect)
        # doubled text pass for thick, stroke-dense glyphs that survive
        # the VLM's downscaling (thin Arial strokes vanish; real handwriting
        # is dense pen ink, so we emulate that density).
        fp = fm.FontProperties(fname=CJK_FONT)
        for ox, oy in ((0, 0), (1.5, 0), (-1.5, 0)):
            self.ax.text(cx + ox, cy + oy, label, ha="center", va="center",
                         fontsize=fs, fontproperties=fp, color="#000000",
                         rotation=rot, zorder=5, weight="bold")

    def edge(self, x0, y0, x1, y1, color=None, label="", lw=3.4, fs=34,
             dashed=False):
        """Hand-drawn arrow between two node centers."""
        rng = self.rng
        color = color or self.ink
        ls = "--" if dashed else "-"
        xs, ys = self._wobble(x0, y0, x1, y1, n=16, amp=2.5 if dashed else 1.8)
        self.ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls,
                     alpha=0.97, zorder=2, solid_capstyle="round")
        arrow = FancyArrowPatch((xs[-2], ys[-2]), (x1, y1),
                                arrowstyle="-|>", mutation_scale=30,
                                color=color, linewidth=lw, zorder=6)
        self.ax.add_patch(arrow)
        if label:
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            fp = fm.FontProperties(fname=CJK_FONT)
            for ox, oy in ((0, 0), (1.2, 0), (-1.2, 0)):
                self.ax.text(mx + ox, my + 8 + oy, label, ha="center", va="bottom",
                             fontsize=fs, color=self.red, weight="bold",
                             fontproperties=fp, rotation=rng.uniform(-4, 4), zorder=7)

    def save(self, path):
        self.ax.imshow  # noqa
        plt.savefig(path, dpi=100, facecolor="white")
        plt.close("all")


# ---- sample definitions: node positions (x,y,label), edges ----
# Each sample carries its exact ground-truth graph so we can score extraction.

def _gt(nodes_order, edges):
    nodes = [Node(f"n{i}", lbl) for i, (_, _, lbl) in enumerate(nodes_order)]
    ids = {lbl: f"n{i}" for i, (_, _, lbl) in enumerate(nodes_order)}
    es = [Edge(ids[a], ids[b], lab) for (a, b, lab) in edges]
    return Diagram(nodes, es).canonical()


SAMPLES_SPEC = {
    "S01": dict(          # simple linear A -> B
        w=140, h=90,
        nodes=[(0.5, 0.7, "输入数据"), (0.82, 0.5, "输出结果")],
        edges=[("输入数据", "输出结果", "")],
    ),
    "S02": dict(          # chain A -> C -> D
        w=160, h=90,
        nodes=[(0.25, 0.7, "开始"), (0.55, 0.55, "处理"), (0.85, 0.55, "结束")],
        edges=[("开始", "处理", ""), ("处理", "结束", "")],
    ),
    "S03": dict(          # branch: A -> B, A -> C
        w=180, h=100,
        nodes=[(0.28, 0.72, "接收请求"), (0.6, 0.85, "正常返回"), (0.6, 0.25, "错误返回")],
        edges=[("接收请求", "正常返回", "成功"), ("接收请求", "错误返回", "失败")],
    ),
    "S04": dict(          # merge: A -> B -> D and A -> C -> D
        w=180, h=100,
        nodes=[(0.2, 0.7, "起点"), (0.5, 0.85, "路径一"), (0.5, 0.25, "路径二"),
               (0.82, 0.5, "汇合")],
        edges=[("起点", "路径一", ""), ("起点", "路径二", ""),
               ("路径一", "汇合", ""), ("路径二", "汇合", "")],
    ),
    "S05": dict(          # loop/回流: A -> B -> C -> A
        w=190, h=110,
        nodes=[(0.3, 0.5, "初始化"), (0.55, 0.75, "迭代"), (0.78, 0.35, "收敛?")],
        edges=[("初始化", "迭代", ""), ("迭代", "收敛?", ""), ("收敛?", "初始化", "否")],
    ),
    "S06": dict(          # linear with labeled arrows
        w=190, h=90,
        nodes=[(0.2, 0.55, "读取配置"), (0.5, 0.55, "构建模型"), (0.8, 0.55, "训练")],
        edges=[("读取配置", "构建模型", "参数"),
               ("构建模型", "训练", "数据")],
    ),
    "S07": dict(          # decision diamond with yes/no branches + merge
        w=200, h=120,
        nodes=[(0.18, 0.72, "检查权限"), (0.5, 0.82, "允许"), (0.5, 0.28, "拒绝"),
               (0.8, 0.55, "记录日志")],
        edges=[("检查权限", "允许", "是"), ("检查权限", "拒绝", "否"),
               ("允许", "记录日志", ""), ("拒绝", "记录日志", "")],
    ),
    "S08": dict(          # start -> [A -> B], [A -> C] -> end (wide)
        w=210, h=110,
        nodes=[(0.12, 0.6, "开始"), (0.4, 0.82, "任务A"), (0.4, 0.3, "任务B"),
               (0.66, 0.55, "汇总"), (0.9, 0.55, "结束")],
        edges=[("开始", "任务A", ""), ("开始", "任务B", ""),
               ("任务A", "汇总", ""), ("任务B", "汇总", ""),
               ("汇总", "结束", "")],
    ),
    "S09": dict(          # cycle with arrow label + annotation arrow
        w=190, h=100,
        nodes=[(0.25, 0.6, "启动"), (0.55, 0.8, "轮询"), (0.62, 0.28, "事件")],
        edges=[("启动", "轮询", ""), ("轮询", "事件", "收到"),
               ("事件", "轮询", "处理")],
    ),
    "S10": dict(          # two-column work flow, 6 nodes
        w=220, h=120,
        nodes=[(0.14, 0.6, "输入"), (0.4, 0.82, "解析"), (0.4, 0.32, "校验"),
               (0.66, 0.6, "生成"), (0.66, 0.9, "输出"), (0.9, 0.6, "完成")],
        edges=[("输入", "解析", ""), ("输入", "校验", ""),
               ("解析", "生成", "合法"), ("校验", "生成", "修正"),
               ("生成", "输出", ""), ("生成", "完成", "")],
    ),
}


def _draw(name, spec, seed):
    hand = Hand(seed)
    W, H = hand.w, hand.h
    for _ in range(2):  # random stray line for realism
        x0, y0 = hand.rng.uniform(0, W), hand.rng.uniform(0, H)
        dx, dy = hand.rng.uniform(-220, 220), hand.rng.uniform(-80, 80)
        c = hand.rng.choice(["#c8c8c8", "#d6d6d6", "#bdbdbd"])
        hand.edge(x0, y0, x0 + dx, y0 + dy, color=c, lw=1.5)
    # nodes
    pos = {}
    for i, (fx, fy, label) in enumerate(spec["nodes"]):
        cx, cy = fx * W, fy * H
        rot = hand.rng.uniform(-3, 3)
        bw, bh = (0.30 + 0.02 * len(label)) * W, 0.17 * H
        if label in ("开始", "结束", "启动", "完成", "输入", "输出"):
            # rounded terminator
            hand.box(cx, cy, bw * 0.9, bh, rot=rot, label=label)
        elif label in ("收敛?", "检查权限", "校验", "判断"):
            hand.box(cx, cy, bw * 0.8, bh * 0.9, rot=rot, lw=2.4, label=label)
        else:
            hand.box(cx, cy, bw, bh, rot=rot, label=label)
        pos[label] = (cx, cy)
    # edges
    for (a, b, lab) in spec["edges"]:
        x0, y0 = pos[a]
        x1, y1 = pos[b]
        hand.edge(x0, y0, x1, y1, label=lab, dashed=bool(hand.rng.random() < 0.15))
    out = os.path.join(SAMPLES, f"{name}.png")
    hand.save(out)
    # ground truth
    gt = _gt(spec["nodes"], spec["edges"])
    with open(os.path.join(GT, f"{name}.json"), "w", encoding="utf-8") as fh:
        json.dump(gt.to_dict(), fh, ensure_ascii=False, indent=2)
    return out, gt


def main():
    created = []
    for idx, (name, spec) in enumerate(SAMPLES_SPEC.items()):
        path, gt = _draw(name, spec, seed=1000 + idx)
        created.append((name, len(gt.nodes), len(gt.edges)))
    for name, nn, ne in created:
        print(f"{name}: {nn} nodes, {ne} edges")
    print(f"samples in {SAMPLES}")
    print(f"ground truth in {GT}")


if __name__ == "__main__":
    main()