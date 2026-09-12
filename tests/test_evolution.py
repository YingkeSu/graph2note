"""Offline unit tests for S2 evolution anchoring (no LLM, no network).

Covers the pure source/threshold rules (table driven) and the version-chain /
pHash-candidate projections against a lightweight stub store, so the API
surface can be pinned without any real gateway.  The TestClient contract lives
in ``tests/test_evolution_api.py``.
"""

from __future__ import annotations

import json

import pytest

from graph2note import evolution
from graph2note.store import FileDocumentStore


# ---------------------------------------------------------------------------
# helpers / stub store
# ---------------------------------------------------------------------------


def _heading(text: str) -> dict:
    return {"type": "heading", "level": 1, "text": text}


def _para(text: str) -> dict:
    return {"type": "paragraph", "text": text}


def _ir_json(*blocks: dict) -> str:
    return json.dumps({"document_type": "note", "blocks": list(blocks)},
                      ensure_ascii=False)


def _version(version_id, *, created_at, ir=None, markdown="", pg_hash="",
             provenance=None, model="fixture", current=True, provenance_detail=None):
    entry = {
        "version_id": version_id,
        "created_at": created_at,
        "model": model,
        "pg_hash": pg_hash,
        "current": current,
        "ir_json": ir if ir is not None else _ir_json(),
        "markdown": markdown,
    }
    if provenance is not None:
        entry["provenance"] = provenance
    if provenance_detail is not None:
        entry["provenance_detail"] = provenance_detail
    return entry


def _record(document_id, versions, *, title=None, live_markdown="", pg_hash="",
            relations=None):
    return {
        "document_id": document_id,
        "title": title or document_id,
        "hash": pg_hash or (versions[-1]["pg_hash"] if versions else ""),
        "current_markdown": live_markdown,
        "updated_at": "2026-01-02T00:00:00",
        "latest_version_id": versions[-1]["version_id"] if versions else None,
        "versions": list(versions),
        "manual_relations": list(relations or []),
    }


class StubStore:
    """Minimal store surface S2 actually consumes (no files, no model)."""

    def __init__(self, records, root=None):
        self._records = {record["document_id"]: record for record in records}
        self.root = root
        self.relation_writes: list[tuple[str, list]] = []

    def get_document(self, document_id):
        return self._records.get(document_id)

    def list_documents(self):
        return [{"document_id": record["document_id"], "title": record.get("title")}
                for record in self._records.values()]

    def version_hashes(self, document_id):
        record = self._records.get(document_id) or {}
        return [{"version_id": version["version_id"],
                 "pg_hash": version.get("pg_hash", "")}
                for version in record.get("versions", [])]

    def document_hashes(self):
        return {doc_id: record.get("hash") or ""
                for doc_id, record in self._records.items()}

    def set_manual_relations(self, document_id, relations):
        record = self._records.get(document_id)
        if record is None:
            return None
        record["manual_relations"] = [dict(item) for item in relations]
        self.relation_writes.append((document_id, [dict(item) for item in relations]))
        return record


# ---------------------------------------------------------------------------
# pure rules (table driven)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("meta,index,expected", [
    ({}, 0, evolution.PROVENANCE_PARSE),
    ({}, 1, evolution.PROVENANCE_REPARSE),
    ({}, 7, evolution.PROVENANCE_REPARSE),
    ({"provenance": None}, 0, evolution.PROVENANCE_PARSE),
    ({"provenance": ""}, 3, evolution.PROVENANCE_REPARSE),
    ({"provenance": "repair"}, 0, evolution.PROVENANCE_REPAIR),
    ({"provenance": "REPAIR"}, 4, evolution.PROVENANCE_REPAIR),
    ({"provenance": "parse"}, 3, evolution.PROVENANCE_PARSE),
    ({"provenance": "reparse"}, 0, evolution.PROVENANCE_REPARSE),
    ({"provenance": "edit"}, 1, evolution.PROVENANCE_EDIT),
    ({"provenance": "totally-new"}, 1, evolution.PROVENANCE_UNKNOWN),
])
def test_classify_version_source_rule_table(meta, index, expected):
    assert evolution.classify_version_source(meta, index=index) == expected


