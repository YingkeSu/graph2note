"""Deterministic matplotlib flowchart renderer (issue 05 fallback engine).

A pure-Python, dependency-free fallback when graphviz/dot is unavailable.
Hand-rolled layered layout (``_layout.LayerLayout``); two renders of the same
semantics are byte-identical.  CJK labels are rendered with the first
available CJK font (probing a small candidate list).  Importing this module
never raises if matplotlib is missing - drawing simply reports unavailable.

D-track (SPEC §1) additions
---------------------------
* ``groups`` are drawn as background boxes with a group title: ``layer`` spans
  the full width as a horizontal band, ``lane`` spans the full height, and
  ``cluster`` hugs its members.  Boxes are drawn *behind* edges and nodes.
* ``node.note`` renders one size smaller, under the primary label.
* ``edge.style == "dashed"`` draws a dashed line + arrow head.

Backward compatibility: with no groups and no notes every drawing call is the
same as the pre-D-track renderer (same call order, same arguments), so the
fallback PNG is byte-identical to the existing golden.
"""

from __future__ import annotations

import os

from . import render_semantics as rs
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

# Font sizes (SPEC §1 "渲染" rule: group label >= node note, note smaller than
# the primary node label).  Kept as module constants so tests can assert the
# ordering without pixel probing.
NODE_FONTSIZE = 13
EDGE_FONTSIZE = 11
NOTE_FONTSIZE = 10
GROUP_FONTSIZE = 15

NOTE_COLOR = "#555b6b"
NODE_COLOR = "#101018"
EDGE_COLOR = "#2a2f3a"
EDGE_LABEL_COLOR = "#a03028"

# Dashed edge pattern (matches the graphviz `dashed` intent, deterministic).
DASH_PATTERN = (0, (5, 3))


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


def _wrap_label(label: str, max_units: int = 18) -> str:
    """Wrap mixed CJK/Latin labels without letting one node fill the canvas."""
    lines: list[str] = []
    current: list[str] = []
    units = 0
    for char in label:
        width = 2 if ord(char) > 127 else 1
        if current and units + width > max_units:
            lines.append("".join(current))
            current, units = [], 0
        current.append(char)
        units += width
    if current or not lines:
        lines.append("".join(current))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# geometry
# ---------------------------------------------------------------------------


def _layout_positions(sem: rs.RenderSemantics, orientation: str) -> dict[str, tuple[float, float]]:
    """Deterministic positions honouring the legacy orientation convention.

    With a D2 ``layout`` the positions are authoritative (``x`` left->right,
    ``y`` top->bottom, normalized) and only the requested orientation is
    applied on top; without one the hand-rolled layered layout is transposed
    exactly as before.
    """
    if sem.positions is not None:
        pos = dict(sem.positions)
        if orientation == "BT":
            return {n: (x, 1.0 - y) for n, (x, y) in pos.items()}
        if orientation == "LR":
            return {n: (y, x) for n, (x, y) in pos.items()}
        if orientation == "RL":
            return {n: (1.0 - y, x) for n, (x, y) in pos.items()}
        return pos  # TB: D2's native frame already is top-to-bottom
    nid = [n.id for n in sem.nodes]
    edge_pairs = [(e.from_, e.to) for e in sem.edges]
    lay = LayerLayout(nid, edge_pairs)
    pos = lay.positions()
    if orientation == "TB":
        # LayerLayout's native coordinates are left-to-right; transpose them
        # so graph depth is top-to-bottom in the fallback renderer too.
        pos = {nid_: (y, 1.0 - x) for nid_, (x, y) in pos.items()}
    elif orientation == "BT":
        pos = {nid_: (y, x) for nid_, (x, y) in pos.items()}
    elif orientation == "RL":
        pos = {nid_: (1.0 - x, y) for nid_, (x, y) in pos.items()}
    return pos


