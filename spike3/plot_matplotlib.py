"""Deterministic matplotlib flowchart renderer (Spike 3).

Hand-rolled layered layout + matplotlib drawing.  Two calls with the same
Diagram semantics produce byte-identical PNGs (FR-020): node/edge input is
canonicalized, layout uses fixed tie-breaks, and no randomness is introduced
at draw time.  Chinese labels render with a registered CJK font - no tophat
boxes for CJK.
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.font_manager as fm  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402
import numpy as np  # noqa: E402

from ir_model import Diagram  # noqa: E402

CJK_FONT = "/Library/Fonts/Arial Unicode.ttf"
try:
    fm.fontManager.addfont(CJK_FONT)
    _CJK = fm.FontProperties(fname=CJK_FONT)
    fam = _CJK.get_name()
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [fam, "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
except Exception:
    _CJK = None


class LayerLayout:
    """Minimal deterministic layered layout (longest-path layering +
    crossing-reduction barycenter with stable tie-breaking)."""

    def __init__(self, diag: Diagram):
        d = diag.canonical()
        self.nodes = d.nodes
        self.nid = [n.id for n in d.nodes]
        self.edges = [(e.src, e.tgt) for e in d.edges]
        self.adj = {nid: [] for nid in self.nid}
        self.parents = {nid: [] for nid in self.nid}
        for s, t in self.edges:
            self.adj[s].append(t)
            self.parents[t].append(s)

    def layers(self):
        # cycle-safe longest-path layering via iterative relaxation.
        n_incoming = {nid: len(self.parents[nid]) for nid in self.nid}
        depth = {nid: 0 for nid in self.nid}
        # propagate until stable (bounded by node count to survive cycles)
        from collections import deque
        q = deque(n for n, d in depth.items() if depth[n] == 0)
        order = list(self.nid)
        changed = True
        for _ in range(len(self.nid) + 2):  # enough passes for any acyclic graph
            changed = False
            for s in list(self.nid):
                for t in self.adj[s]:
                    if depth[t] < depth[s] + 1:
                        depth[t] = depth[s] + 1
                        changed = True
            if not changed:
                break
        maxd = max(depth.values()) if depth else 0
        lay = [[] for _ in range(maxd + 1)]
        for n in self.nid:
            lay[depth[n]].append(n)
        # barycenter ordering per layer (stable)
        for i, layer in enumerate(lay):
            centers = {}
            for n in layer:
                preds = self.parents[n]
                if preds and i > 0:
                    idxs = [lay[i - 1].index(p) for p in preds if p in lay[i - 1]]
                    centers[n] = sum(idxs) / len(idxs) if idxs else float("inf")
                else:
                    centers[n] = float("-inf")
            layer.sort(key=lambda n: (centers[n], self.nid.index(n)))
        return lay

    def positions(self, width=1.0, height=1.0):
        lay = self.layers()
        xstep = width / max(1, len(lay))
        pos = {}
        for li, layer in enumerate(lay):
            x = xstep * (li + 0.5)
            ystep = height / max(1, len(layer))
            for yi, n in enumerate(layer):
                y = height - ystep * (yi + 0.5)
                pos[n] = (x, y)
        return pos


def _label_len(label):
    # visual width: CJK = 2, ascii = 1
    return sum(2 if ord(c) > 127 else 1 for c in label)


def render(diag: Diagram, out_path: str) -> str:
    """Render diagram to PNG at out_path; returns the path."""
    d = diag.canonical()
    lay = LayerLayout(d)
    pos = lay.positions()
    fig = plt.figure(figsize=(12, 8), dpi=120)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)
    ax.invert_yaxis()  # top->down flow
    ax.axis("off")
    # box sizes by label width
    box_w = {nid: 0.06 + 0.012 * _label_len(label) for nid, label in
             [(n.id, n.label) for n in d.nodes]}
    box_h = 0.09
    npos = {n.id: pos[n.id] for n in d.nodes}
    # draw edges first (behind boxes)
    for e in d.edges:
        x0, y0 = npos[e.src]
        x1, y1 = npos[e.tgt]
        _draw_arrow(ax, x0, y0, x1, y1, box_w[e.src], box_h, box_w[e.tgt],
                    box_h, e.label)
    for n in d.nodes:
        x, y = npos[n.id]
        bw = box_w[n.id]
        ax.add_patch(Rectangle((x - bw / 2, y - box_h / 2), bw, box_h,
                               fill=False, edgecolor="#1a1d29", linewidth=2.0,
                               zorder=3))
        ax.text(x, y, n.label, ha="center", va="center", fontsize=15,
                color="#101018", zorder=4)
    fig.savefig(out_path, dpi=120, facecolor="white",
                bbox_inches="tight", pad_inches=0.1)
    plt.close("all")
    return out_path


def _draw_arrow(ax, x0, y0, x1, y1, w0, h0, w1, h1, label=""):
    # clip start/end to box edges; if the box is on top, draw from the side
    sx, sy = _clip(x0, y0, x1, y1, w0, h0)
    ex, ey = _clip(x1, y1, x0, y0, w1, h1)
    ax.plot([sx, ex], [sy, ey], color="#2a2f3a", linewidth=1.8, zorder=1,
            solid_capstyle="round")
    ar = FancyArrowPatch((sx, sy), (ex, ey), arrowstyle="-|>",
                         mutation_scale=18, color="#2a2f3a", linewidth=1.8,
                         zorder=2)
    ax.add_patch(ar)
    if label:
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        ax.text(mx, my, label, ha="center", va="center", fontsize=11,
                color="#a03028", zorder=3)


def _clip(x0, y0, x1, y1, w, h):
    """Point on the box boundary (center x0,y0, size w,h) on the line to
    (x1,y1)."""
    dx, dy = x1 - x0, y1 - y0
    if abs(dx) > 1e-9:
        tx = (w / 2) / abs(dx)
    else:
        tx = 1e9
    if abs(dy) > 1e-9:
        ty = (h / 2) / abs(dy)
    else:
        ty = 1e9
    if tx == 1e9 and ty == 1e9:
        return x0, y0
    t = min(tx, ty)
    return x0 + dx * t, y0 + dy * t