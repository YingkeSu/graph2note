"""D3 rework F1: group semantics must reach the *product* render path.

The original D3 delivery only proved that the renderers draw groups when they
are called directly; the reviewer showed the product chain
(``render_markdown`` -> ``FileAssetWriter`` -> ``engine`` -> renderer) dropped
them, because the renderers did not declare D2's ``layout=`` keyword, so the
engine's ``_renderer_layout_kwargs`` forwarded nothing (F1).

These tests drive the real product chain and assert that a grouped diagram
produces a *different* PNG than the same diagram without groups, and that the
prepared geometry actually arrived at the renderer (spy on ``build_digraph`` /
``build_figure``).

Engine selection: when the installed engine already supports ``groups`` (D2
merged) the real engine is used.  Until then a stub implementing exactly the
D2 contract (same layout dict shape, same ``layout``-signature forwarding) is
installed, so the test still traps a missing ``layout=`` on the renderers.
"""

from __future__ import annotations

import inspect
import os
import shutil
import types

import pytest

from graph2note import render as render_mod
from graph2note.attachments import FileAssetWriter
from tests.test_diagram_render_groups import EDGES, GROUPS, NODES


# ---------------------------------------------------------------------------
# SPEC §1 shaped stubs (no dependency on D1's IR extension)
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


# ---------------------------------------------------------------------------
# a stub engine implementing the D2 contract (used until D2 is merged)
# ---------------------------------------------------------------------------


def _stub_layout(nodes, edges, groups) -> dict:
    """D2-shaped layout dict: positions + per-group bbox, deterministic."""
    ids = sorted({str(getattr(n, "id", n)) for n in nodes})
    id_set = set(ids)
    cleaned = []
    for g in groups or []:
        gid = str(g.get("id", ""))
        if not gid:
            continue
        members = sorted({str(m) for m in (g.get("nodes") or []) if str(m) in id_set})
        cleaned.append({
            "id": gid,
            "label": str(g.get("label", "")),
            "kind": str(g.get("kind") or "cluster"),
            "members": members,
        })
    cleaned.sort(key=lambda g: (g["id"], g["kind"], g["label"], tuple(g["members"])))
    owners = {}
    for g in cleaned:
        for m in g["members"]:
            owners.setdefault(m, g["id"])
    rows = [list(g["members"]) for g in cleaned]
    ungrouped = [n for n in ids if n not in owners]
    if ungrouped:
        rows.append(ungrouped)
    if not rows:
        rows = [ids]
    nrows, ncols = len(rows), max(1, max(len(r) for r in rows))
    positions = {}
    for r, row in enumerate(rows):
        for c, n in enumerate(row):
            positions[n] = {"x": (c + 0.5) / ncols, "y": (r + 0.5) / nrows}
    boxes = []
    for g in cleaned:
        pts = [positions[m] for m in g["members"] if m in positions]
        if pts:
            mx, my = 0.5 / ncols, 0.5 / nrows
            bbox = {
                "x0": max(0.0, min(p["x"] for p in pts) - mx),
                "y0": max(0.0, min(p["y"] for p in pts) - my),
                "x1": min(1.0, max(p["x"] for p in pts) + mx),
                "y1": min(1.0, max(p["y"] for p in pts) + my),
            }
        else:
            bbox = None
        boxes.append({**g, "bbox": bbox, "row_span": None, "col_span": None})
    return {
        "positions": positions, "rows": rows, "columns": [],
        "groups": boxes, "node_groups": {}, "dangling": [],
        "nrows": nrows, "ncols": ncols,
    }


def _forward_layout(renderer, layout):
    """Mirror of D2's ``_renderer_layout_kwargs`` (the F1 trap)."""
    if layout is None:
        return {}
    return {"layout": layout} if "layout" in inspect.signature(renderer).parameters else {}


def _install_engine(monkeypatch) -> str:
    """Use the real D2 engine when present, else a D2-contract stub."""
    from graph2note import attachments
    from graph2note.diagrams import engine as engine_mod
    from graph2note.diagrams import graphviz_renderer, matplotlib_renderer

    monkeypatch.setattr(attachments, "_ENGINE_GROUPS_SUPPORT", None)
    if "groups" in inspect.signature(engine_mod.render_to_png).parameters:
        return "real"

    def stub_render_to_png(nodes, edges, source, out_path, *, prefer="graphviz",
                           max_embed_width=900, orientation="TB", groups=None):
        layout = _stub_layout(nodes, edges, groups) if groups else None
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        if prefer == "graphviz" and graphviz_renderer.available():
            kwargs = _forward_layout(graphviz_renderer.render, layout)
            path = graphviz_renderer.render(nodes, edges, out_path,
                                            orientation=orientation, **kwargs)
            return _outcome("graphviz", path, layout)
        labels = {n.id: n.label for n in nodes}
        kwargs = _forward_layout(matplotlib_renderer.render, layout)
        path = matplotlib_renderer.render(nodes, edges, labels, out_path,
                                          orientation=orientation, **kwargs)
        return _outcome("matplotlib", path, layout)

    monkeypatch.setattr(engine_mod, "render_to_png", stub_render_to_png)
    return "stub"


