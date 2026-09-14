"""D3 F1: group semantics must reach the *product* render path.

The original D3 delivery only proved that the renderers draw groups when they
are called directly; the reviewer showed the product chain
(``render_markdown`` -> ``FileAssetWriter`` -> ``engine`` -> renderer) dropped
them, because the renderers did not declare D2's ``layout=`` keyword, so the
engine's ``_renderer_layout_kwargs`` forwarded nothing (F1).

D1 (IR ``groups``) and D2 (``engine.prepare_diagram_layout``) are now merged on
main, so these tests drive the real product chain end to end and assert that a
grouped diagram produces a *different* PNG than the same diagram without
groups, and that the prepared geometry actually arrived at the renderer (spy on
``build_digraph`` / ``build_figure``).
"""

from __future__ import annotations

import hashlib

import pytest

from graph2note import render as render_mod
from graph2note.attachments import FileAssetWriter
from tests.test_diagram_render_groups import EDGES, GROUPS, NODES


# ---------------------------------------------------------------------------
# SPEC §1 shaped objects (D1's IR also carries note/style/groups now; these
# lightweight objects keep the test independent of the pydantic model wiring)
# ---------------------------------------------------------------------------


class _Node:
    def __init__(self, id, label="", note=None):
        self.id = id
        self.label = label
        self.note = note


class _Edge:
    def __init__(self, src, dst, label="", style="solid"):
        self.from_ = src
        self.to = dst
        self.label = label
        self.style = style


class _Block:
    def __init__(self, **kw):
        self.type = kw.pop("type", "diagram")
        self.caption = kw.pop("caption", "结构图")
        self.nodes = kw.pop("nodes", [])
        self.edges = kw.pop("edges", [])
        self.orientation = kw.pop("orientation", None)
        self.source = kw.pop("source", None)
        self.groups = kw.pop("groups", [])
        self.__dict__.update(kw)


class _Doc:
    def __init__(self, blocks):
        self.blocks = blocks


NODE_OBJS = [_Node(n["id"], n["label"], n.get("note")) for n in NODES]
EDGE_OBJS = [_Edge(e["from"], e["to"], e.get("label", ""), e.get("style", "solid"))
             for e in EDGES]


def _doc(*, with_groups: bool):
    return _Doc([_Block(nodes=NODE_OBJS, edges=EDGE_OBJS,
                        groups=GROUPS if with_groups else [])])