@pytest.mark.parametrize("distance,expected", [
    (0, 1.0),
    (16, 0.75),
    (32, 0.5),
    (64, 0.0),
])
def test_similarity_from_distance(distance, expected):
    assert evolution.similarity_from_distance(distance) == expected


@pytest.mark.parametrize("distance,max_distance,expected", [
    (0, 0, True),      # exact match is always within a zero bound
    (1, 0, False),     # one bit over -> outside (lower side)
    (11, 12, True),    # just below the default bound
    (12, 12, True),    # inclusive upper bound
    (13, 12, False),   # one bit over -> outside (upper side)
    (64, 64, True),
])
def test_within_suggestion_threshold_boundaries(distance, max_distance, expected):
    assert evolution.within_suggestion_threshold(distance, max_distance) is expected


def test_canonical_pair_is_order_insensitive():
    assert evolution.canonical_pair("doc-b", "doc-a") == "doc-a|doc-b"
    assert evolution.canonical_pair("doc-a", "doc-b") == "doc-a|doc-b"


# ---------------------------------------------------------------------------
# version chain
# ---------------------------------------------------------------------------


def test_version_chain_labels_sources_and_diffs_each_step():
    record = _record("doc-a", [
        _version("v1", created_at="2026-01-01T00:00:00",
                 ir=_ir_json(_heading("A"), _para("一")), markdown="# A\n\n一\n"),
        _version("v2", created_at="2026-01-02T00:00:00", provenance="repair",
                 provenance_detail={"source": "preprocessed_raw", "repair_id": "r-1"},
                 ir=_ir_json(_heading("A"), _para("一改")), markdown="# A\n\n一改\n",
                 current=False),
        _version("v3", created_at="2026-01-03T00:00:00",
                 ir=_ir_json(_heading("A"), _para("一改"), _para("二")),
                 markdown="# A\n\n一改\n\n二\n"),
    ], live_markdown="# A\n\n一改\n\n二\n")
    store = StubStore([record])

    chain = evolution.build_version_chain(store, "doc-a")

    assert chain["document_id"] == "doc-a"
    assert chain["count"] == 3
    assert chain["empty"] is False
    assert chain["latest_version_id"] == "v3"
    assert chain["has_uncommitted_edit"] is False

    entries = chain["versions"]
    assert [e["version_id"] for e in entries] == ["v1", "v2", "v3"]
    assert [e["source"] for e in entries] == [
        evolution.PROVENANCE_PARSE,
        evolution.PROVENANCE_REPAIR,
        evolution.PROVENANCE_REPARSE,
    ]
    assert entries[1]["source_label"] == evolution.SOURCE_LABELS[evolution.PROVENANCE_REPAIR]
    assert entries[1]["provenance_detail"]["repair_id"] == "r-1"

    # first version has no predecessor -> no diff, no block locations
    assert entries[0]["diff"] is None
    assert entries[0]["changes"] == []
    assert entries[0]["diff_from"] is None

    # later versions carry the S1 DiffReport summary + block-level locations
    for previous, current in zip(entries, entries[1:]):
        assert current["diff_from"] == previous["version_id"]
        assert current["diff"] is not None
        assert set(current["diff"]) >= {"verdict", "changed_blocks", "change_density",
                                        "by_op", "by_type"}
        assert current["changes"], "block locations must be present"
        assert all("block_type" in change and "op" in change for change in current["changes"])


def test_version_chain_single_version_and_empty_are_safe():
    single = _record("doc-one", [
        _version("v1", created_at="2026-01-01T00:00:00",
                 ir=_ir_json(_heading("Only")), markdown="# Only\n"),
    ], live_markdown="# Only\n")
    empty = _record("doc-empty", [], live_markdown="")
    store = StubStore([single, empty])

    chain = evolution.build_version_chain(store, "doc-one")
    assert chain["count"] == 1
    assert chain["versions"][0]["diff"] is None
    assert chain["versions"][0]["source"] == evolution.PROVENANCE_PARSE

    empty_chain = evolution.build_version_chain(store, "doc-empty")
    assert empty_chain["count"] == 0
    assert empty_chain["empty"] is True
    assert empty_chain["versions"] == []
    assert empty_chain["latest_version_id"] is None

    assert evolution.build_version_chain(store, "doc-missing") is None


