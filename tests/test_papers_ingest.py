"""Offline tests for the SPW I-track P1 paper ingest pipeline.

Everything here is deterministic and offline:

- fixtures are small synthetic PDFs built with PyMuPDF (a born-digital PDF with
  a real text layer, and an image-only "scan" with no text layer);
- the section splitter is driven both through the PDF text layer and through
  synthetic ``TextLine`` objects, so its heuristics are replayable without a
  PDF at all;
- the VLM fallback is exercised through the injectable ``router_factory`` with
  recorded golden content — no gateway call and no network;
- the text-layer path is asserted to make **zero** model calls (the injected
  router factory raises if it is ever constructed).

PDF-dependent tests skip cleanly when PyMuPDF is unavailable.
"""

import io
import json
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from graph2note import papers  # noqa: E402
from graph2note import pdflib  # noqa: E402
from graph2note.papers import structure, textlayer  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore, SessionDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# fixtures: synthetic PDFs (deterministic, no network)
# ---------------------------------------------------------------------------

# A small but realistic two-page born-digital paper: title, abstract, numbered
# sections (1 / 2 / 2.1) and a reference list with named headings.
PAPER_PAGES = [
    [
        ("A Study of Things", 18.0),
        ("Alice, Bob", 10.0),
        ("Abstract", 13.0),
        ("We study things deeply and report a long series of measurements", 10.0),
        ("that together describe the behaviour of the system we built.", 10.0),
        ("Our contributions are threefold and each is supported by evidence.", 10.0),
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


def _text_pdf(pages=None):
    """Build a born-digital PDF; return ``(bytes, exact page texts)``."""
    pages = PAPER_PAGES if pages is None else pages
    doc = pymupdf.open()
    expected = []
    for entries in pages:
        page = doc.new_page()
        y = 90.0
        lines = []
        for text, size in entries:
            page.insert_text((72, y), text, fontsize=size)
            y += size + 10
            lines.append(text)
        expected.append("\n".join(lines) + "\n")
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue(), expected


def _scan_pdf(page_count=2):
    """Image-only PDF (no text layer) — the VLM-fallback trigger."""
    np = pytest.importorskip("numpy")
    PILImage = pytest.importorskip("PIL.Image")
    doc = pymupdf.open()
    for index in range(page_count):
        rng = np.random.default_rng(100 + index)
        arr = np.full((320, 440, 3), 250, np.uint8)
        for row in range(3 + index):
            y = 40 + row * 70
            x = int(rng.integers(20, 140))
            arr[y:y + 6, x:x + int(rng.integers(80, 240)), :] = 20
        image = PILImage.fromarray(arr)
        page = doc.new_page(width=440, height=320)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        page.insert_image(page.rect, stream=buffer.getvalue())
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _stub_router_factory(calls=None, content=GOLDEN, fail=False):
    """Offline router factory: records calls, returns recorded golden IR."""
    calls = calls if calls is not None else []

    def caller(image_path, model, recover=False):
        calls.append(str(image_path))
        if fail:
            raise RuntimeError("injected parse failure")
        return content, {}

    def factory(image_path, model):
        return RouteARouter(model, caller=caller, max_retries=1)

    return factory


def _boom_factory(*_args, **_kwargs):
    raise AssertionError("the text-layer path must never construct a router")


def _lines(entries):
    """Build ordered TextLine objects from ``(text, size)`` / ``(text, size, page)``."""
    out = []
    for index, entry in enumerate(entries):
        text, size = entry[0], entry[1]
        page = entry[2] if len(entry) > 2 else 0
        out.append(textlayer.TextLine(
            page_index=page, text=text, size=size, order=index))
    return out


def _read_layer(data):
    """Extract the text layer of in-memory PDF bytes (no temp file needed)."""
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        return textlayer.extract_text_layer(doc)
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# AC1: text layer direct extraction (no VLM, exact fixture text)
# ---------------------------------------------------------------------------


def test_text_layer_extraction_matches_fixture_text():
    data, expected = _text_pdf()
    layer = _read_layer(data)
    assert layer.page_count == len(expected) == 2
    for page, want in zip(layer.pages, expected):
        assert page.text == want
    # flattened full text preserves every line in reading order
    flat = layer.fulltext
    for line in [entry[0] for page in PAPER_PAGES for entry in page]:
        assert line in flat


def test_text_layer_records_font_size_and_bold_per_line():
    data, _ = _text_pdf()
    layer = _read_layer(data)
    by_text = {line.text: line for line in layer.lines}
    assert by_text["A Study of Things"].size == pytest.approx(18.0)
    assert by_text["1 Introduction"].size == pytest.approx(15.0)
    assert by_text["Alice, Bob"].size == pytest.approx(10.0)
    assert [line.order for line in layer.lines] == list(range(len(layer.lines)))


def test_read_text_layer_from_path(tmp_path):
    data, expected = _text_pdf()
    path = tmp_path / "paper.pdf"
    path.write_bytes(data)
    layer = textlayer.read_text_layer(path)
    assert layer.pages[0].text == expected[0]


# ---------------------------------------------------------------------------
# AC2: deterministic section splitting (offline, replayable)
# ---------------------------------------------------------------------------


def test_split_sections_from_text_lines_numbered_and_named():
    lines = _lines([
        ("A Study of Things", 18.0, 0),
        ("Alice, Bob", 10.0, 0),
        ("Abstract", 13.0, 0),
        ("We study things deeply.", 10.0, 0),
        ("1 Introduction", 15.0, 0),
        ("Papers are nice to read.", 10.0, 0),
        ("2 Method", 15.0, 1),
        ("2.1 Overview", 12.0, 1),
        ("We do stuff carefully.", 10.0, 1),
        ("References", 15.0, 1),
        ("[1] Foo et al. 2020.", 10.0, 1),
    ])
    sections = structure.split_sections(lines)
    assert [(s.level, s.title) for s in sections] == [
        (1, "A Study of Things"),
        (1, "Abstract"),
        (1, "Introduction"),
        (1, "Method"),
        (2, "Overview"),
        (1, "References"),
    ]
    # page ranges are 0-based and trace back to the source pages
    by_title = {s.title: s for s in sections}
    assert (by_title["Introduction"].page_start, by_title["Introduction"].page_end) == (0, 0)
    assert (by_title["Method"].page_start, by_title["Method"].page_end) == (1, 1)
    assert (by_title["References"].page_start, by_title["References"].page_end) == (1, 1)
    assert by_title["Method"].text == ""
    assert by_title["Overview"].text == "We do stuff carefully."


def test_split_sections_page_range_spans_pages():
    lines = _lines([
        ("1 Introduction", 15.0, 0),
        ("First part on page one.", 10.0, 0),
        ("Second part continues on page two.", 10.0, 1),
        ("2 Method", 15.0, 1),
        ("Method body.", 10.0, 1),
    ])
    sections = structure.split_sections(lines)
    intro = sections[0]
    assert intro.title == "Introduction"
    assert (intro.page_start, intro.page_end) == (0, 1)
    assert "page two" in intro.text


def test_split_sections_front_matter_kept_with_empty_title():
    lines = _lines([
        ("Some paper title", 10.0, 0),  # body size + unnumbered: front matter
        ("Author One, Author Two", 10.0, 0),
        ("1 Introduction", 15.0, 0),
        ("Body.", 10.0, 0),
    ])
    sections = structure.split_sections(lines)
    assert sections[0].title == ""  # 前置内容（标题/作者）不丢
    assert "Author One" in sections[0].text
    assert "Some paper title" in sections[0].text
    assert sections[1].title == "Introduction"


def test_large_unnumbered_title_line_is_a_heading():
    lines = _lines([
        ("Some paper title", 18.0, 0),
        ("Author One, Author Two", 10.0, 0),
        ("1 Introduction", 15.0, 0),
        ("Body.", 10.0, 0),
    ])
    sections = structure.split_sections(lines)
    assert sections[0].title == "Some paper title"
    assert "Author One" in sections[0].text


def test_split_sections_is_replayable_for_any_input_order():
    lines = _lines([
        ("1 Introduction", 15.0, 0),
        ("Body text.", 10.0, 0),
        ("References", 15.0, 1),
        ("[1] Foo.", 10.0, 1),
    ])
    first = structure.split_sections(lines)
    shuffled = structure.split_sections(list(reversed(lines)))
    assert [s.model_dump() for s in first] == [s.model_dump() for s in shuffled]
    assert [s.model_dump() for s in structure.split_sections(lines)] == \
        [s.model_dump() for s in first]


def test_split_sections_empty_input():
    assert structure.split_sections([]) == []


def test_font_size_heading_detected_without_numbering():
    lines = _lines([
        ("Introduction", 16.0, 0),
        ("Body text that is much longer than the heading line.", 10.0, 0),
        ("Related Work", 14.0, 0),
        ("More body text.", 10.0, 0),
    ])
    sections = structure.split_sections(lines)
    assert [(s.level, s.title) for s in sections] == [
        (1, "Introduction"),
        (2, "Related Work"),
    ]


def test_body_size_sentence_is_not_a_heading():
    lines = _lines([
        ("1 Introduction", 15.0, 0),
        ("1 the results are better than the baseline. Next we discuss why.", 10.0, 0),
        ("A normal body sentence that ends with a period.", 10.0, 0),
    ])
    sections = structure.split_sections(lines)
    assert [s.title for s in sections] == ["Introduction"]
    assert "the results are better" in sections[0].text


def test_canonical_chinese_headings_detected():
    lines = _lines([
        ("1 引言", 15.0, 0),
        ("正文内容。", 10.0, 0),
        ("参考文献", 15.0, 1),
        ("[1] 张三. 2020.", 10.0, 1),
    ])
    sections = structure.split_sections(lines)
    assert [s.title for s in sections] == ["引言", "参考文献"]
    assert sections[0].level == 1


def test_body_size_is_character_weighted_mode():
    lines = _lines([
        ("Heading", 20.0, 0),
        ("Short body sentence.", 10.0, 0),
        ("A much longer body sentence that clearly dominates the page.", 10.0, 0),
    ])
    assert structure.body_size(lines) == pytest.approx(10.0)
    reasons = [h.reason for h in structure.detect_headings(lines)]
    assert reasons == ["size"]


# ---------------------------------------------------------------------------
# AC3: deterministic text-layer / scan decision
# ---------------------------------------------------------------------------


def test_decide_text_layer_uses_text_layer_for_born_digital_pdf():
    data, _ = _text_pdf()
    decision = textlayer.decide_text_layer(_read_layer(data))
    assert decision.use_text_layer is True
    assert decision.source == "text-layer"
    assert decision.total_chars > 0 and decision.text_pages == 2
    assert decision.as_dict()["source"] == "text-layer"


def test_decide_text_layer_falls_back_for_scan():
    layer = _read_layer(_scan_pdf())
    decision = textlayer.decide_text_layer(layer)
    assert decision.use_text_layer is False
    assert decision.source == "vlm"
    assert decision.total_chars == 0 and decision.text_pages == 0


def test_decide_text_layer_boundaries_are_explicit_and_offline():
    layer = _read_layer(_text_pdf()[0])
    # raising the total-character floor flips the decision to the VLM fallback
    strict = textlayer.decide_text_layer(layer, min_total_chars=10 ** 6)
    assert strict.source == "vlm" and "阈值" in strict.reason
    # requiring every page to carry text rejects a partially-textual document
    partial = textlayer.decide_text_layer(layer, min_text_page_ratio=1.5)
    assert partial.source == "vlm" and "占比" in partial.reason
    # raising the per-page floor classifies the thin pages as non-textual
    per_page = textlayer.decide_text_layer(layer, min_page_chars=10 ** 6)
    assert per_page.source == "vlm" and per_page.text_pages == 0


def test_scan_pdf_has_no_text_layer():
    layer = _read_layer(_scan_pdf())
    assert layer.page_count == 2
    assert layer.char_count == 0
    assert layer.fulltext == ""


# ---------------------------------------------------------------------------
# pipeline: text-layer path (zero LLM) + VLM fallback (injectable router)
# ---------------------------------------------------------------------------


def test_process_paper_text_layer_zero_llm(tmp_path):
    data, expected = _text_pdf()
    store = FileDocumentStore(tmp_path / "store")
    calls = []
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="study.pdf")

    result = papers.process_paper(
        job, pdf_bytes=data, store=store,
        router_factory=lambda *a, **k: calls.append(a) or _boom_factory(),
        model="glm-5.3-flash",
    )

    assert result.status == "done"
    assert result.source == "text-layer"
    assert calls == []                      # zero model calls
    assert result.document_id == papers.paper_document_id(job.paper_id)

    # durable original PDF at pdflib's page-render location (source-page seam)
    assert pdflib.original_pdf_path(store, job.paper_id).is_file()

    payload = store.get_paper_payload(result.document_id)
    assert payload["source"] == "text-layer"
    assert payload["fulltext"] == "\n\n".join(page.strip() for page in expected).strip()
    assert [line for line in payload["fulltext"].splitlines() if line.strip()] == [
        line for page in expected for line in page.splitlines() if line.strip()
    ]
    assert [s["title"] for s in payload["sections"]] == [
        "A Study of Things", "Abstract", "Introduction", "Method",
        "Overview", "References",
    ]
    assert payload["provenance"]["source"] == "text-layer"
    assert payload["provenance"]["pdf_id"] == job.paper_id
    assert payload["provenance"]["decision"]["source"] == "text-layer"
    # P2 slots exist but stay empty
    assert payload["meta"]["title"] == "" and payload["meta"]["source"] == "none"
    assert payload["references"] == []


def test_process_paper_commits_paper_document_with_provenance(tmp_path):
    data, _ = _text_pdf()
    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="study.pdf")
    result = papers.process_paper(job, pdf_bytes=data, store=store)

    record = store.get_document(result.document_id)
    assert record["doc_kind"] == "paper"
    assert record["pdf_id"] == job.paper_id          # issue 08/09 mapping
    assert record["source_pdf"].endswith("original.pdf")
    assert record["page_index"] == 0 and record["page_number"] == 1
    assert len(record["versions"]) == 1
    assert record["versions"][0]["provenance"] == "paper-text-layer"
    # the paper document is a normal library document: listed, searchable text
    listed = {item["document_id"]: item for item in store.list_documents()}
    assert listed[result.document_id]["doc_kind"] == "paper"
    assert "Introduction" in store.get_document(result.document_id)["current_markdown"]


