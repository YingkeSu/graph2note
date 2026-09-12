"""Deterministic Timeline view models for the Knowledge Workspace."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote
from typing import Any, Iterable


GROUPINGS = ("day", "week")

# Source-page extensions treated as a single uploaded image (U5 source icon).
_IMAGE_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic",
})


def _value_and_slot(record: dict[str, Any], field: str) -> tuple[str | None, dict[str, Any]]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    raw = metadata.get(field)
    if isinstance(raw, dict):
        # Keep the projection tolerant of records that contain both the
        # canonical metadata object and a legacy scalar alias.  A blank slot
        # must not hide a valid alias while old records are being backfilled.
        value = raw.get("value") or record.get(field)
        slot = raw
    else:
        value = raw if raw is not None else record.get(field)
        slot = {}
    return (str(value) if value else None), slot


def effective_document_time(record: dict[str, Any]) -> dict[str, Any] | None:
    """Select a record's timeline time using the PRD priority chain."""

    # ``document_time`` intentionally comes before ``capture_time`` regardless
    # of whether its source is inferred or manual; a manual correction is
    # represented by the same slot with ``source=manual`` and therefore wins.
    for field in ("document_time", "capture_time", "import_time"):
        value, slot = _value_and_slot(record, field)
        if not value:
            continue
        source = slot.get("source") or ("manual" if slot.get("manual") else field)
        return {
            "field": field,
            "value": value,
            "source": source,
            "confidence": slot.get("confidence"),
            "evidence": slot.get("evidence"),
        }
    return None


