"""Issue 05: diagram/flow -> deterministic PNG asset + Markdown embedding.

Covers the complete product pipeline and its degrade path.  All tests are
offline (no LLM, no network): rendering uses graphviz/layout engines locally,
and the structured inputs are constructed IRs (mirroring cached extraction).

graphviz-dependent tests SKIP cleanly when either the python ``graphviz``
package or the ``dot`` binary is missing (double-check pattern).
"""

import os

import pytest
from PIL import Image

from graph2note.ir import DocumentIR
from graph2note.attachments import (
    FileAssetWriter,
    missing_attachments,
)
from graph2note.render import render_markdown


def _simple_doc(**kw):
    base = {
        "type": "diagram",
        "caption": "主流程",
        "nodes": [{"id": "n1", "label": "开始"}, {"id": "n2", "label": "处理数据"},
                  {"id": "n3", "label": "结束"}],
        "edges": [{"from": "n1", "to": "n2", "label": ""},
                  {"from": "n2", "to": "n3", "label": "完成"}],
    }
    base.update(kw)
    return DocumentIR(blocks=[base])


def _sha(path):
    import hashlib
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# structured render (graphviz preferred)
# ---------------------------------------------------------------------------


def test_structured_render_emits_md_and_asset(tmp_path):
    md = render_markdown(_simple_doc(), doc_id="doc",
                         attachment_writer=FileAssetWriter(tmp_path, doc_id="doc"))
    assert "![主流程](assets/doc-diagram-0.png)" in md
    png = tmp_path / "assets" / "doc-diagram-0.png"
    assert png.exists()
    im = Image.open(png)
    assert im.width > 0 and im.height > 0  # a real, decodable image


