"""Offline API / CLI / UI contract tests for continuity merge (issue 03).

Uses a real ``FileDocumentStore`` in a temp dir + the existing TestClient, and
the CLI entry point for the batch command.  No router / model / network is
involved; the detector and merge executor are deterministic and zero-LLM.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from graph2note import continuity
from graph2note.cli import main as cli_main
from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app

TESTS_DIR = Path(__file__).parent


def _ir_json(*blocks: dict) -> str:
    return json.dumps({"document_type": "note", "blocks": list(blocks)},
                      ensure_ascii=False)


def _para(text: str) -> dict:
    return {"type": "paragraph", "text": text}


OVERLAP = [_para("重叠甲"), _para("重叠乙")]
A_BLOCKS = [{"type": "heading", "level": 1, "text": "章一"}, _para("甲"), *OVERLAP]
B_BLOCKS = [*OVERLAP, _para("末段")]


def _seed(store: FileDocumentStore, document_id: str, blocks: list[dict], *,
          tags=None, provenance=None, source_pdf=None, page_index=None,
          pg_hash="", topics=None, title=None) -> None:
    root = Path(store.root)
    original = root / f"{document_id}.jpg"
    original.write_bytes(b"fixture-" + document_id.encode())
    store.save_document(
        document_id=document_id,
        title=title or f"手稿 {document_id}",
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {title or document_id}\n\n正文\n",
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


@pytest.fixture()
def signed_library(tmp_path):
    """Same PDF, adjacent pages, overlapping content -> significant pair."""
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", A_BLOCKS, tags=["控制", "重点"],
          provenance={"控制": "auto", "重点": "manual"},
          source_pdf="lecture.pdf", page_index=2, pg_hash="0" * 16,
          topics=["数学"], title="讲义 3")
    _seed(store, "doc-b", B_BLOCKS, tags=["控制", "新词"],
          provenance={"控制": "manual", "新词": "auto"},
          source_pdf="lecture.pdf", page_index=3, pg_hash="0" * 16,
          topics=["物理"], title="讲义 4")
    return store


def _client(store):
    return TestClient(create_app(document_store=store, storage_dir=store.root))


# ---------------------------------------------------------------------------
# candidates endpoint
# ---------------------------------------------------------------------------


def test_candidates_endpoint_payload(signed_library):
    payload = _client(signed_library).get("/api/continuity/candidates").json()
    assert payload["empty"] is False
    assert payload["zero_llm"] is True
    assert payload["llm_calls"] == 0
    assert payload["counts"] == {"significant": 1, "suggested": 0, "total": 1}
    pair = payload["significant"][0]
    assert set(pair) >= {"tier", "key", "document_id", "target_id", "order",
                         "titles", "evidence", "evidence_label"}
    assert pair["order"] == ["doc-a", "doc-b"]
    assert pair["evidence_label"] == "同 PDF 第 3–4 页"
    assert pair["titles"] == ["讲义 3", "讲义 4"]


def test_candidates_endpoint_query_bounds(signed_library):
    client = _client(signed_library)
    assert client.get("/api/continuity/candidates?tail_blocks=0").status_code == 422
    assert client.get("/api/continuity/candidates?min_overlap_ratio=2").status_code == 422
    assert client.get("/api/continuity/candidates?max_distance=99").status_code == 422


def test_candidates_endpoint_empty_state(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "solo", A_BLOCKS)
    payload = _client(store).get("/api/continuity/candidates").json()
    assert payload["empty"] is True
    assert payload["significant"] == [] and payload["suggested"] == []
    assert payload["counts"]["total"] == 0


# ---------------------------------------------------------------------------
# merge endpoint (single pair only)
# ---------------------------------------------------------------------------


def test_merge_endpoint_merges_and_archives(signed_library):
    client = _client(signed_library)
    response = client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-b",
    })
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["conservation_ok"] is True
    assert report["overlap_blocks"] == 2
    assert report["llm_calls"] == 0
    new_id = report["merged_document_id"]

    # Library default list excludes both sources; archive entries carry the marker
    listed = {item["document_id"] for item in client.get("/api/documents").json()}
    assert listed == {new_id}
    archived = signed_library.archived_documents()
    assert {item["document_id"] for item in archived} == {"doc-a", "doc-b"}

    # direct route still reachable and exposes the archive marker
    direct = client.get("/api/documents/doc-a").json()
    assert direct["merged_into"] == new_id
    assert direct["title"] == "讲义 3"

    # the merged document keeps the union of tags / collections / topics
    merged = client.get(f"/api/documents/{new_id}").json()
    assert set(merged["tags"]) == {"控制", "重点", "新词"}
    assert merged["tag_provenance"]["控制"] == "manual"
    assert merged["tag_provenance"]["新词"] == "auto"
    assert set(merged["topics"]) == {"数学", "物理"}


def test_merge_endpoint_rejects_batch_payloads(signed_library):
    client = _client(signed_library)
    for key in ("pairs", "candidates", "items"):
        response = client.post("/api/continuity/merge", json={
            key: [{"document_id": "doc-a", "target_id": "doc-b"}],
        })
        assert response.status_code == 422, key
        assert "逐条" in response.json()["detail"]


def test_merge_endpoint_validates_input(signed_library):
    client = _client(signed_library)
    assert client.post("/api/continuity/merge", json={}).status_code == 422
    assert client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-a",
    }).status_code == 422
    assert client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "nope",
    }).status_code == 404
    assert client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-b",
    }).status_code == 200
    # sources are archived now -> a second merge is refused
    assert client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-b",
    }).status_code == 422


def test_suggested_pair_is_confirmed_one_at_a_time(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-c", A_BLOCKS, source_pdf="other.pdf", page_index=0,
          pg_hash="0" * 16)
    _seed(store, "doc-d", B_BLOCKS, source_pdf="other.pdf", page_index=9,
          pg_hash="8" + "0" * 15)
    client = _client(store)
    payload = client.get("/api/continuity/candidates").json()
    assert payload["counts"]["suggested"] == 1
    pair = payload["suggested"][0]
    response = client.post("/api/continuity/merge", json={
        "document_id": pair["document_id"], "target_id": pair["target_id"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["overlap_blocks"] == 2


# ---------------------------------------------------------------------------
# reject + restore endpoints
# ---------------------------------------------------------------------------


def test_reject_endpoint_persists_and_suppresses(signed_library):
    client = _client(signed_library)
    response = client.post("/api/continuity/reject", json={
        "document_id": "doc-a", "target_id": "doc-b",
    })
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert client.get("/api/continuity/candidates").json()["empty"] is True

    # survives a process restart (reload store + app)
    reloaded = FileDocumentStore(signed_library.root)
    assert _client(reloaded).get("/api/continuity/candidates").json()["empty"] is True
    assert continuity.rejected_pairs(reloaded)


def test_restore_endpoint_reverses_soft_archive(signed_library):
    client = _client(signed_library)
    new_id = client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-b",
    }).json()["merged_document_id"]

    response = client.post("/api/documents/doc-a/restore")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "document_id": "doc-a", "merged_into": None, "restored": True,
    }
    listed = {item["document_id"] for item in client.get("/api/documents").json()}
    assert listed == {new_id, "doc-a"}
    assert client.post("/api/documents/nope/restore").status_code == 404


def test_archived_document_not_in_detection_again(signed_library):
    client = _client(signed_library)
    client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-b",
    })
    assert client.get("/api/continuity/candidates").json()["empty"] is True


# ---------------------------------------------------------------------------
# inbox + version chain wiring
# ---------------------------------------------------------------------------


def test_inbox_exposes_merge_reason(signed_library):
    items = _client(signed_library).get("/api/inbox").json()
    by_id = {item["document_id"]: item for item in items}
    assert {"doc-a", "doc-b"} <= set(by_id)
    item = by_id["doc-a"]
    assert "merge_candidate" in item["inbox_reasons"]
    assert "可合并" in item["inbox_reason_labels"]
    assert item["merge_evidence"] == ["同 PDF 第 3–4 页"]


def test_version_chain_shows_merge_event(signed_library):
    client = _client(signed_library)
    new_id = client.post("/api/continuity/merge", json={
        "document_id": "doc-a", "target_id": "doc-b",
    }).json()["merged_document_id"]
    chain = client.get(f"/api/documents/{new_id}/versions").json()
    first = chain["versions"][0]
    assert first["source"] == "merge"
    assert first["source_label"] == "合并"
    assert first["provenance_detail"]["sources"] == ["doc-a", "doc-b"]
    # the merged document's detail also carries the raw provenance for the UI
    detail = client.get(f"/api/documents/{new_id}").json()
    assert detail["versions"][0]["provenance"] == "merge"


# ---------------------------------------------------------------------------
# CLI: dry-run by default, --yes executes significant tier only
# ---------------------------------------------------------------------------


def _cli(store, *args):
    return cli_main(["docs", "merge-continuous", "--storage", str(store.root), *args])


def test_cli_defaults_to_dry_run(signed_library, capsys):
    assert _cli(signed_library) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert "显著连续对 1 对" in out
    assert "预估 LLM 调用 0" in out
    assert "同 PDF 第 3–4 页" in out
    assert {item["document_id"] for item in signed_library.list_documents()} == {
        "doc-a", "doc-b",
    }


def test_cli_yes_executes_significant_only(signed_library, capsys):
    assert _cli(signed_library, "--yes") == 0
    out = capsys.readouterr().out
    assert "已合并 1 对" in out
    assert "LLM 调用 0" in out
    listed = {item["document_id"] for item in signed_library.list_documents()}
    assert len(listed) == 1
    archived = {item["document_id"] for item in signed_library.archived_documents()}
    assert archived == {"doc-a", "doc-b"}


def test_cli_json_report_is_zero_llm(signed_library, capsys):
    assert _cli(signed_library, "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["llm_calls"] == 0
    assert payload["zero_llm"] is True
    assert payload["counts"]["significant"] == 1
    assert payload["storage"] == str(signed_library.root)


def test_cli_never_batches_suggested(tmp_path, capsys):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-c", A_BLOCKS, source_pdf="other.pdf", page_index=0,
          pg_hash="0" * 16)
    _seed(store, "doc-d", B_BLOCKS, source_pdf="other.pdf", page_index=9,
          pg_hash="0" * 16)
    assert _cli(store) == 0
    out = capsys.readouterr().out
    assert "疑似（仅入确认队列）1 对" in out
    assert "疑似档请在 Inbox 逐条确认" in out
    assert _cli(store, "--yes") == 0
    out = capsys.readouterr().out
    assert "已合并 0 对" in out
    assert {item["document_id"] for item in store.list_documents()} == {
        "doc-c", "doc-d",
    }


# ---------------------------------------------------------------------------
# static wiring + DOM harness
# ---------------------------------------------------------------------------


def test_inbox_merge_static_wiring(signed_library):
    client = _client(signed_library)
    html = client.get("/").text
    assert 'id="inbox-zone"' in html
    core = client.get("/static/js/inbox_merge_core.js")
    assert core.status_code == 200
    view = client.get("/static/js/views/inbox.js").text
    assert "/api/continuity/candidates" in view
    assert "/api/continuity/merge" in view
    assert "/api/continuity/reject" in view
    assert "确认合并" in view and "确认合并" in core.text
    assert "/versions" in core.text


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_inbox_merge_dom_harness():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "inbox_merge_dom.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "all assertions passed" in proc.stdout