def _sha(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _render(tmp_path, prefer: str, *, with_groups: bool):
    tmp_path.mkdir(parents=True, exist_ok=True)
    writer = FileAssetWriter(tmp_path, doc_id="doc", prefer=prefer)
    render_mod.render_markdown(_doc(with_groups=with_groups), doc_id="doc",
                               attachment_writer=writer)
    rel, info = writer.results[0]
    return writer, info, (tmp_path / rel)


def test_engine_accepts_groups_now():
    """Guard for the merge: the shim probe was removed, the engine takes groups."""
    import inspect

    from graph2note.diagrams import engine

    assert "groups" in inspect.signature(engine.render_to_png).parameters
    assert "layout" in inspect.signature(
        __import__("graph2note.diagrams.graphviz_renderer", fromlist=["x"]).render
    ).parameters


@pytest.mark.parametrize("prefer", ["graphviz", "matplotlib"])
def test_product_chain_grouped_render_differs_from_flat(tmp_path, prefer):
    """The reviewer's F1 probe: grouped vs flat PNG must not be identical."""
    from graph2note.diagrams import engine

    if prefer == "graphviz" and not engine.graphviz_available():
        pytest.skip("graphviz/dot unavailable")

    _writer, info, grouped_png = _render(tmp_path / "grouped", prefer, with_groups=True)
    _render(tmp_path / "flat", prefer, with_groups=False)
    flat_png = tmp_path / "flat" / "assets" / "doc-diagram-0.png"

    assert info["engine"] == prefer, info
    assert _sha(grouped_png) != _sha(flat_png), (
        f"{prefer}: product chain dropped the groups (F1 regression)"
    )


def test_product_chain_forwards_layout_to_graphviz(tmp_path, monkeypatch):
    from graph2note.diagrams import engine
    from graph2note.diagrams import graphviz_renderer

    if not engine.graphviz_available():
        pytest.skip("graphviz/dot unavailable")

    captured = {}
    real_build = graphviz_renderer.build_digraph

    def spy(nodes, edges, *, groups=None, layout=None, orientation="TB"):
        graph = real_build(nodes, edges, groups=groups, layout=layout,
                           orientation=orientation)
        captured["layout"] = layout
        captured["groups"] = groups
        captured["source"] = graph.source
        return graph

    monkeypatch.setattr(graphviz_renderer, "build_digraph", spy)
    _render(tmp_path, "graphviz", with_groups=True)

    layout = captured.get("layout")
    assert layout, "engine never forwarded a prepared layout (F1)"
    assert [g["id"] for g in layout["groups"]] == ["g1", "g2", "g3"]
    assert layout["positions"], "layout carries no positions"
    # groups + notes + dashed edges all reached the drawing layer
    source = captured["source"]
    assert source.count("subgraph cluster_") == 3
    assert "style=dashed" in source
    assert f'POINT-SIZE="{graphviz_renderer.NOTE_FONTSIZE}"' in source


def test_product_chain_forwards_layout_to_matplotlib(tmp_path, monkeypatch):
    from graph2note.diagrams import matplotlib_renderer

    captured = {}
    real_build = matplotlib_renderer.build_figure

    def spy(nodes, edges, labels=None, *, groups=None, layout=None, orientation="TB"):
        fig, ax, drawn = real_build(nodes, edges, labels, groups=groups,
                                    layout=layout, orientation=orientation)
        captured["layout"] = layout
        captured["drawn"] = drawn
        return fig, ax, drawn

    monkeypatch.setattr(matplotlib_renderer, "build_figure", spy)
    _render(tmp_path, "matplotlib", with_groups=True)

    assert captured.get("layout"), "engine never forwarded a prepared layout (F1)"
    assert captured["drawn"] == ["g1", "g2", "g3"]


def test_product_chain_records_semantics_for_export(tmp_path):
    _writer, info, _png = _render(tmp_path, "matplotlib", with_groups=True)
    semantics = info["semantics"]
    assert [g["id"] for g in semantics["groups"]] == ["g1", "g2", "g3"]
    assert semantics["notes"], "node notes lost in the export chain"
    assert semantics["dashed_edges"] == [["n3", "n1"]]


def test_layout_is_the_single_source_for_group_order_and_kind():
    """When D2 geometry is present the adapter must not re-order/re-classify."""
    from graph2note.diagrams import render_semantics as rs

    layout = {
        "positions": {"n1": {"x": 0.25, "y": 0.2}, "n2": {"x": 0.75, "y": 0.2},
                      "n3": {"x": 0.5, "y": 0.8}},
        # deliberately NOT node-order, and with an unknown kind to prove it is
        # preserved verbatim instead of degrading to "cluster"
        "groups": [
            {"id": "gz", "label": "后", "kind": "weird", "members": ["n3"],
             "bbox": {"x0": 0.3, "y0": 0.6, "x1": 0.7, "y1": 0.95}},
            {"id": "ga", "label": "前", "kind": "layer", "members": ["n2", "n1"],
             "bbox": {"x0": 0.0, "y0": 0.05, "x1": 1.0, "y1": 0.4}},
        ],
    }
    sem = rs.normalize(NODES, EDGES, GROUPS, layout)
    assert sem.from_layout
    assert [g.id for g in sem.groups] == ["gz", "ga"]        # layout order kept
    assert sem.groups[0].kind == "weird"                      # kind kept verbatim
    assert sem.groups[1].nodes == ("n2", "n1")                # members kept verbatim
    assert sem.groups[0].bbox == (0.3, 0.6, 0.7, 0.95)
    assert sem.positions["n3"] == (0.5, 0.8)


def test_without_layout_group_order_still_node_reading_order():
    from graph2note.diagrams import render_semantics as rs

    sem = rs.normalize(NODES, EDGES, GROUPS)
    assert not sem.from_layout
    assert sem.groups[0].bbox is None
    assert [g.id for g in sem.groups] == ["g1", "g2", "g3"]


def _require_graphviz_source(gv, *, layout):
    if not gv.available():
        pytest.skip("graphviz/dot unavailable")
    nodes = [{"id": "n1", "label": "A"}, {"id": "n3", "label": "C"}]
    return gv.build_digraph(nodes, [], layout=layout).source


def test_graphviz_uses_layout_group_order_and_kind():
    from graph2note.diagrams import graphviz_renderer as gv

    src = _require_graphviz_source(gv, layout={
        "positions": {"n1": {"x": 0.25, "y": 0.2}, "n3": {"x": 0.5, "y": 0.8}},
        "groups": [
            {"id": "gz", "label": "后", "kind": "cluster", "members": ["n3"],
             "bbox": None},
            {"id": "ga", "label": "前", "kind": "layer", "members": ["n1"],
             "bbox": None},
        ],
    })
    assert src.index("cluster_gz") < src.index("cluster_ga")
    # only the layer group pins rank=same, and the kind came from the layout
    assert src.count("rank=same") == 1


def test_matplotlib_uses_layout_positions_and_bbox():
    mpl = pytest.importorskip("graph2note.diagrams.matplotlib_renderer")
    if not mpl.available():
        pytest.skip("matplotlib unavailable")
    from matplotlib.patches import Rectangle

    layout = {
        "positions": {"n1": {"x": 0.25, "y": 0.2}, "n2": {"x": 0.75, "y": 0.2},
                      "n3": {"x": 0.5, "y": 0.8}},
        "groups": [
            {"id": "gz", "label": "执行层", "kind": "cluster", "members": ["n3"],
             "bbox": {"x0": 0.3, "y0": 0.6, "x1": 0.7, "y1": 0.95}},
            {"id": "ga", "label": "通信层", "kind": "layer", "members": ["n1", "n2"],
             "bbox": {"x0": 0.0, "y0": 0.05, "x1": 1.0, "y1": 0.4}},
        ],
    }
    _fig, ax, drawn = mpl.build_figure(
        [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"},
         {"id": "n3", "label": "C"}], [], None, layout=layout)
    assert drawn == ["gz", "ga"]
    boxes = [p for p in ax.patches if isinstance(p, Rectangle) and p.get_zorder() == 0]
    assert len(boxes) == 2
    # background boxes use the layout bbox verbatim (not a re-derived envelope)
    assert (round(boxes[0].get_x(), 6), round(boxes[0].get_y(), 6),
            round(boxes[0].get_width(), 6), round(boxes[0].get_height(), 6)) == \
        (0.3, 0.6, 0.4, 0.35)
    assert (round(boxes[1].get_x(), 6), round(boxes[1].get_y(), 6),
            round(boxes[1].get_width(), 6), round(boxes[1].get_height(), 6)) == \
        (0.0, 0.05, 1.0, 0.35)
    # node boxes sit at the layout positions
    node_boxes = [p for p in ax.patches if isinstance(p, Rectangle) and p.get_zorder() == 3]
    centres = sorted((round(p.get_x() + p.get_width() / 2, 3),
                      round(p.get_y() + p.get_height() / 2, 3))
                     for p in node_boxes)
    assert centres == [(0.25, 0.2), (0.5, 0.8), (0.75, 0.2)]


def test_duplicate_edges_are_not_deduplicated():
    """F2: exact duplicates are kept, matching ``_canonical`` (and the baseline)."""
    from graph2note.diagrams import render_semantics as rs

    edges = [{"from": "n1", "to": "n2", "label": "x"},
             {"from": "n1", "to": "n2", "label": "x"},
             {"from": "n2", "to": "n3", "label": "z"}]
    nodes = [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]
    sem = rs.normalize(nodes, edges)
    assert [(e.from_, e.to, e.label) for e in sem.edges] == \
        [("n1", "n2", "x"), ("n1", "n2", "x"), ("n2", "n3", "z")]


def test_duplicate_edge_flat_render_matches_no_duplicate_shape(tmp_path):
    """A duplicate edge is drawn twice, exactly like the pre-D3 renderer."""
    from graph2note.diagrams import engine

    if not engine.graphviz_available():
        pytest.skip("graphviz/dot unavailable")
    dup_png = _render_edges(tmp_path / "dup", prefer="graphviz", edges=[
        {"from": "n1", "to": "n2", "label": "x"},
        {"from": "n1", "to": "n2", "label": "x"}])
    uniq_png = _render_edges(tmp_path / "uniq", prefer="graphviz", edges=[
        {"from": "n1", "to": "n2", "label": "x"}])
    assert _sha(dup_png) != _sha(uniq_png)


def _render_edges(tmp_path, *, prefer, edges):
    tmp_path.mkdir(parents=True, exist_ok=True)
    node_objs = [_Node("n1", "A"), _Node("n2", "B")]
    edge_objs = [_Edge(e["from"], e["to"], e.get("label", "")) for e in edges]
    writer = FileAssetWriter(tmp_path, doc_id="doc", prefer=prefer)
    render_mod.render_markdown(
        _Doc([_Block(nodes=node_objs, edges=edge_objs)]), doc_id="doc",
        attachment_writer=writer)
    return tmp_path / writer.results[0][0]
