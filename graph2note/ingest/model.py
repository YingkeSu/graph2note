"""Core value objects for the scan-effort ingest pipeline.

These are dependency-free dataclasses (pure Python).  They carry the data
produced by :mod:`graph2note.ingest` and are the thin contract handed to the
parse pipeline (issue 03) through :mod:`graph2note.ingest.adapter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Page:
    """One rendered page image with traceable provenance.

    ``page_index`` is the 0-based position of the page inside its source PDF
    (页码可追溯).  ``page_number`` is an *optional* human-readable page number
    read from the page (e.g. via an OCR / VLM extractor); when absent the page
    only has positional continuity.
    """

    source_pdf: str
    page_index: int
    path: str
    width: int
    height: int
    dpi: int
    pg_hash: str = ""
    page_number: Optional[int] = None
    blank: bool = False
    low_information: bool = False

    @property
    def page_no(self) -> Optional[int]:
        """Detected/known page number (1-based), when available."""
        return self.page_number


@dataclass
class PageCluster:
    """A group of near-duplicate pages (same page scanned/photographed twice).

    The merge decision is *reversible*: ``pages`` always keeps every candidate
    version, and ``representative`` is the one that would be kept when we
    de-duplicate.  Splitting a false merge = expanding ``pages`` back out.
    """

    cluster_id: int
    pages: list[Page] = field(default_factory=list)
    hash_method: str = "phash"
    max_distance: int = 0
    keep: str = "latest"

    @property
    def representative(self) -> Page:
        if self.keep == "latest":
            return max(self.pages, key=lambda p: (p.page_index, p.source_pdf))
        return self.pages[0]

    @property
    def key_hash(self) -> str:
        return self.pages[0].pg_hash if self.pages else ""


@dataclass
class MissingAlert:
    """Best-effort missing-page notice (预警仅为提示，不自动改动文档)."""

    kind: str  # "gap" (sequence clue) | "no_clue" | "duplicate_hint"
    message: str
    missing_numbers: list[int] = field(default_factory=list)
    observed_numbers: list[int] = field(default_factory=list)


@dataclass
class IngestReport:
    """Full result of ingesting one or more scanned PDFs."""

    source_pdfs: list[str] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)
    clusters: list[PageCluster] = field(default_factory=list)
    blank_pages: list[Page] = field(default_factory=list)
    alerts: list[MissingAlert] = field(default_factory=list)
    hash_method: str = "phash"
    threshold: int = 0  # max Hamming distance for a near-dup

    @property
    def unique_pages(self) -> int:
        """Number of pages that would survive de-duplication (one per cluster)."""
        return len(self.clusters)

    @property
    def dedup_removed(self) -> int:
        """Source pages collapsed away as candidate versions."""
        return len(self.pages) - len(self.clusters)

    @property
    def candidate_versions(self) -> int:
        """Total extra scanned copies kept as history (i.e. not the reps)."""
        return self.dedup_removed