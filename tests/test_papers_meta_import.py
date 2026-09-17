"""SPW PRR / 02 — import → metadata/references → persistence → view.

Covers the wiring the diagnosis (D3) found missing: the import pipeline now runs
the existing deterministic P2 parser and persists the P2 slots, so a freshly
imported paper shows its title/authors/abstract instead of the filename, while
the import itself stays successful even when extraction fails.

Everything here is offline: synthetic PyMuPDF papers, the injected no-network
router guard, and a recorded GROBID TEI fixture for the optional external seam.
The real user library is never written to.
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import pdflib  # noqa: E402
from graph2note import papers  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.papers import extract as papers_extract  # noqa: E402
from graph2note.papers import grobid as papers_grobid  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402

TEXT_PAGES = [
    [
        ("A Study of Things", 18.0),
        ("Alice, Bob", 10.0),
        ("Abstract", 13.0),
        ("We study things deeply and report a long series of measurements", 10.0),
        ("that together describe the behaviour of the system we built.", 10.0),
        ("1 Introduction", 15.0),
        ("Papers are nice to read when the text layer is available because", 10.0),
        ("the extraction stays deterministic and needs no model call at all.", 10.0),
    ],
    [
        ("2 Method", 15.0),
        ("2.1 Overview", 12.0),
        ("We do stuff carefully, measuring everything twice for stability.", 10.0),
        ("References", 15.0),
        ("[1] Foo et al. 2020. A useful reference entry for the list.", 10.0),
    ],
]

# A front page without a References section (drives the GROBID reference seam).
NO_REFS_PAGES = [
    [
        ("A Study of Things", 18.0),
        ("Alice, Bob", 10.0),
        ("Abstract", 13.0),
        ("We study things deeply and report a long series of measurements that", 10.0),
        ("together describe the behaviour of the system we built and evaluated.", 10.0),
        ("1 Introduction", 15.0),
        ("Body text that carries no bibliography at all but is long enough to", 10.0),
        ("push the page over the text-layer character threshold comfortably.", 10.0),
    ],
]

# A reflowed byline where ``Abstract`` is glued to the author lines (Y5 case).
REFLOWED_PAGES = [
    [
        ("Graph Neural Networks for Document Understanding", 18.0),
        ("Wei Zhang, Li Chen, Ming Li", 10.0),
        ("Abstract Document understanding has attracted attention in recent years.", 10.0),
        ("We review graph neural network methods for document understanding.", 10.0),
        ("1 Introduction", 15.0),
        ("Body text of the introduction goes here with enough characters.", 10.0),
    ],
]

TEI_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title type="main">Graph Networks in Practice</title>
        <author>
          <persName><forename type="first">Ada</forename><surname>Lovelace</surname></persName>
        </author>
        <author>
          <persName><forename type="first">Alan</forename><surname>Turing</surname></persName>
        </author>
      </titleStmt>
      <publicationStmt><publisher>arXiv</publisher></publicationStmt>
      <sourceDesc>
        <biblStruct>
          <analytic><title level="a">Graph Networks in Practice</title></analytic>
          <monogr><title level="m">Journal of Graphs</title>
            <imprint><date type="published" when="2021"/></imprint>
          </monogr>
          <idno type="DOI">10.1234/grobid.2021</idno>
        </biblStruct>
      </sourceDesc>
    </fileDesc>
    <abstract><p>Graph networks are studied in practice.</p></abstract>
    <profileDesc><textClass><keywords>
      <term>graph networks</term><term>practice</term>
    </keywords></textClass></profileDesc>
  </teiHeader>
  <text><body>
    <listBibl>
      <biblStruct>
        <analytic><title level="a">External Reference One</title></analytic>
        <monogr><imprint><date when="2019"/></imprint></monogr>
      </biblStruct>
    </listBibl>
  </body></text>
</TEI>
"""


def _pdf(pages) -> bytes:
    doc = pymupdf.open()
    for entries in pages:
        page = doc.new_page()
        y = 90.0
        for text, size in entries:
            page.insert_text((72, y), text, fontsize=size)
            y += size + 10
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _boom_factory(*_args, **_kwargs):
    raise AssertionError("the import path must not construct a router")


def _app(tmp_path, store=None) -> webapp.FastAPI:
    store = store or FileDocumentStore(tmp_path / "store")
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=tmp_path / "store",
        document_store=store,
        router_factory=_boom_factory,
        max_retries=1,
    )


def _import(client, data, filename="paper.pdf"):
    return client.post("/api/papers/import",
                       files={"file": (filename, data, "application/pdf")})


