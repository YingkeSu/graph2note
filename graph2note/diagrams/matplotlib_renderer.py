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

X3/X4 additions
---------------
* Text is measured with the real Agg font metrics (``_text_size_in``) instead
  of the historical ``1 unit == half an em`` heuristic, which under-measured
  mixed CJK/Latin labels and let text touch its own node box (D5b F1).
* Group frames no longer use overlapping member-envelope boxes: when the
  derived boxes of a figure intersect, each frame becomes the *partition* of
  its grid domain (one cell belongs to at most one group), so frames may touch
  but never overlap while every member keeps a frame (live 01 = 9 pairs and
  02inc = 2 pairs -> 0).  Disjoint-box figures still draw the layout bbox
  verbatim, so the renderer/geometry contract and golden output are unchanged.

Backward compatibility: with no groups and no notes every drawing call is the
same as the pre-D-track renderer (same call order, same arguments), so the
fallback PNG is byte-identical to the existing golden.

X6 (default-view legibility) additions
--------------------------------------
* The D5b geometry grew the canvas with the content, which made the dense live
diagrams 20-23in wide; displayed in the document's 720px reading column their
10pt note tier collapsed to ~4.5-5px.  The grouped geometry is now bounded by
``legibility_max_figure_width()`` (the width at which the note tier still
measures ``DOC_MIN_NOTE_PX`` px at ``DOC_READING_WIDTH_PX``) and absorbs the
remaining density *vertically* by narrowing the word-aware wrap budget
(``_compact_text``).  Target labels/notes keep their font tiers; only the
number of wrapped lines grows.  The canvas floor drops from 12in to
``_MIN_GROUPED_FIG_W`` (720px at the render DPI) so compact diagrams are not
padded out, and the horizontal text padding / inter-cell seam are tightened
(0.07/0.16 -> 0.05/0.10) to make room.
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
_BOX_PAD_X_IN = 0.05
_BOX_PAD_Y_IN = 0.05
_TITLE_GAP_IN = 0.05
_NOTE_GAP_IN = 0.04
# Horizontal seam kept between two neighbouring grid cells (fraction of a
# cell).  X6 lowered this from 0.16 to 0.10: the reading-width budget (below)
# needs the slack to keep the widest labels on one line, while a 10% seam still
# separates the node boxes visually.
_CELL_GAP_FRAC = 0.10
_BASE_FIGSIZE = (12.0, 8.0)
_AXES_FRACTION = 0.96

# --- X6: default-document-view legibility budget -------------------------
# The reading pane shows a diagram at container width (720px desktop, 390px
# mobile).  A PNG of ``fontsize`` pt displayed at container width ``C`` shows
# glyphs of ``fontsize * C / (72 * trimmed_width_in)`` pixels.  D5b solved
# native overlap by growing the canvas with the content, so the dense live
# diagrams (21/32 nodes) became 20-23in wide and their 10pt note tier shrank to
# ~4.5-5px at 720px - the default view was unreadable without the zoom viewer.
# X6 instead bounds the canvas by the reading width and buys legibility with
# *height* (more wrapped lines / rows) instead of width, so the default view
# itself stays legible.
DOC_READING_WIDTH_PX = 720.0
DOC_MIN_NOTE_PX = 9.4
_PNG_PAD_IN = 0.1          # ``render()``'s ``bbox_inches="tight"`` pad
# 720px at the render DPI: below this the reading pane would up-scale the PNG.
_MIN_GROUPED_FIG_W = 6.0
# Per-line wrap budgets tried as the compact fit narrows (CJK counts 2 units).
# 18 is the historical grouped label budget; the tail is the best effort for a
# pathologically wide band.
_COMPACT_WRAP_UNITS = (18, 16, 14, 12, 10, 9, 8, 7, 6, 5, 4, 3, 2)
# Clearance kept between two group titles that would otherwise share a title
# strip (slid sideways), and between a stacked title and the strip it left.
_TITLE_SLIDE_PAD_IN = 0.12
_TITLE_ROW_PAD_IN = 0.02
# The canvas edge is a soft bound: the row's title strip can sit exactly on
# ``y == 0`` (``ty - text_h`` lands on -1e-18 through float rounding), so the
# on-canvas check needs a tolerance or that legal anchor is rejected.
_CANVAS_EPS = 1e-6