def test_process_paper_result_payload_shape(tmp_path):
    data, _ = _text_pdf()
    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="study.pdf")
    result = papers.process_paper(job, pdf_bytes=data, store=store)

    payload = papers.result_payload(result, store)
    assert payload["doc_kind"] == "paper"
    assert payload["source"] == "text-layer"
    assert payload["document_id"] == result.document_id
    assert payload["pages"][0]["page_number"] == 1
    assert payload["source_page_url"].endswith("/source-page")
    assert payload["original_url"] == f"/api/papers/{job.paper_id}/original"
    assert payload["sections"] and payload["fulltext"]


def test_process_paper_vlm_fallback_uses_router_factory(tmp_path):
    data = _scan_pdf(2)
    store = FileDocumentStore(tmp_path / "store")
    calls = []
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="scan.pdf")

    result = papers.process_paper(
        job, pdf_bytes=data, store=store,
        router_factory=_stub_router_factory(calls), model="glm-5.3-flash",
        page_timeout=60,
    )

    assert result.status == "done"
    assert result.source == "vlm"
    assert calls, "the fallback must go through the injected router factory"
    assert result.document_id == papers.paper_document_id(job.paper_id)

    payload = store.get_paper_payload(result.document_id)
    assert payload["source"] == "vlm"
    assert payload["provenance"]["source"] == "vlm"
    assert payload["provenance"]["page_document_ids"] == result.page_documents
    assert result.page_documents, "VLM fallback commits per-page documents"
    assert payload["sections"], "fallback assembles one section per parsed page"

    # the per-page documents keep issue-08 provenance under the same pdf_id
    for document_id in result.page_documents:
        record = store.get_document(document_id)
        assert record["pdf_id"] == job.paper_id
        assert record["page_index"] is not None


