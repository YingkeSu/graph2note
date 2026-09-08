"""Incremental-export closed loop (notes-organizer issue 03).

One callable path demonstrating the full loop: load the document library ->
classify (rule classifier default; a text-model classifier can be swapped in)
-> persist topics -> incremental export of the vault.  Re-run it after parsing
new documents / re-classifying and the vault reflects only the changes while
preserving user edits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..store import DocumentStore
from .classify import classify_documents
from .exporter import ExportEntry, export_incremental
from .loader import load_entries


def run_incremental_export(
    store: DocumentStore,
    out_dir: str | Path,
    *,
    exported_at: Optional[str] = None,
    __classify=classify_documents,
) -> tuple[dict, object, list[ExportEntry]]:
    """Load, classify, persist topics, then incrementally export the vault.

    Returns ``(report, vault, entries)``.  ``__classify`` is injectable so tests
    can drive the loop fully offline with a deterministic classifier; the LLM
    classifier (``graph2note.notes.llm.classify_via_llm``) may be passed instead
    for a live run through the gateway.
    """
    entries = load_entries(store)
    scheme = __classify(entries) if entries else None
    if scheme is not None:
        from .classify import apply_scheme

        apply_scheme(store, scheme)
        # re-load so the persisted topics flow into the exported frontmatter
        entries = load_entries(store)
    report, vault = export_incremental(
        entries, out_dir, exported_at=exported_at, scheme=scheme
    )
    return report, vault, entries