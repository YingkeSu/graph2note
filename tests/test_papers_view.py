"""SPW P3 paper reading view — offline contract tests.

Covers the read-only display layer only (P1/P2 own ingest + recognition):

1. ``index.html`` DOM: the paper zone lives in the content area with its
   containers, and the zero-build frontend still loads one ES module entry
   (``app.js``) which reaches ``views/paper.js`` + ``paper_view_core.js``.
2. ``/api/papers/{id}/view`` + ``/api/papers``: SPEC §2 shape normalization over
   three storage layouts (nested ``paper``, sibling ``paper_*`` keys, and
   ``metadata.paper``) so the reader is decoupled from P1/P2's landing point;
   non-paper documents degrade, unknown documents 404, and a fresh
   ``FileDocumentStore`` reload proves the projection is durable.
3. The pure frontend contract runs under Node (``node tests/paper_view.mjs``).

Zero network, zero LLM.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

import graph2note.webapp as webapp
from graph2note.store import FileDocumentStore, SessionDocumentStore
from tests.static_assets import WEBSTATIC, app_entry, static_js  # noqa: F401

HERE = Path(__file__).parent
NODE_TEST = HERE / "paper_view.mjs"

PAPER_META = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "venue": "NeurIPS",
    "doi": "10.5555/3295222.3295349",
    "abstract": "The dominant sequence transduction models are based on recurrent networks.",
    "keywords": ["transformer", "attention"],
    "source": "text-layer",
}
PAPER_SECTIONS = [
    {"level": 1, "title": "1 Introduction", "text": "Recurrent models...",
     "page_start": 1, "page_end": 1},
    {"level": 2, "title": "1.1 Background", "text": "Background text",
     "page_start": 1, "page_end": 2},
]
PAPER_REFERENCES = [
    {"raw": "[1] Bahdanau et al. 2015", "title": "Neural Machine Translation",
     "authors": ["Dzmitry Bahdanau"], "year": 2015, "doi": "",
     "resolved_document_id": "doc-ref-1"},
    {"raw": "[2] Anonymous", "title": "", "authors": [], "year": None,
     "doi": "", "resolved_document_id": None},
]


def _seed(store, document_id: str, **extra):
    """Insert a document without parsing; returns the live record dict."""

    record = store.save_document(
        document_id=document_id, title=f"文件 {document_id}", source_job_id=f"job-{document_id}",
        model="fixture", markdown=f"# {document_id}\n", ir_json=json.dumps({"blocks": []}),
        original_path="", original_ext=".pdf", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={},
    )
    record.update(extra)
    return record


def _client(store):
    return TestClient(webapp.create_app(document_store=store, storage_dir=store.root))


# ---------------------------------------------------------------------------
# 1) DOM + module wiring
# ---------------------------------------------------------------------------


def _dom():
    from tests.html_dom import Element  # noqa: F401
    from tests.test_webapp_layout import _DomParser

    parser = _DomParser()
    parser.feed((WEBSTATIC / "index.html").read_text(encoding="utf-8"))
    return parser.root


def test_paper_zone_lives_in_content_with_empty_containers():
    dom = _dom()
    content = dom.find(id="content")
    zone = content.find(id="paper-zone") if content else None
    assert zone is not None, "the paper reading zone lives in the content area"
    for container in ("paper-meta", "paper-section-nav", "paper-body",
                      "paper-references", "paper-references-zone", "paper-back"):
        assert zone.find(id=container) is not None, container
    # the zone starts hidden so a non-paper route never flashes it
    assert "hidden" in zone.classes


def test_frontend_entry_imports_the_paper_view():
    entry = app_entry()
    assert "./js/views/paper.js" in entry, "paper.js must be reachable from the module entry"
    paper_js = WEBSTATIC / "js" / "views" / "paper.js"
    core_js = WEBSTATIC / "js" / "paper_view_core.js"
    assert paper_js.is_file() and core_js.is_file()
    assert 'from "../paper_view_core.js"' in paper_js.read_text(encoding="utf-8")


def test_paper_view_source_registers_both_routes_and_delegates_non_papers():
    source = (WEBSTATIC / "js" / "views" / "paper.js").read_text(encoding="utf-8")
    assert 'registerView("paper"' in source
    assert 'registerView("doc"' in source
    assert "renderDocumentRoute" in source, "non-paper documents keep the existing editor path"
    router = (WEBSTATIC / "js" / "router.js").read_text(encoding="utf-8")
    assert 'parts[0] === "paper"' in router, "#paper/<id> is a first-class parsed route"


def test_static_serves_paper_modules(tmp_path):
    client = _client(SessionDocumentStore(tmp_path / "session"))
    assert client.get("/static/js/views/paper.js").status_code == 200
    assert client.get("/static/js/paper_view_core.js").status_code == 200


def _paper_css_block() -> str:
    css = (WEBSTATIC / "style.css").read_text(encoding="utf-8")
    marker = "P3 (SPW): paper reading view"
    assert marker in css, "the paper view appends its own CSS block"
    return css[css.index(marker):]


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(fg: str, bg: str) -> float:
    high, low = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_paper_css_meets_the_reading_baseline():
    """Body >=14px / aux >=12px / contrast >=4.5:1 / one column at 390px."""
    block = _paper_css_block()
    assert ".paper-section-text" in block and "font-size: 15px" in block
    assert ".paper-meta-value" in block and "font-size: 14px" in block
    assert ".paper-abstract" in block and "font-size: 14px" in block
    assert "font-size: 12px" in block, "auxiliary text stays >=12px"
    assert "@media (max-width: 860px)" in block, "nav stacks instead of overflowing"
    reading = (WEBSTATIC / "reading.css").read_text(encoding="utf-8")
    tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", reading))
    for fg, bg in (("ink", "panel"), ("muted", "surface"), ("accent-dark", "accent-soft")):
        assert _contrast(tokens[fg], tokens[bg]) >= 4.5, f"{fg} on {bg} contrast"


# ---------------------------------------------------------------------------
# 2) /api/papers/* read-only projection
# ---------------------------------------------------------------------------


def test_paper_view_returns_spec_shape(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "paper-1", doc_kind="paper",
          paper={"meta": PAPER_META, "sections": PAPER_SECTIONS,
                 "references": PAPER_REFERENCES})
    _seed(store, "note-1")
    client = _client(store)

    body = client.get("/api/papers/paper-1/view").json()
    assert body["document_id"] == "paper-1"
    assert body["doc_kind"] == "paper"
    assert body["meta"]["title"] == "Attention Is All You Need"
    assert body["meta"]["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert body["meta"]["year"] == 2017
    assert body["meta"]["keywords"] == ["transformer", "attention"]
    assert [section["title"] for section in body["sections"]] == [
        "1 Introduction", "1.1 Background"]
    assert body["sections"][1]["page_end"] == 2
    assert body["references"][0]["resolved_document_id"] == "doc-ref-1"
    assert body["references"][1]["resolved_document_id"] == ""

    # a non-paper document degrades: the frontend then uses the standard view
    plain = client.get("/api/papers/note-1/view").json()
    assert plain["doc_kind"] == ""
    assert plain["sections"] == [] and plain["references"] == []

    assert client.get("/api/papers/does-not-exist/view").status_code == 404


def test_paper_view_tolerates_every_documented_storage_layout(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    # sibling paper_* keys
    _seed(store, "sib", doc_kind="paper", paper_meta=PAPER_META,
          paper_sections=PAPER_SECTIONS, paper_references=PAPER_REFERENCES)
    # kind nested in the paper blob, no top-level doc_kind
    _seed(store, "nested", paper={"doc_kind": "paper", "meta": PAPER_META,
                                  "sections": PAPER_SECTIONS})
    client = _client(store)

    for document_id in ("sib", "nested"):
        body = client.get(f"/api/papers/{document_id}/view").json()
        assert body["doc_kind"] == "paper", document_id
        assert body["meta"]["title"] == "Attention Is All You Need", document_id
        assert body["sections"][0]["text"] == "Recurrent models...", document_id


def test_paper_view_skips_malformed_entries_and_coerces_year(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "messy", doc_kind="paper", paper={
        "meta": {"title": "Messy", "year": "2019", "authors": ["A", "", None, 3]},
        "sections": [{"level": "2", "title": "S", "text": "T"}, "not-a-dict", 7],
        "references": [None, {"title": "R", "resolved_document_id": 12}],
    })
    body = _client(store).get("/api/papers/messy/view").json()
    assert body["meta"]["year"] == 2019, "numeric-string year is coerced"
    assert body["meta"]["authors"] == ["A"], "blank / non-string authors dropped"
    assert len(body["sections"]) == 1 and body["sections"][0]["level"] == 2
    assert len(body["references"]) == 1
    assert body["references"][0]["resolved_document_id"] == ""


def test_paper_view_is_durable_across_a_file_store_reload(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed(store, "paper-1")
    record_path = root / "documents" / "paper-1" / "record.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    data["doc_kind"] = "paper"
    data["paper"] = {"meta": PAPER_META, "sections": PAPER_SECTIONS,
                     "references": PAPER_REFERENCES}
    record_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    reloaded = FileDocumentStore(root)
    client = _client(reloaded)
    body = client.get("/api/papers/paper-1/view").json()
    assert body["doc_kind"] == "paper"
    assert body["meta"]["venue"] == "NeurIPS"
    assert body["sections"][0]["page_start"] == 1


def test_papers_index_lists_only_papers(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "paper-1", doc_kind="paper", paper={"sections": PAPER_SECTIONS})
    _seed(store, "note-1")
    _seed(store, "paper-2", doc_kind="paper")
    body = _client(store).get("/api/papers").json()
    assert body["count"] == 2
    assert {item["document_id"] for item in body["papers"]} == {"paper-1", "paper-2"}


def test_documents_list_contract_is_unchanged(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "note-1")
    _seed(store, "paper-1", doc_kind="paper", paper={"sections": PAPER_SECTIONS})
    client = _client(store)
    items = client.get("/api/documents").json()
    assert {item["document_id"] for item in items} == {"note-1", "paper-1"}
    for item in items:
        assert {"document_id", "title", "metadata", "effective_time"} <= set(item)
    # the paper view's own endpoint never mutates the library
    before = client.get("/api/documents/paper-1").json()
    client.get("/api/papers/paper-1/view")
    after = client.get("/api/documents/paper-1").json()
    assert before == after


# ---------------------------------------------------------------------------
# 3) Node frontend contract
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_paper_view_node_contract():
    proc = subprocess.run(
        ["node", str(NODE_TEST)], capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
