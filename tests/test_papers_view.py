"""SPW P3 paper reading view — offline contract tests.

Covers the read-only display layer only (P1/P2 own ingest + recognition):

1. ``index.html`` DOM: the paper zone lives in the content area with its
   containers, and the zero-build frontend still loads one ES module entry
   (``app.js``) which reaches ``views/paper.js`` + ``paper_view_core.js``.
2. ``GET /api/papers/{id}/view`` reads **through the real store seams**: P1's
   ``save_paper_document`` / ``get_paper_payload`` (sections / full text / page
   map) and P2's ``set_paper_meta`` / ``set_paper_references`` /
   ``paper_payload`` (metadata / references).  The file-backed store keeps P1's
   sections in ``paper.json`` and P2's slots in the ``paper`` key of
   ``record.json``, so the tests assert the endpoint is wired to the public API
   rather than to raw record keys (defect-A regression guard).  A second guard
   asserts P1's ``GET /api/papers`` job-list route is still reachable (P3 must
   not shadow it).
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
# P1 stores 0-based page indexes (see graph2note/papers/model.py).
PAPER_SECTIONS = [
    {"level": 1, "title": "1 Introduction", "text": "Recurrent models...",
     "page_start": 0, "page_end": 0},
    {"level": 2, "title": "1.1 Background", "text": "Background text",
     "page_start": 0, "page_end": 1},
]
PAPER_PAGE_MAP = [
    {"page_index": 0, "page_number": 1, "char_count": 120},
    {"page_index": 1, "page_number": 2, "char_count": 80},
]
# The exact shape ``store.save_paper_document`` persists (P1 PaperPayload).
PAPER_PAYLOAD = {
    "schema_version": 1,
    "source": "text-layer",
    "sections": PAPER_SECTIONS,
    "fulltext": "Recurrent models... Background text",
    "page_map": PAPER_PAGE_MAP,
    "meta": {},
    "references": [],
    "provenance": {"source": "text-layer", "pdf_id": "pdf-1", "sections": 2},
}
PAPER_REFERENCES = [
    {"raw": "[1] Bahdanau et al. 2015", "title": "Neural Machine Translation",
     "authors": ["Dzmitry Bahdanau"], "year": 2015, "doi": "",
     "resolved_document_id": "doc-ref-1"},
    {"raw": "[2] Anonymous", "title": "", "authors": [], "year": None,
     "doi": "", "resolved_document_id": None},
]


def _seed_paper(store, document_id: str, paper: dict | None = None):
    """Commit a paper through P1's real durable API (not a record-key fixture)."""

    return store.save_paper_document(
        document_id=document_id, title=f"论文 {document_id}", markdown="# t\n",
        paper=dict(paper if paper is not None else PAPER_PAYLOAD),
        model="text-layer", ir_json="{}", original_path=None, original_ext=".pdf",
    )


def _seed_note(store, document_id: str):
    return store.save_document(
        document_id=document_id, title=f"笔记 {document_id}", source_job_id=f"job-{document_id}",
        model="fixture", markdown=f"# {document_id}\n", ir_json=json.dumps({"blocks": []}),
        original_path="", original_ext=".jpg", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={},
    )


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
    assert "subscribeRender" not in router, "the redundant render hook was removed"


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
# 2) /api/papers/{id}/view reads through P1/P2 public store APIs
# ---------------------------------------------------------------------------


def test_view_reads_p1_sections_from_the_durable_paper_json(tmp_path):
    """Defect-A guard: the endpoint must use ``get_paper_payload`` (paper.json).

    For the file-backed store ``record.json`` only carries ``paper_sections`` as
    a *count*; a raw record reader yields no sections at all.
    """

    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    record = store.get_document("paper-1")

    # the record really is the lossy shape the old reader tripped over
    assert record["doc_kind"] == "paper"
    assert record["paper_sections"] == len(PAPER_SECTIONS)
    assert "sections" not in (record.get("paper") or {})
    assert (root / "documents" / "paper-1" / "paper.json").is_file()

    body = _client(store).get("/api/papers/paper-1/view").json()
    assert body["doc_kind"] == "paper"
    assert [section["title"] for section in body["sections"]] == [
        "1 Introduction", "1.1 Background"]
    assert body["sections"][0]["text"] == "Recurrent models..."
    # raw P1 index is preserved, the display label is 1-based
    assert body["sections"][0]["page_start"] == 0
    assert body["sections"][1]["page_label"] == "p.1–2"
    # P2 has not run yet: it degrades to the empty defaults, never a crash
    assert body["meta"]["title"] == ""
    assert body["references"] == []