def _box_sizes(sem: rs.RenderSemantics, labels: dict[str, str]):
    """Node box (width, height) map; notes grow the box downward only."""
    wrapped: dict[str, str] = {}
    notes: dict[str, str] = {}
    box_w: dict[str, float] = {}
    box_h: dict[str, float] = {}
    for node in sem.nodes:
        text = labels.get(node.id, node.label)
        wrapped[node.id] = _wrap_label(text)
        notes[node.id] = (rs.wrap_display_label(node.note, 16)
                          if node.note else "")
        box_w[node.id] = min(0.42, max(0.12, 0.06 + 0.012 * min(
            _label_len(text), 24
        )))
        if notes[node.id]:
            box_h[node.id] = min(
                0.28,
                0.09 + 0.035 * wrapped[node.id].count("\n")
                + 0.055 + 0.028 * notes[node.id].count("\n"),
            )
        else:
            # Byte-for-byte the pre-D-track formula (regression lock).
            box_h[node.id] = min(0.20, 0.09 + 0.035 * (wrapped[node.id].count("\n")))
    return wrapped, notes, box_w, box_h


def _bbox_for_orientation(bbox, orientation: str):
    """Map a D2 bbox (x L->R, y T->B) into the rendered orientation frame."""
    x0, y0, x1, y1 = bbox
    if orientation == "BT":
        x0, y0, x1, y1 = x0, 1.0 - y1, x1, 1.0 - y0
    elif orientation == "LR":
        x0, y0, x1, y1 = y0, x0, y1, x1
    elif orientation == "RL":
        x0, y0, x1, y1 = 1.0 - y1, x0, 1.0 - y0, x1
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _group_extent(group: rs.RenderGroup, members: list[str],
                  pos: dict[str, tuple[float, float]],
                  box_w: dict[str, float], box_h: dict[str, float],
                  orientation: str = "TB"):
    """(x0, y0, w, h) background box for one group (y0 is the visual top).

    When the group came from D2's layout its ``bbox`` is authoritative (the
    same geometry that placed the members); otherwise the box is the member
    envelope.  ``layer`` spans the full width and ``lane`` the full height.
    """
    if group.bbox is not None:
        x0, y0, x1, y1 = _bbox_for_orientation(group.bbox, orientation)
        return max(0.0, x0), max(0.0, y0), min(1.0, x1) - max(0.0, x0), \
            min(1.0, y1) - max(0.0, y0)
    xs = [pos[nid][0] for nid in members]
    ys = [pos[nid][1] for nid in members]
    pad_x = max(box_w[nid] for nid in members) / 2 + 0.03
    pad_y = max(box_h[nid] for nid in members) / 2 + 0.025
    x0, x1 = min(xs) - pad_x, max(xs) + pad_x
    y0, y1 = min(ys) - pad_y, max(ys) + pad_y
    if group.kind == "layer":
        # A layer band spans the whole drawing, like a manuscript swim-lane.
        x0, x1 = 0.004, 0.996
    elif group.kind == "lane":
        y0, y1 = 0.004, 0.996
    x0, x1 = max(0.0, x0), min(1.0, x1)
    y0, y1 = max(0.0, y0), min(1.0, y1)
    return x0, y0, max(0.0, x1 - x0), max(0.0, y1 - y0)


def _draw_groups(ax, sem: rs.RenderSemantics,
                 pos: dict[str, tuple[float, float]],
                 box_w: dict[str, float], box_h: dict[str, float],
                 orientation: str = "TB") -> list[str]:
    """Draw group backgrounds + titles; returns the drawn group ids in order."""
    membership = sem.membership
    drawn: list[str] = []
    for index, group in enumerate(sem.groups):
        members = [nid for nid in group.nodes if membership.get(nid) == group.id]
        if not members:
            continue
        fill, line = rs.group_colors(index)
        x0, y0, w, h = _group_extent(group, members, pos, box_w, box_h, orientation)
        if w <= 0 or h <= 0:
            continue
        ax.add_patch(Rectangle((x0, y0), w, h, facecolor=fill, edgecolor=line,
                               linewidth=1.3, alpha=0.45, zorder=0))
        if group.label:
            ax.text(x0 + 0.008, y0 + 0.014, group.label, ha="left", va="top",
                    fontsize=GROUP_FONTSIZE, color=line, fontweight="bold",
                    zorder=1)
        drawn.append(group.id)
    return drawn


# ---------------------------------------------------------------------------
# figure construction / rendering
# ---------------------------------------------------------------------------


