"""Deterministic Timeline view models for the Knowledge Workspace."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote
from typing import Any, Iterable


GROUPINGS = ("day", "week")


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


def _item(record: dict[str, Any], effective: dict[str, Any] | None, scheme: Any) -> dict[str, Any]:
    document_id = str(record.get("document_id") or "")
    day = _date_key(effective["value"] if effective else None)
    return {
        "document_id": document_id,
        "title": record.get("title") or document_id,
        "date": day.isoformat() if day else None,
        "effective_time": effective,
        "topics": _topics(record, scheme),
        "tags": list(record.get("tags") or []),
        "collections": list(record.get("collections") or []),
        "updated_at": record.get("updated_at") or "",
        "route": f"#doc/{quote(document_id, safe='')}" if document_id else "#library",
        "document_url": f"/api/documents/{quote(document_id, safe='')}" if document_id else None,
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
    for key in group_order:
        group = by_key[key]
        group["count"] = len(group["items"])
        group["topic_aggregates"] = _topic_aggregates(group["items"])
        group["adjacent_topic_runs"] = _adjacent_topic_runs(group["items"], key)
        groups.append(group)

    return {
        "group_by": group_by,
        "groups": groups,
        "undated": undated,
        "undated_count": len(undated),
        "total": sum(group["count"] for group in groups) + len(undated),
        "has_undated": bool(undated),
    }


__all__ = ["GROUPINGS", "build_timeline", "effective_document_time"]
