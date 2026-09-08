"""End-to-end ingest orchestration for scanned PDFs (issue 09).

``ingest_pdfs(...)`` bundles the pipeline — split -> hash -> near-dup cluster
-> missing-page alerts — into a single :class:`IngestReport`.  It is a pure
function over files + configuration: no network, no LLM, fully deterministic.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable, Optional

from .cluster import cluster_pages
from .hash import dhash, phash
from .missing import detect_missing
from .model import IngestReport, Page
from .pdf import available as pdf_available, split_pdf

DEFAULT_DEDUP_THRESHOLD = 6  # max Hamming distance (out of ~64 bits) for near-dup


def ingest_pdfs(
    pdfs: Iterable[str | Path],
    work_dir: str | Path,
    dpi: int = 150,
    jpeg_quality: int = 85,
    flag_blank: bool = True,
    hash_method: str = "phash",
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
    keep: str = "latest",
    page_numbers: Optional[dict] = None,
    merge_low_info: bool = False,
) -> IngestReport:
    """Split one or more PDFs and produce a de-duplicated page report.

    ``page_numbers`` maps a flat page index (0..N-1 across all files, in input
    order) to an optional explicit page number, enabling true missing-page gap
    detection.  Without it, completeness is *not* claimed (``no_clue`` alert).
    ``merge_low_info`` opts blank/near-blank pages into normal clustering
    (default: they are kept but each isolated to avoid false merges).
    """
    failures = []
    if not pdf_available():
        raise RuntimeError(
            "PyMuPDF is required to ingest PDFs. Install with: pip install pymupdf"
        )
    work_dir = Path(work_dir)
    all_pages: list[Page] = []
    for pdf in pdfs:
        pages = split_pdf(
            str(pdf), work_dir, dpi=dpi, jpeg_quality=jpeg_quality,
            flag_blank=flag_blank, hash_method=hash_method,
        )
        all_pages.extend(pages)

    clusters = cluster_pages(
        all_pages, threshold=threshold, hash_method=hash_method, keep=keep,
        merge_low_info=merge_low_info,
    )
    blanks = [p for p in all_pages if p.blank]
    alerts = detect_missing(all_pages, page_numbers=page_numbers)

    report = IngestReport(
        source_pdfs=[str(Path(p)) for p in pdfs],
        pages=all_pages,
        clusters=clusters,
        blank_pages=blanks,
        alerts=alerts,
        hash_method=hash_method,
        threshold=threshold,
    )
    return report


def load_page_numbers_from_arg(arg: str) -> dict:
    """Parse ``--page-numbers '0:1,1:2,3:5'`` -> {flat_index: page_number}."""
    out: dict = {}
    if not arg:
        return out
    for tok in arg.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if ":" in tok:
            k, v = tok.split(":", 1)
            out[int(k)] = int(v)
        else:
            out[len(out)] = int(tok)  # 1-based sequential shorthand
    return out


__all__ = [
    "ingest_pdfs",
    "load_page_numbers_from_arg",
    "DEFAULT_DEDUP_THRESHOLD",
    "pdf_available",
]