def legibility_max_figure_width(
    container_px: float = DOC_READING_WIDTH_PX,
    min_note_px: float = DOC_MIN_NOTE_PX,
    note_fontsize: float = NOTE_FONTSIZE,
) -> float:
    """Largest figure width (inches) that keeps the note tier legible.

    ``render()`` writes the PNG with ``bbox_inches="tight"`` and a 0.1in pad,
    and the grouped axes span ``_AXES_FRACTION`` of the figure, so the trimmed
    PNG width is ``_AXES_FRACTION * fig_w + 2 * _PNG_PAD_IN``.  Solving the
    display equation ``note_fontsize * container / (72 * trimmed) >= min_note``
    for ``fig_w`` gives this budget.  The assumption that the drawing fills the
    axes is conservative (a narrower drawing only displays larger).
    """
    trimmed = note_fontsize * container_px / (72.0 * min_note_px)
    return max(0.0, (trimmed - 2 * _PNG_PAD_IN) / _AXES_FRACTION)


def default_view_text_px(
    fontsize: float,
    fig_width_in: float,
    container_px: float = DOC_READING_WIDTH_PX,
) -> float:
    """Displayed pixel height of a ``fontsize`` pt tier in the reading pane.

    Inverse of the budget model: a diagram of ``fig_width_in`` inches is
    trimmed to ``_AXES_FRACTION * fig_width_in + 2 * _PNG_PAD_IN`` and scaled to
    the container width, so the glyphs land at this many pixels.
    """
    trimmed = _AXES_FRACTION * fig_width_in + 2 * _PNG_PAD_IN
    return fontsize * container_px / (72.0 * max(trimmed, 1e-9))


def _title_font_properties(fontsize: float):
    """FontProperties matching the face the group titles are actually drawn in.

    The title layer may switch to a real bold CJK face (D5b), which is a few
    percent wider than the regular face for mixed CJK/Latin labels; measuring
    with the regular face would under-size the de-confliction boxes.
    """
    if _CJK_BOLD_FAMILY and _CJK_BOLD_WEIGHT:
        return fm.FontProperties(family=[_CJK_BOLD_FAMILY], size=fontsize,
                                 weight=_CJK_BOLD_WEIGHT)
    return fm.FontProperties(size=fontsize)


_TEXT_METRIC_RENDERER = None


def _text_metric_renderer():
    """A tiny Agg renderer used only to read real font metrics (in points).

    Created lazily so importing this module never pays for it, and kept for the
    process lifetime so repeated geometry passes stay cheap.
    """
    global _TEXT_METRIC_RENDERER
    if _TEXT_METRIC_RENDERER is None:
        from matplotlib.backends.backend_agg import RendererAgg
        _TEXT_METRIC_RENDERER = RendererAgg(64, 64, _PT_PER_IN)
    return _TEXT_METRIC_RENDERER


def _text_size_in(text: str, fontsize: float,
                  prop=None) -> tuple[float, float]:
    """(width, height) in inches for a (possibly multi-line) label.

    Measures the real Agg font metrics instead of the historical
    ``1 unit == half an em`` heuristic.  That heuristic underestimated mixed
    CJK/Latin + full-width punctuation by ~12% (D5b F1: live02 ``n7`` escaped
    its own box by 3px bbox / 1px ink), because ASCII glyphs are wider than
    half an em in the selected CJK/Latin faces.  The metric renderer resolves
    fonts through the same rcParams family list as the drawn text, so the CJK
    fallback chain and the no-``findfont``-warning property are unchanged.
    ``prop`` lets the title layer measure the exact bold face it draws.
    """
    if not text:
        return 0.0, 0.0
    if prop is None:
        prop = fm.FontProperties(size=fontsize)
    renderer = _text_metric_renderer()
    lines = text.split("\n")
    width_pt = 0.0
    for line in lines:
        w, _h, _d = renderer.get_text_width_height_descent(line, prop, False)
        width_pt = max(width_pt, w)
    # Height keeps the historical line-box model: matplotlib's multi-line
    # ``linespacing`` (default 1.2em) is slightly larger than the glyph
    # metrics returned by the renderer, so the real height would let a wrapped
    # label/note spill vertically out of its box.
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


def _cell_width_in(max_text_w: float) -> float:
    """Grid-cell width needed to hold text of ``max_text_w`` inches."""
    return (max_text_w + 2 * _BOX_PAD_X_IN) / (1 - _CELL_GAP_FRAC)


