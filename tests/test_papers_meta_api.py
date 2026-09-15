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


# ---------------------------------------------------------------------------
# PUT (whole-slot replace) vs PATCH (partial merge) — SPEC §2
# ---------------------------------------------------------------------------

_RICH_META = {
    "title": "Graph Neural Networks for Document Understanding",
    "authors": ["A. Author", "B. Author"],
    "year": 2023,
    "venue": "IEEE TKDE",
    "doi": "10.1109/tkde.2023.1234567",
    "abstract": "We study document understanding.",
    "keywords": ["gnn", "documents"],
    "source": "text-layer",
}

_RICH_PROVENANCE = {
    "title": {"source": "text-layer", "confidence": "high", "evidence": "front"},
    "doi": {"source": "text-layer", "confidence": "high", "evidence": "front"},
    "year": {"source": "text-layer", "confidence": "medium", "evidence": "front"},
}

_MANUAL = {"source": "manual", "confidence": "high", "evidence": "用户手工修正"}

_PAYLOAD_KEYS = {"document_id", "doc_kind", "meta", "meta_provenance",
                 "references", "references_provenance", "notes"}


def _seed_rich(store: FileDocumentStore, document_id: str) -> None:
    store.set_paper_meta(document_id, dict(_RICH_META),
                         provenance=dict(_RICH_PROVENANCE), source="text-layer")


def test_patch_metadata_merges_only_the_provided_fields(tmp_path):
    store, client = _client(tmp_path)
    _seed_rich(store, "doc-gnn")

    response = client.patch("/api/papers/doc-gnn/metadata",
                            json={"meta": {"title": "New Title"}})
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == _PAYLOAD_KEYS  # GET/_paper_payload shape unchanged

    expected = dict(_RICH_META, title="New Title", source="manual")
    assert payload["meta"] == expected  # every omitted field keeps its value

    provenance = payload["meta_provenance"]
    assert provenance["title"] == _MANUAL  # only the provided field flips
    for field, value in _RICH_PROVENANCE.items():
        if field != "title":
            assert provenance[field] == value
    for field in ("authors", "venue", "abstract", "keywords"):
        assert field not in provenance  # untouched, never invented

    assert store.paper_payload("doc-gnn")["meta"] == expected

    reloaded = FileDocumentStore(tmp_path)
    client2 = TestClient(create_app(document_store=reloaded, storage_dir=tmp_path))
    got = client2.get("/api/papers/doc-gnn/metadata").json()
    assert got["meta"] == expected  # durable reload keeps the merged slot
    assert got["meta_provenance"] == provenance


def test_patch_metadata_accepts_several_fields_without_clearing_the_rest(tmp_path):
    store, client = _client(tmp_path)
    _seed_rich(store, "doc-gnn")

    response = client.patch("/api/papers/doc-gnn/metadata", json={"meta": {
        "authors": ["C. Author"],
        "year": 2024,
    }})
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta["authors"] == ["C. Author"]
    assert meta["year"] == 2024
    assert meta["title"] == _RICH_META["title"]
    assert meta["venue"] == _RICH_META["venue"]
    assert meta["doi"] == _RICH_META["doi"]
    assert meta["abstract"] == _RICH_META["abstract"]
    assert meta["keywords"] == _RICH_META["keywords"]


def test_put_metadata_still_replaces_the_whole_slot(tmp_path):
    store, client = _client(tmp_path)
    _seed_rich(store, "doc-gnn")

    response = client.put("/api/papers/doc-gnn/metadata",
                          json={"meta": {"title": "Only Title"}})
    assert response.status_code == 200
    meta = response.json()["meta"]
    assert meta == {"title": "Only Title", "authors": [], "year": None,
                    "venue": "", "doi": "", "abstract": "",
                    "keywords": [], "source": "manual"}


def test_metadata_writes_keep_422_and_never_partially_write(tmp_path):
    store, client = _client(tmp_path)
    _seed_rich(store, "doc-gnn")
    before = client.get("/api/papers/doc-gnn/metadata").json()

    for method in (client.put, client.patch):
        body = {"meta": {"bogus": 1}}
        assert method("/api/papers/doc-gnn/metadata", json=body).status_code == 422
        assert method("/api/papers/doc-gnn/metadata",
                      json={"meta": {"year": "not-a-year"}}).status_code == 422
        assert method("/api/papers/doc-gnn/metadata",
                      json={"meta": "nope"}).status_code == 422

    assert client.get("/api/papers/doc-gnn/metadata").json() == before
    assert store.paper_payload("doc-gnn")["meta"] == _RICH_META


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