def test_process_paper_vlm_fallback_without_pages_fails(tmp_path):
    data = _scan_pdf(1)
    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="scan.pdf")
    result = papers.process_paper(
        job, pdf_bytes=data, store=store,
        router_factory=_stub_router_factory(fail=True), model="glm-5.3-flash",
        page_timeout=60,
    )
    assert result.status == "failed"
    assert result.error_kind == "vlm_empty"
    assert result.document_id is None


def test_process_paper_resume_without_bytes_fails_cleanly(tmp_path):
    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id="pdf-0000000000000000", filename="gone.pdf")
    result = papers.process_paper(job, pdf_bytes=None, store=store)
    assert result.status == "failed"
    assert "原 PDF 缺失" in result.error
    assert result.error_kind == "failed"


def test_process_paper_corrupt_pdf_fails_with_kind(tmp_path):
    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id="pdf-1111111111111111", filename="bad.pdf")
    result = papers.process_paper(job, pdf_bytes=b"not-a-pdf", store=store)
    assert result.status == "failed"
    assert result.error_kind in ("corrupt", "unreadable")


# ---------------------------------------------------------------------------
# durable job state (issue 09 semantics reused)
# ---------------------------------------------------------------------------


def test_paper_job_roundtrip_and_interrupted_reconcile(tmp_path):
    job = papers.PaperJob(paper_id="pdf-abc", filename="p.pdf", work_dir=str(tmp_path))
    with job.lock:
        job.status = "processing"
        job.total_pages = 3
        job.source = "text-layer"
    papers.save_job(job)
    loaded = papers.load_job(tmp_path)
    assert loaded is not None
    assert loaded.total_pages == 3 and loaded.source == "text-layer"
    assert loaded.mark_interrupted() is True
    assert loaded.status == "interrupted" and loaded.error_kind == "interrupted"
    assert loaded.mark_interrupted() is False  # idempotent