def _outcome(engine: str, path: str, layout):
    """Duck-typed ``RenderOutcome`` so the stub works with or without D2."""
    return types.SimpleNamespace(engine=engine, path=path, degraded=False,
                                 notes=[], layout=layout)


def _render(tmp_path, prefer: str, *, with_groups: bool):
    writer = FileAssetWriter(tmp_path, doc_id="doc", prefer=prefer)
    render_mod.render_markdown(_doc(with_groups=with_groups), doc_id="doc",
                               attachment_writer=writer)
    rel, info = writer.results[0]
    return writer, info, (tmp_path / rel)


def _sha(path) -> str:
    with open(path, "rb") as fh:
        return __import__("hashlib").sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# product-chain regression (F1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefer", ["graphviz", "matplotlib"])
def test_product_chain_grouped_render_differs_from_flat(tmp_path, monkeypatch, prefer):
    """The reviewer's F1 probe: grouped vs flat PNG must not be identical."""
    from graph2note.diagrams import engine as engine_mod

    if prefer == "graphviz" and not engine_mod.graphviz_available():
        pytest.skip("graphviz/dot unavailable")
    mode = _install_engine(monkeypatch)

    grouped_dir = tmp_path / "grouped"
    flat_dir = tmp_path / "flat"
    grouped_dir.mkdir()
    flat_dir.mkdir()
    _writer, info, grouped_png = _render(grouped_dir, prefer, with_groups=True)
    _render(flat_dir, prefer, with_groups=False)
    flat_png = flat_dir / "assets" / "doc-diagram-0.png"

    assert info["engine"] == prefer, (mode, info)
    assert _sha(grouped_png) != _sha(flat_png), (
        f"{prefer}: product chain dropped the groups (engine mode={mode})"
    )


def test_product_chain_forwards_layout_to_graphviz(tmp_path, monkeypatch):
    from graph2note.diagrams import engine as engine_mod
    from graph2note.diagrams import graphviz_renderer

    if not engine_mod.graphviz_available():
        pytest.skip("graphviz/dot unavailable")
    mode = _install_engine(monkeypatch)

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

    assert mode in {"real", "stub"}
    assert captured["layout"], "engine never forwarded a prepared layout (F1)"
    layout = captured["layout"]
    assert [g["id"] for g in layout["groups"]] == ["g1", "g2", "g3"]
    assert layout["positions"], "layout carries no positions"
    # groups + notes + dashed edges all reached the drawing layer
    source = captured["source"]
    assert source.count("subgraph cluster_") == 3
    assert "style=dashed" in source
    assert f'POINT-SIZE="{graphviz_renderer.NOTE_FONTSIZE}"' in source


def test_product_chain_forwards_layout_to_matplotlib(tmp_path, monkeypatch):
    from graph2note.diagrams import matplotlib_renderer

    _install_engine(monkeypatch)
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

    assert captured["layout"], "engine never forwarded a prepared layout (F1)"
    assert captured["drawn"] == ["g1", "g2", "g3"]


def test_product_chain_records_semantics_for_export(tmp_path, monkeypatch):
    _install_engine(monkeypatch)
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


def _require_graphviz_source(gv, *, layout):
    if not gv.available():
        pytest.skip("graphviz/dot unavailable")
    nodes = [{"id": "n1", "label": "A"}, {"id": "n3", "label": "C"}]
    return gv.build_digraph(nodes, [], layout=layout).source


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


def test_duplicate_edge_flat_render_matches_no_duplicate_shape(tmp_path, monkeypatch):
    """A duplicate edge is drawn twice, exactly like the pre-D3 renderer."""
    from graph2note.diagrams import engine as engine_mod

    if not engine_mod.graphviz_available():
        pytest.skip("graphviz/dot unavailable")
    _install_engine(monkeypatch)
    dup_png = _render_edges(tmp_path / "dup", [
        {"id": "n1", "label": "A"}, {"id": "n2", "label": "B"},
    ], [{"from": "n1", "to": "n2", "label": "x"},
        {"from": "n1", "to": "n2", "label": "x"}], prefer="graphviz")
    uniq_png = _render_edges(tmp_path / "uniq", [
        {"id": "n1", "label": "A"}, {"id": "n2", "label": "B"},
    ], [{"from": "n1", "to": "n2", "label": "x"}], prefer="graphviz")
    assert _sha(dup_png) != _sha(uniq_png)


def _render_edges(tmp_path, nodes, edges, *, prefer):
    tmp_path.mkdir(parents=True, exist_ok=True)
    node_objs = [_Node(n["id"], n["label"]) for n in nodes]
    edge_objs = [_Edge(e["from"], e["to"], e.get("label", "")) for e in edges]
    writer = FileAssetWriter(tmp_path, doc_id="doc", prefer=prefer)
    render_mod.render_markdown(
        _Doc([_Block(nodes=node_objs, edges=edge_objs)]), doc_id="doc",
        attachment_writer=writer)
    return tmp_path / writer.results[0][0]
