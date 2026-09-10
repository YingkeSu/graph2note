"""Offline contracts for the Knowledge Workspace issue 04 timeline."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from graph2note.store import FileDocumentStore
from graph2note.timeline import build_timeline, effective_document_time
from graph2note.webapp import create_app


def _slot(value=None, source="none", *, manual=False):
    return {
        "value": value,
        "source": source,
        "confidence": "high" if value else None,
        "evidence": "fixture" if value else None,
        "manual": manual,
    }


def _record(
    document_id: str,
    title: str,
    *,
    document_time=None,
    document_source="none",
    document_manual=False,
    capture_time=None,
    import_time=None,
    topics=None,
    tags=None,
    collections=None,
):
    return {
        "document_id": document_id,
        "title": title,
        "metadata": {
            "document_time": _slot(document_time, document_source, manual=document_manual),
            "capture_time": _slot(capture_time, "exif"),
            "import_time": _slot(import_time, "system"),
        },
        "topics": topics or [],
        "tags": tags or [],
        "collections": collections or [],
        "updated_at": "2024-01-10T10:00:00",
    }


def test_effective_time_priority_and_safe_undated_fallback():
    manual = _record(
        "manual", "Manual", document_time="2024-01-03", document_source="manual",
        document_manual=True, capture_time="2024-01-05T10:00:00",
        import_time="2024-01-06T10:00:00",
    )
    inferred = _record(
        "inferred", "Inferred", document_time="2024-01-04", document_source="inferred",
        capture_time="2024-01-05T10:00:00", import_time="2024-01-06T10:00:00",
    )
    captured = _record(
        "captured", "Captured", capture_time="2024-01-05T10:00:00",
        import_time="2024-01-06T10:00:00",
    )
    imported = _record("imported", "Imported", import_time="2024-01-06T10:00:00")
    undated = _record("undated", "Undated")

    assert effective_document_time(manual)["source"] == "manual"
    assert effective_document_time(inferred)["field"] == "document_time"
    assert effective_document_time(captured)["field"] == "capture_time"
    assert effective_document_time(imported)["field"] == "import_time"
    assert effective_document_time(undated) is None

    view = build_timeline([manual, inferred, captured, imported, undated])
    assert view["total"] == 5
    assert view["groups"][0]["items"][0]["document_id"] == "manual"
    assert [item["document_id"] for item in view["undated"]] == ["undated"]
    assert view["undated"][0]["date"] is None


def test_day_timeline_has_stable_sort_topics_runs_and_locator():
    records = [
        _record("b", "B", document_time="2024-01-02", topics=["alpha", "beta"]),
        _record("a", "A", document_time="2024-01-02", topics=["beta"]),
        _record("c", "C", document_time="2024-01-02", topics=["alpha"]),
        _record("old", "Old", document_time="2024-01-01", topics=["alpha"]),
    ]

    view = build_timeline(records)

    assert [group["key"] for group in view["groups"]] == ["2024-01-01", "2024-01-02"]
    day = view["groups"][1]
    assert [item["document_id"] for item in day["items"]] == ["a", "b", "c"]
    assert day["topic_aggregates"] == [
        {"topic": "beta", "count": 2, "document_ids": ["a", "b"]},
        {"topic": "alpha", "count": 2, "document_ids": ["b", "c"]},
    ]
    assert day["adjacent_topic_runs"] == [
        {"topic": "beta", "count": 2, "document_ids": ["a", "b"], "group_key": "2024-01-02"},
        {"topic": "alpha", "count": 2, "document_ids": ["b", "c"], "group_key": "2024-01-02"},
    ]
    assert day["items"][0]["route"] == "#doc/a"
    assert day["items"][0]["document_url"] == "/api/documents/a"


def test_week_grouping_and_scheme_topic_fallback():
    records = [
        _record("mon", "Monday", document_time="2024-01-08"),
        _record("sun", "Sunday", document_time="2024-01-14"),
    ]

    class Scheme:
        topics = ["课程"]
        assignments = {"课程": ["mon", "sun"]}

    view = build_timeline(records, group_by="week", scheme=Scheme())

    assert len(view["groups"]) == 1
    group = view["groups"][0]
    assert group["key"] == "2024-W02"
    assert group["start_date"] == "2024-01-08"
    assert group["end_date"] == "2024-01-14"
    assert group["topic_aggregates"] == [
        {"topic": "课程", "count": 2, "document_ids": ["mon", "sun"]}
    ]


def _seed(store: FileDocumentStore, document_id: str, title: str, metadata: dict):
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
        metadata=metadata,
    )


def test_timeline_api_and_static_ui_contract_are_offline(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", "A", {
        "document_time": _slot("2024-02-02", "inferred"),
    })
    _seed(store, "doc-b", "B", {
        "capture_time": _slot("2024-02-03T09:00:00", "exif"),
    })
    topic_collection = store.create_collection("研究")
    store.set_topics("doc-a", ["数学"])
    store.set_tags("doc-a", ["重点"])
    store.set_collections("doc-a", [topic_collection["collection_id"]])
    client = TestClient(create_app(document_store=store, storage_dir=store.root))

    daily = client.get("/api/timeline?group_by=day")
    assert daily.status_code == 200
    payload = daily.json()
    assert payload["total"] == 2
    assert [group["key"] for group in payload["groups"]] == ["2024-02-02", "2024-02-03"]
    assert payload["groups"][0]["items"][0]["document_id"] == "doc-a"
    assert payload["groups"][0]["items"][0]["topics"] == ["数学"]
    assert payload["groups"][0]["items"][0]["tags"] == ["重点"]
    assert payload["groups"][0]["items"][0]["route"] == "#doc/doc-a"

    weekly = client.get("/api/timeline?group_by=week")
    assert weekly.status_code == 200
    assert weekly.json()["groups"][0]["key"] == "2024-W05"
    filtered = client.get("/api/timeline", params={"collection_id": "研究"})
    assert [item["document_id"] for item in filtered.json()["groups"][0]["items"]] == ["doc-a"]
    assert client.get("/api/timeline?group_by=month").status_code == 422

    html = client.get("/").text
    assert 'id="nav-timeline"' in html
    assert 'id="timeline-zone"' in html
    javascript = client.get("/static/app.js").text
    assert "/api/timeline?group_by=" in javascript
    assert "#timeline/day" in javascript
