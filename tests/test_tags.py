"""Offline contracts for Knowledge Workspace issue 02."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from graph2note.metadata import infer_document_time
from graph2note.notes.exporter import ExportEntry, export_vault
from graph2note.notes.loader import load_entries
from graph2note.store import FileDocumentStore, SessionDocumentStore
from graph2note.tags import normalize_tag, validate_tag_inference
from graph2note.webapp import create_app


def _seed(store, document_id: str, title: str = "Note"):
    original = Path(store.root) / f"{document_id}.jpg"
    original.write_bytes(b"fixture-image")
    store.save_document(
        document_id=document_id,
        title=title,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {title}\n",
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
    )


def test_normalization_and_recorded_auto_output_are_deterministic():
    assert normalize_tag("  AI_tag  ") == "ai tag"
    assert normalize_tag("AI-tag") == "ai tag"
    assert normalize_tag("AI/tag") == "ai tag"
    assert validate_tag_inference({"tags": ["AI_tag", " ai-tag ", "知识库"]}) == [
        "ai tag", "知识库"
    ]
    assert validate_tag_inference({"tags": "not-a-list"}) is None
    assert validate_tag_inference({"tags": [""]}) is None


def test_existing_tag_and_alias_are_reused_with_usage_counts(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "a")
    _seed(store, "b")
    store.set_tags("a", ["Artificial-Intelligence"])
    store.set_tags("b", [" artificial_intelligence "])
    assert store.get_document("a")["tags"] == ["artificial intelligence"]
    assert store.get_document("b")["tags"] == ["artificial intelligence"]
    entries = store.list_tags()
    assert entries == [{
        "tag": "artificial intelligence",
        "aliases": ["Artificial-Intelligence", "artificial_intelligence"],
        "count": 2,
    }]


def test_manual_tags_persist_reload_and_export_consumes_them(tmp_path):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "a", "Tagged")
    store.set_tags("a", ["Research/ML", "AI"])
    reloaded = FileDocumentStore(root)
    rec = reloaded.get_document("a")
    assert rec["tags"] == ["research ml", "ai"]
    assert json.loads((root / "tag-vocabulary.json").read_text())["tags"]

    entries = load_entries(reloaded)
    assert entries[0].tags == ["research ml", "ai"]
    out = export_vault(entries, tmp_path / "vault")
    note = (out.root / "notes" / "a" / "note.md").read_text()
    assert "tags:" in note
    assert "  - research ml" in note
    assert "  - ai" in note


def test_auto_tags_and_merge_rename_update_all_documents(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "a")
    _seed(store, "b")
    assert store.add_auto_tags("a", {"tags": ["ML"]})["tags"] == ["ml"]
    store.set_tags("b", ["machine-learning"])

    merged = store.merge_tags("ml", "machine learning")
    by_name = {item["tag"]: item for item in merged}
    assert "ml" not in by_name
    assert by_name["machine learning"]["count"] == 2
    assert store.get_document("a")["tags"] == ["machine learning"]
    assert "ml" in by_name["machine learning"]["aliases"]

    store.rename_tag("machine learning", "learning")
    assert store.get_document("a")["tags"] == ["learning"]
    assert store.get_document("b")["tags"] == ["learning"]
    assert {item["tag"] for item in store.list_tags()} == {"learning"}


def test_tag_and_document_tag_api_contract(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "a")
    client = TestClient(create_app(document_store=store, storage_dir=store.root))

    assert client.post("/api/tags", json={"tag": "AI_tag"}).status_code == 200
    assert client.put("/api/documents/a/tags", json={"tags": ["AI-tag"]}).json()["tags"] == ["ai tag"]
    added = client.post("/api/documents/a/tags", json={"tags": ["Research"]})
    assert added.status_code == 200
    assert added.json()["tags"] == ["ai tag", "research"]
    removed = client.delete("/api/documents/a/tags/research")
    assert removed.status_code == 200
    assert removed.json()["tags"] == ["ai tag"]

    listed = client.get("/api/tags")
    assert listed.status_code == 200
    assert {item["tag"] for item in listed.json()} == {"ai tag", "research"}
    renamed = client.post("/api/tags/rename", json={"source": "ai tag", "target": "vision"})
    assert renamed.status_code == 200
    assert client.get("/api/documents/a").json()["tags"] == ["vision"]


def test_tagged_entry_does_not_change_topic_classification_seam(tmp_path):
    # A tag is a retrieval label; topics remain an independent exporter field.
    entry = ExportEntry(
        document_id="d", title="D", markdown="# D", parsed_at="2024-01-01",
        updated_at="2024-01-01", original_path="", source_ext=".jpg",
        topics=["数学"], tags=["research"],
    )
    assert entry.topics != entry.tags
    assert infer_document_time("Date: 2024-01-01") is not None
