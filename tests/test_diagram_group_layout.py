"""SPW D2 — group-aware diagram layout (SPEC §1), offline and deterministic.

Three complementary layers, no network and no live model calls:

1. **Golden fixtures** — one per group kind (``layer``/``lane``/``cluster``),
   stored as ``tests/golden/diagram-layout-<kind>.json`` (fixture + expected
   geometry).  They lock the reading order, lane columns and bounding boxes the
   renderers (D3) will draw.
2. **Invariants** — group bounding boxes contain their members; layer members
   share a row, lane members share a column, cluster members are adjacent.
3. **Regressions / edges** — no groups reproduces ``LayerLayout.layers()``
   exactly; determinism (FR-020); zero/one node, empty group, single-node group,
   dangling members, unknown kind, model-object groups (D1 rewiring).

The layout is driven purely by the SPEC §1 JSON shape: no import of the D1
``ir.py`` extension, so this file stays green before and after that merge.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note.diagrams import _canonical, engine, matplotlib_renderer
from graph2note.diagrams._layout import LayerLayout, grouped_layout
from graph2note.ir import Edge, Node

GOLDEN_DIR = Path(__file__).parent / "golden"
KINDS = ("layer", "lane", "cluster")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _golden(kind: str) -> dict:
    return json.loads(
        (GOLDEN_DIR / f"diagram-layout-{kind}.json").read_text(encoding="utf-8")
    )


def _layout_of(kind: str) -> tuple[dict, dict]:
    doc = _golden(kind)
    fx = doc["fixture"]
    return fx, grouped_layout(fx["nodes"], fx["edges"], fx["groups"])


def _row_of(layout: dict) -> dict[str, int]:
    return {n: i for i, row in enumerate(layout["rows"]) for n in row}


def _col_of(layout: dict) -> dict[str, int]:
    return {n: i for i, col in enumerate(layout["columns"]) for n in col}


# ---------------------------------------------------------------------------
# 1) golden fixtures: one per kind
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_golden_fixture_matches(kind):
    doc = _golden(kind)
    layout = grouped_layout(
        doc["fixture"]["nodes"], doc["fixture"]["edges"], doc["fixture"]["groups"]
    )
    assert layout == doc["expected"]


@pytest.mark.parametrize("kind", KINDS)
def test_golden_fixture_uses_a_single_group_kind(kind):
    doc = _golden(kind)
    kinds = {g["kind"] for g in doc["fixture"]["groups"]}
    assert kinds == {kind}


@pytest.mark.parametrize("kind", KINDS)
def test_golden_layout_is_byte_deterministic(kind):
    """FR-020: the same semantics must serialise byte-identically."""
    fx, _ = _layout_of(kind)
    first = json.dumps(grouped_layout(fx["nodes"], fx["edges"], fx["groups"]),
                       ensure_ascii=False, sort_keys=True)
    second = json.dumps(grouped_layout(fx["nodes"], fx["edges"], fx["groups"]),
                        ensure_ascii=False, sort_keys=True)
    assert first == second


@pytest.mark.parametrize("kind", KINDS)
def test_golden_layout_ignores_input_order(kind):
    """Canonicalisation means input order can never change the output."""
    fx, expected = _layout_of(kind)
    shuffled_nodes = list(reversed(fx["nodes"]))
    shuffled_edges = list(reversed(fx["edges"]))
    shuffled_groups = [
        {**g, "nodes": list(reversed(g["nodes"]))} for g in reversed(fx["groups"])
    ]
    assert grouped_layout(shuffled_nodes, shuffled_edges, shuffled_groups) == expected


# ---------------------------------------------------------------------------
# 2) placement invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_group_bbox_contains_every_member(kind):
    _, layout = _layout_of(kind)
    for group in layout["groups"]:
        assert group["members"], group["id"]
        bbox = group["bbox"]
        assert bbox is not None
        for member in group["members"]:
            pos = layout["positions"][member]
            assert bbox["x0"] <= pos["x"] <= bbox["x1"], (group["id"], member)
            assert bbox["y0"] <= pos["y"] <= bbox["y1"], (group["id"], member)


@pytest.mark.parametrize("kind", KINDS)
def test_positions_cover_every_node_exactly_once(kind):
    fx, layout = _layout_of(kind)
    assert sorted(layout["positions"]) == sorted(fx["nodes"])
    flat = [n for row in layout["rows"] for n in row]
    assert sorted(flat) == sorted(fx["nodes"])


def test_layer_members_share_one_horizontal_band():
    _, layout = _layout_of("layer")
    row = _row_of(layout)
    for group in layout["groups"]:
        assert group["kind"] == "layer"
        assert len({row[m] for m in group["members"]}) == 1, group["id"]


def test_lane_members_share_one_vertical_column():
    _, layout = _layout_of("lane")
    col = _col_of(layout)
    for group in layout["groups"]:
        assert group["kind"] == "lane"
        assert len({col[m] for m in group["members"]}) == 1, group["id"]


def test_cluster_members_are_adjacent_in_each_row():
    _, layout = _layout_of("cluster")
    for group in layout["groups"]:
        assert group["kind"] == "cluster"
        members = set(group["members"])
        for row in layout["rows"]:
            idx = [i for i, n in enumerate(row) if n in members]
            if idx:
                assert idx == list(range(idx[0], idx[0] + len(idx))), row


def test_band_order_ignores_vlm_order_hint():
    """Band order comes from graph structure, never from an ``order`` field."""
    nodes = ["a", "b", "c"]
    edges = [("a", "b"), ("b", "c")]
    base = grouped_layout(
        nodes, edges,
        [{"id": "g1", "kind": "layer", "nodes": ["a"]},
         {"id": "g2", "kind": "layer", "nodes": ["b"]},
         {"id": "g3", "kind": "layer", "nodes": ["c"]}],
    )
    assert base["rows"] == [["a"], ["b"], ["c"]]
    # contradicting hints must change nothing (no order_hint is implemented)
    hinted = grouped_layout(
        nodes, edges,
        [{"id": "g1", "kind": "layer", "nodes": ["a"], "order": 3},
         {"id": "g2", "kind": "layer", "nodes": ["b"], "order": 2},
         {"id": "g3", "kind": "layer", "nodes": ["c"], "order": 1}],
    )
    assert hinted == base


# ---------------------------------------------------------------------------
# 3) no-groups regression (behaviour identical to the pre-SPW layered layout)
# ---------------------------------------------------------------------------

_REGRESSION_GRAPHS = {
    "single": (["a"], []),
    "chain": (["a", "b", "c"], [("a", "b"), ("b", "c")]),
    "diamond": (["a", "b", "c", "d"],
                [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")]),
    "cycle": (["a", "b", "c"], [("a", "b"), ("b", "c"), ("c", "a")]),
    "disconnected": (["a", "b", "c", "d"], [("b", "c")]),
}


@pytest.mark.parametrize("name", sorted(_REGRESSION_GRAPHS))
def test_no_groups_matches_layer_layout(name):
    nodes, edges = _REGRESSION_GRAPHS[name]
    expected = [list(layer) for layer in LayerLayout(list(nodes), list(edges)).layers()]
    for groups in (None, [], ()):
        assert grouped_layout(list(nodes), list(edges), groups)["rows"] == expected


def test_no_groups_reports_no_group_boxes_or_dangling():
    layout = grouped_layout(["a", "b"], [("a", "b")], [])
    assert layout["groups"] == []
    assert layout["dangling"] == []
    assert layout["node_groups"] == {"a": [], "b": []}


# ---------------------------------------------------------------------------
# 4) edge cases
# ---------------------------------------------------------------------------


def test_zero_nodes_yields_empty_layout():
    layout = grouped_layout([], [])
    assert layout["positions"] == {}
    assert layout["rows"] == [] and layout["columns"] == []
    assert layout["nrows"] == 0
    assert layout["groups"] == []


def test_zero_nodes_keeps_group_metadata_without_bbox():
    layout = grouped_layout([], [], [{"id": "g", "kind": "layer", "label": "空", "nodes": []}])
    assert [g["id"] for g in layout["groups"]] == ["g"]
    assert layout["groups"][0]["bbox"] is None
    assert layout["groups"][0]["row_span"] is None


def test_single_node_is_positioned():
    layout = grouped_layout(["only"], [])
    assert layout["rows"] == [["only"]]
    assert layout["positions"]["only"] == {"x": 0.5, "y": 0.5}


def test_single_node_group_gets_a_box_around_it():
    layout = grouped_layout(["only"], [], [{"id": "g", "kind": "cluster", "nodes": ["only"]}])
    group = layout["groups"][0]
    assert group["row_span"] == [0, 0]
    assert group["col_span"] == [0, 0]
    assert group["bbox"] is not None


def test_empty_group_does_not_add_a_band():
    # one empty layer group + a two-node chain: still exactly two rows
    layout = grouped_layout(
        ["a", "b"], [("a", "b")],
        [{"id": "empty", "kind": "layer", "nodes": []}],
    )
    assert layout["rows"] == [["a"], ["b"]]
    assert layout["groups"][0]["bbox"] is None


def test_dangling_members_are_reported_and_dropped():
    layout = grouped_layout(
        ["a", "b"], [("a", "b")],
        [{"id": "g", "kind": "lane", "nodes": ["a", "ghost", "a"]}],
    )
    assert layout["dangling"] == ["ghost"]
    assert layout["groups"][0]["members"] == ["a"]


def test_unknown_kind_is_preserved_but_placed_as_a_cluster():
    layout = grouped_layout(
        ["a", "b", "c"], [("a", "c"), ("b", "c")],
        [{"id": "g", "kind": "swimlane", "nodes": ["a", "b"]}],
    )
    assert layout["groups"][0]["kind"] == "swimlane"
    row = _row_of(layout)
    # cluster-style placement: same row and a bbox wrapping the members
    assert row["a"] == row["b"]
    assert layout["groups"][0]["bbox"] is not None


def test_node_may_belong_to_a_layer_and_a_lane_at_once():
    layout = grouped_layout(
        ["a", "b", "c", "d"], [("a", "b"), ("b", "c"), ("c", "d")],
        [
            {"id": "band", "kind": "layer", "nodes": ["b", "c"]},
            {"id": "col", "kind": "lane", "nodes": ["a", "c"]},
        ],
    )
    assert layout["node_groups"]["c"] == ["band", "col"]
    col = _col_of(layout)
    assert col["a"] == col["c"]


# ---------------------------------------------------------------------------
# 5) canonicalisation
# ---------------------------------------------------------------------------


def test_canonical_groups_sorts_groups_and_members():
    groups = [
        {"id": "z", "label": "Z", "kind": "layer", "nodes": ["c", "a", "b"]},
        {"id": "a", "label": "A", "kind": "lane", "nodes": ["b"]},
    ]
    out = _canonical.canonical_groups(groups)
    assert [g["id"] for g in out] == ["a", "z"]
    assert out[1]["nodes"] == ["a", "b", "c"]


def test_canonical_groups_drops_dangling_and_duplicates():
    out = _canonical.canonical_groups(
        [{"id": "g", "kind": "cluster", "nodes": ["b", "ghost", "b", "a"]}],
        node_ids={"a", "b"},
    )
    assert out[0]["nodes"] == ["a", "b"]


def test_canonical_groups_defaults_kind_to_cluster():
    out = _canonical.canonical_groups([{"id": "g", "nodes": ["a"]}])
    assert out[0]["kind"] == "cluster"


def test_canonical_groups_preserves_extra_keys():
    out = _canonical.canonical_groups(
        [{"id": "g", "kind": "layer", "nodes": ["a"], "color": "#fff"}]
    )
    assert out[0]["color"] == "#fff"


def test_canonical_groups_accepts_model_dump_objects():
    class _FakeDiagramGroup:
        def __init__(self, **kw):
            self._data = kw

        def model_dump(self):
            return dict(self._data)

    out = _canonical.canonical_groups(
        [_FakeDiagramGroup(id="g", label="层", kind="layer", nodes=["b", "a"])]
    )
    assert out == [{"id": "g", "label": "层", "kind": "layer", "nodes": ["a", "b"]}]


def test_canonical_groups_accepts_attribute_objects():
    class _PlainGroup:
        id = "g"
        label = "泳道"
        kind = "lane"
        nodes = ["b", "a"]

    out = _canonical.canonical_groups([_PlainGroup()])
    assert out[0]["kind"] == "lane"
    assert out[0]["nodes"] == ["a", "b"]


def test_existing_canonical_helpers_are_unchanged():
    nodes = [Node(id="b"), Node(id="a")]
    assert [n.id for n in _canonical.canonical_nodes(nodes)] == ["a", "b"]
    edges = [Edge(from_="b", to="a"), Edge(from_="a", to="z"), Edge(from_="a", to="b")]
    kept = _canonical.canonical_edges(edges, {"a", "b"})
    assert [(e.from_, e.to) for e in kept] == [("a", "b"), ("b", "a")]


# ---------------------------------------------------------------------------
# 6) engine wiring (geometry prepared in D2, drawn in D3)
# ---------------------------------------------------------------------------


def _engine_nodes():
    return [Node(id="a", label="A"), Node(id="b", label="B"), Node(id="c", label="C")]


def _engine_edges():
    return [Edge(from_="a", to="b"), Edge(from_="b", to="c")]


def test_prepare_diagram_layout_positions_every_node():
    layout = engine.prepare_diagram_layout(
        _engine_nodes(), _engine_edges(),
        [{"id": "g", "kind": "layer", "label": "带", "nodes": ["a", "b"]}],
    )
    assert sorted(layout["positions"]) == ["a", "b", "c"]
    row = _row_of(layout)
    assert row["a"] == row["b"]
    assert layout["groups"][0]["bbox"] is not None


def test_prepare_diagram_layout_without_groups_is_layered():
    layout = engine.prepare_diagram_layout(_engine_nodes(), _engine_edges())
    assert layout["rows"] == [["a"], ["b"], ["c"]]
    assert layout["groups"] == []


def test_render_outcome_layout_defaults_to_none():
    assert engine.RenderOutcome(engine="empty", path="x.png").layout is None


def test_render_structured_without_groups_leaves_layout_none(tmp_path):
    if not matplotlib_renderer.available():
        pytest.skip("matplotlib unavailable")
    outcome = engine.render_structured(
        _engine_nodes(), _engine_edges(), str(tmp_path / "plain.png"),
        prefer="matplotlib",
    )
    assert outcome.layout is None


def test_render_structured_with_groups_attaches_layout(tmp_path):
    if not matplotlib_renderer.available():
        pytest.skip("matplotlib unavailable")
    outcome = engine.render_structured(
        _engine_nodes(), _engine_edges(), str(tmp_path / "grouped.png"),
        prefer="matplotlib",
        groups=[{"id": "g", "kind": "lane", "label": "列", "nodes": ["a", "c"]}],
    )
    assert outcome.layout is not None
    col = _col_of(outcome.layout)
    assert col["a"] == col["c"]
    assert Path(outcome.path).exists()
