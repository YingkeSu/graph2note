"""Offline contracts for Knowledge Workspace issue 03."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from graph2note.notes.exporter import ExportEntry, export_incremental, export_vault
from graph2note.notes.loader import load_entries
from graph2note.store import FileDocumentStore, SessionDocumentStore
from graph2note.webapp import create_app


def _seed(store, document_id: str):
    original = Path(store.root) / f"{document_id}.jpg"
    original.write_bytes(b"fixture-image-" + document_id.encode())
    store.save_document(
        document_id=document_id, title=document_id, source_job_id=f"job-{document_id}",
        model="fixture", markdown=f"# {document_id}\n", ir_json=json.dumps({"blocks": []}),
        original_path=str(original), original_ext=".jpg", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={},
    )


def test_many_to_many_membership_crud_and_reload_without_file_moves(tmp_path):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "doc-a")
    alpha = store.create_collection("毕业设计")
    beta = store.create_collection("强化学习")
    record = store.set_collections("doc-a", [alpha["collection_id"], beta["collection_id"]])
    assert set(record["collections"]) == {"毕业设计", "强化学习"}
    original = root / "documents" / "doc-a" / "original.jpg"
    assert original.is_file()

    reloaded = FileDocumentStore(root)
    assert set(reloaded.get_document("doc-a")["collections"]) == {"毕业设计", "强化学习"}
    renamed = reloaded.rename_collection("毕业设计", "毕业论文")
    assert renamed["collection_id"] == "毕业论文"
    assert reloaded.get_document("doc-a")["collections"] == ["毕业论文", "强化学习"]
    assert reloaded.delete_collection("强化学习") is True
    assert reloaded.get_document("doc-a")["collections"] == ["毕业论文"]
    assert original.is_file()
    assert (root / "documents" / "doc-a").is_dir()


def test_topic_classification_derives_default_collection_but_manual_membership_survives(tmp_path):
    store = SessionDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    manual = store.create_collection("手工集合")
    store.set_collections("doc-a", [manual["collection_id"]])
    store.set_topics("doc-a", ["数学"])
    record = store.get_document("doc-a")
    assert record["collections"] == ["手工集合", "数学"]
    assert record["manual_collections"] == ["手工集合"]
    assert {item["collection_id"] for item in store.list_collections()} == {"手工集合", "数学"}

    store.set_topics("doc-a", ["物理"])
    assert store.get_document("doc-a")["collections"] == ["手工集合", "物理"]


def test_collection_export_mapping_is_deterministic_and_incremental(tmp_path):
    original = tmp_path / "source.jpg"
    original.write_bytes(b"image")
    entry = ExportEntry(
        document_id="doc-a", title="A", markdown="# A", parsed_at="2024-01-01",
        updated_at="2024-01-01", original_path=str(original), source_ext=".jpg",
        collections=["毕业设计", "强化学习"],
    )
    vault = export_vault([entry], tmp_path / "vault")
    assert (vault.root / "collections" / "毕业设计" / "doc-a.md").is_file()
    assert (vault.root / "collections" / "强化学习" / "doc-a.md").is_file()
    assert "collections/毕业设计/doc-a.md" in json.loads(vault.manifest_path.read_text())["collection_files"]

    changed = ExportEntry(**{**entry.__dict__, "collections": ["新集合"], "updated_at": "2024-01-02"})
    report, _ = export_incremental([changed], vault.root)
    assert "collections/毕业设计/doc-a.md" in report["deleted"]
    assert "collections/新集合/doc-a.md" in report["added"]
    assert not (vault.root / "collections" / "毕业设计" / "doc-a.md").exists()


def test_collection_api_filter_and_document_membership_contract(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    client = TestClient(create_app(document_store=store, storage_dir=store.root))
    created = client.post("/api/collections", json={"name": "研究"})
    assert created.status_code == 200
    cid = created.json()["collection_id"]
    assert client.put(f"/api/documents/doc-a/collections", json={"collection_ids": [cid]}).status_code == 200
    assert [d["document_id"] for d in client.get(f"/api/documents?collection_id={cid}").json()] == ["doc-a"]
    assert client.get("/api/collections").json()[0]["document_count"] == 1
    renamed = client.patch(f"/api/collections/{cid}", json={"name": "研究项目"})
    assert renamed.status_code == 200
    new_id = renamed.json()["collection_id"]
    assert client.get("/api/documents/doc-a").json()["collections"] == [new_id]
    deleted = client.delete(f"/api/collections/{new_id}")
    assert deleted.status_code == 200
    assert client.get("/api/documents/doc-a").json()["collections"] == []


def test_loader_exposes_collection_names_to_exporter(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    collection = store.create_collection("研究")
    store.set_collections("doc-a", [collection["collection_id"]])
    entries = load_entries(FileDocumentStore(tmp_path / "storage"))
    assert entries[0].collections == ["研究"]