def _fits_reading_width(ncols: int, sem: rs.RenderSemantics,
                        wrapped: dict[str, str], notes: dict[str, str],
                        max_fig_w: float) -> bool:
    """Would this text wrap fit ``ncols`` cells inside the reading budget?"""
    max_w = 0.0
    for node in sem.nodes:
        max_w = max(max_w, _text_size_in(wrapped[node.id], NODE_FONTSIZE)[0],
                    _text_size_in(notes[node.id], NOTE_FONTSIZE)[0])
    return ncols * _cell_width_in(max_w) / _AXES_FRACTION <= max_fig_w + 1e-9


def _compact_text(sem: rs.RenderSemantics, ncols: int,
                  wrapped: dict[str, str], notes: dict[str, str],
                  raw_labels: dict[str, str],
                  max_fig_w: float) -> tuple[dict[str, str], dict[str, str]]:
    """Narrow the per-line wrap budget until the band fits the reading width.

    Returns the possibly re-wrapped ``(wrapped, notes)`` maps.  The incoming
    wrap is left untouched whenever it already fits the budget, so diagrams
    that never hit the dense path render exactly as before.  Otherwise the
    first (largest) budget from ``_COMPACT_WRAP_UNITS`` that fits is used; the
    text is re-wrapped from the *raw* label (not the already char-wrapped
    ``wrapped`` map) with the word-aware ``rs.wrap_display_label``, so Latin
    words are only split as a last resort.  If even the narrowest budget cannot
    fit the band (a pathologically wide row) the narrowest wrap is returned and
    the caller lets the canvas exceed the budget - density, not legibility, is
    sacrificed.
    """
    if _fits_reading_width(ncols, sem, wrapped, notes, max_fig_w):
        return wrapped, notes
    compact_wrapped, compact_notes = wrapped, notes
    for units in _COMPACT_WRAP_UNITS:
        compact_wrapped = {
            n.id: rs.wrap_display_label(raw_labels.get(n.id, n.label), units)
            for n in sem.nodes
        }
        compact_notes = {
            n.id: (rs.wrap_display_label(notes[n.id], units) if notes[n.id]
                   else "")
            for n in sem.nodes
        }
        if _fits_reading_width(ncols, sem, compact_wrapped, compact_notes,
                               max_fig_w):
            return compact_wrapped, compact_notes
    return compact_wrapped, compact_notes


def _grouped_geometry(sem: rs.RenderSemantics,
                      pos: dict[str, tuple[float, float]],
                      wrapped: dict[str, str],
                      notes: dict[str, str],
                      raw_labels: dict[str, str] | None = None) -> dict:
    """Content-sized figure + node boxes for a grouped diagram.

    Solves the T-vision live defect: a fixed canvas collapsed dense diagrams
    (>=21 nodes) until node text escaped its box and group titles landed on
    node text.  Instead of shrinking fonts, every cell is grown to fit the
    widest wrapped label at the fixed tiers and every row keeps a title strip.
    Node positions and group bboxes remain the layout's authoritative geometry.

    X6 adds the default-view legibility budget: the canvas width never exceeds
    ``legibility_max_figure_width`` when a wrap can fit inside it, and the
    lower bound drops to ``_MIN_GROUPED_FIG_W`` so a compact diagram is not
    padded back out to 12in (which alone costs ~1px of the note tier at 720px).
    Density is absorbed vertically by the compact wrap, so the reading pane's
    default (non-zoomed) view stays legible.
    """
    nrows, ncols = _grid_dims(pos)
    max_fig_w = legibility_max_figure_width()
    if raw_labels is None:
        raw_labels = {n.id: n.label for n in sem.nodes}
    wrapped, notes = _compact_text(sem, ncols, wrapped, notes, raw_labels,
                                   max_fig_w)

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

    title_sizes = [_text_size_in(g.label, GROUP_FONTSIZE,
                                 _title_font_properties(GROUP_FONTSIZE))
                   for g in sem.groups if g.label]
    title_h = max((size[1] for size in title_sizes), default=0.0)

    cell_w_in = _cell_width_in(max_w)
    cell_h_in = max_h + 2 * _BOX_PAD_Y_IN + 2 * (title_h + _TITLE_GAP_IN)
    fig_w = max(_MIN_GROUPED_FIG_W, ncols * cell_w_in / _AXES_FRACTION)
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
        "wrapped": wrapped,
        "notes": notes,
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


