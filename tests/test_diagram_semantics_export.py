"""D3: hierarchy semantics flow through the export chain (SPEC §1).

The Markdown export is the product's text export format.  Grouping, notes and
dashed edges are drawn into the PNG, but a text export must not silently drop
them: ``render_markdown`` appends one deterministic, invisible HTML comment
describing them, and ``FileAssetWriter.results`` keeps an audit record of
exactly what reached the drawing layer.

These tests are dependency-light: plain stub blocks/objects (SPEC §1 shape)
are used instead of D1's unmerged IR models.
"""

from __future__ import annotations

import json
import os

import pytest

from graph2note import render as render_mod
from graph2note.attachments import DiagramSemantics, FileAssetWriter
from graph2note.render import render_markdown


# ---------------------------------------------------------------------------
# SPEC §1 shaped stubs (no dependency on D1)
# ---------------------------------------------------------------------------


class StubNode:
    def __init__(self, id, label="", note=None):
        self.id = id
        self.label = label
        self.note = note


class StubEdge:
    def __init__(self, src, dst, label="", style="solid"):
        self.from_ = src
        self.to = dst
        self.label = label
        self.style = style


class StubBlock:
    def __init__(self, **kw):
        self.type = kw.pop("type", "diagram")
        self.caption = kw.pop("caption", "")
        self.nodes = kw.pop("nodes", [])
        self.edges = kw.pop("edges", [])
        self.orientation = kw.pop("orientation", None)
        self.source = kw.pop("source", None)
        self.groups = kw.pop("groups", [])
        self.__dict__.update(kw)


class StubDoc:
    def __init__(self, blocks):
        self.blocks = blocks


NODES = [
    StubNode("n1", "macmini", note="坑：Tiger VNC 不支持"),
    StubNode("n2", "macbook"),
    StubNode("n3", "windows laptop"),
]
EDGES = [
    StubEdge("n1", "n2"),
    StubEdge("n3", "n1", label="Ragget TS", style="dashed"),
]
GROUPS = [
    {"id": "g1", "label": "通信层", "kind": "layer", "nodes": ["n1", "n3"]},
    {"id": "g2", "label": "执行层", "kind": "cluster", "nodes": ["n2"]},
]


def _sidecar(md: str) -> dict:
    marker = "<!-- diagram-semantics: "
    assert marker in md, md
    payload = md.split(marker, 1)[1].split(" -->", 1)[0]
    return json.loads(payload)


# ---------------------------------------------------------------------------
# DiagramSemantics
# ---------------------------------------------------------------------------


def test_diagram_semantics_carries_groups_and_defaults_empty():
    assert DiagramSemantics("diagram", [], []).groups == []
    sem = DiagramSemantics("diagram", NODES, EDGES, groups=GROUPS)
    assert sem.groups == GROUPS


# ---------------------------------------------------------------------------
# FileAssetWriter audit trail
# ---------------------------------------------------------------------------


def test_writer_records_groups_notes_and_dashed_edges(tmp_path):
    doc = StubDoc([StubBlock(nodes=NODES, edges=EDGES, groups=GROUPS)])
    writer = FileAssetWriter(tmp_path, doc_id="doc")
    render_markdown(doc, doc_id="doc", attachment_writer=writer)
    _rel, info = writer.results[0]
    assert info["engine"] in {"graphviz", "matplotlib"}
    sem = info["semantics"]
    assert [g["id"] for g in sem["groups"]] == ["g1", "g2"]
    assert sem["groups"][0]["label"] == "通信层"
    assert sem["notes"] == {"n1": "坑：Tiger VNC 不支持"}
    assert sem["dashed_edges"] == [["n3", "n1"]]


def test_groups_forwarded_to_engine(tmp_path, monkeypatch):
    """D1+D2 are merged: the writer always forwards groups to the engine."""
    from graph2note.diagrams import engine

    calls = {}

    def fake_render_to_png(nodes, edges, source, out_path, *, groups=None, **kw):
        calls["groups"] = groups
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("png")
        return engine.RenderOutcome(engine="graphviz", path=out_path)

    monkeypatch.setattr(engine, "render_to_png", fake_render_to_png)
    doc = StubDoc([StubBlock(nodes=NODES, edges=EDGES, groups=GROUPS)])
    render_markdown(doc, doc_id="doc", attachment_writer=FileAssetWriter(tmp_path))
    assert calls["groups"] == GROUPS


def test_empty_groups_forward_none(tmp_path, monkeypatch):
    from graph2note.diagrams import engine

    calls = {}

    def fake_render_to_png(nodes, edges, source, out_path, *, groups=None, **kw):
        calls["groups"] = groups
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write("png")
        return engine.RenderOutcome(engine="graphviz", path=out_path)

    monkeypatch.setattr(engine, "render_to_png", fake_render_to_png)
    render_markdown(StubDoc([StubBlock(nodes=NODES, edges=EDGES)]), doc_id="doc",
                    attachment_writer=FileAssetWriter(tmp_path))
    assert calls["groups"] is None


