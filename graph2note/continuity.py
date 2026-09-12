"""Continuity detection & merge (issue 03) — deterministic, zero-LLM.

Two abilities, both fully deterministic (no network, no model, no budget):

1. **Continuity detection** — :func:`detect_continuity` is a pure function over
   plain record dicts.  It reports ordered document pairs in two confidence
   tiers:

   * ``significant`` — two pages of the *same* source (``pdf_id`` /
     ``source_pdf`` / ``source_job_id``, in that order of specificity) whose
     page positions are adjacent.  Evidence: ``同 PDF 第 m–n 页``.
   * ``suggested`` — a cross-document pHash candidate (S2's Hamming rule)
     *and* a tail/head S1 block overlap: the last ``N`` blocks of A match the
     first ``N`` blocks of B.  ``N`` and the minimum match ratio are explicit
     parameters.  Evidence: ``尾首重叠 N 块``.

   Archived (``merged_into``) documents never participate, and rejected /
   confirmed pairs are excluded (rejection memory is persisted by S2's
   ``evolution.json``).

2. **Merge execution** — :func:`merge_documents` stitches two IRs, consuming
   S1's :class:`~graph2note.semantic.DiffReport` to locate the tail/head
   overlap and dropping the duplicated blocks exactly once
   (``|A| + |B| − |overlap| = |merged|``).  The product is a **new document**
   whose first version is stamped ``provenance == "merge"`` with both source
   document ids in ``provenance_detail`` (the R1 ``repair`` field pattern).
   Tags and collections are unions with their auto/manual provenance preserved.
   The two source documents are **soft-archived** (``merged_into``), never
   deleted; clearing the marker restores them.

The batch CLI (``graph2note docs merge-continuous``) only ever executes the
``significant`` tier; ``suggested`` pairs are confirmed one at a time in the
Inbox UI (the API has no batch endpoint).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Optional

from . import evolution
from .ingest.hash import hamming
from .ir import DocumentIR, IRValidationError, dumps_ir, load_dict_as_ir, loads_ir
from .render import render_markdown
from .semantic import diff_ir
from .semantic.text import preview as block_preview

# Version provenance vocabulary (parallel to R1's ``repair``; S2 recognises
# this value in ``evolution.classify_version_source``).
PROVENANCE_MERGE = "merge"

SIGNIFICANT = "significant"
SUGGESTED = "suggested"
TIERS = (SIGNIFICANT, SUGGESTED)

# Explicit, overridable detection parameters.
DEFAULT_TAIL_BLOCKS = 8
DEFAULT_MIN_OVERLAP_RATIO = 0.5

# This module never calls a model.  The constant and the ``llm_calls`` field on
# every report are the machine-checkable contract for that (AC6).
ZERO_LLM = True
LLM_CALLS = 0

# Page/source provenance keys, most specific first.
_SOURCE_KEYS = ("pdf_id", "source_pdf", "source_job_id")
_PAGE_INDEX_KEYS = ("page_index",)
_PAGE_NUMBER_KEYS = ("page_number",)


class ContinuityError(ValueError):
    """Raised when a requested merge is not possible."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def new_document_id() -> str:
    """Deterministic-shape id for a merged document (same shape as ingest)."""
    return "doc-" + uuid.uuid4().hex[:10]


def is_archived(record: dict[str, Any]) -> bool:
    """True when a record is soft-archived (its content lives in another doc)."""
    if not isinstance(record, dict):
        return False
    return bool(str(record.get("merged_into") or "").strip())


# ---------------------------------------------------------------------------
# Record field resolution (page order / source / IR / hashes)
# ---------------------------------------------------------------------------


def _meta_value(record: dict[str, Any], keys: Iterable[str]) -> Any:
    metadata = record.get("metadata")
    for source in (record, metadata if isinstance(metadata, dict) else {}):
        for key in keys:
            value = source.get(key)
            if value is not None and str(value).strip() != "":
                return value
    return None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def source_key(record: dict[str, Any]) -> Optional[str]:
    """Most specific available source identity (PDF page provenance)."""
    value = _meta_value(record, _SOURCE_KEYS)
    return str(value) if value is not None else None


