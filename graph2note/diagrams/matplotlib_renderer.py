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

D5b (dense-diagram) additions
-----------------------------
* The grouped path derives its figure size from the *content* instead of the
  fixed ``12x8in`` canvas: every grid cell is made physically large enough for
  the widest wrapped label at the fixed font tiers, and each row reserves a
  vertical strip for its group title.  Dense diagrams (>=21 nodes, live
  01/02inc) used to overflow their node boxes and stack group titles on top of
  node text; the font tiers are never reduced (T-vision live §2/§4/§7-5).
* Group titles use a real bold CJK face when one is available instead of
  degrading to weight 400 with a ``findfont`` warning.  The *regular* family
  selection is unchanged, so the ungrouped fallback PNG stays byte-identical.

Backward compatibility: with no groups and no notes every drawing call is the
same as the pre-D-track renderer (same call order, same arguments), so the
fallback PNG is byte-identical to the existing golden.
"""

from __future__ import annotations

import math
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

# Smallest face weight matplotlib treats as a *true* bold.  Requesting the
# numeric weight (instead of "bold") keeps a 600-weight face from tripping
# matplotlib's "Failed to find font weight bold" degradation warning.
_BOLD_WEIGHT = 600

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


def _family_weights(family: str) -> set[int]:
    return {f.weight for f in fm.fontManager.ttflist if f.name == family}


def _select_cjk_fonts() -> tuple[str | None, str | None, int | None]:
    """Register the candidate fonts and pick regular + real-bold families.

    Returns ``(regular_family, bold_family, bold_weight)``.  The *regular*
    family keeps the historical first-match preference, so adding more
    candidates cannot change the ungrouped fallback bytes.  ``bold_family`` is
    the first candidate shipping a face heavy enough for a real group-title
    bold, and ``bold_weight`` is that face's numeric weight.
    """
    registered: list[str] = []
    for path in _CJK_FONT_CANDIDATES:
        if not os.path.exists(path):
            continue
        try:
            fm.fontManager.addfont(path)
            family = fm.FontProperties(fname=path).get_name()
        except Exception:
            continue
        if family and family not in registered:
            registered.append(family)
    if not registered:
        return None, None, None
    regular = registered[0]
    bold_family: str | None = None
    bold_weight: int | None = None
    for family in registered:
        heavy = [w for w in _family_weights(family) if w >= _BOLD_WEIGHT]
        if heavy:
            bold_family, bold_weight = family, max(heavy)
            break
    return regular, bold_family, bold_weight


def _register_cjk_font() -> str | None:
    """Pick and configure the regular CJK family; returns it (or ``None``).

    Kept as a named seam so the module-level setup below reads clearly and a
    test can re-run the selection if it ever needs to.
    """
    global _CJK_FAMILY, _CJK_BOLD_FAMILY, _CJK_BOLD_WEIGHT
    _CJK_FAMILY, _CJK_BOLD_FAMILY, _CJK_BOLD_WEIGHT = _select_cjk_fonts()
    if _CJK_FAMILY:
        matplotlib.rcParams["font.family"] = "sans-serif"
        matplotlib.rcParams["font.sans-serif"] = [_CJK_FAMILY, "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
    return _CJK_FAMILY


_CJK_FAMILY: str | None = None
_CJK_BOLD_FAMILY: str | None = None
_CJK_BOLD_WEIGHT: int | None = None
if _MPL_OK:
    _register_cjk_font()


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
# physical text metrics (points -> inches) for the dense/grouped geometry
# ---------------------------------------------------------------------------

_PT_PER_IN = 72.0
_LINE_SPACING = 1.25
_BOX_PAD_X_IN = 0.07
_BOX_PAD_Y_IN = 0.05
_TITLE_GAP_IN = 0.05
_NOTE_GAP_IN = 0.04
_CELL_GAP_FRAC = 0.16
_BASE_FIGSIZE = (12.0, 8.0)
_AXES_FRACTION = 0.96


def _text_size_in(text: str, fontsize: float) -> tuple[float, float]:
    """(width, height) in inches for a (possibly multi-line) label.

    Width reuses the renderer's ``1 unit == half an em`` convention (a CJK
    glyph is 2 units == 1 em, ASCII ~1 unit == half an em), so it tracks the
    CJK font metrics closely without reading font files and stays deterministic
    across environments.
    """
    if not text:
        return 0.0, 0.0
    lines = text.split("\n")
    width_pt = max(_label_len(line) for line in lines) / 2.0 * fontsize
    height_pt = len(lines) * _LINE_SPACING * fontsize
    return width_pt / _PT_PER_IN, height_pt / _PT_PER_IN


def _grid_dims(pos: dict[str, tuple[float, float]]) -> tuple[int, int]:
    """(rows, cols) of the normalized grid the layout placed nodes on.

    Derived from the smallest coordinate gap (the grid pitch); ``ceil`` keeps
    the estimate conservative for hand-built (non-uniform) positions so boxes
    can never be sized wider than their actual spacing.
    """
    def cells(values: list[float]) -> int:
        ordered = sorted(values)
        gaps = [b - a for a, b in zip(ordered, ordered[1:]) if b - a > 1e-9]
        if not gaps:
            return 1
        return max(1, int(math.ceil(1.0 / min(gaps) - 1e-6)))

    return cells([p[1] for p in pos.values()]), cells([p[0] for p in pos.values()])


def _grouped_geometry(sem: rs.RenderSemantics,
                      pos: dict[str, tuple[float, float]],
                      wrapped: dict[str, str],
                      notes: dict[str, str]) -> dict:
    """Content-sized figure + node boxes for a grouped diagram.

    Solves the T-vision live defect: a fixed canvas collapsed dense diagrams
    (>=21 nodes) until node text escaped its box and group titles landed on
    node text.  Instead of shrinking fonts, every cell is grown to fit the
    widest wrapped label at the fixed tiers and every row keeps a title strip.
    Node positions and group bboxes remain the layout's authoritative geometry.
    """
    nrows, ncols = _grid_dims(pos)

    label_sizes: dict[str, tuple[float, float]] = {}
    note_sizes: dict[str, tuple[float, float]] = {}
    text_sizes: dict[str, tuple[float, float]] = {}
    max_w = 0.0
    max_h = 0.0
    for node in sem.nodes:
        label_size = _text_size_in(wrapped[node.id], NODE_FONTSIZE)
        note_size = _text_size_in(notes[node.id], NOTE_FONTSIZE)
        label_sizes[node.id] = label_size
        note_sizes[node.id] = note_size
        width = max(label_size[0], note_size[0])
        height = label_size[1]
        if notes[node.id]:
            height += note_size[1] + _NOTE_GAP_IN
        text_sizes[node.id] = (width, height)
        max_w = max(max_w, width)
        max_h = max(max_h, height)

    title_sizes = [_text_size_in(g.label, GROUP_FONTSIZE)
                   for g in sem.groups if g.label]
    title_h = max((size[1] for size in title_sizes), default=0.0)

    cell_w_in = (max_w + 2 * _BOX_PAD_X_IN) / (1 - _CELL_GAP_FRAC)
    cell_h_in = max_h + 2 * _BOX_PAD_Y_IN + 2 * (title_h + _TITLE_GAP_IN)
    fig_w = max(_BASE_FIGSIZE[0], ncols * cell_w_in / _AXES_FRACTION)
    fig_h = max(_BASE_FIGSIZE[1], nrows * cell_h_in / _AXES_FRACTION)
    axes_w_in = fig_w * _AXES_FRACTION
    axes_h_in = fig_h * _AXES_FRACTION

    max_box_w = (1.0 / ncols) * (1 - _CELL_GAP_FRAC)
    title_h_norm = title_h / axes_h_in
    title_gap_norm = _TITLE_GAP_IN / axes_h_in
    max_box_h = (1.0 / nrows) - 2 * (title_h_norm + title_gap_norm)

    box_w: dict[str, float] = {}
    box_h: dict[str, float] = {}
    label_dy: dict[str, float] = {}
    note_dy: dict[str, float] = {}
    for node in sem.nodes:
        text_w, text_h = text_sizes[node.id]
        box_w[node.id] = min(max_box_w,
                             (text_w + 2 * _BOX_PAD_X_IN) / axes_w_in)
        box_h[node.id] = min(max_box_h,
                             (text_h + 2 * _BOX_PAD_Y_IN) / axes_h_in)
        label_height = label_sizes[node.id][1]
        note_height = note_sizes[node.id][1]
        if notes[node.id]:
            # Stack label above note, centred as one block in the box.
            total = label_height + _NOTE_GAP_IN + note_height
            label_dy[node.id] = (-total / 2 + label_height / 2) / axes_h_in
            note_dy[node.id] = (total / 2 - note_height / 2) / axes_h_in
        else:
            label_dy[node.id] = 0.0
            note_dy[node.id] = 0.0

    return {
        "figsize": (fig_w, fig_h),
        "box_w": box_w,
        "box_h": box_h,
        "label_dy": label_dy,
        "note_dy": note_dy,
        "title_gap": title_gap_norm,
    }


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


def _group_title_style(line_color: str):
    """Font kwargs + optional synthetic-bold effect for a group title.

    A real bold CJK face is preferred; requesting ``"bold"`` when only a
    600-weight face exists still logs matplotlib's degradation warning, so the
    numeric weight is requested.  When no heavy CJK face is installed the
    regular family stays and the weight is faked with a thin stroke, which is
    visually distinguishable and never warns.
    """
    if _CJK_BOLD_FAMILY and _CJK_BOLD_WEIGHT:
        return ({"fontfamily": [_CJK_BOLD_FAMILY],
                 "fontweight": _CJK_BOLD_WEIGHT}, None)
    try:
        import matplotlib.patheffects as pe
        return {}, [pe.withStroke(linewidth=1.0, foreground=line_color)]
    except Exception:  # pragma: no cover - patheffects ships with matplotlib
        return {}, None


def _draw_groups(ax, sem: rs.RenderSemantics,
                 pos: dict[str, tuple[float, float]],
                 box_w: dict[str, float], box_h: dict[str, float],
                 orientation: str = "TB", title_gap: float | None = None) -> list[str]:
    """Draw group backgrounds + titles; returns the drawn group ids in order.

    ``title_gap`` (normalized, grouped/dense path) moves each title into the
    strip the geometry reserved above its topmost member box; ``None`` keeps
    the legacy top-left placement for direct renderer calls.
    """
    membership = sem.membership
    # Top of the tallest node box on each grid row: a group title must clear the
    # *whole* row, not only its own (possibly shorter) members, or it lands on a
    # neighbouring node's label (T-vision live §4).
    row_top: dict[float, float] = {}
    for node in sem.nodes:
        row = round(pos[node.id][1], 6)
        top = pos[node.id][1] - box_h[node.id] / 2
        row_top[row] = min(row_top.get(row, top), top)
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
            if title_gap is None:
                tx, ty, va = x0 + 0.008, y0 + 0.014, "top"
            else:
                # Anchor the title's *bottom* in the reserved strip so the text
                # grows upward, clear of the row's node boxes.
                tx, ty, va = x0 + 0.008, \
                    min(row_top[round(pos[nid][1], 6)] for nid in members) - title_gap, \
                    "bottom"
            style, effects = _group_title_style(line)
            title = ax.text(tx, ty, group.label, ha="left", va=va,
                            fontsize=GROUP_FONTSIZE, color=line, zorder=1,
                            **style)
            if effects:
                title.set_path_effects(effects)
        drawn.append(group.id)
    return drawn


# ---------------------------------------------------------------------------
# figure construction / rendering
# ---------------------------------------------------------------------------


def _draw_nodes(ax, sem: rs.RenderSemantics,
                npos: dict[str, tuple[float, float]],
                wrapped: dict[str, str], notes: dict[str, str],
                box_w: dict[str, float], box_h: dict[str, float],
                label_dy: dict[str, float] | None,
                note_dy: dict[str, float] | None) -> None:
    """Draw node boxes + labels, then the (smaller) note under the label."""
    for node in sem.nodes:
        x, y = npos[node.id]
        bw = box_w[node.id]
        bh = box_h[node.id]
        ax.add_patch(Rectangle((x - bw / 2, y - bh / 2), bw, bh,
                               fill=False, edgecolor="#1a1d29", linewidth=2.0,
                               zorder=3))
        if label_dy is not None:
            # Dense/grouped path: label + note form one block centred in the box.
            ax.text(x, y + label_dy[node.id], wrapped[node.id], ha="center",
                    va="center", fontsize=NODE_FONTSIZE, color=NODE_COLOR,
                    zorder=4)
            if notes[node.id]:
                ax.text(x, y + note_dy[node.id], notes[node.id], ha="center",
                        va="center", fontsize=NOTE_FONTSIZE, color=NOTE_COLOR,
                        zorder=4)
        elif notes[node.id]:
            # Legacy ungrouped placement (PNG byte-locked by the golden).
            ax.text(x, y - 0.016, wrapped[node.id], ha="center", va="center",
                    fontsize=NODE_FONTSIZE, color=NODE_COLOR, zorder=4)
            ax.text(x, y + bh / 2 - 0.028, notes[node.id], ha="center",
                    va="center", fontsize=NOTE_FONTSIZE, color=NOTE_COLOR,
                    zorder=4)
        else:
            ax.text(x, y, wrapped[node.id], ha="center", va="center",
                    fontsize=NODE_FONTSIZE, color=NODE_COLOR, zorder=4)


def build_figure(nodes, edges, labels=None, *, groups=None, layout=None,
                 orientation: str = "TB"):
    """Build the deterministic figure; returns ``(fig, ax, drawn_group_ids)``.

    ``layout`` is D2's prepared geometry: its ``positions`` place the nodes and
    its per-group ``bbox`` draws the background boxes (authoritative), so the
    fallback renderer matches the layout engine byte-for-byte.  With groups the
    canvas auto-sizes to the content (D5b); without groups the legacy fixed
    canvas is kept byte-for-byte.
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

    label_dy: dict[str, float] | None = None
    note_dy: dict[str, float] | None = None
    title_gap: float | None = None
    avoid_boxes: list[tuple[float, float, float, float]] = []
    if sem.groups:
        geometry = _grouped_geometry(sem, pos, wrapped, notes)
        fig_w, fig_h = geometry["figsize"]
        box_w, box_h = geometry["box_w"], geometry["box_h"]
        label_dy, note_dy = geometry["label_dy"], geometry["note_dy"]
        title_gap = geometry["title_gap"]
    else:
        fig_w, fig_h = _BASE_FIGSIZE
    avoid_boxes = [
        (pos[n.id][0] - box_w[n.id] / 2, pos[n.id][1] - box_h[n.id] / 2,
         pos[n.id][0] + box_w[n.id] / 2, pos[n.id][1] + box_h[n.id] / 2)
        for n in sem.nodes
    ]

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=120)
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    ax.set_xlim(0, 1.0)
    ax.set_ylim(0, 1.0)
    ax.invert_yaxis()  # top->down flow
    ax.axis("off")

    drawn = _draw_groups(ax, sem, pos, box_w, box_h, orientation,
                         title_gap=title_gap)

    for edge in sem.edges:
        x0, y0 = npos[edge.from_]
        x1, y1 = npos[edge.to]
        _draw_arrow(ax, x0, y0, x1, y1, box_w[edge.from_], box_h[edge.from_],
                    box_w[edge.to], box_h[edge.to], edge.label,
                    dashed=edge.dashed,
                    avoid_boxes=(avoid_boxes if sem.groups else None),
                    axes_size=(fig_w * _AXES_FRACTION, fig_h * _AXES_FRACTION))
    _draw_nodes(ax, sem, npos, wrapped, notes, box_w, box_h, label_dy, note_dy)

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


