"""D3: hierarchy rendering (groups / notes / dashed edges) contract tests.

Offline and deterministic.  The D-track renderers are developed against the
**SPEC §1 JSON shape** (plain dicts), so these tests never need D1's or D2's
unmerged code - they feed dicts straight into the renderers and assert on the
DOT source / matplotlib artists / rendered bytes.

Coverage:
  * render_semantics normalization: determinism, dict+object parity, defensive
    handling of dangling members, style/kind fallbacks, group ordering;
  * graphviz: cluster_* subgraphs, layer rank=same, group label, small note
    font (HTML-like label), dashed edges, font-size rule;
  * matplotlib: group background boxes + titles, note text, dashed arrows,
    font-size rule, no-groups golden regression;
  * byte-level regression lock for the ungrouped fallback PNG.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile

import pytest

from graph2note.diagrams import render_semantics as rs

# ---------------------------------------------------------------------------
# fixtures (SPEC §1 JSON shape, no IR import)
# ---------------------------------------------------------------------------

# 01-requirements-arch-ish: three layers + a note + a weak (dashed) link.
NODES = [
    {"id": "n1", "label": "macmini", "note": "坑：Tiger VNC 不支持"},
    {"id": "n2", "label": "macbook"},
    {"id": "n3", "label": "windows laptop", "note": "客户端"},
    {"id": "n4", "label": "360 Linux"},
]
EDGES = [
    {"from": "n1", "to": "n2", "label": ""},
    {"from": "n3", "to": "n1", "label": "Ragget TS", "style": "dashed"},
]
GROUPS = [
    {"id": "g1", "label": "通信层", "kind": "layer", "nodes": ["n1", "n3"]},
    {"id": "g2", "label": "层间通信", "kind": "layer", "nodes": ["n2"]},
    {"id": "g3", "label": "执行层", "kind": "cluster", "nodes": ["n4"]},
]

SIMPLE_NODES = [
    {"id": "n1", "label": "开始"},
    {"id": "n2", "label": "处理数据"},
    {"id": "n3", "label": "结束"},
]
SIMPLE_EDGES = [
    {"from": "n1", "to": "n2", "label": ""},
    {"from": "n2", "to": "n3", "label": "完成"},
]

# sha256 of the ungrouped matplotlib fallback for SIMPLE_NODES/EDGES at the
# D-track baseline (pre-D3 code).  Locked to the matplotlib version because the
# PNG embeds it in metadata; a different environment skips with a reason.
MPL_GOLDEN_SHA = "e5f561dd3056cedf61d4fd0626141c01c7f26662d1a97021e799401952fb3ced"
MPL_GOLDEN_VERSION = "3.11.1"


def _sha(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# render_semantics
# ---------------------------------------------------------------------------


def test_normalize_is_order_independent_and_deterministic():
    shuffled_nodes = [NODES[2], NODES[0], NODES[3], NODES[1]]
    shuffled_edges = [EDGES[1], EDGES[0]]
    shuffled_groups = [GROUPS[2], GROUPS[0], GROUPS[1]]
    a = rs.normalize(shuffled_nodes, shuffled_edges, shuffled_groups)
    b = rs.normalize(NODES, EDGES, GROUPS)
    assert a == b
    assert [n.id for n in a.nodes] == ["n1", "n2", "n3", "n4"]
    # groups ordered by node reading order (layer before cluster), not input
    assert [g.id for g in a.groups] == ["g1", "g2", "g3"]


def test_normalize_parity_between_dict_and_object_shapes():
    class Obj:
        def __init__(self, **kw):
            self.__dict__.update(kw)

    nodes = [Obj(id="n1", label="A", note="N"), Obj(id="n2", label="B")]
    edges = [Obj(from_="n1", to="n2", label="", style="dashed")]
    groups = [Obj(id="g1", label="G", kind="layer", nodes=["n1"])]
    sem = rs.normalize(nodes, edges, groups)
    assert sem.nodes == rs.normalize(
        [{"id": "n1", "label": "A", "note": "N"}, {"id": "n2", "label": "B"}],
        [], [],
    ).nodes
    assert sem.edges[0].dashed is True
    assert sem.groups[0].kind == "layer"


def test_normalize_drops_dangling_members_and_bad_kinds_styles():
    sem = rs.normalize(
        [{"id": "n1", "label": "A"}],
        [{"from": "n1", "to": "ghost", "style": "wavy"},
         {"from": "n1", "to": "n1", "style": "dashed"}],
        [{"id": "g1", "label": "G", "kind": "swimlane-ish", "nodes": ["ghost", "n1"]},
         {"id": "g2", "label": "empty", "nodes": ["ghost"]}],
    )
    # edge to an unknown node is dropped (same rule as canonical layout)
    assert [(e.from_, e.to, e.style) for e in sem.edges] == [("n1", "n1", "dashed")]
    # unknown kind -> cluster, dangling members dropped, empty group dropped
    assert [(g.id, g.kind, g.nodes) for g in sem.groups] == [
        ("g1", "cluster", ("n1",)),
    ]


def test_group_membership_first_wins_deterministically():
    sem = rs.normalize(
        [{"id": "n1"}],
        [],
        [{"id": "gb", "label": "b", "nodes": ["n1"]},
         {"id": "ga", "label": "a", "nodes": ["n1"]}],
    )
    # both groups have the same (kind, member) key -> label is the tie-break
    assert sem.membership == {"n1": "ga"}


def test_from_block_accepts_spec_json_dict():
    sem = rs.from_block({
        "type": "diagram", "caption": "c",
        "nodes": NODES, "edges": EDGES, "groups": GROUPS,
    })
    assert len(sem.nodes) == 4 and len(sem.groups) == 3
    assert sem.has_notes and sem.has_dashed


def test_font_size_three_tiers_group_above_label_above_note():
    """SPEC §1: group title > node label > note, strictly decreasing."""
    gv = pytest.importorskip("graph2note.diagrams.graphviz_renderer")
    mpl = pytest.importorskip("graph2note.diagrams.matplotlib_renderer")
    for mod in (gv, mpl):
        assert mod.GROUP_FONTSIZE > mod.NODE_FONTSIZE > mod.NOTE_FONTSIZE > 0
    # reference ladders (values may be tuned; the strict order is the contract)
    assert (gv.GROUP_FONTSIZE, gv.NODE_FONTSIZE, gv.NOTE_FONTSIZE) == (24, 20, 14)
    assert (mpl.GROUP_FONTSIZE, mpl.NODE_FONTSIZE, mpl.NOTE_FONTSIZE) == (15, 13, 10)


def test_label_wrapping_keeps_ascii_words_whole():
    # Readability strategy: narrow ranks -> bigger post-fit text.  CJK may
    # break per character, but an ASCII word must never be cut mid-word unless
    # it is longer than the whole line budget.
    assert rs.wrap_display_label("亮点：Critical Path 优化 ☆", 12) == \
        "亮点：\nCritical\nPath 优化 ☆"
    assert rs.wrap_display_label("坑：Tiger VNC 不支持", 12) == \
        "坑：Tiger\nVNC 不支持"
    assert rs.wrap_display_label("windows laptop", 12) == "windows\nlaptop"
    # an over-long single token is hard-split as a last resort
    assert rs.wrap_display_label("averyveryverylongword", 12) == \
        "averyveryver\nylongword"
    # explicit newlines are preserved; trailing spaces are trimmed
    assert rs.wrap_display_label("多行\n标签", 12) == "多行\n标签"


# ---------------------------------------------------------------------------
# graphviz
# ---------------------------------------------------------------------------


def _gv():
    mod = pytest.importorskip("graph2note.diagrams.graphviz_renderer")
    if not mod.available():
        pytest.skip("graphviz python pkg or dot binary unavailable")
    return mod


def test_graphviz_groups_become_clusters_with_labels_and_layer_rank():
    gv = _gv()
    src = gv.build_digraph(NODES, EDGES, groups=GROUPS).source
    assert src.count("subgraph cluster_") == 3
    for label in ("通信层", "层间通信", "执行层"):
        assert f'label="{label}"' in src
    # layer groups pin rank=same (a layer is one horizontal band) ...
    assert src.count("rank=same") == 2
    # ... and a cluster group does not
    assert "cluster_g3" in src


def test_graphviz_note_renders_smaller_second_line():
    gv = _gv()
    src = gv.build_digraph(NODES, EDGES, groups=GROUPS).source
    assert f'POINT-SIZE="{gv.NOTE_FONTSIZE}"' in src
    assert "坑：Tiger" in src
    assert "客户端" in src
    # note font must be strictly smaller than the node font
    assert int(gv.NOTE_FONTSIZE) < int(gv.NODE_FONTSIZE)


def test_graphviz_dashed_edge_only_for_dashed_style():
    gv = _gv()
    src = gv.build_digraph(NODES, EDGES, groups=GROUPS).source
    assert "style=dashed" in src
    # the solid edge line carries no style attribute
    solid = [line for line in src.splitlines() if "n1 -> n2" in line][0]
    assert "style=" not in solid
    plain = gv.build_digraph(SIMPLE_NODES, SIMPLE_EDGES).source
    assert "dashed" not in plain


def test_graphviz_ungrouped_source_matches_legacy_renderer():
    """The D-track additions must not change flat output (regression lock)."""
    gv = _gv()
    import graphviz

    g = graphviz.Digraph(format="png", engine="dot")
    g.attr(rankdir="TB", dpi="120", nodesep="0.4", ranksep="0.5")
    g.attr(label="", labelloc="t")
    for n in SIMPLE_NODES:
        g.node(n["id"], label=n["label"] or "", shape="box",
               fontname=gv.FONTNAME, fontsize="20", style="rounded")
    for e in SIMPLE_EDGES:
        g.edge(e["from"], e["to"], label=e["label"] or "",
               fontname=gv.FONTNAME, fontsize="14")
    src = gv.build_digraph(SIMPLE_NODES, SIMPLE_EDGES).source
    assert src == g.source
    # flat path never picks up the grouped-path additions (byte-level lock)
    assert "newrank" not in src
    assert "POINT-SIZE" not in src
    assert "rank=same" not in src


def test_graphviz_groups_render_deterministic_png(tmp_path):
    gv = _gv()
    p1 = gv.render(NODES, EDGES, str(tmp_path / "a.png"), groups=GROUPS)
    p2 = gv.render(NODES, EDGES, str(tmp_path / "b.png"), groups=GROUPS)
    assert os.path.getsize(p1) > 0
    assert _sha(p1) == _sha(p2)


# ---------------------------------------------------------------------------
# graphviz: dot's *actual* ranks must equal D2's rows
# (T-audit F-A/F-B/F-C/F-D: cluster members split, lane zig-zag collapsed,
#  disconnected layer band merged, annotation clusters drifting)
# ---------------------------------------------------------------------------

_GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "golden")
_LAYOUT_FIXTURES = ("layer", "lane", "cluster", "increment")


def _layout_fixture(name):
    with open(os.path.join(_GOLDEN_DIR, f"diagram-layout-{name}.json"),
              encoding="utf-8") as fh:
        return json.load(fh)["fixture"]


def _d1_anchor_payloads():
    """The three SPEC §1 anchors, read from D1's own test module (no copy)."""
    from graph2note import diagram
    from tests.test_diagram_groups_ir import (
        _ANCHOR_01, _ANCHOR_02, _ANCHOR_02_INCREMENT,
    )

    payloads = []
    for anchor in (_ANCHOR_01, _ANCHOR_02, _ANCHOR_02_INCREMENT):
        payload, verdict = diagram.validate_diagram_json(anchor)
        assert verdict == "ok"
        payloads.append(payload)
    return payloads


