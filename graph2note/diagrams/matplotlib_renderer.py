"""Deterministic matplotlib flowchart renderer (issue 05 fallback engine).

A pure-Python, dependency-free fallback when graphviz/dot is unavailable.
Hand-rolled layered layout (``_layout.LayerLayout``); two renders of the same
semantics are byte-identical.  CJK labels are rendered with the first
available CJK font (probing a small candidate list).  Importing this module
never raises if matplotlib is missing - drawing simply reports unavailable.
"""

from __future__ import annotations

import os

from ._layout import LayerLayout

try:  # matplotlib is optional (fallback engine only)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.font_manager as fm
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, Rectangle
    import numpy as np
    _MPL_OK = True
except Exception:  # pragma: no cover - env without matplotlib
    _MPL_OK = False
    fm = plt = FancyArrowPatch = Rectangle = np = None

# Candidate CJK font files (ordered by preference).  Kept small & portable.
_CJK_FONT_CANDIDATES = [
    "/Library/Fonts/Arial Unicode.ttf",       # macOS
    "/System/Library/Fonts/PingFang.ttc",     # macOS
    "/System/Library/Fonts/Hiragino Sans GB.ttc",  # macOS
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux
]


def _register_cjk_font() -> str | None:
    for path in _CJK_FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)
                fam = fm.FontProperties(fname=path).get_name()
                matplotlib.rcParams["font.family"] = "sans-serif"
                matplotlib.rcParams["font.sans-serif"] = [fam, "DejaVu Sans"]
                matplotlib.rcParams["axes.unicode_minus"] = False
                return fam
            except Exception:
                continue
    return None


_CJK_FAMILY = _register_cjk_font() if _MPL_OK else None


def available() -> bool:
    """True if matplotlib can render (fallback engine usable)."""
    return _MPL_OK


def _label_len(label: str) -> int:
    return sum(2 if ord(c) > 127 else 1 for c in label)


def render(nodes, edges, labels: dict[str, str], out_path: str) -> str:
    """Render canonical node ids/edge pairs to a deterministic PNG."""
    if not _MPL_OK:  # pragma: no cover
        raise RuntimeError("matplotlib is not available")

    nid = [n.id for n in nodes]
    edge_pairs = [(e.from_, e.to) for e in edges]
    lay = LayerLayout(nid, edge_pairs)
    pos = lay.positions()

    fig = plt.figure(figsize=(12, 8), dpi=120)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)
    ax.invert_yaxis()  # top->down flow
    ax.axis("off")

    box_w = {nid: 0.06 + 0.012 * _label_len(labels.get(nid, "")) for nid in nid}
    box_h = 0.09
    npos = {n.id: pos[n.id] for n in nodes}

    for e in edges:
        x0, y0 = npos[e.from_]
        x1, y1 = npos[e.to]
        _draw_arrow(ax, x0, y0, x1, y1, box_w[e.from_], box_h,
                    box_w[e.to], box_h, e.label)
    for n in nodes:
        x, y = npos[n.id]
        bw = box_w[n.id]
        ax.add_patch(Rectangle((x - bw / 2, y - box_h / 2), bw, box_h,
                               fill=False, edgecolor="#1a1d29", linewidth=2.0,
                               zorder=3))
        ax.text(x, y, labels.get(n.id, ""), ha="center", va="center",
                fontsize=15, color="#101018", zorder=4)

    fig.savefig(out_path, dpi=120, facecolor="white",
                bbox_inches="tight", pad_inches=0.1)
    plt.close("all")
    return out_path


def _draw_arrow(ax, x0, y0, x1, y1, w0, h0, w1, h1, label=""):
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
    dx, dy = x1 - x0, y1 - y0
    tx = (w / 2) / abs(dx) if abs(dx) > 1e-9 else 1e9
    ty = (h / 2) / abs(dy) if abs(dy) > 1e-9 else 1e9
    if tx == 1e9 and ty == 1e9:
        return x0, y0
    t = min(tx, ty)
    return x0 + dx * t, y0 + dy * t