def _wait(client, paper_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/papers/{paper_id}").json()
        if body["status"] not in ("queued", "processing"):
            return body
        time.sleep(0.1)
    raise AssertionError("paper job did not finish in time")


def _ref_key(reference: dict) -> tuple:
    """Canonical comparison key across the raw and view reference shapes."""

    return (
        reference.get("raw") or "",
        reference.get("title") or "",
        list(reference.get("authors") or []),
        reference.get("year"),
        reference.get("doi") or "",
        reference.get("resolved_document_id") or "",
    )


def _imported_paper(client, tmp_path, pages=None) -> dict:
    data = _pdf(pages or TEXT_PAGES)
    response = _import(client, data)
    assert response.status_code == 200, response.text
    status = _wait(client, response.json()["paper_id"])
    assert status["status"] == "done"
    return status


# ---------------------------------------------------------------------------
# AC1/AC4: import extracts and persists metadata; result == metadata == view
# ---------------------------------------------------------------------------

def test_import_persists_metadata_and_references_through_the_p2_slot(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)
    document_id = status["document_id"]

    assert status["meta_status"] == "ok" and status["meta_error"] is None

    metadata = client.get(f"/api/papers/{document_id}/metadata").json()
    assert metadata["meta"]["title"] == "A Study of Things"
    assert metadata["meta"]["authors"] == ["Alice", "Bob"]
    assert metadata["meta"]["abstract"].startswith("We study things deeply")
    assert metadata["meta"]["source"] == "text-layer"
    assert metadata["references"][0]["raw"].startswith("[1] Foo")

    result = client.get(f"/api/papers/{status['paper_id']}/result").json()
    view = client.get(f"/api/papers/{document_id}/view").json()
    assert result["meta"] == metadata["meta"] == view["meta"]
    # The view normalises (None -> "", adds provenance notes) while the raw
    # endpoints keep the contract shape; the underlying values are identical.
    assert [_ref_key(ref) for ref in result["references"]] == [
        _ref_key(ref) for ref in view["references"]
    ]
    assert result["meta_status"] == "ok"


def test_library_card_reads_the_same_title_as_the_reading_view(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)
    document_id = status["document_id"]

    cards = {item["document_id"]: item
             for item in client.get("/api/documents").json()}
    view = client.get(f"/api/papers/{document_id}/view").json()
    assert cards[document_id]["headline"] == view["meta"]["title"] == "A Study of Things"
    # the record title was committed from the extraction, not the filename
    assert client.get(f"/api/documents/{document_id}").json()["title"] \
        == "A Study of Things"


def test_historical_backfill_makes_the_card_show_the_extracted_title(tmp_path):
    store = FileDocumentStore(tmp_path / "store")
    store.save_paper_document(
        document_id="paper-old", title="old-filename", markdown="# old-filename\n",
        paper={
            "source": "text-layer",
            "sections": [{"level": 1, "title": "1 Introduction", "text": "x"}],
            "fulltext": (
                "Attention Is All You Need\n\nAshish Vaswani, Noam Shazeer\n\n"
                "Abstract\n\nThe dominant sequence transduction models are based "
                "on recurrent networks and attention mechanisms."
            ),
            "page_map": [], "meta": {}, "references": [], "provenance": {},
        },
        model="text-layer", ir_json="{}",
    )
    client = TestClient(_app(tmp_path, store))
    before = {item["document_id"]: item
              for item in client.get("/api/documents").json()}
    assert before["paper-old"]["headline"] == "old-filename"

    body = client.post("/api/papers/paper-old/metadata/extract").json()
    assert body["meta"]["title"] == "Attention Is All You Need"
    after = {item["document_id"]: item
             for item in client.get("/api/documents").json()}
    assert after["paper-old"]["headline"] == "Attention Is All You Need"


def test_import_metadata_survives_a_store_reload(tmp_path):
    root = tmp_path / "store"
    store = FileDocumentStore(root)
    client = TestClient(_app(tmp_path, store))
    status = _imported_paper(client, tmp_path)
    document_id = status["document_id"]
    view_before = client.get(f"/api/papers/{document_id}/view").json()

    reopened = FileDocumentStore(root)
    reopened_client = TestClient(_app(tmp_path, reopened))
    assert reopened_client.get(
        f"/api/papers/{document_id}/metadata").json()["meta"] == view_before["meta"]
    assert reopened_client.get(
        f"/api/papers/{document_id}/view").json() == view_before


def test_reference_status_keeps_raw_text_and_never_fabricates_a_link(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)
    document_id = status["document_id"]

    reference = client.get(f"/api/papers/{document_id}/view").json()["references"][0]
    assert reference["raw"].startswith("[1] Foo et al. 2020")
    assert reference["notes"], "an unparsed field keeps its explicit status"
    assert "authors-unparsed" in reference["notes"]
    assert reference["doi"] == ""
    assert reference["resolved_document_id"] == ""


# ---------------------------------------------------------------------------
# AC2: historical re-extraction (single + batch), idempotent, manual-safe
# ---------------------------------------------------------------------------

def test_reextract_is_idempotent_and_preserves_manual_fields(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)
    document_id = status["document_id"]

    # Y1 semantics: a partial PATCH only touches the provided field.
    patched = client.patch(f"/api/papers/{document_id}/metadata",
                           json={"meta": {"title": "手工标题"}}).json()
    assert patched["meta"]["title"] == "手工标题"
    assert patched["meta"]["authors"] == ["Alice", "Bob"]

    first = client.post(f"/api/papers/{document_id}/metadata/extract").json()
    assert first["meta"]["title"] == "手工标题"
    assert first["extraction"]["preserved"] == ["title"]
    assert first["meta"]["authors"] == ["Alice", "Bob"]
    assert first["meta_provenance"]["title"]["source"] == "manual"

    second = client.post(f"/api/papers/{document_id}/metadata/extract").json()
    assert second["meta"] == first["meta"]
    assert second["meta_provenance"] == first["meta_provenance"]
    assert second["references"] == first["references"]


def test_batch_backfill_covers_only_papers_and_counts_statuses(tmp_path):
    store = FileDocumentStore(tmp_path / "store")
    client = TestClient(_app(tmp_path, store))
    status = _imported_paper(client, tmp_path, TEXT_PAGES)
    other = _imported_paper(client, tmp_path, NO_REFS_PAGES)
    store.save_document(
        document_id="note-1", title="笔记", source_job_id="job-note",
        model="fixture", markdown="# note\n", ir_json=json.dumps({"blocks": []}),
        original_path="", original_ext=".jpg", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={},
    )

    body = client.post("/api/papers/extract-metadata", json={}).json()
    ids = {item["document_id"] for item in body["results"]}
    assert body["total"] == 2 and "note-1" not in ids
    assert body["counts"]["ok"] == 2
    assert ids == {status["document_id"], other["document_id"]}

    filtered = client.post("/api/papers/extract-metadata",
                           json={"document_ids": [status["document_id"]]}).json()
    assert [item["document_id"] for item in filtered["results"]] == [
        status["document_id"]]


def test_batch_isolates_a_failing_item(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected extractor failure")

    monkeypatch.setattr(papers_extract, "extract_and_persist", _boom)
    body = client.post("/api/papers/extract-metadata", json={}).json()
    assert body["counts"]["failed"] == body["total"] >= 1
    assert all(item["status"] == "failed" for item in body["results"])
    # the stored slots are untouched by a failed retry
    assert client.get(
        f"/api/papers/{status['document_id']}/metadata").json()["meta"]["title"] \
        == "A Study of Things"


def test_import_survives_a_failing_metadata_pass(tmp_path, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected extractor failure")

    monkeypatch.setattr(papers_extract, "run_extraction", _boom)
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)   # import still succeeds
    assert status["meta_status"] == "failed"
    assert "injected extractor failure" in status["meta_error"]
    result = client.get(f"/api/papers/{status['paper_id']}/result").json()
    assert result["meta_status"] == "failed"
    assert result["meta"]["title"] == "" and result["sections"]


def test_missing_evidence_fields_stay_empty_and_explained(tmp_path):
    store = FileDocumentStore(tmp_path / "store")
    store.save_paper_document(
        document_id="paper-body", title="body", markdown="# body\n",
        paper={"source": "text-layer", "sections": [
            {"level": 1, "title": "1 Introduction", "text": "Body."}],
            "fulltext": "we discuss results and methods in the following sections "
                        "with more detail about the work and its evaluation.",
            "page_map": [], "meta": {}, "references": [], "provenance": {}},
        model="text-layer", ir_json="{}",
    )
    client = TestClient(_app(tmp_path, store))
    body = client.post("/api/papers/paper-body/metadata/extract").json()
    # No evidence for year/DOI/venue/authors must not become a guess.
    assert body["meta"]["year"] is None and body["meta"]["doi"] == ""
    assert body["meta"]["venue"] == "" and body["meta"]["authors"] == []
    assert body["references"] == []
    assert "year-not-found" in body["notes"]
    assert "venue-not-found" in body["notes"]
    assert body["extraction"]["status"] != "failed"


# ---------------------------------------------------------------------------
# AC5: hooks into the Y1/Y5 fixes already merged into main
# ---------------------------------------------------------------------------

def test_reflowed_byline_keeps_the_abstract_out_of_the_authors(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path, REFLOWED_PAGES)
    meta = client.get(
        f"/api/papers/{status['document_id']}/metadata").json()["meta"]
    assert meta["authors"] == ["Wei Zhang", "Li Chen", "Ming Li"]
    assert meta["abstract"].startswith("Document understanding has attracted")
    assert meta["title"] == "Graph Neural Networks for Document Understanding"


# ---------------------------------------------------------------------------
# Optional GROBID seam (offline: recorded TEI + injected transport)
# ---------------------------------------------------------------------------

def test_grobid_tei_parser_is_a_pure_offline_mapping():
    fields = papers_grobid.parse_tei(TEI_FIXTURE)
    assert fields.title == "Graph Networks in Practice"
    assert fields.authors == ["Ada Lovelace", "Alan Turing"]
    assert fields.year == 2021
    assert fields.venue == "Journal of Graphs"
    assert fields.doi == "10.1234/grobid.2021"
    assert fields.abstract == "Graph networks are studied in practice."
    assert fields.keywords == ["graph networks", "practice"]
    assert fields.references[0]["raw"]
    assert fields.references[0]["title"] == "External Reference One"


def test_grobid_is_unavailable_without_a_transport_or_url(monkeypatch):
    monkeypatch.delenv("GRAPH2NOTE_GROBID_URL", raising=False)
    assert not papers_grobid.is_configured()
    with pytest.raises(papers_grobid.GrobidUnavailable):
        papers_grobid.extract("unused.pdf")


def test_grobid_fills_empty_fields_and_annotates_evidence(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path, TEXT_PAGES)
    document_id = status["document_id"]
    client.app.state.grobid_transport = (
        lambda url, data, timeout: TEI_FIXTURE.encode("utf-8"))

    body = client.post(f"/api/papers/{document_id}/metadata/extract",
                       json={"grobid": True}).json()
    assert body["extraction"]["applied"], "GROBID fills the empty venue/doi"
    assert body["meta"]["doi"] == "10.1234/grobid.2021"
    assert body["meta"]["venue"] == "Journal of Graphs"
    assert body["meta"]["title"] == "A Study of Things"  # deterministic wins
    assert body["meta_provenance"]["doi"]["evidence"] == "grobid:tei"
    assert any(note.startswith("grobid-fields:") for note in body["notes"])
    # deterministic references already exist, so GROBID never replaces them
    assert body["references"][0]["raw"].startswith("[1] Foo")


def test_grobid_reference_fallback_only_when_the_paper_has_none(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path, NO_REFS_PAGES)
    document_id = status["document_id"]
    assert client.get(f"/api/papers/{document_id}/view").json()["references"] == []
    client.app.state.grobid_transport = (
        lambda url, data, timeout: TEI_FIXTURE.encode("utf-8"))

    body = client.post(f"/api/papers/{document_id}/metadata/extract",
                       json={"grobid": True}).json()
    assert [ref["title"] for ref in body["references"]] == ["External Reference One"]
    assert body["references"][0]["resolved_document_id"] is None
    assert "references:grobid" in body["notes"]


def test_grobid_request_degrades_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPH2NOTE_GROBID_URL", raising=False)
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path, TEXT_PAGES)
    document_id = status["document_id"]

    body = client.post(f"/api/papers/{document_id}/metadata/extract",
                       json={"grobid": True}).json()
    assert body["extraction"]["status"] == "ok"
    assert "grobid-unavailable:not-configured" in body["notes"]
    assert body["meta"]["title"] == "A Study of Things"


# ---------------------------------------------------------------------------
# Import job surface carries the extraction status (separate from `done`)
# ---------------------------------------------------------------------------

def test_job_summary_and_result_expose_the_metadata_status(tmp_path):
    client = TestClient(_app(tmp_path))
    status = _imported_paper(client, tmp_path)
    listing = client.get("/api/papers").json()
    entry = next(item for item in listing
                 if item["paper_id"] == status["paper_id"])
    assert entry["meta_status"] == "ok"


def test_import_job_json_roundtrip_keeps_the_metadata_status(tmp_path):
    from graph2note.papers.pipeline import PaperJob

    job = PaperJob(paper_id="pdf-x", filename="x.pdf")
    job.meta_status = "failed"
    job.meta_error = "boom"
    restored = PaperJob.from_dict(job.to_dict())
    assert restored.meta_status == "failed" and restored.meta_error == "boom"