def test_flat_diagram_still_renders(tmp_path):
    """A flat block keeps rendering through the (now group-aware) engine."""
    doc = StubDoc([StubBlock(nodes=NODES, edges=EDGES)])
    writer = FileAssetWriter(tmp_path, doc_id="doc")
    rel = render_markdown(doc, doc_id="doc", attachment_writer=writer)
    assert rel.startswith("![")
    assert (tmp_path / "assets" / "doc-diagram-0.png").exists()


# ---------------------------------------------------------------------------
# Markdown sidecar (export must not lose hierarchy semantics)
# ---------------------------------------------------------------------------


def test_render_emits_semantics_sidecar_with_groups_notes_dashed():
    doc = StubDoc([StubBlock(caption="主流程", nodes=NODES, edges=EDGES, groups=GROUPS)])
    md = render_markdown(doc, doc_id="doc")
    assert md.startswith("![主流程](assets/doc-diagram-0.png)")
    payload = _sidecar(md)
    assert payload["groups"] == [
        {"id": "g1", "kind": "layer", "label": "通信层", "nodes": ["n1", "n3"]},
        {"id": "g2", "kind": "cluster", "label": "执行层", "nodes": ["n2"]},
    ]
    assert payload["notes"] == {"n1": "坑：Tiger VNC 不支持"}
    assert payload["dashed_edges"] == [["n3", "n1"]]


def test_flat_diagram_output_is_unchanged_regression():
    flat_nodes = [StubNode("n1", "A"), StubNode("n2", "B")]
    doc = StubDoc([StubBlock(caption="流程", nodes=flat_nodes,
                             edges=[StubEdge("n1", "n2")])])
    assert render_markdown(doc, doc_id="mynote") == \
        "![流程](assets/mynote-diagram-0.png)\n"


def test_sidecar_is_deterministic_and_injection_safe():
    hostile = StubNode("n1", "A", note="危险 --> 注释 & <b>")
    doc = StubDoc([StubBlock(nodes=[hostile], edges=[],
                             groups=[{"id": "g<1>", "label": "层 -- 组",
                                      "kind": "layer", "nodes": ["n1"]}])])
    first = render_markdown(doc, doc_id="doc")
    second = render_markdown(doc, doc_id="doc")
    assert first == second
    # The raw comment must not contain a real terminator or raw markup ...
    body = first.split("<!-- diagram-semantics: ", 1)[1]
    assert body.count("<!--") == 0
    assert body.rstrip().endswith("-->")
    assert "-->" not in body[:body.index("-->")]
    assert "<b>" not in body
    # ... yet it still decodes to the original text.
    payload = json.loads(body.split(" -->", 1)[0])
    assert payload["notes"] == {"n1": "危险 --> 注释 & <b>"}
    assert payload["groups"][0]["id"] == "g<1>"


def test_sidecar_lives_in_the_rendered_markdown_only_when_needed():
    flat = StubDoc([StubBlock(nodes=[StubNode("n1", "A")])])
    assert "diagram-semantics" not in render_markdown(flat, doc_id="d")


# ---------------------------------------------------------------------------
# degrade compatibility (crop & embed must ignore visual grouping)
# ---------------------------------------------------------------------------


def test_degrade_required_ignores_groups():
    from graph2note.diagrams.degrade import degrade_required

    groups = [{"id": "g", "label": "层", "kind": "layer", "nodes": ["n1"]}]
    assert degrade_required([], [], groups) is True
    assert degrade_required([], [], None) is True
    assert degrade_required(NODES, [], groups) is False
    assert degrade_required([], EDGES, groups) is False


def test_crop_output_unaffected_by_group_semantics(tmp_path):
    from PIL import Image, ImageDraw
    from graph2note.diagrams.degrade import crop_image

    src = tmp_path / "src.png"
    im = Image.new("RGB", (500, 400), (250, 249, 244))
    ImageDraw.Draw(im).rectangle([100, 120, 260, 200], outline=(20, 25, 40), width=4)
    im.save(src)

    a = crop_image(str(src), str(tmp_path / "a.png"))
    b = crop_image(str(src), str(tmp_path / "b.png"))
    assert open(a, "rb").read() == open(b, "rb").read()


def test_group_only_block_still_degrades_to_crop(tmp_path):
    """groups without nodes/edges must not fabricate a structured render."""
    from PIL import Image, ImageDraw

    src = tmp_path / "src.png"
    im = Image.new("RGB", (400, 300), (250, 249, 244))
    ImageDraw.Draw(im).rectangle([40, 40, 200, 160], outline=(0, 0, 0), width=3)
    im.save(src)
    block = StubBlock(caption="降级", source=str(src),
                      groups=[{"id": "g", "label": "层", "kind": "layer",
                               "nodes": ["ghost"]}])
    writer = FileAssetWriter(tmp_path, doc_id="doc")
    render_markdown(StubDoc([block]), doc_id="doc", attachment_writer=writer)
    _rel, info = writer.results[0]
    assert info["engine"] == "degrade"
    assert info["degraded"] is True


def test_pure_helpers_are_dependency_free_for_placeholder_writer():
    """Placeholder rendering must not require the optional diagram extras."""
    doc = StubDoc([StubBlock(caption="c", nodes=NODES, edges=EDGES, groups=GROUPS)])
    md = render_markdown(doc, doc_id="doc")
    assert "assets/doc-diagram-0.png" in md
    assert render_mod.escape_text("a*b") == r"a\*b"