def _date_key(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _topics(record: dict[str, Any], scheme: Any = None) -> list[str]:
    topics = [str(topic) for topic in (record.get("topics") or []) if str(topic)]
    if topics or scheme is None:
        return list(dict.fromkeys(topics))
    document_id = record.get("document_id")
    result = []
    for topic in getattr(scheme, "topics", []) or []:
        if document_id in (getattr(scheme, "assignments", {}) or {}).get(topic, []):
            result.append(str(topic))
    return list(dict.fromkeys(result))


def _source_info(record: dict[str, Any]) -> tuple[str, str]:
    """Classify an entry's source page for the timeline source icon.

    The timeline is read-only: this only reads fields the document record
    already carries and never touches the filesystem.
    """

    if record.get("source_pdf") or record.get("pdf_id"):
        return "pdf", "PDF 页面"
    extension = str(record.get("original_ext") or "").lower()
    if extension in _IMAGE_EXTENSIONS:
        return "image", "图片上传"
    return "document", "文档"


def _thumbnail_url(record: dict[str, Any], document_id: str) -> str | None:
    """Read-only preview URL (added U5 field; existing fields untouched).

    The API handler may resolve the URL against the filesystem and pass it in
    as ``thumbnail_url`` (so a missing preprocessed page falls back to the
    original); when called directly this projection trusts the declared store
    paths and stays a pure function.  Prefers the preprocessed page.
    """

    if not document_id:
        return None
    if "thumbnail_url" in record:
        value = record.get("thumbnail_url")
        return str(value) if value else None
    quoted = quote(document_id, safe="")
    latest = record.get("latest") if isinstance(record.get("latest"), dict) else {}
    if latest.get("preprocessed_path"):
        return f"/api/documents/{quoted}/preprocessed"
    if record.get("original_path"):
        return f"/api/documents/{quoted}/original"
    return None


def _item(record: dict[str, Any], effective: dict[str, Any] | None, scheme: Any) -> dict[str, Any]:
    document_id = str(record.get("document_id") or "")
    day = _date_key(effective["value"] if effective else None)
    topics = _topics(record, scheme)
    tags = [str(tag) for tag in (record.get("tags") or []) if str(tag)]
    source_kind, source_label = _source_info(record)
    return {
        "document_id": document_id,
        "title": record.get("title") or document_id,
        "date": day.isoformat() if day else None,
        "effective_time": effective,
        "topics": topics,
        "tags": tags,
        "collections": list(record.get("collections") or []),
        "updated_at": record.get("updated_at") or "",
        "route": f"#doc/{quote(document_id, safe='')}" if document_id else "#library",
        "document_url": f"/api/documents/{quote(document_id, safe='')}" if document_id else None,
        # U5 additions (append-only; existing fields above keep their semantics).
        "thumbnail_url": _thumbnail_url(record, document_id),
        "source_kind": source_kind,
        "source_label": source_label,
        "tag_count": len(tags),
        "topic_count": len(topics),
    }


def _group_descriptor(day: date, group_by: str) -> dict[str, str]:
    if group_by == "day":
        key = day.isoformat()
        return {"key": key, "label": key, "start_date": key, "end_date": key}
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    iso_year, iso_week, _ = start.isocalendar()
    return {
        "key": f"{iso_year:04d}-W{iso_week:02d}",
        "label": f"{start.isoformat()} – {end.isoformat()}",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    }


def _topic_aggregates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order: list[str] = []
    grouped: dict[str, list[str]] = {}
    for item in items:
        for topic in item["topics"]:
            if topic not in grouped:
                grouped[topic] = []
                order.append(topic)
            if item["document_id"] not in grouped[topic]:
                grouped[topic].append(item["document_id"])
    return [
        {"topic": topic, "count": len(grouped[topic]), "document_ids": grouped[topic]}
        for topic in order
    ]


def _monthly_density(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mini density overview: documents per calendar month (U5 bonus).

    ``group_key`` points at the first group in that month so the density bar
    can jump straight to it without re-deriving the grouping in the browser.
    """

    order: list[str] = []
    by_month: dict[str, dict[str, Any]] = {}
    for group in groups:
        month = group["start_date"][:7]
        entry = by_month.get(month)
        if entry is None:
            entry = {
                "month": month,
                "label": month,
                "count": 0,
                "group_key": group["key"],
                "start_date": group["start_date"],
            }
            by_month[month] = entry
            order.append(month)
        entry["count"] += group["count"]
    return [by_month[month] for month in order]


def _adjacent_topic_runs(items: list[dict[str, Any]], group_key: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    last_index: dict[str, int] = {}
    run_index: dict[str, int] = {}
    for index, item in enumerate(items):
        for topic in item["topics"]:
            previous = last_index.get(topic)
            if previous == index - 1 and topic in run_index:
                run = runs[run_index[topic]]
                run["document_ids"].append(item["document_id"])
                run["count"] += 1
            else:
                run_index[topic] = len(runs)
                runs.append({
                    "topic": topic,
                    "count": 1,
                    "document_ids": [item["document_id"]],
                    "group_key": group_key,
                })
            last_index[topic] = index
    return runs


def build_timeline(
    records: Iterable[dict[str, Any]],
    *,
    group_by: str = "day",
    scheme: Any = None,
) -> dict[str, Any]:
    """Project document records into a stable, read-only timeline payload."""

    if group_by not in GROUPINGS:
        raise ValueError("group_by 必须是 day 或 week")

    dated: list[tuple[date, str, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for record in records:
        effective = effective_document_time(record)
        item = _item(record, effective, scheme)
        day = _date_key(effective["value"] if effective else None)
        if day is None:
            undated.append(item)
        else:
            dated.append((day, str(item["document_id"]), item))

    dated.sort(key=lambda value: (value[0], value[2]["effective_time"]["value"], value[1]))
    undated.sort(key=lambda item: (str(item.get("title") or "").casefold(), item["document_id"]))
    by_key: dict[str, dict[str, Any]] = {}
    group_order: list[str] = []
    for day, _, item in dated:
        descriptor = _group_descriptor(day, group_by)
        key = descriptor["key"]
        if key not in by_key:
            by_key[key] = {
                **descriptor,
                "items": [],
                "topic_aggregates": [],
                "adjacent_topic_runs": [],
            }
            group_order.append(key)
        by_key[key]["items"].append(item)

    groups = []
    previous_last: date | None = None
    for key in group_order:
        group = by_key[key]
        group["count"] = len(group["items"])
        group["first_date"] = group["items"][0]["date"]
        group["last_date"] = group["items"][-1]["date"]
        first_day = _date_key(group["first_date"])
        if previous_last is None or first_day is None:
            group["gap_days"] = None
        else:
            # Days between the previous group's last document and this group's
            # first one (0 when the two groups touch).
            group["gap_days"] = max(0, (first_day - previous_last).days - 1)
        previous_last = _date_key(group["last_date"]) or previous_last
        group["topic_aggregates"] = _topic_aggregates(group["items"])
        group["adjacent_topic_runs"] = _adjacent_topic_runs(group["items"], key)
        groups.append(group)

    density = _monthly_density(groups)
    return {
        "group_by": group_by,
        "groups": groups,
        "undated": undated,
        "undated_count": len(undated),
        "total": sum(group["count"] for group in groups) + len(undated),
        "has_undated": bool(undated),
        "density": density,
        "density_max": max((entry["count"] for entry in density), default=0),
    }


__all__ = ["GROUPINGS", "build_timeline", "effective_document_time"]