def _axis_cells(values: list[float]):
    """(value -> index, cell boundaries, sorted centres) of a layout axis."""
    unique = sorted({round(v, 6) for v in values})
    if not unique:
        return {}, [], []
    if len(unique) == 1:
        return {unique[0]: 0}, [unique[0] - 0.5, unique[0] + 0.5], unique
    bounds = [unique[0] - (unique[1] - unique[0]) / 2.0]
    for i in range(1, len(unique)):
        bounds.append((unique[i - 1] + unique[i]) / 2.0)
    bounds.append(unique[-1] + (unique[-1] - unique[-2]) / 2.0)
    return {v: i for i, v in enumerate(unique)}, bounds, unique


def _axis_range(centres: list[float], lo: float, hi: float):
    """Inclusive index range of the centres inside ``[lo, hi]`` (or ``None``)."""
    inside = [i for i, v in enumerate(centres) if lo - 1e-9 <= v <= hi + 1e-9]
    return (inside[0], inside[-1]) if inside else None


def _merge_cells(cells):
    """Merge grid cells into maximal rectangles ``(r0, c0, c1, r1)``."""
    runs: list[list[int]] = []
    for row, col in sorted(set(cells)):
        if runs and runs[-1][0] == row and runs[-1][2] + 1 == col:
            runs[-1][2] = col
        else:
            runs.append([row, col, col])
    merged: list[list[int]] = []
    for row, c0, c1 in runs:
        if (merged and merged[-1][1] == c0 and merged[-1][2] == c1
                and merged[-1][3] + 1 == row):
            merged[-1][3] = row
        else:
            merged.append([row, c0, c1, row])
    return merged


def _group_frame_cells(sem: rs.RenderSemantics,
                       pos: dict[str, tuple[float, float]],
                       box_w: dict[str, float], box_h: dict[str, float],
                       orientation: str):
    """Disjoint per-group frame rectangles for the drawn figure.

    D5b/D6 left ``_group_extent``'s member *bounding boxes* overlapping when a
    lane band and one or more clusters shared a row strip, or when clusters
    interleaved across rows (live 01 = 9 pairs, 02inc = 2 pairs).  Each frame
    is still the group's domain rectangle (``_group_extent``) snapped to the
    layout grid, but **every cell belongs to at most one group**: a cell that
    holds another group's member is never claimed, and among empty cells that
    two domains could share the earlier group (``sem.groups`` order) wins.
    The frames therefore form a partition - borders may touch but never
    intersect - while every member still sits inside its own group's frame.

    Returns ``(rects_by_group, cell_of)`` with normalized ``(x0, y0, w, h)``
    rectangles (``y0`` is the visual top).
    """
    xs = [pos[n.id][0] for n in sem.nodes]
    ys = [pos[n.id][1] for n in sem.nodes]
    x_of, x_bounds, x_centres = _axis_cells(xs)
    y_of, y_bounds, y_centres = _axis_cells(ys)
    cell_of = {n.id: (y_of[round(pos[n.id][1], 6)],
                      x_of[round(pos[n.id][0], 6)]) for n in sem.nodes}
    membership = sem.membership
    cell_owner = {cell_of[n.id]: membership.get(n.id) for n in sem.nodes}

    claimed: dict[tuple[int, int], str] = {}
    cells_by_group: dict[str, list[tuple[int, int]]] = {}
    for group in sem.groups:
        members = [nid for nid in group.nodes if membership.get(nid) == group.id]
        if not members:
            continue
        x0, y0, w, h = _group_extent(group, members, pos, box_w, box_h,
                                     orientation)
        cols = _axis_range(x_centres, x0, x0 + w)
        rows = _axis_range(y_centres, y0, y0 + h)
        if cols is None or rows is None:
            rows = (min(cell_of[m][0] for m in members),
                    max(cell_of[m][0] for m in members))
            cols = (min(cell_of[m][1] for m in members),
                    max(cell_of[m][1] for m in members))
        owned: list[tuple[int, int]] = []
        for row in range(rows[0], rows[1] + 1):
            for col in range(cols[0], cols[1] + 1):
                cell = (row, col)
                if cell in claimed:
                    continue
                owner = cell_owner.get(cell)
                if owner is not None and owner != group.id:
                    continue
                claimed[cell] = group.id
                owned.append(cell)
        cells_by_group[group.id] = owned

    rects_by_group: dict[str, list[tuple[float, float, float, float]]] = {}
    for group_id, cells in cells_by_group.items():
        rects = []
        for r0, c0, c1, r1 in _merge_cells(cells):
            x0 = x_bounds[c0]
            y0 = y_bounds[r0]
            rects.append((x0, y0, x_bounds[c1 + 1] - x0,
                          y_bounds[r1 + 1] - y0))
        rects_by_group[group_id] = rects
    return rects_by_group, cell_of


