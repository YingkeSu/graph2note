"""Offline API + store contracts for paper metadata/references (SPW I 轨 P2).

Uses a durable ``FileDocumentStore`` and a FastAPI ``TestClient``; the optional
LLM seam is an injected stub, so CI never touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app

FIXTURES = Path(__file__).parent / "fixtures" / "papers"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _seed(store: FileDocumentStore, document_id: str, title: str, doi: str = "") -> None:
    assets = store.root / "seed" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    store.save_document(
        document_id=document_id,
        title=title,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {title}",
        ir_json="{}",
        original_path="",
        original_ext=".pdf",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir=str(assets.parent),
        timing_json={},
    )
    if doi:
        store.set_paper_meta(document_id, {
            "title": title, "doi": doi, "source": "text-layer",
        })
    else:
        store.set_paper_meta(document_id, {"title": title, "source": "text-layer"})


def _client(tmp_path: Path):
    store = FileDocumentStore(tmp_path)
    _seed(store, "doc-gnn", "Graph Neural Networks for Document Understanding",
          "10.1109/TKDE.2023.1234567")
    _seed(store, "doc-cvpr", "Robust Feature Matching under Extreme Viewpoint Changes")
    return store, TestClient(create_app(document_store=store, storage_dir=tmp_path))


def _attach_references(store: FileDocumentStore, document_id: str) -> None:
    from graph2note.papers import references as papers_references

    parsed = papers_references.parse_references(_fixture("references_numbered.txt"))
    store.set_paper_references(
        document_id,
        [ref.model_dump() for ref in parsed.references],
        provenance=[p.model_dump() for p in parsed.provenance],
    )


# ---------------------------------------------------------------------------
# Deterministic parse endpoint (stateless)
# ---------------------------------------------------------------------------

def test_parse_metadata_endpoint_is_deterministic(tmp_path):
    _store, client = _client(tmp_path)
    body = {
        "front_text": _fixture("front_single_column.txt"),
        "references_text": _fixture("references_numbered.txt"),
    }
    first = client.post("/api/papers/parse-metadata", json=body)
    second = client.post("/api/papers/parse-metadata", json=body)
    assert first.status_code == 200
    assert first.json() == second.json()
    payload = first.json()
    assert payload["meta"]["title"].startswith("Graph Neural Networks")
    assert len(payload["references"]) == 3
    assert payload["meta_provenance"]["doi"]["confidence"] == "high"


def test_parse_metadata_requires_text(tmp_path):
    _store, client = _client(tmp_path)
    assert client.post("/api/papers/parse-metadata", json={}).status_code == 422
    assert client.post("/api/papers/parse-metadata",
                       json={"front_text": "x", "source": "bogus"}).status_code == 422


# ---------------------------------------------------------------------------
# Stored metadata: read / manual correction / durability
# ---------------------------------------------------------------------------

def test_metadata_read_update_and_durable_reload(tmp_path):
    store, client = _client(tmp_path)
    assert client.get("/api/papers/doc-cvpr/metadata").json()["meta"]["doi"] == ""

    response = client.put("/api/papers/doc-cvpr/metadata", json={"meta": {
        "title": "Corrected Title",
        "authors": ["A. Author"],
        "year": 2021,
        "doi": "https://doi.org/10.1/ABC",
        "source": "text-layer",
    }})
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["title"] == "Corrected Title"
    assert payload["meta"]["doi"] == "10.1/abc"
    assert payload["meta"]["source"] == "manual"
    assert payload["meta_provenance"]["title"]["source"] == "manual"

    reloaded = FileDocumentStore(tmp_path)
    client2 = TestClient(create_app(document_store=reloaded, storage_dir=tmp_path))
    assert client2.get("/api/papers/doc-cvpr/metadata").json()["meta"]["title"] == "Corrected Title"
    assert store.paper_payload("doc-cvpr")["meta"]["title"] == "Corrected Title"


def test_metadata_validation_rejects_unknown_fields(tmp_path):
    _store, client = _client(tmp_path)
    bad = client.put("/api/papers/doc-cvpr/metadata",
                     json={"meta": {"title": "x", "bogus": 1}})
    assert bad.status_code == 422


def test_unknown_document_is_404(tmp_path):
    _store, client = _client(tmp_path)
    assert client.get("/api/papers/nope/metadata").status_code == 404
    assert client.post("/api/papers/nope/references/resolve").status_code == 404


# ---------------------------------------------------------------------------
# Reference resolution
# ---------------------------------------------------------------------------

def test_references_resolve_backfills_only_real_matches(tmp_path):
    store, client = _client(tmp_path)
    _attach_references(store, "doc-gnn")
    response = client.post("/api/papers/doc-gnn/references/resolve")
    assert response.status_code == 200
    payload = response.json()
    resolved = [item["resolved_document_id"] for item in payload["references"]]
    assert resolved[0] == "doc-gnn"  # DOI match against the library
    assert resolved[1] == "doc-cvpr"  # normalized-title match
    assert resolved[2] is None
    assert payload["unresolved"] == 1


def test_manual_resolution_and_clearing(tmp_path):
    store, client = _client(tmp_path)
    _attach_references(store, "doc-gnn")

    response = client.patch("/api/papers/doc-gnn/references/1",
                            json={"resolved_document_id": "doc-cvpr"})
    assert response.status_code == 200
    assert response.json()["references"][1]["resolved_document_id"] == "doc-cvpr"

    cleared = client.patch("/api/papers/doc-gnn/references/1",
                           json={"resolved_document_id": None})
    assert cleared.json()["references"][1]["resolved_document_id"] is None

    assert client.patch("/api/papers/doc-gnn/references/99",
                        json={"resolved_document_id": None}).status_code == 422
    assert client.patch("/api/papers/doc-gnn/references/0",
                        json={"resolved_document_id": "missing"}).status_code == 404


def test_store_lists_paper_entries(tmp_path):
    store, _client_ = _client(tmp_path)
    entries = store.list_paper_entries()
    assert [entry["document_id"] for entry in entries] == ["doc-cvpr", "doc-gnn"]
    by_id = {entry["document_id"]: entry for entry in entries}
    assert by_id["doc-gnn"]["doi"] == "10.1109/TKDE.2023.1234567"


# ---------------------------------------------------------------------------
# Optional LLM enhancement seam (injected stub; never live in tests)
# ---------------------------------------------------------------------------

def test_enhance_endpoint_uses_injected_planner_offline(tmp_path):
    store, _ = _client(tmp_path)
    app = create_app(document_store=store, storage_dir=tmp_path)
    app.state.paper_meta_planner = lambda prompt, model: (
        json.dumps({"doi": "10.2222/llm", "title": "Should Not Win"}), {})
    client = TestClient(app)

    response = client.post("/api/papers/doc-cvpr/metadata/enhance",
                           json={"front_text": _fixture("front_two_column.txt")})
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"]["doi"] == "10.2222/llm"
    assert payload["meta"]["title"] == "Robust Feature Matching under Extreme Viewpoint Changes"
    assert payload["meta_provenance"]["doi"]["source"] == "vlm"


def test_enhance_endpoint_is_offline_by_default(tmp_path):
    store, _ = _client(tmp_path)
    app = create_app(document_store=store, storage_dir=tmp_path)
    client = TestClient(app)
    before = client.get("/api/papers/doc-gnn/metadata").json()["meta"]
    response = client.post("/api/papers/doc-gnn/metadata/enhance", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["meta"] == before
    assert "llm-planner-absent" in payload["notes"]
