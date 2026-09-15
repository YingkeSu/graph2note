"""Paper document contract (SPW I-track / P1).

The shapes here are the SPEC §2 paper contract:

- :class:`PaperSection` is **P1's product** (deterministic text-layer structure);
- :class:`PaperMeta` and :class:`PaperReference` are the **P2 slots** — P1
  records them empty so P2 can fill them in without a schema migration;
- :class:`PaperPayload` is what actually lands in the document store next to
  ``doc_kind == "paper"`` (``paper.json`` for the file-backed store).

Page numbers follow the rest of the library: ``page_start`` / ``page_end`` are
**0-based page indexes** in the original PDF (the same numbering as
``store``'s ``page_index`` and ``pdflib``), so they can be handed straight to
``/api/documents/{id}/source-page`` and ``/api/papers/{paper_id}/page/{n}``.
The ``page_map`` carries the 1-based ``page_number`` for display.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

#: Bumped only when the stored payload shape changes incompatibly.
PAPER_SCHEMA_VERSION = 1

#: Where a paper document's text came from (SPEC §2 `PaperMeta.source` set).
PaperTextSource = Literal["text-layer", "vlm"]

#: `doc_kind` marker written on every P1-imported paper document.
PAPER_DOC_KIND = "paper"


class PaperSection(BaseModel):
    """One deterministic section of a paper (P1 output, SPEC §2)."""

    model_config = ConfigDict(extra="forbid")

    level: int  # 1=章 2=节 ...
    title: str
    text: str  # 该节正文（含公式占位/图表占位）
    page_start: Optional[int] = None  # 0-based PDF page index
    page_end: Optional[int] = None    # 0-based PDF page index (inclusive)


class PaperMeta(BaseModel):
    """Paper metadata (P2 output; P1 writes the empty default)."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""  # 期刊/会议/arXiv
    doi: str = ""
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    source: Literal["text-layer", "vlm", "manual", "none"] = "none"


class PaperReference(BaseModel):
    """One bibliography entry (P2 output; P1 writes an empty list)."""

    model_config = ConfigDict(extra="forbid")

    raw: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: str = ""
    resolved_document_id: Optional[str] = None


class PaperPage(BaseModel):
    """Per-page mapping record (page → character count) for the reader view."""

    model_config = ConfigDict(extra="forbid")

    page_index: int   # 0-based
    page_number: int  # 1-based (display)
    char_count: int = 0


class PaperProvenance(BaseModel):
    """How this paper document was produced (SPEC §2 `source` + issue 08/09 id)."""

    model_config = ConfigDict(extra="forbid")

    source: PaperTextSource
    pdf_id: str = ""
    source_pdf: str = ""
    page_count: int = 0
    sections: int = 0
    #: Deterministic text-layer decision evidence (thresholds + measured counts).
    decision: dict = Field(default_factory=dict)
    #: Page documents committed by the VLM fallback (empty on the text path).
    page_document_ids: list[str] = Field(default_factory=list)
    #: Pages that produced no text (blank / duplicate / failed).
    skipped_pages: list[dict] = Field(default_factory=list)


class PaperPayload(BaseModel):
    """Full paper payload persisted with the library document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = PAPER_SCHEMA_VERSION
    source: PaperTextSource
    sections: list[PaperSection] = Field(default_factory=list)
    fulltext: str = ""
    page_map: list[PaperPage] = Field(default_factory=list)
    meta: PaperMeta = Field(default_factory=PaperMeta)
    references: list[PaperReference] = Field(default_factory=list)
    provenance: PaperProvenance

    @property
    def page_count(self) -> int:
        return len(self.page_map)

    def as_dict(self) -> dict:
        """JSON-ready payload (stable key order, no pydantic objects leaked)."""
        return self.model_dump(mode="json")


__all__ = [
    "PAPER_DOC_KIND",
    "PAPER_SCHEMA_VERSION",
    "PaperMeta",
    "PaperPage",
    "PaperPayload",
    "PaperProvenance",
    "PaperReference",
    "PaperSection",
    "PaperTextSource",
]
