"""U5 timeline visual upgrade contracts (offline).

Covers the `/api/timeline` append-only field extensions (thumbnail / source
icon / tag count / gap markers / monthly density), the preserved day-week
grouping semantics, the read-only red line (no write verbs anywhere in the
timeline view) and the static trunk/ticks/density markup.  The Node contract
test (``tests/timeline_view.mjs``) exercises the real frontend module; it is
skipped when ``node`` is unavailable.

No network: everything runs through the local FastAPI TestClient.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph2note.store import FileDocumentStore
from graph2note.timeline import build_timeline
from graph2note.webapp import create_app
from tests.static_assets import WEBSTATIC

TESTS_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _slot(value=None, source="none"):
    return {
        "value": value,
        "source": source,
        "confidence": "high" if value else None,
        "evidence": "fixture" if value else None,
        "manual": source == "manual",
    }


def _record(
    document_id: str,
    title: str,
    *,
    document_time=None,
    topics=None,
    tags=None,
    original_ext=".jpg",
    source_pdf=None,
    latest=None,
    original_path=None,
):
    record = {
        "document_id": document_id,
        "title": title,
        "metadata": {
            "document_time": _slot(
                document_time, "inferred" if document_time else "none"
            ),
            "capture_time": _slot(None, "exif"),
            "import_time": _slot(None, "system"),
        },
        "topics": topics or [],
        "tags": tags or [],
        "collections": [],
        "updated_at": "2024-01-10T10:00:00",
        "original_ext": original_ext,
    }
    if source_pdf:
        record["source_pdf"] = source_pdf
    if latest is not None:
        record["latest"] = latest
    if original_path is not None:
        record["original_path"] = original_path
    return record


def _items(view: dict) -> list[dict]:
    return [item for group in view["groups"] for item in group["items"]]


def _by_id(view: dict) -> dict[str, dict]:
    return {item["document_id"]: item for item in _items(view)}


def _seed(
    store: FileDocumentStore,
    document_id: str,
    title: str,
    metadata: dict,
    *,
    preprocessed: Path | None = None,
    original: Path | None = None,
    source_pdf: str | None = None,
    page_number: int | None = None,
):
    store.save_document(
        document_id=document_id,
        title=title,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {title}\n",
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original) if original else "",
        original_ext=".png" if original else ".jpg",
        preprocessed_path=str(preprocessed) if preprocessed else "",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
        metadata=metadata,
        source_pdf=source_pdf,
        page_number=page_number,
    )


def _png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fixture")
    return path


def _seed_undated(store: FileDocumentStore, document_id: str, title: str) -> None:
    """A pre-workspace record with no usable time at all (no import_time)."""

    base = store.root / "documents" / document_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "record.json").write_text(
        json.dumps({
            "document_id": document_id,
            "title": title,
            "created_at": "",
            "updated_at": "",
            "versions": [],
        }),
        encoding="utf-8",
    )


def _timeline_source() -> str:
    return "\n".join(
        (WEBSTATIC / relative).read_text(encoding="utf-8")
        for relative in ("js/views/timeline.js", "js/timeline_view.js")
    )


# ---------------------------------------------------------------------------
# 1) append-only payload fields
# ---------------------------------------------------------------------------


def test_item_exposes_thumbnail_source_icon_and_counts():
    records = [
        _record(
            "a", "A", document_time="2024-01-01", topics=["数学", "物理"], tags=["重点"],
            original_ext=".png", latest={"preprocessed_path": "/tmp/preprocessed.png"},
        ),
        _record("b", "B", document_time="2024-01-02", original_ext=".jpg"),
        _record("c", "C", document_time="2024-01-03", original_ext="", source_pdf="lecture.pdf"),
        _record(
            "d", "D", document_time="2024-01-04", original_ext="",
            latest={"preprocessed_path": "/tmp/p.png"}, original_path="/tmp/o.png",
        ),
    ]
    view = build_timeline(records)
    items = _by_id(view)

    assert items["a"]["thumbnail_url"] == "/api/documents/a/preprocessed"
    assert items["a"]["source_kind"] == "image"
    assert items["a"]["source_label"] == "图片上传"
    assert items["a"]["tag_count"] == 1
    assert items["a"]["topic_count"] == 2
    assert items["b"]["thumbnail_url"] is None
    assert items["c"]["source_kind"] == "pdf"
    assert items["c"]["source_label"] == "PDF 页面"
    assert items["d"]["thumbnail_url"] == "/api/documents/d/preprocessed"

    # the API handler may resolve the URL against the filesystem; an explicit
    # ``None`` (nothing on disk) must not fall through to a declared path.
    resolved = _record(
        "e", "E", document_time="2024-01-05", original_ext=".png",
        latest={"preprocessed_path": "/tmp/p.png"},
    )
    resolved["thumbnail_url"] = None
    assert _by_id(build_timeline([resolved]))["e"]["thumbnail_url"] is None


def test_existing_fields_keep_their_semantics():
    record = _record(
        "a", "A", document_time="2024-01-02", topics=["数学"], tags=["重点"],
        original_ext=".png", latest={"preprocessed_path": "/tmp/p.png"},
    )
    item = _by_id(build_timeline([record]))["a"]
    for field in (
        "document_id", "title", "date", "effective_time", "topics", "tags",
        "collections", "updated_at", "route", "document_url",
    ):
        assert field in item, field
    assert item["route"] == "#doc/a"
    assert item["document_url"] == "/api/documents/a"
    assert item["effective_time"]["source"] == "inferred"


# ---------------------------------------------------------------------------
# 2) gap markers + preserved grouping semantics
# ---------------------------------------------------------------------------


def test_gap_markers_and_group_dates():
    records = [
        _record("d1", "D1", document_time="2024-01-01"),
        _record("d14", "D14", document_time="2024-01-14"),
        _record("d15", "D15", document_time="2024-01-15"),
        _record("d20", "D20", document_time="2024-01-20"),
    ]
    view = build_timeline(records)
    groups = view["groups"]
    assert [group["key"] for group in groups] == [
        "2024-01-01", "2024-01-14", "2024-01-15", "2024-01-20",
    ]
    assert groups[0]["gap_days"] is None
    assert groups[0]["first_date"] == groups[0]["last_date"] == "2024-01-01"
    assert groups[1]["gap_days"] == 12
    assert groups[2]["gap_days"] == 0
    assert groups[3]["gap_days"] == 4

    weekly = build_timeline(records, group_by="week")
    assert [group["key"] for group in weekly["groups"]] == ["2024-W01", "2024-W02", "2024-W03"]
    assert weekly["groups"][0]["gap_days"] is None
    # W01 ends at document Jan 1; W02's first document is Jan 14 -> 12 days
    assert weekly["groups"][1]["gap_days"] == 12
    # W02's last document is Jan 14; W03's first is Jan 15 -> touching
    assert weekly["groups"][2]["gap_days"] == 0


def test_day_and_week_grouping_semantics_not_regressed():
    records = [
        _record("b", "B", document_time="2024-01-02", topics=["alpha", "beta"]),
        _record("a", "A", document_time="2024-01-02", topics=["beta"]),
        _record("c", "C", document_time="2024-01-02", topics=["alpha"]),
        _record("old", "Old", document_time="2024-01-01", topics=["alpha"]),
        _record("sun", "Sunday", document_time="2024-01-14"),
    ]
    view = build_timeline(records)
    assert [group["key"] for group in view["groups"]] == [
        "2024-01-01", "2024-01-02", "2024-01-14",
    ]
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

    weekly = build_timeline(records, group_by="week")
    assert [group["key"] for group in weekly["groups"]] == ["2024-W01", "2024-W02"]
    assert weekly["groups"][0]["start_date"] == "2024-01-01"
    assert weekly["groups"][0]["end_date"] == "2024-01-07"
    assert [item["document_id"] for item in weekly["groups"][1]["items"]] == ["sun"]

    with pytest.raises(ValueError):
        build_timeline(records, group_by="month")


# ---------------------------------------------------------------------------
# 3) monthly density overview
# ---------------------------------------------------------------------------


def test_monthly_density_counts_and_jump_targets():
    records = [
        _record("jan1", "Jan1", document_time="2024-01-01"),
        _record("jan2", "Jan2", document_time="2024-01-31"),
        _record("feb1", "Feb1", document_time="2024-02-02"),
        _record("feb2", "Feb2", document_time="2024-02-03"),
        _record("feb3", "Feb3", document_time="2024-02-04"),
    ]
    view = build_timeline(records)
    assert [entry["month"] for entry in view["density"]] == ["2024-01", "2024-02"]
    assert [entry["count"] for entry in view["density"]] == [2, 3]
    assert view["density_max"] == 3
    assert view["density"][1]["group_key"] == "2024-02-02"
    assert view["density"][1]["group_key"] in {group["key"] for group in view["groups"]}


def test_density_ignores_undated_documents():
    view = build_timeline([
        _record("dated", "Dated", document_time="2024-01-01"),
        _record("undated", "Undated"),
    ])
    assert [entry["count"] for entry in view["density"]] == [1]
    assert view["undated_count"] == 1
    assert view["has_undated"] is True
    assert view["undated"][0]["date"] is None
    assert view["undated"][0]["route"] == "#doc/undated"


# ---------------------------------------------------------------------------
# 4) API contract (append-only) + empty / undated states
# ---------------------------------------------------------------------------


def test_timeline_api_appends_fields_and_serves_thumbnails(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    preprocessed = _png(tmp_path / "pre.png")
    original = _png(tmp_path / "orig.png")
    _seed(
        store, "doc-a", "A",
        {"document_time": _slot("2024-02-02", "inferred")},
        preprocessed=preprocessed,
    )
    _seed(
        store, "doc-b", "B",
        {"capture_time": _slot("2024-02-03T09:00:00", "exif")},
        original=original, source_pdf="lecture.pdf", page_number=12,
    )
    store.set_tags("doc-a", ["重点"])
    client = TestClient(create_app(document_store=store, storage_dir=store.root))

    payload = client.get("/api/timeline?group_by=day").json()
    assert payload["total"] == 2
    assert payload["density"][0]["month"] == "2024-02"
    assert payload["density_max"] == 2
    first = payload["groups"][0]["items"][0]
    assert first["document_id"] == "doc-a"
    assert first["thumbnail_url"] == "/api/documents/doc-a/preprocessed"
    assert first["source_kind"] == "image"
    assert first["tag_count"] == 1
    assert client.get(first["thumbnail_url"]).status_code == 200

    second = payload["groups"][1]["items"][0]
    assert second["document_id"] == "doc-b"
    assert second["thumbnail_url"] == "/api/documents/doc-b/original"
    assert second["source_kind"] == "pdf"
    assert second["source_label"] == "PDF 页面"
    assert client.get(second["thumbnail_url"]).status_code == 200

    assert client.get("/api/timeline?group_by=month").status_code == 422


def test_timeline_api_empty_and_undated_states(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    client = TestClient(create_app(document_store=store, storage_dir=store.root))
    empty = client.get("/api/timeline").json()
    assert empty["total"] == 0
    assert empty["groups"] == []
    assert empty["undated"] == []
    assert empty["density"] == []
    assert empty["density_max"] == 0
    assert empty["has_undated"] is False

    _seed_undated(store, "undated", "Undated")
    undated = client.get("/api/timeline").json()
    assert undated["has_undated"] is True
    assert undated["undated_count"] == 1
    assert undated["undated"][0]["document_id"] == "undated"
    assert undated["undated"][0]["date"] is None
    assert undated["density"] == []


# ---------------------------------------------------------------------------
# 5) static UI: trunk/ticks/density markup + read-only red line
# ---------------------------------------------------------------------------


def test_static_timeline_markup_is_trunk_based_and_read_only():
    html = (WEBSTATIC / "index.html").read_text(encoding="utf-8")
    zone = html[html.index('id="timeline-zone"'):html.index('id="graph-zone"')]
    assert 'id="timeline-density"' in zone
    assert 'id="timeline-undated-reason"' in zone or "timeline-undated-reason" in zone
    assert 'id="timeline-undated-items"' in zone
    assert "<ol" in zone, "undated entries are list items"
    assert "<form" not in zone
    assert "method=" not in zone
    assert "contenteditable" not in zone

    source = _timeline_source()
    for marker in (
        "timeline-tick", "timeline-gap", "timeline-run-band", "timeline-run-rail",
        "timeline-density-bar", "data-src", "timeline-thumb", "timeline-source",
    ):
        assert marker in source, marker
    # read-only red line: the timeline never issues a write request
    assert re.search(r"method\s*:\s*[\"'](POST|PUT|PATCH|DELETE)", source) is None
    assert "XMLHttpRequest" not in source
    assert "<form" not in source
    # the view loads through the read-only loader (single GET endpoint)
    assert "loadTimeline(api," in source
    assert "/api/timeline?group_by=" in source
    assert "#timeline/day" in source


def test_timeline_zone_wires_change_and_lazy_loading():
    source = (WEBSTATIC / "js/views/timeline.js").read_text(encoding="utf-8")
    assert 'createThumbnailLoader' in source
    assert 'IntersectionObserver' in source
    assert 'loadTimeline(api, groupBy)' in source
    assert 'wireTimeline' in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_timeline_view_node_contract():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "timeline_view.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "all assertions passed" in proc.stdout
