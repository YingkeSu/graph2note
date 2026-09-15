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
    assert len(backgrounds) == 3
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