def test_load_jobs_scans_durable_paper_state(tmp_path):
    store = FileDocumentStore(tmp_path / "store")
    directory = papers.paper_dir(store, "pdf-xyz")
    directory.mkdir(parents=True)
    job = papers.PaperJob(paper_id="pdf-xyz", filename="p.pdf", work_dir=str(directory))
    with job.lock:
        job.status = "queued"
    papers.save_job(job)
    jobs = papers.load_jobs(store)
    assert [j.paper_id for j in jobs] == ["pdf-xyz"]
    assert jobs[0].status == "interrupted"


# ---------------------------------------------------------------------------
# AC4: append-only store extension (existing behaviour unchanged)
# ---------------------------------------------------------------------------


def test_save_document_behaviour_is_unchanged(tmp_path):
    """The pre-existing commit path gains no `doc_kind` and keeps its versions."""
    for store in (SessionDocumentStore(tmp_path / "s"), FileDocumentStore(tmp_path / "f")):
        record = store.save_document(
            document_id="plain-doc", title="Plain", source_job_id="job-1",
            model="m", markdown="hello", ir_json="{}",
            original_path=None, original_ext=".png",
            preprocessed_path=None, preprocessed_raw_path=None,
            assets_dir=None, timing_json={},
        )
        assert record["document_id"] == "plain-doc"
        assert "doc_kind" not in record
        assert store.get_paper_payload("plain-doc") is None
        assert len(store.get_document("plain-doc")["versions"]) == 1