def _dot_ranks(source: str, orientation: str) -> dict[str, int]:
    """Parse ``dot -Tplain`` into ``{node_id: rank_index}``.

    ``rank_index 0`` is the first rank in the reading direction (top for TB,
    left for LR), so it lines up with ``layout["rows"][0]``.
    """
    with tempfile.TemporaryDirectory() as directory:
        dot_path = os.path.join(directory, "graph.dot")
        with open(dot_path, "w", encoding="utf-8") as fh:
            fh.write(source)
        proc = subprocess.run(["dot", "-Tplain", dot_path],
                              capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    coord: dict[str, float] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == "node":
            name = parts[1].strip('"')
            coord[name] = (float(parts[2]) if orientation in ("LR", "RL")
                           else float(parts[3]))
    order = sorted(set(coord.values()), reverse=orientation in ("TB", "RL"))
    index = {value: i for i, value in enumerate(order)}
    return {name: index[value] for name, value in coord.items()}


def _assert_dot_ranks_equal_rows(node_ids, edge_pairs, groups):
    """dot's ranks (pinned to the D2 layout) must equal D2's rows exactly."""
    gv = _gv()
    from graph2note.diagrams._layout import grouped_layout

    layout = grouped_layout(node_ids, edge_pairs, groups)
    row_of = {n: i for i, row in enumerate(layout["rows"]) for n in row}
    nodes = [{"id": n, "label": n} for n in node_ids]
    edges = [{"from": s, "to": t} for s, t in edge_pairs]
    # orientation is pinned to TB (the product-chain default) so the fixture's
    # missing ``orientation`` cannot flip the reading axis across engines.
    source = gv.build_digraph(nodes, edges, groups=groups, layout=layout,
                              orientation="TB").source
    ranks = _dot_ranks(source, "TB")
    assert {n: ranks.get(n) for n in row_of} == row_of
    # every D2 row is exactly one dot rank (no collapsed/phantom rows)
    assert len(set(ranks.values())) == layout["nrows"]
    return layout


@pytest.mark.parametrize("name", _LAYOUT_FIXTURES)
def test_dot_ranks_match_d2_rows_for_layout_fixtures(name):
    fx = _layout_fixture(name)
    _assert_dot_ranks_equal_rows(fx["nodes"], [tuple(e) for e in fx["edges"]],
                                 fx["groups"])


def test_dot_ranks_match_d2_rows_for_d1_anchors():
    for payload in _d1_anchor_payloads():
        _assert_dot_ranks_equal_rows(
            [n["id"] for n in payload["nodes"]],
            [(e["from"], e["to"]) for e in payload["edges"]],
            payload["groups"],
        )


def test_newrank_is_only_on_the_grouped_path():
    """The flat path must stay byte-identical: no newrank, no rank spine."""
    gv = _gv()
    flat = gv.build_digraph(SIMPLE_NODES, SIMPLE_EDGES).source
    assert "newrank" not in flat
    grouped = gv.build_digraph(NODES, EDGES, groups=GROUPS).source
    assert "newrank=true" in grouped


# ---------------------------------------------------------------------------
# matplotlib fallback
# ---------------------------------------------------------------------------


def _mpl():
    mod = pytest.importorskip("graph2note.diagrams.matplotlib_renderer")
    if not mod.available():
        pytest.skip("matplotlib unavailable")
    return mod


def test_matplotlib_groups_draw_background_boxes_and_titles():
    mpl = _mpl()
    from matplotlib.patches import Rectangle

    _fig, ax, drawn = mpl.build_figure(NODES, EDGES, None, groups=GROUPS)
    assert drawn == ["g1", "g2", "g3"]
    backgrounds = [p for p in ax.patches
                   if isinstance(p, Rectangle) and p.get_zorder() == 0]
    # X3: frames are a partition of each group's grid domain, so a domain that
    # another group's member cuts through draws as several rectangles.  Every
    # group still contributes at least one frame, and the three group fills are
    # all present.
    assert len(backgrounds) >= 3
    assert len({p.get_facecolor() for p in backgrounds}) == 3
    texts = [t.get_text() for t in ax.texts]
    for label in ("通信层", "层间通信", "执行层"):
        assert label in texts
    # group titles are drawn at the group font size
    title = [t for t in ax.texts if t.get_text() == "通信层"][0]
    assert title.get_fontsize() == mpl.GROUP_FONTSIZE


def test_matplotlib_note_drawn_smaller_than_label():
    mpl = _mpl()
    _fig, ax, _drawn = mpl.build_figure(NODES, EDGES, None, groups=GROUPS)
    note = [t for t in ax.texts if "坑" in t.get_text()][0]
    label = [t for t in ax.texts if "macmini" in t.get_text()][0]
    assert note.get_fontsize() == mpl.NOTE_FONTSIZE
    assert note.get_fontsize() < label.get_fontsize()


def test_matplotlib_dashed_edge_uses_dashed_style():
    mpl = _mpl()
    from matplotlib.patches import FancyArrowPatch

    _fig, ax, _drawn = mpl.build_figure(NODES, EDGES, None, groups=GROUPS)
    arrow = [p for p in ax.patches if isinstance(p, FancyArrowPatch)]
    styles = [str(p.get_linestyle()) for p in arrow]
    assert "dashed" in styles, styles
    _fig2, ax2, _ = mpl.build_figure(SIMPLE_NODES, SIMPLE_EDGES, None)
    assert all("dashed" not in str(p.get_linestyle())
               for p in ax2.patches if isinstance(p, FancyArrowPatch))


def test_matplotlib_ungrouped_png_matches_baseline_golden(tmp_path):
    """No groups/notes -> the fallback PNG is byte-identical to the baseline."""
    import matplotlib

    mpl = _mpl()
    if matplotlib.__version__ != MPL_GOLDEN_VERSION:
        pytest.skip(
            "matplotlib %s != golden %s (PNG embeds the version); determinism "
            "is still covered by the sibling test"
            % (matplotlib.__version__, MPL_GOLDEN_VERSION)
        )
    out = tmp_path / "plain.png"
    mpl.render(SIMPLE_NODES, SIMPLE_EDGES, None, str(out))
    assert _sha(out) == MPL_GOLDEN_SHA


def test_matplotlib_groups_path_is_deterministic(tmp_path):
    mpl = _mpl()
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    mpl.render(NODES, EDGES, None, str(a), groups=GROUPS)
    mpl.render(NODES, EDGES, None, str(b), groups=GROUPS)
    assert _sha(a) == _sha(b)
    assert os.path.getsize(a) > 0


def test_matplotlib_groups_change_the_image():
    """Grouping must be visible: the grouped render differs from the flat one."""
    mpl = _mpl()
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        flat = os.path.join(d, "flat.png")
        grouped = os.path.join(d, "grouped.png")
        mpl.render(NODES, EDGES, None, flat)
        mpl.render(NODES, EDGES, None, grouped, groups=GROUPS)
        assert _sha(flat) != _sha(grouped)


# ---------------------------------------------------------------------------
# D5b: dense grouped diagrams must not overlap (T-vision live §2/§4/§7-5)
#
# The fixed 12x8in canvas collapsed at >=21 nodes: node text escaped its box
# and group titles landed on node labels.  The geometry now grows with the
# content; these tests measure the drawn artists (window extents) instead of
# trusting the box-size formulas.
# ---------------------------------------------------------------------------

def _dense_fixture(rows: int = 3, cols: int = 8):
    nodes = []
    for r in range(rows):
        for c in range(cols):
            node = {"id": f"n{r}{c}", "label": f"Stage {r}{c} process here"}
            if c % 4 == 0:
                node["note"] = f"marginal note {r}{c}"
            nodes.append(node)
    edges = [
        {"from": f"n{r}{c}", "to": f"n{r + 1}{c}"}
        for r in range(rows - 1) for c in range(cols)
    ]
    # long diagonals whose midpoint label would land on an unrelated node
    edges.append({"from": "n00", "to": f"n{rows - 1}{cols - 1}",
                  "label": "cross step"})
    edges.append({"from": f"n0{cols - 1}", "to": f"n{rows - 1}0",
                  "label": "back ref"})
    groups = [
        {"id": f"L{r}", "label": f"Layer {r}", "kind": "layer",
         "nodes": [f"n{r}{c}" for c in range(cols)]}
        for r in range(rows)
    ]
    return nodes, edges, groups


def _render_grouped_via_engine(nodes, edges, groups):
    """Reproduce the product chain: canonicalise -> layout -> matplotlib."""
    from graph2note.diagrams import _canonical, engine
    from graph2note.ir import Edge, Node

    mpl_mod = _mpl()
    nc = _canonical.canonical_nodes(
        [Node(id=n["id"], label=n.get("label", ""), note=n.get("note"))
         for n in nodes])
    ec = _canonical.canonical_edges(
        [Edge(**{"from": e.get("from"), "to": e.get("to"),
                 "label": e.get("label", ""),
                 "style": e.get("style", "solid")}) for e in edges],
        {n.id for n in nc})
    layout = engine.prepare_diagram_layout(nc, ec, groups)
    # engine.render_structured forwards only ``layout`` to the renderer
    fig, ax, drawn = mpl_mod.build_figure(
        nc, ec, {n.id: n.label for n in nc}, layout=layout)
    return fig, ax, drawn


def _overlap(a, b) -> float:
    x0, y0 = max(a.x0, b.x0), max(a.y0, b.y0)
    x1, y1 = min(a.x1, b.x1), min(a.y1, b.y1)
    return (x1 - x0) * (y1 - y0) if (x1 > x0 and y1 > y0) else 0.0


def _contains(outer, inner, tol=1.0) -> bool:
    return (inner.x0 >= outer.x0 - tol and inner.x1 <= outer.x1 + tol
            and inner.y0 >= outer.y0 - tol and inner.y1 <= outer.y1 + tol)


def _assert_no_overlap(ax):
    from matplotlib.patches import Rectangle

    mpl = _mpl()
    fig = ax.figure
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    boxes = [p.get_window_extent(rend) for p in ax.patches
             if isinstance(p, Rectangle) and p.get_zorder() == 3]
    assert boxes, "no node boxes drawn"
    # 1) node boxes never intersect one another
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert _overlap(a, b) <= 1.0, (a, b)
    # 2) every node label / note stays inside exactly its own box ...
    for text in ax.texts:
        size = text.get_fontsize()
        if size not in (mpl.NODE_FONTSIZE, mpl.NOTE_FONTSIZE):
            continue
        tb = text.get_window_extent(rend)
        inside = [b for b in boxes
                  if _overlap(tb, b) >= 0.9 * (tb.width * tb.height)]
        assert len(inside) == 1, (text.get_text(), len(inside))
        assert _contains(inside[0], tb, tol=2.0), text.get_text()
    # 3) edge labels also stay clear of node boxes on the grouped path
    for text in ax.texts:
        if text.get_fontsize() != mpl.EDGE_FONTSIZE:
            continue
        tb = text.get_window_extent(rend)
        for box in boxes:
            assert _overlap(tb, box) <= 1.0, (text.get_text(), box)
    # 4) group titles never land on a node box
    for text in ax.texts:
        if text.get_fontsize() != mpl.GROUP_FONTSIZE:
            continue
        tb = text.get_window_extent(rend)
        for box in boxes:
            assert _overlap(tb, box) <= 1.0, (text.get_text(), box)

    # 5) group titles never stack on one another (D6: same-row-band /
    #    same-left-edge groups used to anchor both titles on the same point)
    _titles = [(t.get_text(), t.get_window_extent(rend)) for t in ax.texts
               if round(t.get_fontsize(), 3) == round(mpl.GROUP_FONTSIZE, 3)]
    for i, (label_a, box_a) in enumerate(_titles):
        for label_b, box_b in _titles[i + 1:]:
            assert _overlap(box_a, box_b) <= 1.0, (label_a, label_b, box_a, box_b)


def test_dense_grouped_diagram_has_no_artist_overlap():
    nodes, edges, groups = _dense_fixture()
    _fig, ax, drawn = _render_grouped_via_engine(nodes, edges, groups)
    assert drawn == ["L0", "L1", "L2"]
    _assert_no_overlap(ax)


def test_dense_grouped_diagram_grows_the_canvas_with_the_grid():
    """The whole point: no font shrink, the canvas does the work."""
    nodes, edges, groups = _dense_fixture()
    _fig, ax, _drawn = _render_grouped_via_engine(nodes, edges, groups)
    assert tuple(ax.figure.get_size_inches())[0] > 12.0


# ---------------------------------------------------------------------------
# D6: group titles must not stack on each other
#
# T-vision final report §3: a lane band and a cluster sharing a row band *and*
# a left edge anchored their titles on the same point (live 01 = 2 pairs,
# 02inc = 1 pair).  The title layer now de-conflicts across groups; this fixture
# is that shape in miniature and is red without the fix.
# ---------------------------------------------------------------------------


def _same_left_edge_two_group_layout():
    """Hand-built D2 layout: lane + cluster, same row band, same left edge.

    Both groups have a member on row ``y=0.25`` (membership is disjoint, as in
    the live 01 render) and both bboxes start at ``x0=0``, so the historical
    title anchors coincide.
    """
    return {
        "positions": {
            "n1": {"x": 0.6, "y": 0.25},
            "n2": {"x": 0.85, "y": 0.25},
            "n3": {"x": 0.25, "y": 0.25},
            "n4": {"x": 0.25, "y": 0.75},
        },
        "groups": [
            {"id": "g1", "label": "用户侧", "kind": "lane",
             "members": ["n1", "n2"],
             "bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}},
            {"id": "g2", "label": "调度方案选型", "kind": "cluster",
             "members": ["n3", "n4"],
             "bbox": {"x0": 0.0, "y0": 0.0, "x1": 0.5, "y1": 1.0}},
        ],
    }


_SAME_LEFT_EDGE_NODES = [
    {"id": "n1", "label": "alpha"},
    {"id": "n2", "label": "beta"},
    {"id": "n3", "label": "gamma"},
    {"id": "n4", "label": "delta"},
]


def _group_title_geometry(ax):
    """(rendered title boxes, rendered node boxes) as window extents."""
    mpl = _mpl()
    from matplotlib.patches import Rectangle

    fig = ax.figure
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    titles = [(t.get_text(), t.get_window_extent(rend)) for t in ax.texts
              if round(t.get_fontsize(), 3) == round(mpl.GROUP_FONTSIZE, 3)]
    nodes = [p.get_window_extent(rend) for p in ax.patches
             if isinstance(p, Rectangle) and p.get_zorder() == 3]
    return titles, nodes


def test_same_left_edge_group_titles_are_kept_apart():
    """Two same-row-band, same-left-edge titles must not overlap."""
    mpl = _mpl()
    _fig, ax, drawn = mpl.build_figure(
        _SAME_LEFT_EDGE_NODES, [], None, layout=_same_left_edge_two_group_layout())
    assert drawn == ["g1", "g2"]
    titles, nodes = _group_title_geometry(ax)
    assert sorted(label for label, _box in titles) == ["用户侧", "调度方案选型"]
    for i, (label_a, box_a) in enumerate(titles):
        for label_b, box_b in titles[i + 1:]:
            assert _overlap(box_a, box_b) <= 1.0, (label_a, label_b)
    # the moved title must still clear every node box and stay on the canvas
    for label, box in titles:
        assert 0.0 <= box.x0 and box.x1 <= ax.figure.bbox.x1 + 1.0, label
        for node_box in nodes:
            assert _overlap(box, node_box) <= 1.0, label


def test_same_left_edge_group_titles_are_deterministic():
    mpl = _mpl()
    layout = _same_left_edge_two_group_layout()

    def anchors():
        _fig, ax, _drawn = mpl.build_figure(
            _SAME_LEFT_EDGE_NODES, [], None, layout=layout)
        return [t.get_position() for t in ax.texts
                if round(t.get_fontsize(), 3) == round(mpl.GROUP_FONTSIZE, 3)]

    assert anchors() == anchors()
    assert anchors()[1][0] != anchors()[0][0]  # the second title slid aside


def test_group_title_does_not_degrade_weight_silently(caplog):
    """T-vision live §4: a real bold face (or a warning-free fallback), never
    matplotlib's silent 'Failed to find font weight bold, now using 400'."""
    with caplog.at_level("WARNING", logger="matplotlib.font_manager"):
        nodes, edges, groups = _dense_fixture(rows=1, cols=3)
        fig, _ax, _drawn = _render_grouped_via_engine(nodes, edges, groups)
        fig.canvas.draw()
    assert "Failed to find font weight" not in caplog.text


def test_group_title_style_never_requests_a_missing_weight():
    mpl = _mpl()
    kwargs, effects = mpl._group_title_style("#123456")
    if mpl._CJK_BOLD_FAMILY is None:
        # no heavy CJK face installed -> synthetic bold, never weight 700
        assert kwargs.get("fontweight") != "bold"
        assert effects
    else:
        assert kwargs["fontfamily"] == [mpl._CJK_BOLD_FAMILY]
        assert kwargs["fontweight"] == mpl._CJK_BOLD_WEIGHT >= 600
        assert effects is None


# ---------------------------------------------------------------------------
# X3: group frames must not intersect (live 01 = 9 pairs, 02inc = 2 pairs)
#
# A lane band and clusters can share a row strip, and clusters can interleave
# across rows, so the member-envelope frames overlapped.  Frames are now the
# partition of each group's grid domain: borders may touch, never intersect,
# and every member still sits inside its own group's frame.
# ---------------------------------------------------------------------------

_X3_NODES = [{"id": f"n{i}", "label": f"节点{i}"} for i in range(1, 9)]


def _x3_overlapping_layout():
    """Hand-built D2 layout whose group bboxes overlap (live 01/02inc shape).

    The full-width ``lane`` band shares row 0 with both clusters, ``ca``
    interleaves ``lane``/``cb`` across rows, and ``cb``'s bbox contains
    ``ca``'s members.  Before X3 these member-envelope boxes intersected in
    several pairs; the fixture is red without the partition.
    """
    return {
        "positions": {
            "n1": {"x": 0.85, "y": 0.15},
            "n2": {"x": 0.15, "y": 0.15},
            "n3": {"x": 0.50, "y": 0.15},
            "n4": {"x": 0.50, "y": 0.50},
            "n5": {"x": 0.15, "y": 0.50},
            "n6": {"x": 0.85, "y": 0.50},
            "n7": {"x": 0.15, "y": 0.85},
            "n8": {"x": 0.85, "y": 0.85},
        },
        "groups": [
            {"id": "lane", "label": "用户侧", "kind": "lane",
             "members": ["n1", "n2"],
             "bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.34}},
            {"id": "ca", "label": "簇 A", "kind": "cluster",
             "members": ["n3", "n4"],
             "bbox": {"x0": 0.0, "y0": 0.0, "x1": 0.7, "y1": 0.7}},
            {"id": "cb", "label": "簇 B", "kind": "cluster",
             "members": ["n5", "n6", "n7", "n8"],
             "bbox": {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}},
        ],
    }


def _frame_boxes(ax):
    """Rendered group-frame rectangles (``zorder == 0``) as window extents."""
    from matplotlib.patches import Rectangle
    fig = ax.figure
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    return [p.get_window_extent(rend) for p in ax.patches
            if isinstance(p, Rectangle) and p.get_zorder() == 0]


def test_group_frames_do_not_intersect_on_overlapping_layout():
    mpl = _mpl()
    layout = _x3_overlapping_layout()
    _fig, ax, drawn = mpl.build_figure(_X3_NODES, [], None, layout=layout)
    assert drawn == ["lane", "ca", "cb"]
    frames = _frame_boxes(ax)
    assert len(frames) >= 3
    for i, a in enumerate(frames):
        for b in frames[i + 1:]:
            assert _overlap(a, b) <= 1.0, (a, b)
    # the old member-envelope frames really did overlap: the fix is not vacuous
    envelopes = [
        (g["bbox"]["x0"], g["bbox"]["y0"], g["bbox"]["x1"], g["bbox"]["y1"])
        for g in layout["groups"]
    ]
    assert any(
        envelopes[i][0] < envelopes[j][2] and envelopes[i][2] > envelopes[j][0]
        and envelopes[i][1] < envelopes[j][3] and envelopes[i][3] > envelopes[j][1]
        for i in range(len(envelopes)) for j in range(i + 1, len(envelopes))
    )


def test_group_frame_rects_partition_the_grid_and_cover_members():
    """Pure-geometry check: frames are pairwise disjoint and contain members."""
    mpl = _mpl()
    layout = _x3_overlapping_layout()
    sem = rs.normalize(_X3_NODES, [], None, layout=layout)
    pos = rs.positions_from_layout(layout)
    rects, _cell_of = mpl._group_frame_cells(sem, pos, {}, {}, "TB")
    flat = [rect for group_rects in rects.values() for rect in group_rects]
    assert len(flat) >= 3
    for i, (x0, y0, w, h) in enumerate(flat):
        for (x1, y1, w1, h1) in flat[i + 1:]:
            ox = min(x0 + w, x1 + w1) - max(x0, x1)
            oy = min(y0 + h, y1 + h1) - max(y0, y1)
            assert ox * oy <= 1e-12, ((x0, y0, w, h), (x1, y1, w1, h1))
    membership = sem.membership
    for node in sem.nodes:
        owner = membership[node.id]
        x, y = pos[node.id]
        assert any(x0 - 1e-9 <= x <= x0 + w + 1e-9
                   and y0 - 1e-9 <= y <= y0 + h + 1e-9
                   for x0, y0, w, h in rects[owner]), (node.id, owner)


def test_lane_frames_stay_columns_on_golden_fixture():
    """X3 must not clear overlaps by deleting/hiding frames: on the lane golden
    each swim-lane still renders as one continuous, column-disjoint frame."""
    mpl = _mpl()
    from matplotlib.patches import Rectangle
    with open(os.path.join(_GOLDEN_DIR, "diagram-layout-lane.json"),
              encoding="utf-8") as fh:
        doc = json.load(fh)
    layout = doc["expected"]
    nodes = [{"id": n, "label": n} for n in doc["fixture"]["nodes"]]
    _fig, ax, drawn = mpl.build_figure(nodes, [], None, layout=layout)
    assert drawn == ["lane-back", "lane-front"]
    frames = [p for p in ax.patches
              if isinstance(p, Rectangle) and p.get_zorder() == 0]
    assert len(frames) == 2  # one rectangle per lane: a real swim-lane column
    left, right = sorted(frames, key=lambda p: p.get_x())
    assert left.get_x() + left.get_width() <= right.get_x() + 1e-6
    # each lane frame spans exactly its layout bbox (verbatim when disjoint)
    lanes = {g["id"]: g for g in layout["groups"]}
    for patch, gid in ((left, "lane-back"), (right, "lane-front")):
        bbox = lanes[gid]["bbox"]
        assert abs(patch.get_x() - bbox["x0"]) < 1e-6
        assert abs(patch.get_width() - (bbox["x1"] - bbox["x0"])) < 1e-6
        assert abs(patch.get_y() - bbox["y0"]) < 1e-6


def test_grouped_frame_geometry_is_hash_seed_independent():
    """X3 determinism: PYTHONHASHSEED variants render identical frames."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = (
        "from graph2note.diagrams import matplotlib_renderer as mpl\n"
        "from matplotlib.patches import Rectangle\n"
        "NODES = %r\n"
        "LAYOUT = %r\n"
        "fig, ax, _drawn = mpl.build_figure(NODES, [], None, layout=LAYOUT)\n"
        "fig.canvas.draw()\n"
        "rend = fig.canvas.get_renderer()\n"
        "data = sorted(round(v, 6) for p in ax.patches\n"
        "              if isinstance(p, Rectangle) and p.get_zorder() == 0\n"
        "              for v in p.get_window_extent(rend).bounds)\n"
        "print(data)\n"
    ) % (_X3_NODES, _x3_overlapping_layout())
    digests = set()
    for seed in ("0", "1", "2"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True,
            env=env, cwd=root,
            check=False,
        )
        if proc.returncode != 0:
            raise AssertionError(proc.stderr)
        digests.add(proc.stdout.strip())
    assert len(digests) == 1


# ---------------------------------------------------------------------------
# X4: real font metrics (the half-em heuristic under-measured mixed text)
# ---------------------------------------------------------------------------


def test_text_size_uses_real_metrics_not_half_em():
    """The old ``1 unit = half an em`` width under-measured ASCII glyphs."""
    mpl = _mpl()
    text = "LLM 直接转？OCR？路由？"
    width, height = mpl._text_size_in(text, mpl.NODE_FONTSIZE)
    heuristic = mpl._label_len(text) / 2.0 * mpl.NODE_FONTSIZE / 72.0
    assert width > heuristic
    assert height > 0.0


def _mixed_text_fixture():
    """Mixed CJK/Latin labels, full-width punctuation and notes."""
    nodes = [
        {"id": "n1", "label": "LLM 直接转？OCR？路由？",
         "note": "跨组：Critical Path 优化 ★"},
        {"id": "n2", "label": "Windows (RDP/TS) 客户端"},
        {"id": "n3", "label": "a. HTML/CSS；b. markdown→md；c. pdf"},
        {"id": "n4", "label": "笔记/手册电子化入口"},
    ]
    edges = [{"from": "n1", "to": "n2", "label": "下一步"},
             {"from": "n1", "to": "n3"},
             {"from": "n2", "to": "n4"}]
    groups = [
        {"id": "g1", "label": "调度方案选型", "kind": "layer",
         "nodes": ["n1", "n2"]},
        {"id": "g2", "label": "输出与视图", "kind": "cluster",
         "nodes": ["n3", "n4"]},
    ]
    return nodes, edges, groups


def test_node_text_has_positive_slack_inside_its_own_box():
    """X4: no node label/note may escape its own box; slack must exceed 1px."""
    mpl = _mpl()
    from matplotlib.patches import Rectangle
    nodes, edges, groups = _mixed_text_fixture()
    _fig, ax, _drawn = _render_grouped_via_engine(nodes, edges, groups)
    fig = ax.figure
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    boxes = [p.get_window_extent(rend) for p in ax.patches
             if isinstance(p, Rectangle) and p.get_zorder() == 3]
    worst = None
    for text in ax.texts:
        if round(text.get_fontsize(), 3) not in (
                round(mpl.NODE_FONTSIZE, 3), round(mpl.NOTE_FONTSIZE, 3)):
            continue
        tb = text.get_window_extent(rend)
        cx, cy = (tb.x0 + tb.x1) / 2, (tb.y0 + tb.y1) / 2
        owner = [b for b in boxes if b.x0 <= cx <= b.x1 and b.y0 <= cy <= b.y1]
        assert len(owner) == 1, text.get_text()
        b = owner[0]
        slack = min(tb.x0 - b.x0, b.x1 - tb.x1,
                    tb.y0 - b.y0, b.y1 - tb.y1)
        worst = slack if worst is None else min(worst, slack)
    assert worst is not None and worst >= 1.0, worst
