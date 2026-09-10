"""Collection registry helpers for the Knowledge Workspace.

Collections are logical memberships, not directories in the source library.
The slug is deterministic and is also the Obsidian folder key, so the same
collection name always maps to the same export folder.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


class CollectionError(ValueError):
    """Raised when a collection request is invalid."""


def collection_id_for(name: Any) -> str:
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^\w\-]+", "-", text, flags=re.UNICODE)
    text = re.sub(r"-+", "-", text).strip("-").casefold()
    if not text:
        raise CollectionError("集合名称不能为空")
    if len(text) > 80:
        text = text[:80].rstrip("-")
    return text


def new_registry() -> dict[str, Any]:
    return {"version": 1, "collections": {}}


def normalize_registry(raw: Any) -> dict[str, Any]:
    out = new_registry()
    if isinstance(raw, dict) and isinstance(raw.get("collections"), dict):
        source = raw["collections"]
    elif isinstance(raw, dict):
        source = raw
    else:
        source = {}
    for raw_id, details in source.items():
        if isinstance(details, dict):
            name = details.get("name") or raw_id
            source_kind = details.get("source") or "manual"
            topic = details.get("topic")
        else:
            name = details or raw_id
            source_kind = "manual"
            topic = None
        try:
            cid = collection_id_for(raw_id)
            display_name = str(name).strip() or str(raw_id)
        except CollectionError:
            continue
        out["collections"][cid] = {
            "collection_id": cid,
            "name": display_name,
            "source": source_kind if source_kind in ("manual", "topic") else "manual",
            "topic": str(topic) if topic else None,
        }
    return out


def ensure_collection(
    registry: dict[str, Any],
    name: Any,
    *,
    source: str = "manual",
    topic: str | None = None,
) -> tuple[str, bool]:
    cid = collection_id_for(name)
    collections = registry.setdefault("collections", {})
    if cid in collections:
        changed = False
        entry = collections[cid]
        if source == "topic" and entry.get("source") != "topic":
            # A same-named user collection already satisfies the default
            # topic; don't downgrade it or erase its human name.
            return cid, False
        if source == "topic" and topic and entry.get("topic") != topic:
            entry["topic"] = topic
            changed = True
        return cid, changed
    collections[cid] = {
        "collection_id": cid,
        "name": str(name).strip(),
        "source": source if source in ("manual", "topic") else "manual",
        "topic": topic if source == "topic" else None,
    }
    return cid, True


def collection_entries(
    registry: dict[str, Any],
    counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    counts = counts or {}
    return [
        {
            **entry,
            "document_count": int(counts.get(cid, 0)),
            "folder": f"collections/{cid}",
        }
        for cid, entry in sorted(registry.get("collections", {}).items())
    ]


def apply_topic_defaults(record: dict[str, Any], registry: dict[str, Any]) -> bool:
    """Add topic-derived memberships while retaining manual memberships."""

    topics = [str(topic).strip() for topic in (record.get("topics") or []) if str(topic).strip()]
    changed = False
    derived: list[str] = []
    for topic in topics:
        cid, created = ensure_collection(registry, topic, source="topic", topic=topic)
        changed = changed or created
        derived.append(cid)

    existing = list(record.get("collections") or [])
    manual = record.get("manual_collections")
    if manual is None:
        # Records created before this distinction treated all memberships as
        # user-owned.  Topic collections are recognized and kept derived.
        manual = [
            cid for cid in existing
            if (registry.get("collections", {}).get(cid) or {}).get("source") != "topic"
        ]
    manual = list(dict.fromkeys(manual))
    memberships = list(dict.fromkeys(manual + derived))
    if record.get("manual_collections") != manual:
        record["manual_collections"] = manual
        changed = True
    if record.get("collections") != memberships:
        record["collections"] = memberships
        changed = True
    return changed


def set_manual_memberships(
    record: dict[str, Any],
    collection_ids: list[str],
    registry: dict[str, Any],
) -> bool:
    normalized = list(dict.fromkeys(collection_ids))
    missing = [cid for cid in normalized if cid not in registry.get("collections", {})]
    if missing:
        raise CollectionError(f"集合不存在：{', '.join(missing)}")
    before = (record.get("manual_collections"), record.get("collections"))
    record["manual_collections"] = normalized
    apply_topic_defaults(record, registry)
    return before != (record.get("manual_collections"), record.get("collections"))


__all__ = [
    "CollectionError",
    "apply_topic_defaults",
    "collection_entries",
    "collection_id_for",
    "ensure_collection",
    "new_registry",
    "normalize_registry",
    "set_manual_memberships",
]
