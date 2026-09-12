"""Offline API contract tests for S2 evolution anchoring (issue S2).

Uses a real ``FileDocumentStore`` in a temp dir plus the existing TestClient so
"restart persistence" can be simulated by rebuilding a fresh app over the same
storage root.  Every document is seeded directly through the store, so no
router / model / network is involved.
"""

from __future__ import annotations

import json

import pytest

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import evolution  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402
from graph2note.store import SessionDocumentStore  # noqa: E402
from graph2note.webapp import create_app  # noqa: E402


def _ir(text: str) -> str:
    return json.dumps(
        {"document_type": "note",
         "blocks": [{"type": "heading", "level": 1, "text": text}]},
        ensure_ascii=False,
    )


def _seed(store, document_id, *, pg_hash, title=None, markdown=None, ir=None):
    store.save_document(
        document_id=document_id,
        title=title or document_id,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=markdown or f"# {title or document_id}\n",
        ir_json=ir or _ir(title or document_id),
        original_path="",
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
        pg_hash=pg_hash,
    )


def _client(store):
    return TestClient(create_app(document_store=store, storage_dir=store.root))


@pytest.fixture()
def library(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    # one document with two versions (chain) and one single-version document
    _seed(store, "doc-a", pg_hash="0000000000000000", title="手稿 A",
          markdown="# A\n\n第一版\n", ir=_ir("第一版"))
    _seed(store, "doc-a", pg_hash="0000000000000000", title="手稿 A",
          markdown="# A\n\n第二版\n", ir=_ir("第二版"))
    _seed(store, "doc-single", pg_hash="ffffffffffffffff", title="单版本")
    # pHash neighbours: doc-b / doc-d are close to doc-a, doc-c is far away
    _seed(store, "doc-b", pg_hash="0000000000000003", title="手稿 B")     # distance 2
    _seed(store, "doc-d", pg_hash="0000000000000005", title="手稿 D")     # distance 2
    return store


# ---------------------------------------------------------------------------
# version chain API
# ---------------------------------------------------------------------------


def test_versions_endpoint_returns_time_ordered_chain_with_sources(library):
    client = _client(library)

    r = client.get("/api/documents/doc-a/versions")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["document_id"] == "doc-a"
    assert payload["title"] == "手稿 A"
    assert payload["count"] == 2
    assert payload["empty"] is False
    assert payload["latest_version_id"] == payload["versions"][-1]["version_id"]

    first, second = payload["versions"]
    assert first["source"] == evolution.PROVENANCE_PARSE
    assert first["source_label"] == "解析"
    assert first["diff"] is None
    assert second["source"] == evolution.PROVENANCE_REPARSE
    assert second["source_label"] == "重解析"
    assert second["diff_from"] == first["version_id"]
    assert second["diff"] is not None
    assert set(second["diff"]) >= {"verdict", "changed_blocks", "by_op", "by_type"}
    assert second["changes"], "block-level locations are part of the contract"
    refs_b = [change["block_ref_b"] for change in second["changes"]
              if change["block_ref_b"]]
    assert refs_b
    assert {"index", "block_type", "anchor"} <= set(refs_b[0])


def test_versions_endpoint_is_safe_for_single_version_and_empty_chain(library):
    client = _client(library)

    single = client.get("/api/documents/doc-single/versions").json()
    assert single["count"] == 1
    assert single["versions"][0]["diff"] is None
    assert single["has_uncommitted_edit"] is False

    assert client.get("/api/documents/doc-missing/versions").status_code == 404


def test_versions_endpoint_reads_r1_repair_provenance_from_record_json(library):
    """R1 contract: a re-run version carries provenance=repair in record.json.

    S2 must label it "repair" without importing any R1 code.  The field is
    absent on the other version, which is the "not written" path and stays a
    plain parse/reparse; this is the fixture self-supplied field.
    """
    record_path = library.root / "documents" / "doc-a" / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    repaired = record["versions"][1]
    repaired["provenance"] = "repair"
    repaired["provenance_detail"] = {
        "source": "preprocessed_raw", "repair_id": "repair-fixture",
        "old_version_id": record["versions"][0]["version_id"],
    }
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    payload = _client(FileDocumentStore(library.root)).get(
        "/api/documents/doc-a/versions").json()
    first, second = payload["versions"]
    assert first["source"] == evolution.PROVENANCE_PARSE       # field not written
    assert second["source"] == evolution.PROVENANCE_REPAIR     # field written
    assert second["source_label"] == "修复"
    assert second["provenance_detail"]["repair_id"] == "repair-fixture"


def test_saved_edits_show_as_the_edit_head(library):
    client = _client(library)

    saved = client.post("/api/documents/doc-single/markdown",
                        json={"markdown": "# 单版本\n\n用户手改内容\n"})
    assert saved.status_code == 200, saved.text

    payload = client.get("/api/documents/doc-single/versions").json()
    assert payload["has_uncommitted_edit"] is True
    head = payload["versions"][-1]
    assert head["is_edit"] is True
    assert head["source"] == evolution.PROVENANCE_EDIT
    assert head["source_label"] == "编辑保存"
    assert head["diff"] is not None


# ---------------------------------------------------------------------------
# pHash candidate API + confirmation -> graph manual edge
# ---------------------------------------------------------------------------


def test_candidates_confirm_graph_edge_and_restart_persistence(library):
    client = _client(library)

    view = client.get("/api/documents/doc-a/candidates").json()
    assert view["empty"] is False
    ids = [candidate["document_id"] for candidate in view["candidates"]]
    assert "doc-b" in ids and "doc-d" in ids
    assert "doc-single" not in ids          # 64 bits away -> not suggested
    assert view["candidates"][0]["similarity"] == round(1 - 2 / 64, 4)

    confirmed = client.post("/api/documents/doc-a/relations",
                            json={"target_id": "doc-b", "distance": 2})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["ok"] is True

    # confirmed pair is no longer suggested
    after = client.get("/api/documents/doc-a/candidates").json()
    assert "doc-b" not in {c["document_id"] for c in after["candidates"]}

    graph = client.get("/api/graph").json()
    manual = [edge for edge in graph["edges"] if edge["source"] == "manual"]
    pairs = {(edge["from"], edge["to"]) for edge in manual}
    assert ("document:doc-a", "document:doc-b") in pairs
    # the relation was written symmetrically, so it is navigable from either side
    assert ("document:doc-b", "document:doc-a") in pairs
    assert all(edge["source"] in {"topic", "tag", "manual"} for edge in graph["edges"])

    # reject the other close candidate -> remembered
    rejected = client.post("/api/documents/doc-a/candidates/reject",
                           json={"target_id": "doc-d", "distance": 2})
    assert rejected.status_code == 200, rejected.text
    assert "doc-d" not in {
        c["document_id"]
        for c in client.get("/api/documents/doc-a/candidates").json()["candidates"]
    }

    # fresh store + fresh app over the same storage root == restart
    reloaded = FileDocumentStore(library.root)
    client2 = _client(reloaded)
    record = client2.get("/api/documents/doc-a").json()
    assert any(rel.get("to") == "doc-b" for rel in record.get("manual_relations") or [])

    graph2 = client2.get("/api/graph").json()
    pairs2 = {(edge["from"], edge["to"]) for edge in graph2["edges"]
              if edge["source"] == "manual"}
    assert ("document:doc-a", "document:doc-b") in pairs2

    candidates2 = client2.get("/api/documents/doc-a/candidates").json()
    remaining = {c["document_id"] for c in candidates2["candidates"]}
    assert "doc-b" not in remaining   # confirmed relation excluded after restart
    assert "doc-d" not in remaining   # rejected pair excluded after restart
    assert evolution.canonical_pair("doc-a", "doc-d") in evolution.load_rejections(reloaded)


def test_candidate_threshold_is_configurable_and_bounded(library):
    client = _client(library)

    # default (12) includes the 2-bit neighbours; a 0 bound only allows exact hits
    strict = client.get("/api/documents/doc-a/candidates?max_distance=0").json()
    assert strict["max_distance"] == 0
    assert strict["empty"] is True

    loose = client.get("/api/documents/doc-a/candidates?max_distance=64").json()
    assert "doc-single" in {c["document_id"] for c in loose["candidates"]}

    assert client.get("/api/documents/doc-a/candidates?max_distance=999").status_code == 422
    assert client.get("/api/documents/doc-a/candidates?max_distance=-1").status_code == 422


def test_candidate_and_relation_endpoint_errors(library):
    client = _client(library)

    assert client.get("/api/documents/nope/candidates").status_code == 404
    assert client.post("/api/documents/nope/relations",
                       json={"target_id": "doc-b"}).status_code == 404
    assert client.post("/api/documents/doc-a/relations",
                       json={}).status_code == 422
    assert client.post("/api/documents/doc-a/relations",
                       json={"target_id": "nope"}).status_code == 404
    assert client.post("/api/documents/doc-a/relations",
                       json={"target_id": "doc-a"}).status_code == 422
    assert client.post("/api/documents/doc-a/candidates/reject",
                       json={}).status_code == 422
    assert client.post("/api/documents/doc-a/candidates/reject",
                       json={"target_id": "nope"}).status_code == 404


def test_candidates_are_read_only_until_confirmed(library):
    """Listing candidates must not mutate relations or the graph."""
    client = _client(library)
    before = client.get("/api/graph").json()
    client.get("/api/documents/doc-a/candidates")
    client.get("/api/documents/doc-a/candidates?max_distance=64")
    after = client.get("/api/graph").json()
    assert before["edges"] == after["edges"]


def test_editor_panel_is_wired_to_the_evolution_api(library):
    client = _client(library)
    html = client.get("/").text
    assert 'id="evolution-panel"' in html
    assert "/static/evolution.js" in html

    script = client.get("/static/evolution.js")
    assert script.status_code == 200
    assert "/versions" in script.text
    assert "/candidates" in script.text


def test_api_contract_with_in_memory_stub_store(tmp_path):
    """The same endpoints work against the non-durable in-memory seam."""
    store = SessionDocumentStore(tmp_path / "session-storage")
    for label, pg_hash in (("旧", "0000000000000000"), ("新", "0000000000000003")):
        store.save_document(
            document_id="doc-stub", title="Stub", source_job_id="job-stub",
            model="fixture", markdown=f"# {label}\n", ir_json=_ir(label),
            original_path="", original_ext=".jpg", preprocessed_path="",
            preprocessed_raw_path="", assets_dir="", timing_json={}, pg_hash=pg_hash,
        )
    store.save_document(
        document_id="doc-other", title="Other", source_job_id="job-other",
        model="fixture", markdown="# Other\n", ir_json=_ir("Other"),
        original_path="", original_ext=".jpg", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={}, pg_hash="000000000000000f",
    )
    client = TestClient(create_app(document_store=store, storage_dir=store.root))

    chain = client.get("/api/documents/doc-stub/versions").json()
    assert chain["count"] == 2
    assert [entry["source"] for entry in chain["versions"]] == [
        evolution.PROVENANCE_PARSE, evolution.PROVENANCE_REPARSE]
    assert chain["versions"][1]["diff"] is not None

    view = client.get("/api/documents/doc-stub/candidates").json()
    assert [c["document_id"] for c in view["candidates"]] == ["doc-other"]

    assert client.post("/api/documents/doc-stub/relations",
                       json={"target_id": "doc-other"}).json()["ok"] is True
    graph = client.get("/api/graph").json()
    assert any(edge["source"] == "manual" for edge in graph["edges"])
