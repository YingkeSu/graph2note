"""Evolution anchoring (issue S2): version chain + pHash cross-document hints.

Two strictly separated anchoring lines answer *"what versions / evolution does
this manuscript have?"*:

1. **Same ``document_id`` version chain (deterministic, primary anchor).**
   :func:`build_version_chain` turns the store's persisted versions into a
   time-ordered *evolution timeline*: every entry carries its creation time, its
   **source** (initial parse / re-parse / edit save / R1 repair) and the S1
   :class:`~graph2note.semantic.DiffReport` summary against the previous entry,
   including block-level locations.  Empty and single-version documents are
   safe (``diff`` is simply ``null``).

2. **pHash cross-document candidates (suggestive, secondary anchor).**
   :func:`find_phash_candidates` lists other documents whose *page* perceptual
   hash is close to this document's — "this may be the same manuscript".  It is
   **read-only and never auto-links**: the user must confirm, which persists a
   regular ``manual`` relation (the existing graph model, no new edge type), or
   reject, which is remembered so the same pair is not suggested again.

Nothing here calls a model: hashing is pure numpy/PIL and the diff engine is
S1's pure function.  Version metadata (including the R1 ``provenance`` field)
is read from the store; edit saves are surfaced as an uncommitted ``edit`` head
because :meth:`~graph2note.store.DocumentStore.save_edits` does not create a new
persisted version.

Provenance contract (agreed with R1): a repaired re-run version carries
``provenance == "repair"`` (``graph2note.repair.PROVENANCE_REPAIR``) plus a
``provenance_detail`` object in ``record.json`` version metadata.  Versions
without the field are treated as ``parse`` (first version) / ``reparse``
(later versions).  An explicit but unrecognised value is reported as
``unknown``.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from .ingest.hash import hamming
from .ir import IRValidationError, DocumentIR, load_dict_as_ir, loads_ir
from .semantic import diff_ir
from .semantic.cli import load_version_ir

# --- provenance vocabulary (agreed with R1) --------------------------------

PROVENANCE_PARSE = "parse"
PROVENANCE_REPARSE = "reparse"
PROVENANCE_EDIT = "edit"
PROVENANCE_REPAIR = "repair"
PROVENANCE_UNKNOWN = "unknown"
# Issue 03 (continuity merge): the first version of a document produced by
# merging two source documents carries ``provenance == "merge"`` plus a
# ``provenance_detail`` naming both sources (same field pattern as R1's
# ``repair``).  Recognised here so the version chain labels the event.
PROVENANCE_MERGE = "merge"

SOURCE_LABELS = {
    PROVENANCE_PARSE: "解析",
    PROVENANCE_REPARSE: "重解析",
    PROVENANCE_EDIT: "编辑保存",
    PROVENANCE_REPAIR: "修复",
    PROVENANCE_MERGE: "合并",
    PROVENANCE_UNKNOWN: "未知",
}

# --- pHash suggestion threshold --------------------------------------------

HASH_BITS = 64
# Max Hamming distance (bits, out of 64) for a cross-document "possibly the
# same manuscript" *suggestion*.  Deliberately looser than the ingest dedup
# threshold (6): pairs below dedup were already merged into one document, so a
# suggestion list is only useful for the slightly-larger distances that the
# store left as separate documents.  Explicit and overridable per call.
PHASH_SUGGEST_MAX_DISTANCE = 12

STATE_FILE = "evolution.json"
_EDIT_VERSION_ID = "working-copy"

_PROVENANCE_KEYS = ("provenance", "provenance_detail")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


# ---------------------------------------------------------------------------
# Pure rules (table-driven unit tests live in tests/test_evolution.py)
# ---------------------------------------------------------------------------


def provenance_of(meta: dict[str, Any]) -> Optional[str]:
    """Return the explicit provenance value, or None when absent/blank."""
    raw = (meta or {}).get("provenance")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def classify_version_source(meta: dict[str, Any], *, index: int) -> str:
    """Deterministic source rule for one persisted version.

    * an explicit ``provenance`` field wins (``repair`` from R1, or any other
      value the store already records);
    * an unrecognised explicit value becomes ``unknown`` (never guessed);
    * without the field, the first version is the initial ``parse`` and every
      later version is a ``reparse`` of the same document.
    """
    explicit = provenance_of(meta)
    if explicit is not None:
        value = explicit.casefold()
        if value in (PROVENANCE_PARSE, PROVENANCE_REPARSE,
                     PROVENANCE_EDIT, PROVENANCE_REPAIR, PROVENANCE_MERGE):
            return value
        return PROVENANCE_UNKNOWN
    return PROVENANCE_PARSE if index <= 0 else PROVENANCE_REPARSE


def similarity_from_distance(distance: int, *, bits: int = HASH_BITS) -> float:
    """Fractional similarity in ``[0, 1]`` for a Hamming distance."""
    if bits <= 0:
        return 1.0
    return max(0.0, 1.0 - max(0, int(distance)) / bits)


def within_suggestion_threshold(distance: int, max_distance: int) -> bool:
    """True when a distance is at or below the (inclusive) suggestion bound."""
    return int(distance) <= int(max_distance)


def canonical_pair(document_a: str, document_b: str) -> str:
    """Order-insensitive key for an unordered document pair."""
    a, b = str(document_a), str(document_b)
    return "|".join(sorted((a, b)))


# ---------------------------------------------------------------------------
# Version chain (primary anchor)
# ---------------------------------------------------------------------------


def _safe_id(document_id: str) -> str:
    from .store import _safe

    return _safe(document_id)


def _raw_version_meta(store, document_id: str) -> dict[str, dict]:
    """Version metadata straight from ``record.json`` (pre-R1 provenance).

    ``FileDocumentStore.get_document`` exposes a curated ``versions[]``; the
    R1 ``provenance`` fields arrive there after R1 merges.  Reading the raw
    record makes S2 work both before and after that merge, without importing
    any R1 code.
    """
    root = getattr(store, "root", None)
    if root is None:
        return {}
    path = Path(root) / "documents" / _safe_id(document_id) / "record.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, dict] = {}
    for version in raw.get("versions") or []:
        if isinstance(version, dict) and version.get("version_id"):
            out[str(version["version_id"])] = version
    return out


def versions_for_document(store, document_id: str) -> list[dict]:
    """Normalized, time-ordered version metadata for one document.

    Mirrors the naming the issue reserved (``store.versions_for_document``) but
    lives here so the semantic track does not contend with R1/A1 for
    ``store.py``.  Returns ``[]`` for an unknown/empty document.
    """
    record = store.get_document(document_id)
    if record is None:
        return []
    raw_meta = _raw_version_meta(store, document_id)
    out: list[dict] = []
    for index, version in enumerate(record.get("versions") or []):
        if not isinstance(version, dict):
            continue
        vid = version.get("version_id")
        if not vid:
            continue
        raw = raw_meta.get(str(vid), {})
        meta = dict(version)
        for key in _PROVENANCE_KEYS:
            if key not in meta and key in raw:
                meta[key] = raw[key]
        if "ir_json" not in meta and "ir_json" in raw:
            meta["ir_json"] = raw["ir_json"]
        if "markdown" not in meta and "markdown" in raw:
            meta["markdown"] = raw["markdown"]
        meta["version_id"] = str(vid)
        meta["_order"] = index
        out.append(meta)
    out.sort(key=lambda m: (m.get("created_at") or "", m["_order"]))
    for index, meta in enumerate(out):
        meta["index"] = index
    return out


def _version_ir(store, document_id: str, meta: dict) -> Optional[DocumentIR]:
    raw = meta.get("ir_json")
    if raw:
        try:
            return loads_ir(raw) if isinstance(raw, str) else load_dict_as_ir(raw)
        except (IRValidationError, ValueError, TypeError):
            return None
    try:
        return load_version_ir(store, document_id, str(meta["version_id"]))
    except (OSError, IRValidationError, KeyError, TypeError):
        return None


def _markdown_ir(markdown: str) -> Optional[DocumentIR]:
    """Best-effort deterministic Markdown -> IR (no model call)."""
    if not markdown or not markdown.strip():
        return None
    try:
        from .vlm import _markdown_to_ir

        return load_dict_as_ir(_markdown_to_ir(markdown))
    except Exception:  # never let a projection break the whole chain
        return None


def _latest_version_markdown(store, record: dict, versions: list[dict]) -> str:
    latest = record.get("latest") or {}
    path = latest.get("markdown_path")
    if path and Path(path).is_file():
        try:
            return Path(path).read_text(encoding="utf-8")
        except OSError:
            pass
    if versions:
        return versions[-1].get("markdown") or ""
    return ""


def _report_payload(report) -> tuple[dict, list]:
    return report.summary.model_dump(), [change.model_dump() for change in report.changes]


def build_version_chain(store, document_id: str) -> Optional[dict]:
    """Evolution timeline for one document (see module docstring).

    Returns ``None`` when the document does not exist, otherwise a dict with
    ``versions`` (oldest first), each carrying ``source``/``source_label`` and
    the DiffReport ``diff`` summary + block-level ``changes`` against the
    previous entry.
    """
    record = store.get_document(document_id)
    if record is None:
        return None

    versions = versions_for_document(store, document_id)
    entries: list[dict] = []
    previous_ir: Optional[DocumentIR] = None
    previous_vid: Optional[str] = None
    last_ir: Optional[DocumentIR] = None

    for index, meta in enumerate(versions):
        vid = meta["version_id"]
        ir = _version_ir(store, document_id, meta)
        source = classify_version_source(meta, index=index)
        entry = {
            "version_id": vid,
            "index": index,
            "created_at": meta.get("created_at"),
            "model": meta.get("model"),
            "source": source,
            "source_label": SOURCE_LABELS.get(source, source),
            "provenance_detail": meta.get("provenance_detail"),
            "current": bool(meta.get("current", index == len(versions) - 1)),
            "is_edit": False,
            "block_count": len(ir.blocks) if ir is not None else 0,
            "diff_from": None,
            "diff": None,
            "changes": [],
        }
        if previous_ir is not None and ir is not None:
            report = diff_ir(previous_ir, ir, label_a=previous_vid, label_b=vid)
            entry["diff_from"] = previous_vid
            entry["diff"], entry["changes"] = _report_payload(report)
        entries.append(entry)
        previous_ir = ir
        previous_vid = vid
        if ir is not None:
            last_ir = ir

    # An edit save does not create a persisted version; surface the live
    # (edited) markdown as the uncommitted head of the timeline so the
    # "编辑保存" source is visible and diffable.
    live = record.get("current_markdown") or ""
    latest_markdown = _latest_version_markdown(store, record, versions)
    has_edit = bool(live.strip()) and live != latest_markdown
    if has_edit:
        edit_ir = _markdown_ir(live)
        entry = {
            "version_id": _EDIT_VERSION_ID,
            "index": len(entries),
            "created_at": record.get("updated_at"),
            "model": None,
            "source": PROVENANCE_EDIT,
            "source_label": SOURCE_LABELS[PROVENANCE_EDIT],
            "provenance_detail": None,
            "current": False,
            "is_edit": True,
            "block_count": len(edit_ir.blocks) if edit_ir is not None else 0,
            "diff_from": previous_vid,
            "diff": None,
            "changes": [],
        }
        if last_ir is not None and edit_ir is not None:
            report = diff_ir(last_ir, edit_ir, label_a=previous_vid, label_b=_EDIT_VERSION_ID)
            entry["diff"], entry["changes"] = _report_payload(report)
        entries.append(entry)

    latest_version_id = record.get("latest_version_id")
    if not latest_version_id and versions:
        latest_version_id = versions[-1]["version_id"]
    return {
        "document_id": document_id,
        "title": record.get("title"),
        "count": len(entries),
        "empty": not entries,
        "latest_version_id": latest_version_id,
        "has_uncommitted_edit": has_edit,
        "versions": entries,
    }


# ---------------------------------------------------------------------------
# pHash cross-document candidates (secondary anchor)
# ---------------------------------------------------------------------------


def _document_hashes(store, document_id: str) -> list[str]:
    hashes: list[str] = []
    record = store.get_document(document_id)
    if record is None:
        return hashes
    current = record.get("hash") or record.get("current_hash") or ""
    if current:
        hashes.append(str(current))
    for meta in record.get("versions") or []:
        value = meta.get("pg_hash") or ""
        if value and value not in hashes:
            hashes.append(str(value))
    return hashes


def versions_for_original_phash(
    store,
    pg_hash: str,
    *,
    max_distance: int = PHASH_SUGGEST_MAX_DISTANCE,
) -> list[dict]:
    """Every version across the library within ``max_distance`` of ``pg_hash``.

    The issue reserved this name (``store.versions_for_original_phash``); it is
    implemented here as a pure read over the store's public surface.  Empty
    hashes never match (a blank page is not evidence of anything).
    """
    if not pg_hash:
        return []
    matches: list[dict] = []
    for summary in store.list_documents():
        other = summary.get("document_id")
        if not other:
            continue
        for meta in versions_for_document(store, other):
            candidate_hash = meta.get("pg_hash") or ""
            if not candidate_hash:
                continue
            distance = hamming(str(pg_hash), str(candidate_hash))
            if not within_suggestion_threshold(distance, max_distance):
                continue
            matches.append({
                "document_id": other,
                "title": summary.get("title"),
                "version_id": meta.get("version_id"),
                "created_at": meta.get("created_at"),
                "model": meta.get("model"),
                "pg_hash": candidate_hash,
                "distance": distance,
                "similarity": round(similarity_from_distance(distance), 4),
            })
    matches.sort(key=lambda item: (item["distance"], item["document_id"],
                                   str(item["version_id"])))
    return matches


def confirmed_pairs(store) -> set[str]:
    """Canonical pair keys already confirmed as manual relations."""
    pairs: set[str] = set()
    for summary in store.list_documents():
        document_id = summary.get("document_id")
        record = store.get_document(document_id) if document_id else None
        if not record:
            continue
        for relation in record.get("manual_relations") or []:
            if not isinstance(relation, dict):
                continue
            kind = str(relation.get("kind") or "manual").casefold()
            if kind not in ("manual", "user", "user_manual"):
                continue
            source = relation.get("from") or relation.get("from_id") or document_id
            target = (relation.get("to") or relation.get("to_id")
                      or relation.get("target") or relation.get("target_id"))
            if source and target and str(source) != str(target):
                pairs.add(canonical_pair(str(source), str(target)))
        for target in record.get("related_documents") or []:
            if target and str(target) != str(document_id):
                pairs.add(canonical_pair(str(document_id), str(target)))
    return pairs


def find_phash_candidates(
    store,
    document_id: str,
    *,
    max_distance: int = PHASH_SUGGEST_MAX_DISTANCE,
) -> Optional[dict]:
    """Read-only "possibly the same manuscript" suggestions for a document.

    Confirmed relations and previously rejected pairs are excluded, so a pair
    is never suggested twice.  The result is a plain, JSON-serializable dict;
    ``empty`` is True for a blank/no-hash document or a library without any
    close page.
    """
    record = store.get_document(document_id)
    if record is None:
        return None
    max_distance = int(max_distance)
    target_hashes = _document_hashes(store, document_id)
    result = {
        "document_id": document_id,
        "title": record.get("title"),
        "max_distance": max_distance,
        "bits": HASH_BITS,
        "target_hashes": target_hashes,
        "candidates": [],
        "empty": True,
    }
    if not target_hashes:
        return result

    excluded = confirmed_pairs(store) | set(load_rejections(store).keys())
    for summary in store.list_documents():
        other = summary.get("document_id")
        if not other or other == document_id:
            continue
        if canonical_pair(document_id, other) in excluded:
            continue
        best: Optional[int] = None
        for candidate_hash in _document_hashes(store, other):
            distance = min(hamming(candidate_hash, target) for target in target_hashes)
            if best is None or distance < best:
                best = distance
        if best is None or not within_suggestion_threshold(best, max_distance):
            continue
        result["candidates"].append({
            "document_id": other,
            "title": summary.get("title"),
            "distance": best,
            "similarity": round(similarity_from_distance(best), 4),
        })
    result["candidates"].sort(key=lambda item: (item["distance"], item["document_id"]))
    result["empty"] = not result["candidates"]
    return result


# ---------------------------------------------------------------------------
# Persisted confirmations / rejections
# ---------------------------------------------------------------------------


def _state_path(store) -> Optional[Path]:
    root = getattr(store, "root", None)
    if root is None:
        return None
    return Path(root) / STATE_FILE


def load_rejections(store) -> dict[str, dict]:
    """Persisted rejected pairs, keyed by :func:`canonical_pair`."""
    path = _state_path(store)
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rejected = data.get("rejected")
    if not isinstance(rejected, dict):
        return {}
    return {str(key): dict(value) for key, value in rejected.items()
            if isinstance(value, dict)}


def _save_rejections(store, rejected: dict[str, dict]) -> None:
    path = _state_path(store)
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "rejected": rejected}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def reject_candidate(
    store,
    document_id: str,
    target_id: str,
    *,
    distance: Optional[int] = None,
) -> dict:
    """Persistently remember that this pair should not be suggested again."""
    pair = canonical_pair(document_id, target_id)
    rejected = load_rejections(store)
    rejected[pair] = {
        "document_id": str(document_id),
        "target_id": str(target_id),
        "distance": distance,
        "rejected_at": _now(),
    }
    _save_rejections(store, rejected)
    return {
        "ok": True,
        "pair": pair,
        "document_id": document_id,
        "target_id": target_id,
        "rejected_at": rejected[pair]["rejected_at"],
    }


def _manual_relations(record: dict) -> list[dict]:
    raw = record.get("manual_relations")
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def confirm_relation(
    store,
    document_id: str,
    target_id: str,
    *,
    distance: Optional[int] = None,
) -> Optional[dict]:
    """Confirm a suggested pair as a persisted manual relation (both sides).

    Idempotent: re-confirming does not duplicate the edge.  A previously
    rejected pair becomes confirmable again (the rejection is dropped).
    """
    source_record = store.get_document(document_id)
    target_record = store.get_document(target_id)
    if source_record is None or target_record is None:
        return None

    created_at = _now()
    relation = {
        "kind": "manual",
        "reason": "evolution-candidate",
        "created_at": created_at,
    }
    if distance is not None:
        relation["distance"] = int(distance)
        relation["similarity"] = round(similarity_from_distance(int(distance)), 4)

    def _add(record: dict, source: str, target: str) -> None:
        relations = _manual_relations(record)
        already = any(
            (item.get("from") or item.get("from_id")) == source
            and (item.get("to") or item.get("to_id") or item.get("target")
                 or item.get("target_id")) == target
            and str(item.get("kind") or "manual").casefold() in ("manual", "user", "user_manual")
            for item in relations
        )
        if already:
            return
        relations.append({**relation, "from": source, "to": target})
        store.set_manual_relations(source, relations)

    _add(source_record, str(document_id), str(target_id))
    _add(target_record, str(target_id), str(document_id))

    rejected = load_rejections(store)
    if rejected.pop(canonical_pair(document_id, target_id), None) is not None:
        _save_rejections(store, rejected)

    return {
        "ok": True,
        "document_id": document_id,
        "target_id": target_id,
        "relation": {**relation, "from": str(document_id), "to": str(target_id)},
        "confirmed_at": created_at,
    }


__all__ = [
    "PROVENANCE_PARSE",
    "PROVENANCE_REPARSE",
    "PROVENANCE_EDIT",
    "PROVENANCE_REPAIR",
    "PROVENANCE_MERGE",
    "PROVENANCE_UNKNOWN",
    "SOURCE_LABELS",
    "PHASH_SUGGEST_MAX_DISTANCE",
    "HASH_BITS",
    "classify_version_source",
    "provenance_of",
    "similarity_from_distance",
    "within_suggestion_threshold",
    "canonical_pair",
    "versions_for_document",
    "versions_for_original_phash",
    "build_version_chain",
    "find_phash_candidates",
    "confirmed_pairs",
    "load_rejections",
    "reject_candidate",
    "confirm_relation",
]