def test_uncommitted_edit_is_the_timeline_head():
    record = _record("doc-a", [
        _version("v1", created_at="2026-01-01T00:00:00",
                 ir=_ir_json(_heading("A"), _para("旧内容")), markdown="# A\n\n旧内容\n"),
    ], live_markdown="# A\n\n新内容\n")
    store = StubStore([record])

    chain = evolution.build_version_chain(store, "doc-a")

    assert chain["count"] == 2
    assert chain["has_uncommitted_edit"] is True
    head = chain["versions"][-1]
    assert head["is_edit"] is True
    assert head["source"] == evolution.PROVENANCE_EDIT
    assert head["source_label"] == "编辑保存"
    assert head["diff_from"] == "v1"
    assert head["diff"]["changed_blocks"] >= 1


def test_saved_edits_equal_to_latest_version_do_not_add_an_edit_head():
    markdown = "# A\n\n相同内容\n"
    record = _record("doc-a", [
        _version("v1", created_at="2026-01-01T00:00:00",
                 ir=_ir_json(_heading("A"), _para("相同内容")), markdown=markdown),
    ], live_markdown=markdown)
    store = StubStore([record])

    chain = evolution.build_version_chain(store, "doc-a")
    assert chain["count"] == 1
    assert chain["has_uncommitted_edit"] is False


# ---------------------------------------------------------------------------
# pHash candidates
# ---------------------------------------------------------------------------


def test_versions_for_original_phash_threshold_upper_bound():
    store = StubStore([
        _record("doc-q", [
            _version("v1", created_at="2026-01-01T00:00:00", pg_hash="0000000000000000"),
        ]),
        _record("doc-in", [
            _version("v1", created_at="2026-01-01T00:00:00", pg_hash="0000000000000fff"),
        ]),
        _record("doc-out", [
            _version("v1", created_at="2026-01-01T00:00:00", pg_hash="0000000000001fff"),
        ]),
    ])

    matches = evolution.versions_for_original_phash(
        store, "0000000000000000", max_distance=12)
    by_doc = {match["document_id"]: match for match in matches}
    assert by_doc["doc-in"]["distance"] == 12
    assert by_doc["doc-in"]["similarity"] == round(1 - 12 / 64, 4)
    assert "doc-out" not in by_doc          # 13 bits > 12 -> excluded
    assert matches[0]["document_id"] == "doc-q"  # exact match sorts first
    assert [m["document_id"] for m in matches] == ["doc-q", "doc-in"]  # sorted by distance

    # tightening the bound excludes the 12-bit match too (lower side)
    tight = evolution.versions_for_original_phash(
        store, "0000000000000000", max_distance=11)
    assert [m["document_id"] for m in tight] == ["doc-q"]


