"""Offline contracts for the Knowledge Workspace issue 05 graph."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from graph2note.notes.classify import ClassificationScheme
from graph2note.store import FileDocumentStore
from graph2note.graph import build_graph
from graph2note.webapp import create_app

from tests.static_assets import static_js


def _record(
    document_id: str,
    title: str,
    *,
    topics=None,
    tags=None,
    manual_collections=None,
    collection_names=None,
    manual_relations=None,
):
    return {
        "document_id": document_id,
        "title": title,
        "topics": topics or [],
        "tags": tags or [],
        "manual_collections": manual_collections or [],
        "collection_names": collection_names or {},
        "manual_relations": manual_relations or [],
    }


def test_graph_snapshot_has_stable_nodes_edges_sources_and_navigation():
    records = [
        _record(
            "d2",
            "B",
            tags=["重点"],
            manual_collections=["research"],
            collection_names={"research": "研究"},
            manual_relations=[{"target": "d1"}],
        ),
        _record("d3", "孤立文档"),
        _record("d1", "A", tags=["重点", "草稿"]),
    ]
    scheme = ClassificationScheme(
        topics=["数学", "空主题"],
        assignments={"数学": ["d1"]},
        summaries={},
    )

    view = build_graph(records, scheme=scheme)
    reversed_view = build_graph(list(reversed(records)), scheme=scheme)

    assert view == reversed_view
    assert view["sources"] == ["topic", "tag", "manual"]
    assert view["empty"] is False
    assert {node["id"] for node in view["nodes"]} == {
        "document:d1", "document:d2", "document:d3",
        "topic:数学", "topic:空主题", "tag:重点", "tag:草稿",
        "collection:research",
    }
    assert view["nodes"][-1]["route"] == "#library/collection/research"
    assert next(node for node in view["nodes"] if node["id"] == "document:d1")["route"] == "#doc/d1"
    assert next(node for node in view["nodes"] if node["id"] == "topic:数学")["route"] == "#library/topic/%E6%95%B0%E5%AD%A6"
    assert next(node for node in view["nodes"] if node["id"] == "tag:重点")["route"] == "#library/tag/%E9%87%8D%E7%82%B9"

    sources = {(edge["from"], edge["to"]): edge["source"] for edge in view["edges"]}
    assert sources["document:d1", "topic:数学"] == "topic"
    assert sources["document:d1", "tag:重点"] == "tag"
    assert sources["document:d2", "document:d1"] == "manual"
    assert sources["document:d2", "collection:research"] == "manual"
    assert all(edge["source"] in {"topic", "tag", "manual"} for edge in view["edges"])
    assert next(node for node in view["nodes"] if node["id"] == "document:d3")["isolated"] is True
    assert next(node for node in view["nodes"] if node["id"] == "topic:空主题")["isolated"] is True


def test_empty_graph_is_explicit_and_does_not_infer_edges():
    view = build_graph([_record("d1", "Only", manual_relations=[
        {"target": "d2", "source": "inferred"},
    ])])
    assert view["edges"] == []
    assert view["sources"] == []
    assert view["empty"] is False  # the lone document remains navigable
    assert view["nodes"][0]["isolated"] is True
    assert build_graph([]) == {
        "nodes": [], "edges": [], "sources": [], "empty": True,
        "counts": {
            "nodes": 0, "edges": 0, "documents": 0, "topics": 0,
            "tags": 0, "collections": 0,
        },
    }


def _seed(store: FileDocumentStore, document_id: str, title: str):
    store.save_document(
        document_id=document_id,
        title=title,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {title}\n",
        ir_json=json.dumps({"blocks": []}),
        original_path="",
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
    )


def test_graph_api_and_library_navigation_filters_are_offline(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "d1", "数学笔记")
    _seed(store, "d2", "草稿")
    store.set_topics("d1", ["数学"])
    store.set_tags("d1", ["重点"])
    research = store.create_collection("研究")
    store.set_collections("d1", [research["collection_id"]])
    client = TestClient(create_app(document_store=store, storage_dir=store.root))

    graph = client.get("/api/graph")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["counts"]["nodes"] >= 4
    assert {edge["source"] for edge in payload["edges"]} == {"topic", "tag", "manual"}
    assert next(node for node in payload["nodes"] if node["kind"] == "document" and node["document_id"] == "d1")["route"] == "#doc/d1"

    assert [item["document_id"] for item in client.get("/api/documents?topic=数学").json()] == ["d1"]
    assert [item["document_id"] for item in client.get("/api/documents?tag=重点").json()] == ["d1"]

    html = client.get("/").text
    javascript = static_js()
    assert 'id="nav-graph"' in html
    assert 'id="graph-zone"' in html
    assert "/api/graph" in javascript
    assert 'parts[1] === "topic"' in javascript
    assert 'parts[1] === "tag"' in javascript