def test_save_paper_document_is_durable_across_store_instances(tmp_path):
    root = tmp_path / "store"
    store = FileDocumentStore(root)
    payload = {
        "schema_version": 1, "source": "text-layer",
        "sections": [{"level": 1, "title": "Intro", "text": "body",
                      "page_start": 0, "page_end": 0}],
        "fulltext": "body", "page_map": [], "meta": {}, "references": [],
        "provenance": {"source": "text-layer", "pdf_id": "pdf-1"},
    }
    store.save_paper_document(
        document_id="pdf-1-paper", title="t", markdown="# t\n", paper=payload,
        model="text-layer", ir_json="{}", original_path=None, original_ext=".pdf",
    )
    assert store.get_document("pdf-1-paper")["doc_kind"] == "paper"
    assert (store._doc_dir("pdf-1-paper") / "paper.json").is_file()

    reopened = FileDocumentStore(root)
    assert reopened.get_document("pdf-1-paper")["doc_kind"] == "paper"
    restored = reopened.get_paper_payload("pdf-1-paper")
    assert restored["sections"][0]["title"] == "Intro"
    summaries = reopened.list_documents()
    assert summaries[0]["doc_kind"] == "paper"


def test_update_paper_payload_merges_p2_slots(tmp_path):
    """P2 (metadata/references) can fill its slots without re-committing."""
    store = SessionDocumentStore(tmp_path / "s")
    store.save_paper_document(
        document_id="d1", title="t", markdown="x",
        paper={"source": "text-layer", "meta": {}, "references": []},
    )
    updated = store.update_paper_payload("d1", {
        "meta": {"title": "Real Title", "source": "text-layer"},
        "references": [{"raw": "[1] Foo"}],
    })
    assert updated["doc_kind"] == "paper"
    payload = store.get_paper_payload("d1")
    assert payload["meta"]["title"] == "Real Title"
    assert payload["references"][0]["raw"] == "[1] Foo"
    # unknown documents never grow a paper payload
    assert store.update_paper_payload("nope", {"meta": {}}) is None