def _rects_intersect(rects) -> bool:
    """Does any pair of ``(x0, y0, w, h)`` rectangles overlap by area?"""
    for i, (x0, y0, w, h) in enumerate(rects):
        for x1, y1, w1, h1 in rects[i + 1:]:
            ox = min(x0 + w, x1 + w1) - max(x0, x1)
            oy = min(y0 + h, y1 + h1) - max(y0, y1)
            if ox > 1e-9 and oy > 1e-9:
                return True
    return False


def _group_frames(sem: rs.RenderSemantics,
                  pos: dict[str, tuple[float, float]],
                  box_w: dict[str, float], box_h: dict[str, float],
                  orientation: str):
    """Frame rectangles for every drawable group, keyed by group id.

    When the authoritative/derived boxes are already disjoint the layout bbox
    is drawn **verbatim** - the D3 contract that the renderer never disagrees
    with the geometry owner (and the reason golden/flat output is unchanged).
    Only a figure whose boxes actually intersect takes the X3 partition path,
    where frames can no longer intersect while every member keeps a frame.
    """
    membership = sem.membership
    naive: dict[str, tuple[float, float, float, float]] = {}
    for group in sem.groups:
        members = [nid for nid in group.nodes if membership.get(nid) == group.id]
        if not members:
            continue
        x0, y0, w, h = _group_extent(group, members, pos, box_w, box_h,
                                     orientation)
        if w <= 0 or h <= 0:
            continue
        naive[group.id] = (x0, y0, w, h)
    if not _rects_intersect(list(naive.values())):
        return {group_id: [rect] for group_id, rect in naive.items()}
    return _group_frame_cells(sem, pos, box_w, box_h, orientation)[0]


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


def _title_box(tx: float, ty: float, w: float, h: float):
    """Text box of a ``va="bottom"`` title anchored at ``(tx, ty)``.

    The y axis is inverted (top -> down), so the glyph block grows towards
    *smaller* y; the box is ``(x0, top, x1, bottom)``.
    """
    return tx, ty - h, tx + w, ty


def _boxes_hit(a, b, pad_x: float = 0.0, pad_y: float = 0.0) -> bool:
    """Do two ``(x0, top, x1, bottom)`` boxes intersect (padded slack)?"""
    return (a[0] < b[2] + pad_x and a[2] > b[0] - pad_x
            and a[1] < b[3] + pad_y and a[3] > b[1] - pad_y)


def _place_group_titles(candidates: list[dict], node_boxes: list, axes_size,
                        title_gap: float) -> list[tuple[float, float]]:
    """Resolve group-title collisions; returns ``[(tx, ty)]`` in input order.

    T-vision final report §3: a lane band and a cluster that share a row band
    *and* a left edge produced two titles anchored on the same point (01: 2
    pairs, 02inc: 1 pair).  Titles are now placed greedily in group order: a
    title keeps its historical anchor unless that box hits an already-placed
    title, in which case it first slides sideways along its own title strip and
    then stacks into the reserved strip above the row.  Every move is checked
    against the node boxes too, and the historical anchor is the fallback, so a
    collision-free figure is laid out exactly as before (golden-safe).
    """
    axes_w_in, axes_h_in = axes_size
    pad_x = _TITLE_SLIDE_PAD_IN / max(axes_w_in, 1e-9)
    pad_y = _TITLE_ROW_PAD_IN / max(axes_h_in, 1e-9)
    placed: list[tuple[float, float, float, float]] = []
    anchors: list[tuple[float, float]] = []
    for cand in candidates:
        tx, ty, w, h = cand["tx"], cand["ty"], cand["w"], cand["h"]
        base = _title_box(tx, ty, w, h)
        chosen = base
        if any(_boxes_hit(base, other, pad_x, pad_y) for other in placed):
            # Same title strip = already-visible titles this one would cross.
            band = [r for r in placed
                    if r[1] < base[3] + pad_y and r[3] > base[1] - pad_y]
            xs = [tx]
            if band:
                xs.append(max(r[2] for r in band) + pad_x)
                xs.append(min(r[0] for r in band) - pad_x - w)
            found = None
            for y in [ty] + [ty - k * (h + title_gap) for k in (1, 2, 3)]:
                for x in xs:
                    box = _title_box(x, y, w, h)
                    if (box[0] < -_CANVAS_EPS or box[2] > 1.0 + _CANVAS_EPS
                            or box[1] < -_CANVAS_EPS):
                        continue  # off-canvas / above the drawing
                    if any(_boxes_hit(box, other, pad_x, pad_y)
                           for other in placed):
                        continue
                    if any(_boxes_hit(box, nb) for nb in node_boxes):
                        continue
                    found = box
                    break
                if found is not None:
                    break
            if found is not None:
                chosen = found
        placed.append(chosen)
        anchors.append((chosen[0], chosen[3]))
    return anchors


