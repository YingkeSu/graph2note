"""Offline contracts for the Knowledge Workspace Inbox projection."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from graph2note.inbox import build_inbox, is_inbox
from graph2note.notes.loop import run_incremental_export
from graph2note.notes.loader import load_entries
from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app

from tests.static_assets import static_js


def test_inbox_uses_only_present_signals_and_exposes_reasons():
    records = [
        {
            "document_id": "no-topic",
            "title": "No topic",
            "topics": [],
            "tags": ["keep"],
        },
        {
            "document_id": "no-tag",
            "title": "No tag",
            "topics": ["数学"],
            "tags": [],
        },
        {
            "document_id": "explicit",
            "title": "Explicit",
            "topics": ["数学"],
            "tags": ["keep"],
            "metadata": {"needs_organization": True},
        },
        {
            "document_id": "low-confidence",
            "title": "Low confidence",
            "topics": ["数学"],
            "tags": ["keep"],
            "metadata": {"document_time": {"confidence": "low"}},
        },
        {
            "document_id": "organized",
            "title": "Organized",
            "topics": ["数学"],
            "tags": ["keep"],
            "metadata": {"needs_organization": False},
        },
        {
            "document_id": "legacy-organized",
            "title": "Legacy organized",
            "topics": ["数学"],
            "tags": ["keep"],
            "metadata": {"inbox": "false"},
        },
    ]

    result = build_inbox(records)

    assert [item["document_id"] for item in result] == [
        "no-topic", "no-tag", "explicit", "low-confidence",
    ]
    by_id = {item["document_id"]: item for item in result}
    assert by_id["no-topic"]["inbox_reasons"] == ["no_topic"]
    assert by_id["no-tag"]["inbox_reasons"] == ["no_tag"]
    assert by_id["explicit"]["inbox_reasons"] == ["explicit"]
    assert by_id["low-confidence"]["inbox_reasons"] == ["low_confidence"]
    assert not is_inbox(records[-1])
    assert not is_inbox(records[-2])


def _seed(store: FileDocumentStore, document_id: str, *, topics, tags):
    original = Path(store.root) / f"{document_id}.jpg"
    original.write_bytes(b"fixture-image-" + document_id.encode())
    record = store.save_document(
        document_id=document_id,
        title=document_id,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {document_id}\n",
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
    )
    store.set_topics(document_id, topics)
    store.set_tags(document_id, tags)
    return record


def test_inbox_api_writes_explicit_marker_and_survives_reload(tmp_path):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "needs-topic", topics=[], tags=["已有"])
    _seed(store, "organized", topics=["数学"], tags=["已有"])
    client = TestClient(create_app(document_store=store, storage_dir=root))

    first = client.get("/api/inbox")
    assert first.status_code == 200
    assert [item["document_id"] for item in first.json()] == ["needs-topic"]
    assert "current_markdown" not in first.json()[0]

    marked = client.put(
        "/api/documents/organized/metadata",
        json={"needs_organization": True},
    )
    assert marked.status_code == 200
    assert marked.json()["metadata"]["needs_organization"] is True
    assert {item["document_id"] for item in client.get("/api/inbox").json()} == {
        "needs-topic", "organized",
    }

    reloaded = FileDocumentStore(root)
    assert reloaded.get_document("organized")["metadata"]["needs_organization"] is True
    client = TestClient(create_app(document_store=reloaded, storage_dir=root))
    cleared = client.put(
        "/api/documents/organized/metadata",
        json={"needs_organization": False},
    )
    assert cleared.status_code == 200
    assert cleared.json()["metadata"]["needs_organization"] is False
    assert [item["document_id"] for item in client.get("/api/inbox").json()] == [
        "needs-topic",
    ]
    html = client.get("/").text
    javascript = static_js()
    assert 'id="nav-inbox"' in html
    assert 'id="inbox-zone"' in html
    assert 'id="metadata-needs-organization"' in html
    inbox_markup = html.split('id="inbox-zone"', 1)[1].split("</section>", 1)[0]
    assert "md-editor" not in inbox_markup
    assert "textarea" not in inbox_markup
    assert "/api/inbox" in javascript


def test_workspace_metadata_flows_into_next_incremental_export(tmp_path):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "doc-a", topics=["数学"], tags=["重点"])
    first_collection = store.create_collection("第一组")
    second_collection = store.create_collection("第二组")
    store.set_collections("doc-a", [first_collection["collection_id"]])
    store.update_metadata("doc-a", {
        "document_time": "2024-03-01",
        "needs_organization": True,
    })
    vault = tmp_path / "vault"

    run_incremental_export(store, vault, exported_at="2024-03-10T00:00:00", __classify=lambda entries: None)
    note = (vault / "notes" / "doc-a" / "note.md").read_text(encoding="utf-8")
    assert "document_time: 2024-03-01" in note
    assert "needs_organization: true" in note
    assert "- 重点" in note
    assert "- 第一组" in note
    assert (vault / "collections" / "第一组" / "doc-a.md").is_file()

    store = FileDocumentStore(root)
    store.update_metadata("doc-a", {
        "document_time": "2024-03-02",
        "needs_organization": False,
    })
    store.set_tags("doc-a", ["已整理"])
    store.set_collections("doc-a", [second_collection["collection_id"]])
    reloaded = FileDocumentStore(root)
    assert load_entries(reloaded)[0].metadata["document_time"]["value"] == "2024-03-02"

    report, _, _ = run_incremental_export(
        reloaded, vault, exported_at="2024-03-11T00:00:00", __classify=lambda entries: None
    )
    note = (vault / "notes" / "doc-a" / "note.md").read_text(encoding="utf-8")
    assert "document_time: 2024-03-02" in note
    assert "needs_organization: false" in note
    assert "- 已整理" in note
    assert "- 第一组" not in note
    assert "- 第二组" in note
    assert "collections/第一组/doc-a.md" in report["deleted"]
    assert "collections/第二组/doc-a.md" in report["added"]
    assert not (vault / "collections" / "第一组" / "doc-a.md").exists()
    assert (vault / "collections" / "第二组" / "doc-a.md").is_file()
