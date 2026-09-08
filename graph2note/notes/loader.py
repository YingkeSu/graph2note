"""Thin adaptor: ``DocumentStore`` records -> :class:`ExportEntry` list.

Because the exporter is a pure function over :class:`ExportEntry`, it needs a
minimal translation from the durable document library (issue 07).  Only the
*latest* version of each record is surfaced (that is the intra-record
same-source dedup — a reparse updates the same record in place, so the vault
never sees stale parses).  Inter-record same-source collapses are handled by
:func:`graph2note.notes.exporter.dedupe_documents` over the materialized
entries.
"""

from __future__ import annotations

from pathlib import Path

from ..store import DocumentStore
from .exporter import ExportEntry, DEFAULT_DEDUP_THRESHOLD, dedupe_documents


def load_entries(
    store: DocumentStore,
    *,
    dedup_threshold: int = DEFAULT_DEDUP_THRESHOLD,
    hash_of=None,
) -> list[ExportEntry]:
    """Load the library into per-document latest-version entries (deduped)."""
    entries = []
    for meta in store.list_documents():
        rec = store.get_document(meta["document_id"])
        if rec is None:
            continue
        latest = rec.get("latest") or {}
        original_path = rec.get("original_path") or ""
        entries.append(
            ExportEntry(
                document_id=rec["document_id"],
                title=rec.get("title") or rec["document_id"],
                markdown=rec.get("current_markdown") or "",
                parsed_at=latest.get("created_at") or rec.get("created_at") or "",
                updated_at=rec.get("updated_at") or rec.get("created_at") or "",
                original_path=original_path,
                source_ext=rec.get("original_ext") or Path(
                    original_path
                ).suffix or ".jpg",
                preprocessed_path=latest.get("preprocessed_path") or "",
                topics=rec.get("topics") or [],
                attachments=_latest_attachments(latest),
            )
        )
    if not entries:
        return []
    return dedupe_documents(entries, threshold=dedup_threshold, hash_of=hash_of)


def _latest_attachments(latest: dict) -> dict:
    root = latest.get("assets_root")
    if not root:
        return {}
    leaf = Path(root) / "assets"
    if not leaf.is_dir():
        return {}
    return {f.name: str(f) for f in leaf.iterdir() if f.is_file()}