def test_view_combines_p1_sections_with_p2_meta_and_references(tmp_path):
    """The live integration path: P1 import → P2 metadata/references → view."""

    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    store.set_paper_meta("paper-1", PAPER_META)
    store.set_paper_references("paper-1", PAPER_REFERENCES)
    _seed_note(store, "note-1")
    client = _client(store)

    body = client.get("/api/papers/paper-1/view").json()
    assert body["doc_kind"] == "paper"
    assert body["meta"]["title"] == "Attention Is All You Need"
    assert body["meta"]["authors"] == ["Ashish Vaswani", "Noam Shazeer"]
    assert body["meta"]["year"] == 2017
    assert body["meta"]["keywords"] == ["transformer", "attention"]
    assert len(body["sections"]) == 2
    assert body["references"][0]["resolved_document_id"] == "doc-ref-1"
    assert body["references"][1]["resolved_document_id"] == ""

    # a non-paper document degrades: the frontend then uses the standard view
    plain = client.get("/api/papers/note-1/view").json()
    assert plain["doc_kind"] == ""
    assert plain["sections"] == [] and plain["references"] == []
    assert client.get("/api/papers/does-not-exist/view").status_code == 404


def test_view_uses_p2_metadata_written_to_the_record_slot(tmp_path):
    """P2's durable landing is the ``paper`` key of record.json, not paper.json."""

    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    store.set_paper_meta("paper-1", PAPER_META)
    store.set_paper_references("paper-1", PAPER_REFERENCES)

    record = json.loads(
        (root / "documents" / "paper-1" / "record.json").read_text(encoding="utf-8"))
    assert record["paper"]["meta"]["title"] == "Attention Is All You Need"
    assert "sections" not in record["paper"], "P2 slot holds only its own keys"
    payload = json.loads(
        (root / "documents" / "paper-1" / "paper.json").read_text(encoding="utf-8"))
    assert payload["sections"][0]["title"] == "1 Introduction"

    body = _client(FileDocumentStore(root)).get("/api/papers/paper-1/view").json()
    assert body["meta"]["title"] == "Attention Is All You Need"
    assert len(body["sections"]) == 2


def test_view_is_durable_across_a_file_store_reload(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    store.set_paper_meta("paper-1", PAPER_META)
    store.set_paper_references("paper-1", PAPER_REFERENCES)

    body = _client(FileDocumentStore(root)).get("/api/papers/paper-1/view").json()
    assert body["meta"]["venue"] == "NeurIPS"
    assert body["sections"][0]["title"] == "1 Introduction"
    assert len(body["references"]) == 2


def test_view_works_on_the_in_memory_store_too(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    store.set_paper_meta("paper-1", PAPER_META)
    store.set_paper_references("paper-1", PAPER_REFERENCES)
    body = _client(store).get("/api/papers/paper-1/view").json()
    assert body["meta"]["title"] == "Attention Is All You Need"
    assert len(body["sections"]) == 2
    assert len(body["references"]) == 2


def test_view_skips_malformed_entries_and_coerces_year(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store, "messy", {
        "source": "text-layer",
        "sections": [{"level": "2", "title": "S", "text": "T"}, "x", 7],
        "page_map": [], "meta": {}, "references": [], "provenance": {},
    })
    # simulate a legacy/hostile P2 slot with wrong types
    record_path = root / "documents" / "messy" / "record.json"
    data = json.loads(record_path.read_text(encoding="utf-8"))
    data["paper"] = {
        "meta": {"title": "Messy", "year": "2019", "authors": ["A", "", None, 3]},
        "references": [None, {"title": "R", "resolved_document_id": 12}],
    }
    record_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    body = _client(FileDocumentStore(root)).get("/api/papers/messy/view").json()
    assert body["meta"]["year"] == 2019, "numeric-string year is coerced"
    assert body["meta"]["authors"] == ["A"], "blank / non-string authors dropped"
    assert len(body["sections"]) == 1 and body["sections"][0]["level"] == 2
    assert len(body["references"]) == 1
    assert body["references"][0]["resolved_document_id"] == ""


def test_p1_papers_endpoint_is_not_shadowed(tmp_path):
    """Defect-B guard: P3 must not register a second ``GET /api/papers``.

    P1 owns that route and answers with a *list* of paper job summaries.
    """

    client = _client(SessionDocumentStore(tmp_path / "session"))
    listing = client.get("/api/papers")
    assert listing.status_code == 200
    body = listing.json()
    assert isinstance(body, list), "P1's /api/papers returns a job-summary list"
    assert not (isinstance(body, dict) and "papers" in body), "the P3 index is gone"


def test_documents_list_exposes_doc_kind_for_the_badge(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    _seed_note(store, "note-1")
    items = {item["document_id"]: item for item in _client(store).get("/api/documents").json()}
    assert items["paper-1"]["doc_kind"] == "paper"
    assert items["note-1"].get("doc_kind") in (None, "")


def test_view_never_mutates_the_library(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed_paper(store, "paper-1", PAPER_PAYLOAD)
    client = _client(store)
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
