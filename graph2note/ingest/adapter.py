"""Thin adapter between ingest (this issue) and the parse pipeline (issue 03).

Issue 03 owns the parse pipeline files; by contract we MUST NOT edit them.
This module documents the *only* seam ingest publishes into, and offers a pure
function that turns an :class:`IngestReport` into the flat list of individual
parse tasks the pipeline can consume.

Each unique page surfaces as a :class:`ParseInput` carrying traceable
provenance (``source_pdf``, ``page_index``, ``page_number``) — so a downstream
``page -> DocumentRecord`` step can keep pairing source with result.  Candidate
*versions* of the same page are reported alongside, so the pipeline can store
history without treating them as new documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .model import IngestReport, Page, PageCluster


@dataclass
class ParseInput:
    """One page fed to the parse pipeline (issue 03 seam)."""

    image_path: str
    source_pdf: str
    page_index: int
    page_number: Optional[int] = None
    blank: bool = False
    candidate_versions: list = field(default_factory=list)

    @property
    def traceable_id(self) -> str:
        """Stable identifier a pipeline can key a DocumentRecord on."""
        return f"{self.source_pdf}#p{self.page_index + 1}"


def report_to_parse_inputs(report: IngestReport) -> list[ParseInput]:
    """Map an ingest report to one parse input per unique page.

    Filtering blank/low-information pages is left to the pipeline's policy
    (default behaviour keeps them, so we surface them too and let the pipeline
    decide): we only aggregate candidate versions.
    """
    by_id: dict[str, ParseInput] = {}
    for cluster in report.clusters:
        rep = cluster.representative
        key = f"{rep.source_pdf}#{rep.page_index}"
        by_id[key] = ParseInput(
            image_path=rep.path,
            source_pdf=rep.source_pdf,
            page_index=rep.page_index,
            page_number=rep.page_number,
            blank=rep.blank,
            candidate_versions=[
                {"source_pdf": p.source_pdf, "page_index": p.page_index,
                 "path": p.path, "blank": p.blank}
                for p in cluster.pages
                if (p.source_pdf, p.page_index) != (rep.source_pdf, rep.page_index)
            ],
        )
    return list(by_id.values())


__all__ = ["ParseInput", "report_to_parse_inputs"]