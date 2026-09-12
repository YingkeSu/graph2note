"""Pure Inbox projection for document-level workspace organization.

The Inbox is a read-only view over document metadata.  It does not infer a
new classification and it does not inspect or mutate Markdown content.  A
record is actionable when it has no topic, no tag, has an explicit
``needs_organization`` marker, or already contains a low-confidence/review
signal from another subsystem.
"""

from __future__ import annotations

from typing import Any, Iterable


REASON_LABELS = {
    "no_topic": "无主题",
    "no_tag": "无标签",
    "explicit": "标记待整理",
    "low_confidence": "低置信度",
    # Issue 03: a continuity pair (same-PDF adjacent pages / tail-head overlap)
    # that the user can confirm or reject.  Projected only when the caller
    # supplies the candidate evidence (``merge_reasons=``); the pure inbox
    # reasons above are unchanged.
    "merge_candidate": "可合并",
}

_FLAG_KEYS = (
    "needs_organization",
    "inbox",
    "pending_organization",
    "pending",
)
_LOW_CONFIDENCE_VALUES = {"low", "低", "degraded", "needs_review", "待复核"}
_LOW_SIGNAL_KEYS = {
    "low_confidence",
    "needs_review",
    "review_required",
    "degraded",
}


def _values(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple, set)):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _has_values(value: Any) -> bool:
    return any(item is not None and str(item).strip() for item in _values(value))


def _text_values(value: Any) -> list[str]:
    return [str(item).strip() for item in _values(value)
            if item is not None and str(item).strip()]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "待整理"}:
            return True
        if normalized in {"", "0", "false", "no", "off", "已整理"}:
            return False
    return bool(value)


def _explicit_flag(record: dict[str, Any]) -> bool:
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in _FLAG_KEYS:
            if key in metadata and _as_bool(metadata.get(key)):
                return True
    for key in _FLAG_KEYS:
        if key in record and _as_bool(record.get(key)):
            return True
    return False


def _has_low_confidence(value: Any) -> bool:
    """Read only explicitly-present review signals from existing metadata."""

    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).strip().casefold()
            if normalized_key in {"confidence", "confidence_level"}:
                if isinstance(item, str) and item.strip().casefold() in _LOW_CONFIDENCE_VALUES:
                    return True
            if normalized_key in _LOW_SIGNAL_KEYS and _as_bool(item):
                return True
            if isinstance(item, (dict, list, tuple)) and _has_low_confidence(item):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_has_low_confidence(item) for item in value)
    return False


def inbox_reasons(record: dict[str, Any]) -> list[str]:
    """Return deterministic reason codes for why a record belongs in Inbox."""

    reasons: list[str] = []
    if not _has_values(record.get("topics")):
        reasons.append("no_topic")
    if not _has_values(record.get("tags")):
        reasons.append("no_tag")
    if _explicit_flag(record):
        reasons.append("explicit")
    if _has_low_confidence(record):
        reasons.append("low_confidence")
    return reasons


def is_inbox(record: dict[str, Any]) -> bool:
    """Whether a document record should appear in Inbox."""

    return isinstance(record, dict) and bool(inbox_reasons(record))


def _view_item(record: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    metadata = record.get("metadata")
    metadata = dict(metadata) if isinstance(metadata, dict) else {}
    return {
        "document_id": record.get("document_id"),
        "title": record.get("title") or record.get("document_id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "version_count": len(record.get("versions") or []),
        "metadata": metadata,
        "effective_time": record.get("effective_time") or metadata.get("effective_time"),
        "topics": _text_values(record.get("topics")),
        "tags": _text_values(record.get("tags")),
        "collections": _text_values(record.get("collections")),
        "needs_organization": _explicit_flag(record),
        "inbox_reasons": reasons,
        "inbox_reason_labels": [REASON_LABELS[reason] for reason in reasons],
    }


def build_inbox(
    records: Iterable[dict[str, Any]],
    *,
    merge_reasons: dict[str, list[str]] | None = None,
) -> list[dict[str, Any]]:
    """Project records into Inbox items without exposing editable Markdown.

    ``merge_reasons`` (issue 03) maps a document id to continuity evidence
    labels; documents appearing there gain the ``merge_candidate`` reason and
    carry the labels in ``merge_evidence`` so the UI can explain *why*.
    """

    evidence = merge_reasons or {}
    result: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        reasons = inbox_reasons(record)
        extra = evidence.get(str(record.get("document_id")))
        if extra and "merge_candidate" not in reasons:
            reasons = [*reasons, "merge_candidate"]
        if reasons:
            item = _view_item(record, reasons)
            if extra:
                item["merge_evidence"] = list(extra)
            result.append(item)
    return result


__all__ = [
    "REASON_LABELS",
    "build_inbox",
    "inbox_reasons",
    "is_inbox",
]