def _draw_groups(ax, sem: rs.RenderSemantics,
                 pos: dict[str, tuple[float, float]],
                 box_w: dict[str, float], box_h: dict[str, float],
                 orientation: str = "TB", title_gap: float | None = None) -> list[str]:
    """Draw group backgrounds + titles; returns the drawn group ids in order.

    Frames come from :func:`_group_frames`: a disjoint set of group boxes is
    drawn verbatim (layout bbox), while an intersecting figure is partitioned
    into grid cells so two frames never overlap (X3).  ``title_gap``
    (normalized, grouped/dense path) moves each title into the strip the
    geometry reserved above its topmost member box and de-conflicts titles
    *across groups*; ``None`` keeps the legacy top-left placement for direct
    renderer calls.
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
    frame_rects = _group_frames(sem, pos, box_w, box_h, orientation)
    entries = []
    for index, group in enumerate(sem.groups):
        members = [nid for nid in group.nodes if membership.get(nid) == group.id]
        if not members:
            continue
        rects = frame_rects.get(group.id) or []
        if not rects:
            continue
        fill, line = rs.group_colors(index)
        # Topmost rectangle (then leftmost) is where the title is anchored, so
        # it always sits inside its own frame's strip.
        top_rect = min(rects, key=lambda rect: (rect[1], rect[0]))
        ty = None
        if group.label and title_gap is not None:
            # Anchor the title's *bottom* in the reserved strip so the text
            # grows upward, clear of the row's node boxes.
            ty = min(row_top[round(pos[nid][1], 6)] for nid in members) \
                - title_gap
        entries.append((group, fill, line, rects, top_rect[0], top_rect[1], ty))

    anchors: list[tuple[float, float] | None] = [None] * len(entries)
    titled = [i for i, e in enumerate(entries) if e[6] is not None]
    if titled:
        axes_w_in = ax.get_figure().get_size_inches()[0] * _AXES_FRACTION
        axes_h_in = ax.get_figure().get_size_inches()[1] * _AXES_FRACTION
        title_prop = _title_font_properties(GROUP_FONTSIZE)
        candidates = []
        for i in titled:
            group, _fill, _line, _rects, x0, _y0, ty = entries[i]
            text_w, text_h = _text_size_in(group.label, GROUP_FONTSIZE,
                                           title_prop)
            candidates.append({"tx": x0 + 0.008, "ty": ty,
                               "w": text_w / axes_w_in,
                               "h": text_h / axes_h_in})
        node_boxes = [
            (pos[n.id][0] - box_w[n.id] / 2, pos[n.id][1] - box_h[n.id] / 2,
             pos[n.id][0] + box_w[n.id] / 2, pos[n.id][1] + box_h[n.id] / 2)
            for n in sem.nodes
        ]
        resolved = _place_group_titles(candidates, node_boxes,
                                       (axes_w_in, axes_h_in), title_gap)
        for i, anchor in zip(titled, resolved):
            anchors[i] = anchor

    drawn: list[str] = []
    for entry, anchor in zip(entries, anchors):
        group, fill, line, rects, x0, y0, ty = entry
        for rx, ry, rw, rh in rects:
            ax.add_patch(Rectangle((rx, ry), rw, rh, facecolor=fill,
                                   edgecolor=line, linewidth=1.3, alpha=0.45,
                                   zorder=0))
        if group.label:
            if title_gap is None:
                tx, ty, va = x0 + 0.008, y0 + 0.014, "top"
            else:
                tx, ty = anchor
                va = "bottom"
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
        geometry = _grouped_geometry(sem, pos, wrapped, notes, text_labels)
        fig_w, fig_h = geometry["figsize"]
        box_w, box_h = geometry["box_w"], geometry["box_h"]
        label_dy, note_dy = geometry["label_dy"], geometry["note_dy"]
        title_gap = geometry["title_gap"]
        # X6: the compact fit may have re-wrapped labels/notes to honour the
        # reading-width budget; draw the text that was actually measured.
        wrapped, notes = geometry["wrapped"], geometry["notes"]
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