def page_position(record: dict[str, Any]) -> Optional[int]:
    """Comparable 0-based page position, or None when unknown.

    ``page_index`` (0-based) wins; ``page_number`` (1-based) is the fallback.
    Two records are page-adjacent when their positions differ by exactly 1.
    """
    index = _as_int(_meta_value(record, _PAGE_INDEX_KEYS))
    if index is not None:
        return index
    number = _as_int(_meta_value(record, _PAGE_NUMBER_KEYS))
    if number is not None:
        return number - 1
    return None


def page_label(record: dict[str, Any]) -> Optional[int]:
    """Human-facing 1-based page number (``page_number`` preferred)."""
    number = _as_int(_meta_value(record, _PAGE_NUMBER_KEYS))
    if number is not None:
        return number
    position = page_position(record)
    return None if position is None else position + 1


def document_ir(record: dict[str, Any]) -> Optional[DocumentIR]:
    """Best-effort IR for a record (top-level, or its latest version)."""
    raw = record.get("ir")
    if isinstance(raw, DocumentIR):
        return raw
    raw = record.get("ir_json")
    if raw is None:
        for version in reversed(record.get("versions") or []):
            if isinstance(version, dict):
                if isinstance(version.get("ir"), DocumentIR):
                    return version["ir"]
                if version.get("ir_json"):
                    raw = version["ir_json"]
                    break
    if raw is None and isinstance(record.get("blocks"), list):
        try:
            return DocumentIR(document_type="note", blocks=list(record["blocks"]))
        except Exception:  # invalid block dicts: treat as "no IR"
            return None
    if isinstance(raw, DocumentIR):
        return raw
    if isinstance(raw, str):
        try:
            return loads_ir(raw)
        except IRValidationError:
            return None
    if isinstance(raw, (dict, list)):
        try:
            return load_dict_as_ir(raw)
        except IRValidationError:
            return None
    return None


def store_document_ir(store, record: dict[str, Any]) -> Optional[DocumentIR]:
    """IR for a store record, falling back to the version's on-disk ``ir.json``.

    :func:`document_ir` is pure and only sees in-memory fields; durable stores
    write the IR to ``versions/<version_id>/ir.json`` and keep only metadata in
    ``record.json``, so this store-backed variant reuses S2's version metadata
    and S1's CLI loader for the fallback.  Still zero-LLM and read-only.
    """
    parsed = document_ir(record)
    if parsed is not None:
        return parsed
    document_id = record.get("document_id")
    if not document_id:
        return None
    from .semantic.cli import load_version_ir

    for version in reversed(evolution.versions_for_document(store, str(document_id))):
        version_id = version.get("version_id")
        if not version_id:
            continue
        try:
            return load_version_ir(store, str(document_id), str(version_id))
        except (OSError, IRValidationError, KeyError, TypeError):
            continue
    return None


