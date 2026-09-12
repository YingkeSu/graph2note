"""Offline unit tests for continuity detection & merge (issue 03).

Covers the pure detector (table driven) and the deterministic merge executor
against a real ``FileDocumentStore`` in a temp dir.  Everything here is offline
and zero-LLM; the API/CLI/UI contracts live in ``tests/test_continuity_api.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note import continuity, evolution
from graph2note.ir import DocumentIR
from graph2note.store import FileDocumentStore

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _ir_json(*blocks: dict) -> str:
    return json.dumps({"document_type": "note", "blocks": list(blocks)},
                      ensure_ascii=False)


def _heading(text: str) -> dict:
    return {"type": "heading", "level": 1, "text": text}


def _para(text: str) -> dict:
    return {"type": "paragraph", "text": text}


def _record(
    document_id: str,
    blocks: list[dict],
    *,
    job: str = "job-1",
    source_pdf: str | None = None,
    page_index: int | None = None,
    page_number: int | None = None,
    pg_hash: str | None = None,
    tags: list[str] | None = None,
    title: str | None = None,
    merged_into: str | None = None,
) -> dict:
    record: dict = {
        "document_id": document_id,
        "title": title or document_id,
        "source_job_id": job,
        "source_pdf": source_pdf,
        "page_index": page_index,
        "page_number": page_number,
        "current_hash": pg_hash,
        "tags": tags or [],
        "versions": [{"version_id": "v1", "ir_json": _ir_json(*blocks)}],
    }
    if merged_into:
        record["merged_into"] = merged_into
    return record


# A's tail continues into B's head ("重叠甲", "重叠乙").
OVERLAP_BLOCKS = [_para("重叠甲"), _para("重叠乙")]
A_BLOCKS = [_heading("章一"), _para("甲"), *OVERLAP_BLOCKS]
B_BLOCKS = [*OVERLAP_BLOCKS, _para("末段")]


# ---------------------------------------------------------------------------
# detector — table driven
# ---------------------------------------------------------------------------


def test_ir_helpers_and_page_positions():
    record = _record("d", A_BLOCKS, source_pdf="lecture.pdf", page_index=3)
    assert continuity.source_key(record) == "lecture.pdf"
    assert continuity.page_position(record) == 3
    assert continuity.page_label(record) == 4
    numbered = _record("d", A_BLOCKS, source_pdf="x.pdf", page_number=7)
    assert continuity.page_position(numbered) == 6
    assert continuity.page_label(numbered) == 7
    assert continuity.document_ir(record).blocks[0].type == "heading"


def test_ir_priority_pdf_id_then_source_pdf_then_job():
    record = {"document_id": "d", "pdf_id": "P1", "source_pdf": "x.pdf",
              "source_job_id": "j"}
    assert continuity.source_key(record) == "P1"
    assert continuity.source_key({"document_id": "d", "source_pdf": "x.pdf",
                                  "source_job_id": "j"}) == "x.pdf"
    assert continuity.source_key({"document_id": "d", "source_job_id": "j"}) == "j"
    assert continuity.source_key({"document_id": "d"}) is None


def test_significant_same_source_adjacent_pages():
    records = [
        _record("p3", A_BLOCKS, source_pdf="lecture.pdf", page_index=2),
        _record("p4", B_BLOCKS, source_pdf="lecture.pdf", page_index=3),
    ]
    pairs = continuity.detect_continuity(records)
    assert [pair["tier"] for pair in pairs] == ["significant"]
    pair = pairs[0]
    assert pair["document_id"] == "p3"
    assert pair["target_id"] == "p4"
    assert pair["order"] == ["p3", "p4"]
    assert pair["evidence_label"] == "同 PDF 第 3–4 页"


def test_significant_same_source_non_adjacent_not_reported():
    records = [
        _record("p3", A_BLOCKS, source_pdf="lecture.pdf", page_index=2),
        _record("p5", B_BLOCKS, source_pdf="lecture.pdf", page_index=4),
    ]
    assert continuity.detect_continuity(records) == []


def test_significant_requires_a_page_order():
    records = [
        _record("a", A_BLOCKS, source_pdf="lecture.pdf"),
        _record("b", B_BLOCKS, source_pdf="lecture.pdf"),
    ]
    assert continuity.detect_continuity(records) == []


def test_different_sources_never_significant():
    records = [
        _record("a", A_BLOCKS, job="job-a", page_index=0),
        _record("b", B_BLOCKS, job="job-b", page_index=1),
    ]
    # no hashes -> no suggested candidate either
    assert continuity.detect_continuity(records) == []


def test_suggested_phash_plus_tail_head_overlap():
    records = [
        _record("a", A_BLOCKS, job="job-a", pg_hash="0" * 16),
        _record("b", B_BLOCKS, job="job-b", pg_hash="0" * 16),
    ]
    pairs = continuity.detect_continuity(records)
    assert [pair["tier"] for pair in pairs] == ["suggested"]
    pair = pairs[0]
    assert pair["order"] == ["a", "b"]
    assert pair["overlap_blocks"] == 2
    assert pair["phash_distance"] == 0
    assert pair["evidence_label"] == "尾首重叠 2 块"
    assert pair["evidence"]["previews"] == ["重叠甲", "重叠乙"]


def test_suggested_direction_is_reversed_when_only_b_tail_matches_a_head():
    blocks_a = [_para("重叠甲"), _para("重叠乙"), _para("尾")]
    blocks_b = [_para("头"), _para("重叠甲"), _para("重叠乙")]
    records = [
        _record("a", blocks_a, job="job-a", pg_hash="0" * 16),
        _record("b", blocks_b, job="job-b", pg_hash="0" * 16),
    ]
    pair = continuity.detect_continuity(records)[0]
    assert pair["tier"] == "suggested"
    assert pair["order"] == ["b", "a"]
    assert pair["document_id"] == "b"
    assert pair["target_id"] == "a"


def test_suggested_requires_both_hash_and_overlap():
    no_overlap = [
        _record("a", [_para("甲")], pg_hash="0" * 16),
        _record("b", [_para("乙")], pg_hash="0" * 16),
    ]
    assert continuity.detect_continuity(no_overlap) == []

    far_hash = [
        _record("a", A_BLOCKS, pg_hash="0" * 16),
        _record("b", B_BLOCKS, pg_hash="f" * 16),
    ]
    assert continuity.detect_continuity(far_hash) == []


@pytest.mark.parametrize(
    "max_distance,expected",
    [(0, False), (1, True)],
)
def test_phash_distance_threshold_boundary(max_distance, expected):
    # "0" vs "8" differs by exactly one bit (distance 1).
    records = [
        _record("a", A_BLOCKS, pg_hash="0" * 16),
        _record("b", B_BLOCKS, pg_hash="8" + "0" * 15),
    ]
    assert bool(continuity.detect_continuity(records, phash_max_distance=max_distance)) is expected
    # a 64-bit-different pair is never a candidate at the default bound
    far = [
        _record("a", A_BLOCKS, pg_hash="0" * 16),
        _record("b", B_BLOCKS, pg_hash="f" * 16),
    ]
    assert continuity.detect_continuity(far, phash_max_distance=12) == []


def test_suggested_overlap_ratio_threshold_boundary():
    # window = min(N=4, |A|=3, |B|=3) = 3, overlap = 2 -> ratio 0.6667
    records = [
        _record("a", A_BLOCKS, pg_hash="0" * 16),
        _record("b", B_BLOCKS, pg_hash="0" * 16),
    ]
    assert continuity.detect_continuity(records, tail_blocks=4, min_overlap_ratio=0.66)
    assert continuity.detect_continuity(records, tail_blocks=4, min_overlap_ratio=0.67) == []


def test_tail_blocks_boundary_limits_the_search_window():
    records = [
        _record("a", A_BLOCKS, pg_hash="0" * 16),
        _record("b", B_BLOCKS, pg_hash="0" * 16),
    ]
    # N=2 finds both overlap blocks; N=1 only sees A's last block vs B's first
    assert continuity.detect_continuity(records, tail_blocks=2)[0]["overlap_blocks"] == 2
    assert continuity.detect_continuity(records, tail_blocks=1) == []
    # N=0 disables the overlap search entirely
    assert continuity.detect_continuity(records, tail_blocks=0) == []


def test_archived_documents_never_participate():
    records = [
        _record("a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0,
                merged_into="doc-merged"),
        _record("b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1),
    ]
    assert continuity.detect_continuity(records) == []
    assert continuity.is_archived(records[0]) is True
    assert continuity.is_archived(records[1]) is False


def test_rejected_and_confirmed_pairs_are_not_repeated():
    records = [
        _record("a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0),
        _record("b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1),
    ]
    assert continuity.detect_continuity(records)
    key = evolution.canonical_pair("a", "b")
    assert continuity.detect_continuity(records, rejected_pairs=[key]) == []
    assert continuity.detect_continuity(records, confirmed_pairs=[key]) == []


def test_significant_suppresses_duplicate_suggested():
    records = [
        _record("a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0,
                pg_hash="0" * 16),
        _record("b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1,
                pg_hash="0" * 16),
    ]
    pairs = continuity.detect_continuity(records)
    assert [pair["tier"] for pair in pairs] == ["significant"]


def test_tail_head_overlap_is_lossless_and_deterministic():
    ir_a = DocumentIR(blocks=A_BLOCKS)
    ir_b = DocumentIR(blocks=B_BLOCKS)
    overlap, report = continuity.tail_head_overlap(ir_a, ir_b, 8)
    assert overlap == 2
    assert report is not None
    # S1 found the two exact matches, everything else is removed/added.
    assert report.summary.by_op["unchanged"] == 2
    assert continuity.tail_head_overlap(ir_a, ir_b, 8)[0] == overlap
    assert continuity.tail_head_overlap(DocumentIR(blocks=[]), ir_b, 8) == (0, None)


def test_overlap_ratio_window():
    assert continuity.overlap_ratio(2, 8, 3, 3) == round(2 / 3, 4)
    assert continuity.overlap_ratio(0, 8, 3, 3) == 0.0
    assert continuity.overlap_ratio(5, 0, 3, 3) == 0.0


# ---------------------------------------------------------------------------
# merge executor (integration snapshot on a real store)
# ---------------------------------------------------------------------------


def _seed(store: FileDocumentStore, document_id: str, blocks: list[dict], *,
          tags=None, provenance=None, source_pdf=None, page_index=None,
          pg_hash="", topics=None, manual_collections=None):
    root = Path(store.root)
    original = root / f"{document_id}.jpg"
    original.write_bytes(b"fixture-" + document_id.encode())
    store.save_document(
        document_id=document_id,
        title=f"手稿 {document_id}",
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {document_id}\n",
        ir_json=_ir_json(*blocks),
        original_path=str(original),
        original_ext=".jpg",
        preprocessed_path=None,
        preprocessed_raw_path=None,
        assets_dir=None,
        timing_json={},
        pg_hash=pg_hash,
        source_pdf=source_pdf,
        page_index=page_index,
    )
    if tags:
        store.set_tags_with_provenance(document_id, tags, provenance or {})
    if topics:
        store.set_topics(document_id, topics)
    if manual_collections:
        store.set_collections(document_id, manual_collections)


@pytest.fixture()
def library(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", A_BLOCKS, tags=["控制", "重点"],
          provenance={"控制": "auto", "重点": "manual"},
          source_pdf="lecture.pdf", page_index=2, pg_hash="0" * 16,
          topics=["数学"])
    _seed(store, "doc-b", B_BLOCKS, tags=["控制", "新词"],
          provenance={"控制": "manual", "新词": "auto"},
          source_pdf="lecture.pdf", page_index=3, pg_hash="0" * 16,
          topics=["物理"])
    return store


def test_merge_documents_snapshot(library):
    pair = continuity.candidates_for_store(library)[0]
    assert pair["tier"] == "significant"
    report = continuity.merge_documents(library, "doc-a", "doc-b")

    assert report["conservation_ok"] is True
    assert report["block_counts"] == {"a": 4, "b": 3, "overlap": 2, "merged": 5}
    assert report["overlap_blocks"] == 2
    assert report["overlap_previews"] == ["重叠甲", "重叠乙"]
    assert report["llm_calls"] == 0 and report["zero_llm"] is True

    merged = library.get_document(report["merged_document_id"])
    # title comes from the first document
    assert merged["title"] == "手稿 doc-a"
    # markdown keeps the overlap exactly once
    assert merged["current_markdown"].count("重叠甲") == 1
    assert merged["current_markdown"].count("重叠乙") == 1
    blocks = [line for line in merged["current_markdown"].splitlines() if line.strip()]
    assert blocks == ["# 章一", "甲", "重叠甲", "重叠乙", "末段"]


def test_merge_documents_union_tags_and_collections(library):
    first = library.create_collection("第一组")["collection_id"]
    second = library.create_collection("第二组")["collection_id"]
    library.set_collections("doc-a", [first])
    library.set_collections("doc-b", [second])

    report = continuity.merge_documents(library, "doc-a", "doc-b")
    assert report["tags"] == ["控制", "重点", "新词"]
    # manual wins per tag, but a tag that was only ever auto stays auto
    assert report["tag_provenance"] == {
        "控制": "manual", "重点": "manual", "新词": "auto",
    }
    assert report["topics"] == ["数学", "物理"]
    merged = library.get_document(report["merged_document_id"])
    assert set(merged["collections"]) == {"数学", "物理", first, second}
    # manual memberships preserved as manual, topic-derived stay auto
    assert set(merged["manual_collections"]) == {first, second}


def test_merge_documents_version_provenance_and_chain(library):
    report = continuity.merge_documents(library, "doc-a", "doc-b")
    record = library.get_document(report["merged_document_id"])
    version = record["versions"][0]
    assert version["provenance"] == "merge"
    detail = version["provenance_detail"]
    assert detail["sources"] == ["doc-a", "doc-b"]
    assert detail["overlap_blocks"] == 2
    assert [item["document_id"] for item in detail["source_versions"]] == ["doc-a", "doc-b"]

    chain = evolution.build_version_chain(library, report["merged_document_id"])
    assert chain["versions"][0]["source"] == "merge"
    assert chain["versions"][0]["source_label"] == "合并"


def test_soft_archive_closed_loop(library):
    report = continuity.merge_documents(library, "doc-a", "doc-b")
    merged_id = report["merged_document_id"]

    # Library default list excludes both sources; the archive listing shows them
    listed = {item["document_id"] for item in library.list_documents()}
    assert listed == {merged_id}
    archived = {item["document_id"] for item in library.archived_documents()}
    assert archived == {"doc-a", "doc-b"}
    # direct route still reachable
    assert library.get_document("doc-a")["merged_into"] == merged_id
    assert library.get_document("doc-b")["merged_into"] == merged_id

    # detection excludes archived documents
    assert continuity.candidates_for_store(library) == []

    # clearing the marker restores list visibility
    assert library.restore_document("doc-a").get("merged_into") is None
    listed = {item["document_id"] for item in library.list_documents()}
    assert listed == {merged_id, "doc-a"}


def test_archived_documents_do_not_get_auto_tag_backfill(library):
    from graph2note import autotag

    before = {record["document_id"] for record in autotag.pending_documents(library)}
    assert {"doc-a", "doc-b"} <= before
    continuity.merge_documents(library, "doc-a", "doc-b")
    after = {record["document_id"] for record in autotag.pending_documents(library)}
    assert "doc-a" not in after and "doc-b" not in after


def test_merge_documents_rejects_invalid_requests(library):
    with pytest.raises(continuity.ContinuityError):
        continuity.merge_documents(library, "doc-a", "doc-a")
    with pytest.raises(continuity.ContinuityError):
        continuity.merge_documents(library, "doc-a", "missing")
    continuity.merge_documents(library, "doc-a", "doc-b")
    with pytest.raises(continuity.ContinuityError):
        continuity.merge_documents(library, "doc-a", "doc-a")


def test_merge_continuous_dry_run_does_not_write(library):
    plan = continuity.merge_continuous(library, dry_run=True)
    assert plan["dry_run"] is True
    assert plan["merged_count"] == 0
    assert plan["counts"]["significant"] == 1
    assert plan["llm_calls"] == 0
    assert {item["document_id"] for item in library.list_documents()} == {"doc-a", "doc-b"}


def test_merge_continuous_executes_significant_only(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    # significant pair (same PDF, adjacent pages)
    _seed(store, "sig-a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0,
          pg_hash="0" * 16)
    _seed(store, "sig-b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1,
          pg_hash="0" * 16)
    # suggested-only pair (different PDFs, same content overlap + close hash)
    _seed(store, "sus-a", A_BLOCKS, source_pdf="other.pdf", page_index=0,
          pg_hash="0" * 16)
    _seed(store, "sus-b", B_BLOCKS, source_pdf="other.pdf", page_index=9,
          pg_hash="0" * 16)

    report = continuity.merge_continuous(store, dry_run=False)
    assert report["counts"]["suggested"] >= 1
    merged_ids = {item["merged_document_id"] for item in report["executed"]}
    assert len(merged_ids) == 1
    for item in report["executed"]:
        assert item["order"] == ["sig-a", "sig-b"]
    # suggested docs stay untouched (per-item confirmation only)
    listed = {item["document_id"] for item in store.list_documents()}
    assert {"sus-a", "sus-b"} <= listed


def test_merge_continuous_chains_multiple_pages_into_one(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    p1 = [_heading("讲义 1"), _para("a"), *OVERLAP_BLOCKS]
    p2 = [*OVERLAP_BLOCKS, _para("b"), _para("重叠丙")]
    p3 = [_para("重叠丙"), _para("c")]
    _seed(store, "p1", p1, source_pdf="deck.pdf", page_index=0, pg_hash="0" * 16)
    _seed(store, "p2", p2, source_pdf="deck.pdf", page_index=1, pg_hash="1" * 16)
    _seed(store, "p3", p3, source_pdf="deck.pdf", page_index=2, pg_hash="2" * 16)

    report = continuity.merge_continuous(store, dry_run=False)
    assert report["merged_count"] == 2
    listed = [item["document_id"] for item in store.list_documents()]
    assert len(listed) == 1
    assert {"p1", "p2", "p3"} <= {
        item["document_id"] for item in store.archived_documents()
    }
    merged = store.get_document(listed[0])
    # each overlap block survives exactly once across the chained merge
    assert merged["current_markdown"].count("重叠甲") == 1
    assert merged["current_markdown"].count("重叠丙") == 1
    assert merged["page_index"] == 2  # later page provenance carried forward


# ---------------------------------------------------------------------------
# rejection memory + zero-LLM contract
# ---------------------------------------------------------------------------


def test_reject_pair_persists_and_suppresses(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0)
    _seed(store, "b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1)
    assert continuity.candidates_for_store(store)
    continuity.reject_pair(store, "a", "b")

    reloaded = FileDocumentStore(tmp_path / "storage")
    assert continuity.candidates_for_store(reloaded) == []
    assert evolution.canonical_pair("a", "b") in evolution.load_rejections(reloaded)


def test_continuity_module_is_zero_llm(tmp_path):
    source = Path(continuity.__file__).read_text(encoding="utf-8")
    for token in ("eval.gateway", "post_gateway", "graph2note.vlm", "llm_settings"):
        assert token not in source
    assert continuity.ZERO_LLM is True
    assert continuity.LLM_CALLS == 0

    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0,
          pg_hash="0" * 16)
    _seed(store, "b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1,
          pg_hash="0" * 16)
    detected = continuity.candidates_for_store(store)
    merged = continuity.merge_documents(store, "a", "b")
    assert detected and merged["llm_calls"] == 0


def test_zero_llm_assertion_via_gateway_patch(tmp_path, monkeypatch):
    import eval.gateway as gateway

    def _boom(*args, **kwargs):  # pragma: no cover - only on a broken path
        raise AssertionError("continuity must never call the model gateway")

    monkeypatch.setattr(gateway, "post_gateway", _boom, raising=False)
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "a", A_BLOCKS, source_pdf="lecture.pdf", page_index=0,
          pg_hash="0" * 16)
    _seed(store, "b", B_BLOCKS, source_pdf="lecture.pdf", page_index=1,
          pg_hash="0" * 16)
    assert continuity.merge_continuous(store, dry_run=False)["merged_count"] == 1
    assert continuity.candidates_for_store(store) == []