def test_structured_render_is_byte_deterministic(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir(), b.mkdir()
    for d in (a, b):
        render_markdown(_simple_doc(), doc_id="doc",
                        attachment_writer=FileAssetWriter(d, doc_id="doc"))
    assert _sha(a / "assets" / "doc-diagram-0.png") == \
        _sha(b / "assets" / "doc-diagram-0.png")


def test_flow_orientation_and_cycle_render(tmp_path):
    doc = DocumentIR(blocks=[{
        "type": "flow", "caption": "回流", "orientation": "TB",
        "nodes": [{"id": "a", "label": "初始化"}, {"id": "b", "label": "迭代"},
                  {"id": "c", "label": "收敛？"}],
        "edges": [{"from": "a", "to": "b", "label": ""},
                  {"from": "b", "to": "c", "label": ""},
                  {"from": "c", "to": "a", "label": "否"}],
    }])
    w = FileAssetWriter(tmp_path, doc_id="doc")
    md = render_markdown(doc, doc_id="doc", attachment_writer=w)
    assert "assets/doc-flow-0.png" in md
    assert w.results[0][1]["engine"] in {"graphviz", "matplotlib"}


# ---------------------------------------------------------------------------
# degrade path
# ---------------------------------------------------------------------------


def _fake_manuscript(path, w=500, h=400):
    from PIL import Image as I, ImageDraw
    im = I.new("RGB", (w, h), (250, 249, 244))
    d = ImageDraw.Draw(im)
    d.rectangle([100, 120, 260, 200], outline=(20, 25, 40), width=4)
    d.rectangle([300, 220, 440, 300], outline=(20, 25, 40), width=4)
    im.save(path, "PNG")
    return path


def test_degrade_crops_source_when_no_semantics(tmp_path):
    src = tmp_path / "src.png"
    _fake_manuscript(str(src))
    doc = DocumentIR(blocks=[{"type": "diagram", "caption": "手稿（降级）",
                              "source": str(src)}])
    w = FileAssetWriter(tmp_path, doc_id="doc")
    md = render_markdown(doc, doc_id="doc", attachment_writer=w)
    assert "assets/doc-diagram-0.png" in md
    assert w.results[0][1]["engine"] == "degrade"
    assert w.results[0][1]["degraded"] is True
    png = tmp_path / "assets" / "doc-diagram-0.png"
    assert png.exists()
    im = Image.open(png)
    assert im.width < 500 and im.height < 400  # content bbox crop


def test_empty_block_still_emits_resolvable_asset(tmp_path):
    doc = DocumentIR(blocks=[{"type": "diagram", "caption": "空"}])
    w = FileAssetWriter(tmp_path, doc_id="doc")
    md = render_markdown(doc, doc_id="doc", attachment_writer=w)
    assert w.results[0][1]["engine"] == "empty"
    assert (tmp_path / "assets" / "doc-diagram-0.png").exists()
    assert missing_attachments(md, tmp_path) == []


def test_degrade_missing_source_raises_clear_error(tmp_path):
    doc = DocumentIR(blocks=[{"type": "diagram", "caption": "x",
                              "source": "/no/such/file.png"}])
    w = FileAssetWriter(tmp_path, doc_id="doc")
    with pytest.raises(FileNotFoundError):
        render_markdown(doc, doc_id="doc", attachment_writer=w)


# ---------------------------------------------------------------------------
# attachment completeness
# ---------------------------------------------------------------------------


def test_missing_attachments_reports_absent(tmp_path):
    assert missing_attachments("![x](assets/ghost.png)", tmp_path) == \
        ["assets/ghost.png"]


def test_missing_attachments_ignores_remote_and_absolute(tmp_path):
    md = "![a](https://x/y.png)\n![b](/abs/z.png)\n![c](data:image/png;base64,AA)"
    assert missing_attachments(md, tmp_path) == []


def test_complete_doc_has_no_missing(tmp_path):
    md = render_markdown(_simple_doc(), doc_id="doc",
                         attachment_writer=FileAssetWriter(tmp_path, doc_id="doc"))
    assert missing_attachments(md, tmp_path) == []


# ---------------------------------------------------------------------------
# matplotlib fallback engine
# ---------------------------------------------------------------------------


def test_matplotlib_engine_is_byte_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    for d in (a, b):
        render_markdown(_simple_doc(), doc_id="doc",
                        attachment_writer=FileAssetWriter(
                            d, doc_id="doc", prefer="matplotlib"))
    pa = a / "assets" / "doc-diagram-0.png"
    pb = b / "assets" / "doc-diagram-0.png"
    assert pa.exists() and pb.exists()
    assert _sha(str(pa)) == _sha(str(pb))


def test_render_engines_available_consistent():
    from graph2note.diagrams import engine
    assert "matplotlib" in engine.engines_available()


# ---------------------------------------------------------------------------
# graphviz (double-check skip pattern)
# ---------------------------------------------------------------------------


def test_graphviz_renders_chinese_without_crash(tmp_path):
    pg = pytest.importorskip("graph2note.diagrams.graphviz_renderer")
    if not pg.available():
        pytest.skip("graphviz python pkg or dot binary unavailable")
    md = render_markdown(_simple_doc(), doc_id="doc",
                         attachment_writer=FileAssetWriter(
                             tmp_path, doc_id="doc", prefer="graphviz"))
    assert "![主流程](assets/doc-diagram-0.png)" in md


def test_graphviz_engine_byte_deterministic(tmp_path):
    pytest.importorskip("graph2note.diagrams.graphviz_renderer")
    from graph2note.diagrams import engine
    if not engine.graphviz_available():
        pytest.skip("graphviz unavailable")
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    for d in (a, b):
        render_markdown(_simple_doc(), doc_id="doc",
                        attachment_writer=FileAssetWriter(
                            d, doc_id="doc", prefer="graphviz"))
    assert _sha(str(a / "assets" / "doc-diagram-0.png")) == \
        _sha(str(b / "assets" / "doc-diagram-0.png"))


# ---------------------------------------------------------------------------
# IR backward compatibility
# ---------------------------------------------------------------------------


def test_source_field_is_backward_compatible():
    # documents without `source` still load
    d1 = DocumentIR(blocks=[{"type": "diagram", "caption": "x",
                             "nodes": [{"id": "a"}], "edges": []}])
    assert d1.blocks[0].source is None
    # documents with `source` load and carry it
    d2 = DocumentIR(blocks=[{"type": "diagram", "caption": "x", "source": "s.png"}])
    assert d2.blocks[0].source == "s.png"