def test_phash_candidates_exclude_confirmed_rejected_and_far_documents(tmp_path):
    target = _record("doc-a", [
        _version("v1", created_at="2026-01-01T00:00:00", pg_hash="0000000000000000"),
    ])
    store = StubStore([
        target,
        _record("doc-b", [_version("v1", created_at="2026-01-01T00:00:00",
                                   pg_hash="0000000000000007")]),   # distance 3
        _record("doc-c", [_version("v1", created_at="2026-01-01T00:00:00",
                                   pg_hash="00000000000000ff")]),   # distance 8
        _record("doc-confirmed", [_version("v1", created_at="2026-01-01T00:00:00",
                                           pg_hash="000000000000000f")],
                relations=[{"kind": "manual", "from": "doc-a", "to": "doc-confirmed"}]),
        _record("doc-maybe", [_version("v1", created_at="2026-01-01T00:00:00",
                                       pg_hash="0000000000000003")]),  # distance 2
        _record("doc-far", [_version("v1", created_at="2026-01-01T00:00:00",
                                     pg_hash="ffffffffffffffff")]),    # distance 64
    ], root=tmp_path)

    view = evolution.find_phash_candidates(store, "doc-a")
    assert view["empty"] is False
    assert [c["document_id"] for c in view["candidates"]] == ["doc-maybe", "doc-b", "doc-c"]
    assert view["candidates"][0]["distance"] == 2
    assert "doc-confirmed" not in {c["document_id"] for c in view["candidates"]}
    assert "doc-far" not in {c["document_id"] for c in view["candidates"]}

    # reject the closest pair -> it disappears (and stays gone after reload)
    evolution.reject_candidate(store, "doc-a", "doc-maybe", distance=2)
    assert "doc-maybe" not in {
        c["document_id"] for c in evolution.find_phash_candidates(store, "doc-a")["candidates"]
    }

    # confirm doc-b -> manual relation persisted on both sides + no longer suggested
    assert evolution.confirm_relation(store, "doc-a", "doc-b", distance=3)["ok"] is True
    assert evolution.canonical_pair("doc-a", "doc-b") in evolution.confirmed_pairs(store)
    assert [c["document_id"] for c in
            evolution.find_phash_candidates(store, "doc-a")["candidates"]] == ["doc-c"]
    assert any(rel.get("to") == "doc-b" for rel in target["manual_relations"])
    assert any(rel.get("to") == "doc-a"
               for rel in store.get_document("doc-b")["manual_relations"])


def test_phash_candidates_empty_states():
    # no hash at all -> explicit empty result (blank pages are not evidence)
    blank = _record("doc-blank", [_version("v1", created_at="2026-01-01T00:00:00",
                                           pg_hash="")], live_markdown="")
    # a library where every page is far away -> safe empty list
    target = _record("doc-a", [
        _version("v1", created_at="2026-01-01T00:00:00", pg_hash="0000000000000000"),
    ])
    far = _record("doc-far", [
        _version("v1", created_at="2026-01-01T00:00:00", pg_hash="ffffffffffffffff"),
    ])
    store = StubStore([blank, target, far])

    blank_view = evolution.find_phash_candidates(store, "doc-blank")
    assert blank_view["empty"] is True
    assert blank_view["target_hashes"] == []
    assert blank_view["candidates"] == []

    far_view = evolution.find_phash_candidates(store, "doc-a")
    assert far_view["empty"] is True
    assert far_view["candidates"] == []

    assert evolution.find_phash_candidates(store, "doc-missing") is None


# ---------------------------------------------------------------------------
# durable rejection record
# ---------------------------------------------------------------------------


def _seed_file_store(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    for document_id, pg_hash in (("doc-a", "0000000000000000"),
                                 ("doc-b", "0000000000000007")):
        store.save_document(
            document_id=document_id, title=document_id, source_job_id=f"job-{document_id}",
            model="fixture", markdown=f"# {document_id}\n",
            ir_json=_ir_json(_heading(document_id)), original_path="",
            original_ext=".jpg", preprocessed_path="", preprocessed_raw_path="",
            assets_dir="", timing_json={}, pg_hash=pg_hash,
        )
    return store


def test_rejection_persists_across_store_reload(tmp_path):
    store = _seed_file_store(tmp_path)
    assert evolution.find_phash_candidates(store, "doc-a")["candidates"]

    evolution.reject_candidate(store, "doc-a", "doc-b", distance=3)

    reloaded = FileDocumentStore(store.root)
    rejected = evolution.load_rejections(reloaded)
    assert evolution.canonical_pair("doc-a", "doc-b") in rejected
    assert evolution.find_phash_candidates(reloaded, "doc-a")["empty"] is True

    # confirming the same pair clears the rejection again
    evolution.confirm_relation(reloaded, "doc-a", "doc-b", distance=3)
    assert evolution.load_rejections(FileDocumentStore(store.root)) == {}