def _draw_arrow(ax, x0, y0, x1, y1, w0, h0, w1, h1, label="", dashed=False,
                avoid_boxes=None, axes_size=None):
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
        if avoid_boxes and axes_size:
            mx, my = _place_edge_label(label, sx, sy, ex, ey, avoid_boxes,
                                       axes_size)
        ax.text(mx, my, label, ha="center", va="center", fontsize=EDGE_FONTSIZE,
                color=EDGE_LABEL_COLOR, zorder=3)


def _place_edge_label(label, sx, sy, ex, ey, boxes, axes_size):
    """Pick a point on the edge whose label box misses every node box.

    Long diagonal edges can cross an unrelated node; the midpoint label then
    landed on that node's text.  The grouped path slides the label towards an
    endpoint (fixed candidate order -> deterministic) until it is clear; the
    flat path never calls this, so its PNG stays byte-identical.
    """
    axes_w_in, axes_h_in = axes_size
    half_w = (_label_len(label) / 2.0 * EDGE_FONTSIZE / _PT_PER_IN
              / max(axes_w_in, 1e-9)) / 2.0
    half_h = (_LINE_SPACING * EDGE_FONTSIZE / _PT_PER_IN
              / max(axes_h_in, 1e-9)) / 2.0

    def clear(mx, my):
        for bx0, by0, bx1, by1 in boxes:
            if (mx - half_w < bx1 and mx + half_w > bx0
                    and my - half_h < by1 and my + half_h > by0):
                return False
        return True

    for t in (0.5, 0.35, 0.65, 0.28, 0.72, 0.22, 0.78, 0.15, 0.85):
        mx, my = sx + (ex - sx) * t, sy + (ey - sy) * t
        if clear(mx, my):
            return mx, my
    return (sx + ex) / 2, (sy + ey) / 2


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