# ---------------------------------------------------------------------------
# AC5: reuse pdflib limits / identities (no re-implementation)
# ---------------------------------------------------------------------------


def test_validate_paper_reuses_pdflib_limits(monkeypatch):
    data, _ = _text_pdf()
    original_size = pdflib.MAX_PDF_SIZE
    assert papers.validate_paper(data, "paper.pdf") == 2

    with pytest.raises(pdflib.PdfError) as wrong:
        papers.validate_paper(data, "paper.txt")
    assert wrong.value.kind == "wrong_type"

    with pytest.raises(pdflib.PdfError) as empty:
        papers.validate_paper(b"", "paper.pdf")
    assert empty.value.kind == "corrupt"

    with pytest.raises(pdflib.PdfError) as corrupt:
        papers.validate_paper(b"not-a-pdf", "paper.pdf")
    assert corrupt.value.kind == "corrupt"

    monkeypatch.setattr(pdflib, "MAX_PDF_SIZE", 10)
    with pytest.raises(pdflib.PdfError) as large:
        papers.validate_paper(data, "paper.pdf")
    assert large.value.kind == "too_large"

    monkeypatch.setattr(pdflib, "MAX_PDF_SIZE", original_size)
    monkeypatch.setattr(pdflib, "MAX_PDF_PAGES", 1)
    with pytest.raises(pdflib.PdfError) as pages_error:
        papers.validate_paper(data, "paper.pdf")
    assert pages_error.value.kind == "too_many_pages"


def test_stable_paper_id_reuses_pdf_content_hash():
    data, _ = _text_pdf()
    assert papers.stable_paper_id(data) == pdflib.stable_pdf_id(data)
    assert papers.paper_document_id("pdf-x") == "pdf-x-paper"


def test_render_paper_markdown_is_deterministic():
    sections = [
        papers.PaperSection(level=1, title="Introduction", text="Body.",
                            page_start=0, page_end=0),
        papers.PaperSection(level=2, title="Overview", text="More.",
                            page_start=1, page_end=1),
    ]
    markdown = papers.render_paper_markdown("My Paper", sections)
    assert markdown.startswith("# My Paper")
    assert "## Introduction" in markdown and "### Overview" in markdown
    assert markdown == papers.render_paper_markdown("My Paper", sections)


def test_paper_payload_schema_is_spec_shaped():
    payload = papers.PaperPayload(
        source="text-layer",
        provenance=papers.PaperProvenance(source="text-layer"),
    )
    dumped = payload.as_dict()
    assert set(dumped) == {
        "schema_version", "source", "sections", "fulltext", "page_map",
        "meta", "references", "provenance",
    }
    assert set(dumped["meta"]) == {
        "title", "authors", "year", "venue", "doi", "abstract", "keywords",
        "source",
    }
    assert set(papers.PaperSection(level=1, title="t", text="x").model_dump()) == {
        "level", "title", "text", "page_start", "page_end",
    }
    # the contract is strict: an unknown field is rejected (no silent drift)
    with pytest.raises(Exception):
        papers.PaperSection(level=1, title="t", text="x", unknown=1)


def test_sections_json_roundtrip_through_payload(tmp_path):
    data, _ = _text_pdf()
    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="study.pdf")
    result = papers.process_paper(job, pdf_bytes=data, store=store)
    payload = store.get_paper_payload(result.document_id)
    sections = [papers.PaperSection(**section) for section in payload["sections"]]
    assert [s.title for s in sections] == [s["title"] for s in payload["sections"]]
    assert json.loads(json.dumps(payload))["source"] == "text-layer"
