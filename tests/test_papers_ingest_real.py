"""Offline regression over **real** paper text-layer fixtures (SPW I 轨 / Y4).

The P1 suite (``tests/test_papers_ingest.py``) is entirely synthetic: a
hand-built PyMuPDF page and hand-written ``TextLine`` lists.  This module lifts
that to *real* born-digital papers: each fixture directory under
``tests/fixtures/papers/real/<key>/`` holds

- ``lines.jsonl`` — the full PyMuPDF text-layer export (page / size / bold /
  text per line) of one real arXiv paper;
- ``front.txt`` — the exact first-page text of the same PDF;
- ``references.txt`` — the located reference section text;
- ``expected.json`` — provenance/license, layout class, and the per-paper
  expectations (including the failures we knowingly accept).

Everything runs offline: the fixtures are frozen text, the text-layer decision
and the section splitter are pure functions, and the one pipeline test rebuilds
a tiny in-memory PDF from the frozen lines and injects a router factory that
raises if the text-layer path ever tried to call a model.

Known degradations are asserted on purpose (see each ``expected.json`` and
``README.md``); fixing the parser must update the fixture, never silently
rewrite it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

import graph2note.papers as papers  # noqa: E402
from graph2note.papers import structure, textlayer  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402

REAL = Path(__file__).parent / "fixtures" / "papers" / "real"

KEYS = sorted(
    path.name for path in REAL.iterdir()
    if path.is_dir() and (path / "expected.json").is_file()
)


def _expected(key: str) -> dict:
    return json.loads((REAL / key / "expected.json").read_text(encoding="utf-8"))


def _lines(key: str) -> list[textlayer.TextLine]:
    """Rebuild ordered ``TextLine`` records from the frozen text-layer export."""
    out: list[textlayer.TextLine] = []
    for order, raw in enumerate((REAL / key / "lines.jsonl").read_text(encoding="utf-8").split("\n")):
        if not raw.strip():
            continue
        entry = json.loads(raw)
        out.append(textlayer.TextLine(
            page_index=entry["p"], text=entry["t"], size=entry["s"],
            bold=entry["b"], order=order,
        ))
    return out


def _layer(key: str) -> textlayer.TextLayer:
    lines = _lines(key)
    pages: dict[int, list[textlayer.TextLine]] = {}
    for line in lines:
        pages.setdefault(line.page_index, []).append(line)
    return textlayer.TextLayer(pages=[
        textlayer.PageText(
            page_index=index,
            text="\n".join(line.text for line in pages[index]),
            lines=pages[index],
        )
        for index in sorted(pages)
    ])


def _forbid_router(*_args, **_kwargs):
    raise AssertionError("P1 text-layer path must never construct a router")


def _rebuild_pdf(key: str, path: Path, *, max_pages: int = 2) -> None:
    """Rebuild a tiny born-digital PDF from frozen real lines (no network)."""
    doc = pymupdf.open()
    by_page: dict[int, list[textlayer.TextLine]] = {}
    for line in _lines(key):
        if line.page_index < max_pages:
            by_page.setdefault(line.page_index, []).append(line)
    for page_index in sorted(by_page):
        page = doc.new_page()
        y = 60.0
        for line in by_page[page_index]:
            size = max(4.0, min(float(line.size or 10.0), 20.0))
            # base-14 fonts are latin-1 only; replace the few math glyphs (the
            # density/heading signals we assert on survive the substitution).
            text = line.text.encode("latin-1", "replace").decode("latin-1")
            page.insert_text((40, y), text, fontsize=size)
            y += size + 3.0
            if y > 780:
                break
    doc.save(str(path))
    doc.close()


# ---------------------------------------------------------------------------
# fixture integrity / coverage (AC1)
# ---------------------------------------------------------------------------

def test_real_fixture_set_covers_required_layouts():
    assert 3 <= len(KEYS) <= 6, KEYS
    layouts = {_expected(key)["layout"]["kind"] for key in KEYS}
    assert "two-column-conference" in layouts, layouts
    assert {"single-column-arxiv", "single-column-tech-report"} <= layouts, layouts
    for key in KEYS:
        for name in ("front.txt", "lines.jsonl", "references.txt", "expected.json"):
            assert (REAL / key / name).is_file(), (key, name)
        assert (REAL / key / "lines.jsonl").stat().st_size > 0


def test_real_fixture_source_and_license_are_recorded():
    for key in KEYS:
        source = _expected(key)["source"]
        assert source["license"], key
        assert source["arxiv_id"], key
        assert source["source_url"].startswith("https://arxiv.org/"), key
        assert len(source["sha256_16"]) == 16, key
        assert source["pages"] > 0, key


# ---------------------------------------------------------------------------
# P1: text-layer decision + deterministic section splitting (AC3, AC4)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_real_text_layer_is_born_digital(key):
    expected = _expected(key)
    decision = textlayer.decide_text_layer(_layer(key))
    assert expected["p1"]["decision_source"] == "text-layer"
    assert decision.use_text_layer is True
    assert decision.source == "text-layer"
    assert decision.total_pages == expected["p1"]["page_count"]
    assert decision.text_pages == expected["p1"]["text_pages"]
    assert decision.total_chars > 0


@pytest.mark.parametrize("key", KEYS)
def test_real_decision_is_a_pure_offline_function(key):
    layer = _layer(key)
    first = textlayer.decide_text_layer(layer).as_dict()
    second = textlayer.decide_text_layer(_layer(key)).as_dict()
    assert first == second
    assert first["source"] == "text-layer"


@pytest.mark.parametrize("key", KEYS)
def test_real_required_headings_are_detected(key):
    expected = _expected(key)
    sections = structure.split_sections(_lines(key))
    present = {(section.title, section.level) for section in sections}
    for title, level in expected["p1"]["required_headings"]:
        assert (title, level) in present, (key, title, level)
    assert sections, key


@pytest.mark.parametrize("key", KEYS)
def test_real_section_snapshot_documents_degradation(key):
    """Lock the real-layout section count and the known spurious headings.

    The count is large for every real paper because figure/table/axis text is
    promoted to headings; this is the Y4 finding, not a passing state.
    """
    expected = _expected(key)
    sections = structure.split_sections(_lines(key))
    assert len(sections) == expected["p1"]["section_count"]

    titles = {section.title for section in sections}
    evidence = expected["p1"]["front_title_evidence"]
    assert evidence in titles or any(evidence in section.text for section in sections)

    # The paper title must survive somewhere: front matter is never dropped.
    front = [section for section in sections if section.title == ""]
    if front:
        assert front[0].text.strip()

    for spurious in expected["p1"]["spurious_heading_examples"]:
        assert spurious in titles, (key, spurious)


@pytest.mark.parametrize("key", KEYS)
def test_real_section_page_ranges_are_valid(key):
    expected = _expected(key)
    pages = expected["p1"]["page_count"]
    for section in structure.split_sections(_lines(key)):
        assert 0 <= section.page_start <= section.page_end < pages, section


@pytest.mark.parametrize("key", KEYS)
def test_real_text_layer_pipeline_makes_zero_llm_calls(key, tmp_path):
    """AC3: the real text-layer path runs end-to-end without a model call."""
    pdf = tmp_path / "real.pdf"
    _rebuild_pdf(key, pdf, max_pages=2)
    data = pdf.read_bytes()

    store = FileDocumentStore(tmp_path / "store")
    job = papers.PaperJob(paper_id=papers.stable_paper_id(data), filename="paper.pdf")
    result = papers.process_paper(
        job, pdf_bytes=data, store=store,
        router_factory=_forbid_router, model="glm-5.3-flash",
    )

    assert result.status == "done"
    assert result.source == "text-layer"
    payload = store.get_paper_payload(result.document_id)
    assert payload["source"] == "text-layer"
    assert payload["provenance"]["decision"]["source"] == "text-layer"
    assert payload["fulltext"].strip()  # real text actually survived the rebuild


# ---------------------------------------------------------------------------
# AC4: explicitly offline (no socket) — fixtures need no network
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_real_p1_fixtures_are_offline(key, monkeypatch):
    import socket

    def _no_network(*_args, **_kwargs):
        raise AssertionError("P1 real fixtures must not touch the network")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    assert textlayer.decide_text_layer(_layer(key)).use_text_layer is True
    assert structure.split_sections(_lines(key))