def _hashes(record: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def add(value: Any) -> None:
        text = str(value) if value else ""
        if text and text not in out:
            out.append(text)

    for key in ("current_hash", "hash", "pg_hash"):
        add(record.get(key))
    for version in record.get("versions") or []:
        if isinstance(version, dict):
            add(version.get("pg_hash"))
    return out


def _min_hash_distance(record_a: dict[str, Any], record_b: dict[str, Any]) -> Optional[int]:
    hashes_a, hashes_b = _hashes(record_a), _hashes(record_b)
    if not hashes_a or not hashes_b:
        return None
    return min(hamming(a, b) for a in hashes_a for b in hashes_b)


# ---------------------------------------------------------------------------
# Tail/head overlap (S1 consumption)
# ---------------------------------------------------------------------------


def tail_head_overlap(
    ir_a: DocumentIR,
    ir_b: DocumentIR,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
) -> tuple[int, Optional[Any]]:
    """Size of the contiguous A-tail / B-head overlap, located by S1.

    Runs :func:`~graph2note.semantic.diff_ir` over A's last ``N`` blocks and
    B's first ``N`` blocks, keeps the **exact content** matches, and returns
    the largest ``k`` such that A's last ``k`` blocks match B's first ``k``
    blocks one-to-one in order.  Only exact identities qualify, so the merge
    can drop the overlap without losing any edited content.

    Returns ``(k, report)`` where ``report`` is the S1 ``DiffReport`` (or
    ``None`` when there was nothing to compare).
    """
    n = max(0, int(tail_blocks))
    a_blocks = list(ir_a.blocks)
    b_blocks = list(ir_b.blocks)
    if n == 0 or not a_blocks or not b_blocks:
        return 0, None
    tail = a_blocks[-n:]
    head = b_blocks[:n]
    report = diff_ir(
        DocumentIR(document_type=ir_a.document_type or "note", blocks=tail),
        DocumentIR(document_type=ir_b.document_type or "note", blocks=head),
        label_a="tail",
        label_b="head",
    )
    matched: dict[int, int] = {}
    for change in report.changes:
        if change.op in ("unchanged", "moved") and change.block_ref_a and change.block_ref_b:
            matched[change.block_ref_b.index] = change.block_ref_a.index
    best = 0
    for k in range(1, min(len(tail), len(head)) + 1):
        if all(matched.get(t) == len(tail) - k + t for t in range(k)):
            best = k
    return best, report


def overlap_ratio(overlap: int, tail_blocks: int, blocks_a: int, blocks_b: int) -> float:
    """Fraction of the searched window (``min(N, |A|, |B|)``) that matched."""
    if overlap <= 0:
        return 0.0
    window = min(int(tail_blocks), max(0, blocks_a), max(0, blocks_b))
    if window <= 0:
        return 0.0
    return round(overlap / window, 4)


# ---------------------------------------------------------------------------
# Detection (pure function)
# ---------------------------------------------------------------------------


def _title(record: dict[str, Any]) -> str:
    return str(record.get("title") or record.get("document_id") or "")


def _pair_key(document_a: str, document_b: str) -> str:
    return evolution.canonical_pair(document_a, document_b)


def _significant_pair(record_a: dict[str, Any], record_b: dict[str, Any],
                      key: str) -> dict[str, Any]:
    a_id, b_id = str(record_a["document_id"]), str(record_b["document_id"])
    label_a, label_b = page_label(record_a), page_label(record_b)
    if label_a is not None and label_b is not None:
        low, high = sorted((label_a, label_b))
        evidence_label = f"同 PDF 第 {low}–{high} 页"
    else:
        evidence_label = "同 PDF 页序相邻"
    return {
        "tier": SIGNIFICANT,
        "key": _pair_key(a_id, b_id),
        "document_id": a_id,
        "target_id": b_id,
        "order": [a_id, b_id],
        "titles": [_title(record_a), _title(record_b)],
        "evidence": {
            "kind": "page_adjacency",
            "source": key,
            "page_a": label_a,
            "page_b": label_b,
        },
        "evidence_label": evidence_label,
        "phash_distance": None,
        "overlap_blocks": None,
        "overlap_ratio": None,
    }


def _suggested_pair(record_a: dict[str, Any], record_b: dict[str, Any],
                    ir_a: DocumentIR, ir_b: DocumentIR, distance: int,
                    tail_blocks: int, min_ratio: float) -> Optional[dict[str, Any]]:
    a_id, b_id = str(record_a["document_id"]), str(record_b["document_id"])
    forward, _ = tail_head_overlap(ir_a, ir_b, tail_blocks)
    backward, _ = tail_head_overlap(ir_b, ir_a, tail_blocks)
    ratio_forward = overlap_ratio(forward, tail_blocks, len(ir_a.blocks), len(ir_b.blocks))
    ratio_backward = overlap_ratio(backward, tail_blocks, len(ir_b.blocks), len(ir_a.blocks))
    # Pick the direction with the strongest overlap; on a tie keep the
    # (document-id ordered) forward direction so the result never depends on
    # input order.
    if backward > forward:
        first, second, ir_second = record_b, record_a, ir_a
        overlap, ratio = backward, ratio_backward
    else:
        first, second, ir_second = record_a, record_b, ir_b
        overlap, ratio = forward, ratio_forward
    if overlap <= 0 or ratio < min_ratio:
        return None
    first_id, second_id = str(first["document_id"]), str(second["document_id"])
    report_overlap = ir_second.blocks[:overlap]
    return {
        "tier": SUGGESTED,
        "key": _pair_key(a_id, b_id),
        "document_id": first_id,
        "target_id": second_id,
        "order": [first_id, second_id],
        "titles": [_title(first), _title(second)],
        "evidence": {
            "kind": "tail_head_overlap",
            "overlap_blocks": overlap,
            "tail_blocks": int(tail_blocks),
            "phash_distance": int(distance),
            "previews": [block_preview(block) for block in report_overlap],
        },
        "evidence_label": f"尾首重叠 {overlap} 块",
        "phash_distance": int(distance),
        "overlap_blocks": overlap,
        "overlap_ratio": ratio,
    }


def detect_continuity(
    records: Iterable[dict[str, Any]],
    *,
    phash_max_distance: int = evolution.PHASH_SUGGEST_MAX_DISTANCE,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
    rejected_pairs: Iterable[str] = (),
    confirmed_pairs: Iterable[str] = (),
    include_significant: bool = True,
    include_suggested: bool = True,
) -> list[dict[str, Any]]:
    """Report ordered continuous document pairs, deterministic and pure.

    Archived records are skipped; pairs in ``rejected_pairs`` /
    ``confirmed_pairs`` (S2 canonical pair keys) are never re-suggested.
    """
    recs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        document_id = record.get("document_id")
        if not document_id or is_archived(record):
            continue
        key = str(document_id)
        if key in seen_ids:
            continue
        seen_ids.add(key)
        recs.append(record)
    recs.sort(key=lambda r: str(r["document_id"]))

    excluded = {str(pair) for pair in rejected_pairs} | {str(pair) for pair in confirmed_pairs}
    seen_pairs: set[str] = set()
    out: list[dict[str, Any]] = []

    if include_significant:
        groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for record in recs:
            key = source_key(record)
            position = page_position(record)
            if key is None or position is None:
                continue
            groups.setdefault(key, []).append((position, record))
        for key in sorted(groups):
            members = sorted(groups[key], key=lambda item: (item[0], str(item[1]["document_id"])))
            for index in range(len(members) - 1):
                position_a, record_a = members[index]
                position_b, record_b = members[index + 1]
                if position_b - position_a != 1:
                    continue
                pair = _pair_key(str(record_a["document_id"]), str(record_b["document_id"]))
                if pair in excluded or pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                out.append(_significant_pair(record_a, record_b, key))

    if include_suggested:
        max_distance = int(phash_max_distance)
        for index, record_a in enumerate(recs):
            for record_b in recs[index + 1:]:
                pair = _pair_key(str(record_a["document_id"]), str(record_b["document_id"]))
                if pair in excluded or pair in seen_pairs:
                    continue
                distance = _min_hash_distance(record_a, record_b)
                if distance is None or distance > max_distance:
                    continue
                ir_a = document_ir(record_a)
                ir_b = document_ir(record_b)
                if ir_a is None or ir_b is None:
                    continue
                candidate = _suggested_pair(
                    record_a, record_b, ir_a, ir_b, distance, tail_blocks, min_overlap_ratio,
                )
                if candidate is None:
                    continue
                seen_pairs.add(pair)
                out.append(candidate)

    order = {SIGNIFICANT: 0, SUGGESTED: 1}
    out.sort(key=lambda item: (
        order.get(item["tier"], 9),
        -int(item.get("overlap_blocks") or 0),
        int(item.get("phash_distance") or 0),
        str(item["document_id"]),
        str(item["target_id"]),
    ))
    return out


# ---------------------------------------------------------------------------
# Store-backed helpers (read-only)
# ---------------------------------------------------------------------------


def detection_records(store) -> list[dict[str, Any]]:
    """Active library records enriched with raw version metadata (incl. IR).

    ``store.get_document`` exposes a curated ``versions[]`` without the IR;
    S2's :func:`~graph2note.evolution.versions_for_document` reads the raw
    ``record.json`` and carries ``ir_json``, so detection can run without
    re-reading files itself.
    """
    records: list[dict[str, Any]] = []
    for summary in store.list_documents():  # already excludes archived docs
        document_id = summary.get("document_id")
        if not document_id:
            continue
        record = store.get_document(document_id)
        if record is None:
            continue
        record = dict(record)
        record["versions"] = evolution.versions_for_document(store, str(document_id))
        parsed = store_document_ir(store, record)
        if parsed is not None:
            record["ir"] = parsed
        records.append(record)
    return records


def rejected_pairs(store) -> list[str]:
    """Persisted rejected pairs (S2 ``evolution.json`` memory)."""
    return list(evolution.load_rejections(store).keys())


def load_rejected_pairs(store) -> list[str]:
    """Alias kept for readability; see :func:`rejected_pairs`."""
    return rejected_pairs(store)


def candidates_for_store(
    store,
    *,
    phash_max_distance: int = evolution.PHASH_SUGGEST_MAX_DISTANCE,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
) -> list[dict[str, Any]]:
    """Detection over the store's active library (read-only, zero LLM)."""
    return detect_continuity(
        detection_records(store),
        phash_max_distance=phash_max_distance,
        tail_blocks=tail_blocks,
        min_overlap_ratio=min_overlap_ratio,
        rejected_pairs=rejected_pairs(store),
        confirmed_pairs=evolution.confirmed_pairs(store),
    )


def split_candidates(pairs: Iterable[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    significant = [pair for pair in pairs if pair.get("tier") == SIGNIFICANT]
    suggested = [pair for pair in pairs if pair.get("tier") == SUGGESTED]
    return significant, suggested


def merge_reasons_index(pairs: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    """Map each involved document id to its continuity evidence labels."""
    index: dict[str, list[str]] = {}
    for pair in pairs:
        label = pair.get("evidence_label") or ""
        for document_id in (pair.get("document_id"), pair.get("target_id")):
            if not document_id:
                continue
            labels = index.setdefault(str(document_id), [])
            if label and label not in labels:
                labels.append(label)
    return index


def candidates_payload(
    store,
    *,
    phash_max_distance: int = evolution.PHASH_SUGGEST_MAX_DISTANCE,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
) -> dict[str, Any]:
    """JSON-serializable detection payload for the API / Inbox UI."""
    pairs = candidates_for_store(
        store,
        phash_max_distance=phash_max_distance,
        tail_blocks=tail_blocks,
        min_overlap_ratio=min_overlap_ratio,
    )
    significant, suggested = split_candidates(pairs)
    return {
        "significant": significant,
        "suggested": suggested,
        "counts": {"significant": len(significant), "suggested": len(suggested),
                   "total": len(pairs)},
        "tail_blocks": int(tail_blocks),
        "min_overlap_ratio": float(min_overlap_ratio),
        "phash_max_distance": int(phash_max_distance),
        "empty": not pairs,
        "zero_llm": ZERO_LLM,
        "llm_calls": LLM_CALLS,
    }


# ---------------------------------------------------------------------------
# Rejection memory (delegates to S2's persisted rejection store)
# ---------------------------------------------------------------------------


def reject_pair(store, document_id: str, target_id: str, *,
                distance: Optional[int] = None) -> dict[str, Any]:
    """Persist "never suggest this pair again" (reuses S2's memory)."""
    if str(document_id) == str(target_id):
        raise ContinuityError("不能拒绝文档自身的配对。")
    result = evolution.reject_candidate(
        store, str(document_id), str(target_id), distance=distance,
    )
    result["kind"] = "continuity"
    return result


# ---------------------------------------------------------------------------
# Merge executor (deterministic)
# ---------------------------------------------------------------------------


def _latest_version_id(record: dict[str, Any]) -> Optional[str]:
    for version in reversed(record.get("versions") or []):
        if isinstance(version, dict) and version.get("version_id"):
            return str(version["version_id"])
    return None


def _record_with_raw_versions(store, record: dict[str, Any]) -> dict[str, Any]:
    """Attach the raw (IR-carrying) version metadata to an API record."""
    document_id = record.get("document_id")
    if not document_id:
        return record
    raw = evolution.versions_for_document(store, str(document_id))
    if not raw:
        return record
    record = dict(record)
    record["versions"] = raw
    return record


def _union_tags(rec_a: dict[str, Any], rec_b: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
    from .store import AUTO_TAG_PROVENANCE, MANUAL_TAG_PROVENANCE, ensure_tag_provenance

    provenance_a = ensure_tag_provenance(rec_a)
    provenance_b = ensure_tag_provenance(rec_b)
    tags: list[str] = []
    provenance: dict[str, str] = {}
    for record, mapping in ((rec_a, provenance_a), (rec_b, provenance_b)):
        for tag in record.get("tags") or []:
            if tag not in tags:
                tags.append(tag)
            current = mapping.get(tag, MANUAL_TAG_PROVENANCE)
            if tag not in provenance:
                provenance[tag] = current
            elif current == MANUAL_TAG_PROVENANCE or provenance[tag] == MANUAL_TAG_PROVENANCE:
                provenance[tag] = MANUAL_TAG_PROVENANCE
            else:
                provenance[tag] = AUTO_TAG_PROVENANCE
    return tags, provenance


def _union(lists: Iterable[Iterable[Any]]) -> list[str]:
    out: list[str] = []
    for values in lists:
        for value in values or []:
            text = str(value)
            if text and text not in out:
                out.append(text)
    return sorted(out)


def _source_assets_dirs(store, record: dict[str, Any]) -> list[Path]:
    root = getattr(store, "root", None)
    document_id = str(record.get("document_id") or "")
    versions: list[dict] = []
    path = None
    if root and document_id:
        try:
            from .store import _safe

            path = Path(root) / "documents" / _safe(document_id) / "record.json"
        except Exception:  # pragma: no cover - defensive
            path = None
    if path is not None and path.is_file():
        try:
            versions = list(json.loads(path.read_text(encoding="utf-8")).get("versions") or [])
        except (OSError, ValueError):
            versions = []
    if not versions:
        versions = [v for v in (record.get("versions") or []) if isinstance(v, dict)]
    for version in reversed(versions):
        if not isinstance(version, dict):
            continue
        version_id = version.get("version_id")
        if root and document_id and version_id:
            from .store import _safe

            candidate = (Path(root) / "documents" / _safe(document_id) / "versions"
                         / str(version_id) / "assets")
            if candidate.is_dir():
                return [candidate]
        raw = version.get("assets_dir")
        if raw:
            base = Path(str(raw))
            if (base / "assets").is_dir():
                return [base / "assets"]
            if base.is_dir() and base.name == "assets":
                return [base]
    return []


@contextmanager
def _merged_assets(store, rec_a: dict[str, Any], rec_b: dict[str, Any]):
    """Temporary ``assets/`` leaf merging both sources' attachments."""
    dirs = _source_assets_dirs(store, rec_a) + _source_assets_dirs(store, rec_b)
    if not dirs:
        yield None
        return
    with tempfile.TemporaryDirectory(prefix="g2n-merge-") as tmp:
        leaf = Path(tmp) / "assets"
        leaf.mkdir(parents=True, exist_ok=True)
        for directory in dirs:
            for item in sorted(directory.iterdir()):
                if item.is_file():
                    try:
                        shutil.copy2(str(item), leaf / item.name)
                    except OSError:
                        pass
        yield tmp


def _latest_preprocessed(record: dict[str, Any]) -> Optional[str]:
    latest = record.get("latest") or {}
    candidate = latest.get("preprocessed_path")
    if candidate and Path(str(candidate)).is_file():
        return str(candidate)
    for version in reversed(record.get("versions") or []):
        if isinstance(version, dict) and version.get("preprocessed_path"):
            candidate = version["preprocessed_path"]
            if Path(str(candidate)).is_file():
                return str(candidate)
    return None


def _primary_original(record: dict[str, Any]) -> str:
    candidate = record.get("original_path")
    return str(candidate) if candidate else ""


def merge_documents(
    store,
    document_id: str,
    target_id: str,
    *,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
) -> dict[str, Any]:
    """Merge ``document_id`` (first) with ``target_id`` (second) into a new doc.

    Deterministic: IR blocks are concatenated, the tail/head overlap located by
    S1 is kept exactly once, and the two sources are soft-archived.  Raises
    :class:`ContinuityError` when the merge is not possible.
    """
    a_id, b_id = str(document_id), str(target_id)
    if a_id == b_id:
        raise ContinuityError("不能合并文档自身。")
    rec_a = store.get_document(a_id)
    rec_b = store.get_document(b_id)
    if rec_a is None or rec_b is None:
        raise ContinuityError("文档不存在。")
    rec_a = _record_with_raw_versions(store, rec_a)
    rec_b = _record_with_raw_versions(store, rec_b)
    if is_archived(rec_a) or is_archived(rec_b):
        raise ContinuityError("归档稿不能再次合并。")
    ir_a = store_document_ir(store, rec_a)
    ir_b = store_document_ir(store, rec_b)
    if ir_a is None or ir_b is None:
        raise ContinuityError("源文档缺少可解析的 IR。")

    overlap, _report = tail_head_overlap(ir_a, ir_b, tail_blocks)
    merged_blocks = list(ir_a.blocks) + list(ir_b.blocks[overlap:])
    merged_ir = DocumentIR(document_type=ir_a.document_type or "note", blocks=merged_blocks)
    new_id = new_document_id()
    title = rec_a.get("title") or a_id
    detail = {
        "kind": "merge",
        "sources": [a_id, b_id],
        "source_versions": [
            {"document_id": a_id, "version_id": _latest_version_id(rec_a),
             "title": rec_a.get("title") or a_id, "block_count": len(ir_a.blocks)},
            {"document_id": b_id, "version_id": _latest_version_id(rec_b),
             "title": rec_b.get("title") or b_id, "block_count": len(ir_b.blocks)},
        ],
        "overlap_blocks": overlap,
        "merged_at": _now(),
    }
    markdown = render_markdown(merged_ir, doc_id=new_id)
    # Carry the page provenance forward when both sources belong to the same
    # PDF, so a 3+ page run can keep chaining in a later detection pass.
    same_source = bool(source_key(rec_a)) and source_key(rec_a) == source_key(rec_b)
    page_meta = {
        "source_pdf": rec_b.get("source_pdf") if same_source else None,
        "pdf_id": (rec_b.get("pdf_id") or rec_a.get("pdf_id")) if same_source else None,
        "page_index": page_position(rec_b) if same_source else None,
        "page_number": page_label(rec_b) if same_source else None,
    }
    with _merged_assets(store, rec_a, rec_b) as assets_dir:
        store.save_document(
            document_id=new_id,
            title=title,
            source_job_id=f"merge-{a_id}-{b_id}",
            model="merge",
            markdown=markdown,
            ir_json=dumps_ir(merged_ir),
            original_path=_primary_original(rec_a) or _primary_original(rec_b),
            original_ext=rec_a.get("original_ext") or ".jpg",
            preprocessed_path=_latest_preprocessed(rec_a),
            preprocessed_raw_path=None,
            assets_dir=assets_dir,
            timing_json={},
            pg_hash="",
            provenance=PROVENANCE_MERGE,
            provenance_detail=detail,
            **page_meta,
        )

    tags, provenance = _union_tags(dict(rec_a), dict(rec_b))
    if tags:
        store.set_tags_with_provenance(new_id, tags, provenance)
    topics = _union([rec_a.get("topics") or [], rec_b.get("topics") or []])
    if topics:
        store.set_topics(new_id, topics)
    manual_collections = _union([
        rec_a.get("manual_collections") or [], rec_b.get("manual_collections") or [],
    ])
    if manual_collections:
        store.set_collections(new_id, manual_collections)

    store.archive_document(a_id, new_id)
    store.archive_document(b_id, new_id)
    merged_record = store.get_document(new_id) or {}

    return {
        "ok": True,
        "merged_document_id": new_id,
        "title": title,
        "order": [a_id, b_id],
        "sources": detail["source_versions"],
        "overlap_blocks": overlap,
        "overlap_previews": [block_preview(block) for block in ir_b.blocks[:overlap]],
        "block_counts": {
            "a": len(ir_a.blocks),
            "b": len(ir_b.blocks),
            "overlap": overlap,
            "merged": len(merged_blocks),
        },
        "conservation_ok": len(ir_a.blocks) + len(ir_b.blocks) - overlap == len(merged_blocks),
        "tags": list(merged_record.get("tags") or tags),
        "tag_provenance": dict(merged_record.get("tag_provenance") or provenance),
        "topics": topics,
        "collections": _union([merged_record.get("collections") or [],
                               rec_a.get("collections") or [], rec_b.get("collections") or []]),
        "archived": [a_id, b_id],
        "provenance": PROVENANCE_MERGE,
        "provenance_detail": detail,
        "zero_llm": ZERO_LLM,
        "llm_calls": LLM_CALLS,
    }


# ---------------------------------------------------------------------------
# Controlled batch execution (CLI): significant tier only
# ---------------------------------------------------------------------------


def plan_continuous_merge(
    store,
    *,
    phash_max_distance: int = evolution.PHASH_SUGGEST_MAX_DISTANCE,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
) -> dict[str, Any]:
    """Dry-run plan: significant pairs (batchable) + suggested (confirm only)."""
    payload = candidates_payload(
        store,
        phash_max_distance=phash_max_distance,
        tail_blocks=tail_blocks,
        min_overlap_ratio=min_overlap_ratio,
    )
    return {
        "significant": payload["significant"],
        "suggested": payload["suggested"],
        "counts": payload["counts"],
        "tail_blocks": payload["tail_blocks"],
        "min_overlap_ratio": payload["min_overlap_ratio"],
        "phash_max_distance": payload["phash_max_distance"],
        "zero_llm": ZERO_LLM,
        "llm_calls": LLM_CALLS,
    }


def merge_continuous(
    store,
    *,
    dry_run: bool = True,
    phash_max_distance: int = evolution.PHASH_SUGGEST_MAX_DISTANCE,
    tail_blocks: int = DEFAULT_TAIL_BLOCKS,
    min_overlap_ratio: float = DEFAULT_MIN_OVERLAP_RATIO,
) -> dict[str, Any]:
    """Execute (or report) the significant-tier batch merge.

    ``suggested`` pairs are never executed here: they stay in the per-item
    confirmation queue.  ``dry_run=True`` performs no writes.
    """
    plan = plan_continuous_merge(
        store,
        phash_max_distance=phash_max_distance,
        tail_blocks=tail_blocks,
        min_overlap_ratio=min_overlap_ratio,
    )
    executed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if not dry_run:
        # Re-plan after every merge so a 3+ page run chains into one document
        # (the merged document carries the later page's provenance forward).
        attempted: set[str] = set()
        for _ in range(500):
            current = plan_continuous_merge(
                store,
                phash_max_distance=phash_max_distance,
                tail_blocks=tail_blocks,
                min_overlap_ratio=min_overlap_ratio,
            )["significant"]
            candidate = next((pair for pair in current
                              if pair["key"] not in attempted), None)
            if candidate is None:
                break
            attempted.add(candidate["key"])
            a_id, b_id = str(candidate["document_id"]), str(candidate["target_id"])
            rec_a = store.get_document(a_id)
            rec_b = store.get_document(b_id)
            if rec_a is None or rec_b is None or is_archived(rec_a) or is_archived(rec_b):
                skipped.append({"key": candidate["key"], "reason": "已归档或不存在"})
                continue
            try:
                executed.append(merge_documents(store, a_id, b_id, tail_blocks=tail_blocks))
            except ContinuityError as exc:
                skipped.append({"key": candidate["key"], "reason": str(exc)})
    return {
        **plan,
        "dry_run": bool(dry_run),
        "significant_only": True,
        "executed": executed,
        "skipped": skipped,
        "merged_count": len(executed),
        "llm_calls": LLM_CALLS,
    }


__all__ = [
    "PROVENANCE_MERGE",
    "SIGNIFICANT",
    "SUGGESTED",
    "TIERS",
    "DEFAULT_TAIL_BLOCKS",
    "DEFAULT_MIN_OVERLAP_RATIO",
    "ZERO_LLM",
    "LLM_CALLS",
    "ContinuityError",
    "new_document_id",
    "is_archived",
    "source_key",
    "page_position",
    "page_label",
    "document_ir",
    "store_document_ir",
    "tail_head_overlap",
    "overlap_ratio",
    "detect_continuity",
    "detection_records",
    "rejected_pairs",
    "load_rejected_pairs",
    "candidates_for_store",
    "split_candidates",
    "merge_reasons_index",
    "candidates_payload",
    "reject_pair",
    "merge_documents",
    "plan_continuous_merge",
    "merge_continuous",
]