def build_figure(nodes, edges, labels=None, *, groups=None, layout=None,
                 orientation: str = "TB"):
    """Build the deterministic figure; returns ``(fig, ax, drawn_group_ids)``.

    ``layout`` is D2's prepared geometry: its ``positions`` place the nodes and
    its per-group ``bbox`` draws the background boxes (authoritative), so the
    fallback renderer matches the layout engine byte-for-byte.
    """
    if not _MPL_OK:  # pragma: no cover
        raise RuntimeError("matplotlib is not available")

    sem = rs.normalize(nodes, edges, groups, layout)
    text_labels = dict(labels or {})
    for node in sem.nodes:
        text_labels.setdefault(node.id, node.label)
    pos = _layout_positions(sem, orientation)
    wrapped, notes, box_w, box_h = _box_sizes(sem, text_labels)
    npos = {n.id: pos[n.id] for n in sem.nodes}

    fig = plt.figure(figsize=(12, 8), dpi=120)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)
    ax.invert_yaxis()  # top->down flow
    ax.axis("off")

    drawn = _draw_groups(ax, sem, pos, box_w, box_h, orientation)

    for edge in sem.edges:
        x0, y0 = npos[edge.from_]
        x1, y1 = npos[edge.to]
        _draw_arrow(ax, x0, y0, x1, y1, box_w[edge.from_], box_h[edge.from_],
                    box_w[edge.to], box_h[edge.to], edge.label,
                    dashed=edge.dashed)
    for node in sem.nodes:
        x, y = npos[node.id]
        bw = box_w[node.id]
        bh = box_h[node.id]
        ax.add_patch(Rectangle((x - bw / 2, y - bh / 2), bw, bh,
                               fill=False, edgecolor="#1a1d29", linewidth=2.0,
                               zorder=3))
        if notes[node.id]:
            ax.text(x, y - 0.016, wrapped[node.id], ha="center", va="center",
                    fontsize=NODE_FONTSIZE, color=NODE_COLOR, zorder=4)
            ax.text(x, y + bh / 2 - 0.028, notes[node.id], ha="center",
                    va="center", fontsize=NOTE_FONTSIZE, color=NOTE_COLOR,
                    zorder=4)
        else:
            ax.text(x, y, wrapped[node.id], ha="center", va="center",
                    fontsize=NODE_FONTSIZE, color=NODE_COLOR, zorder=4)

    return fig, ax, drawn


def render(nodes, edges, labels=None, out_path: str = "", *,
           groups=None, layout=None, orientation: str = "TB") -> str:
    """Render canonical node ids/edge pairs to a deterministic PNG."""
    fig, _ax, _drawn = build_figure(nodes, edges, labels, groups=groups,
                                    layout=layout, orientation=orientation)
    fig.savefig(out_path, dpi=120, facecolor="white",
                bbox_inches="tight", pad_inches=0.1)
    plt.close("all")
    return out_path


def _draw_arrow(ax, x0, y0, x1, y1, w0, h0, w1, h1, label="", dashed=False):
    sx, sy = _clip(x0, y0, x1, y1, w0, h0)
    ex, ey = _clip(x1, y1, x0, y0, w1, h1)
    if dashed:
        ax.plot([sx, ex], [sy, ey], color=EDGE_COLOR, linewidth=1.8, zorder=1,
                solid_capstyle="round", linestyle=DASH_PATTERN)
        arrow_kwargs = {"linestyle": "dashed"}
    else:
        ax.plot([sx, ex], [sy, ey], color=EDGE_COLOR, linewidth=1.8, zorder=1,
                solid_capstyle="round")
        arrow_kwargs = {}
    ar = FancyArrowPatch((sx, sy), (ex, ey), arrowstyle="-|>",
                         mutation_scale=18, color=EDGE_COLOR, linewidth=1.8,
                         zorder=2, **arrow_kwargs)
    ax.add_patch(ar)
    if label:
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        ax.text(mx, my, label, ha="center", va="center", fontsize=EDGE_FONTSIZE,
                color=EDGE_LABEL_COLOR, zorder=3)


def _clip(x0, y0, x1, y1, w, h):
    dx, dy = x1 - x0, y1 - y0
    tx = (w / 2) / abs(dx) if abs(dx) > 1e-9 else 1e9
    ty = (h / 2) / abs(dy) if abs(dy) > 1e-9 else 1e9
    if tx == 1e9 and ty == 1e9:
        return x0, y0
    t = min(tx, ty)
    return x0 + dx * t, y0 + dy * t


__all__ = [
    "NODE_FONTSIZE",
    "EDGE_FONTSIZE",
    "NOTE_FONTSIZE",
    "GROUP_FONTSIZE",
    "DASH_PATTERN",
    "available",
    "build_figure",
    "render",
]
