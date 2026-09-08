"""Best-effort missing-page detection (issue 09, FR-023)."""

from graph2note.ingest import (
    Page, detect_missing, SequencePageNumberExtractor,
    report_to_parse_inputs, IngestReport, PageCluster,
)


def _page(idx, num=None, source="a.pdf"):
    return Page(source, idx, f"/tmp/{source}{idx}.png", 400, 500, 150,
                page_number=num)


def test_gap_in_page_numbers_triggers_alert():
    pages = [_page(0, 1), _page(1, 2), _page(2, 3), _page(3, 5), _page(4, 6)]
    kinds = {a.kind for a in detect_missing(pages)}
    assert "gap" in kinds
    gap = next(a for a in detect_missing(pages) if a.kind == "gap")
    assert gap.missing_numbers == [4]
    assert gap.observed_numbers == [1, 2, 3, 5, 6]


def test_no_page_numbers_does_not_claim_complete():
    pages = [_page(i) for i in range(4)]  # no page_number
    alerts = detect_missing(pages)
    assert any(a.kind == "no_clue" for a in alerts)
    assert not any(a.kind == "gap" for a in alerts)


def test_duplicate_hint_when_number_repeats():
    pages = [_page(0, 2), _page(1, 2), _page(2, 3)]
    assert any(a.kind == "duplicate_hint" for a in detect_missing(pages))


def test_sequence_extractor_is_continuity_only():
    # positional only: pages 1..N, so no gap can be reported between files
    ex = SequencePageNumberExtractor()
    pages = [_page(i) for i in range(3)]
    numbers = [ex(p) for p in pages]
    assert numbers == [1, 2, 3]


def test_empty_pages_no_clue():
    alerts = detect_missing([])
    assert alerts and alerts[0].kind == "no_clue"


def test_adapter_flattens_unique_pages_with_versions():
    p1 = _page(0, 1)
    p2 = Page("scanB.pdf", 0, "/tmp/b.png", 400, 500, 150, page_number=1)
    cluster = PageCluster(0, [p1, p2], "phash", 4)
    rep = cluster.representative
    report = IngestReport(pages=[p1, p2], clusters=[cluster])
    inputs = report_to_parse_inputs(report)
    assert len(inputs) == 1
    assert inputs[0].source_pdf == rep.source_pdf
    assert inputs[0].page_number == 1
    assert len(inputs[0].candidate_versions) == 1
    assert inputs[0].traceable_id.startswith(rep.source_pdf)