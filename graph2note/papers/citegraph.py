"""In-library reference resolution and citation graph (SPW I 轨 P2).

Given the ``references`` parsed by :mod:`graph2note.papers.references` and the
library's existing papers, this module back-fills ``resolved_document_id``.

Matching rules (acceptance criteria §3):

- A DOI match (after ``normalize_doi``) wins over a title match.
- A title match uses the punctuation/case/whitespace-folded key
  (``normalize_title``).
- **No false matches**: if two different library documents share a normalized
  DOI/title key the key becomes *ambiguous* and matches nothing.
- Unresolved references stay ``None`` — never guessed.

All functions are pure and deterministic; the web layer only supplies the
library index.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .metadata import normalize_doi, normalize_title
from .references import PaperReference

__all__ = [
    "CitationEdge",
    "CitationGraph",
    "CitationIndex",
    "CitationSource",
    "LibraryEntry",
    "ResolveResult",
    "ResolvedReference",
    "build_citation_graph",
    "build_index",
    "library_entries_from_documents",
    "resolve_reference",
    "resolve_references",
]


@dataclass(frozen=True)
class LibraryEntry:
    """The minimal library-paper view needed for matching."""

    document_id: str
    title: str = ""
    doi: str = ""


@dataclass
class CitationIndex:
    by_doi: dict[str, str] = field(default_factory=dict)
    by_title: dict[str, str] = field(default_factory=dict)
    ambiguous_doi: set[str] = field(default_factory=set)
    ambiguous_title: set[str] = field(default_factory=set)

    def resolve(self, *, doi: str = "", title: str = "") -> tuple[Optional[str], Optional[str]]:
        """Return ``(document_id, matched_by)`` or ``(None, None)``."""

        doi_key = normalize_doi(doi)
        if doi_key and doi_key in self.by_doi:
            return self.by_doi[doi_key], "doi"
        title_key = normalize_title(title)
        if title_key and title_key in self.by_title:
            return self.by_title[title_key], "title"
        return None, None


class ResolvedReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    raw: str
    document_id: Optional[str] = None
    matched_by: Optional[Literal["doi", "title"]] = None


class ResolveResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    references: list[PaperReference] = Field(default_factory=list)
    resolutions: list[ResolvedReference] = Field(default_factory=list)
    unresolved: int = 0
    notes: list[str] = Field(default_factory=list)

    @property
    def resolved(self) -> int:
        return len(self.references) - self.unresolved


def library_entries_from_documents(documents: Iterable[dict[str, Any]]) -> list[LibraryEntry]:
    """Build index entries from store records (``document_id``/``title``/paper meta).

    Accepts both the library list shape and a full document record; the DOI is
    read from ``paper.meta.doi`` (the P2 slot) or a top-level ``doi``.
    """

    entries: list[LibraryEntry] = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        document_id = str(document.get("document_id") or "")
        if not document_id:
            continue
        title = str(document.get("title") or "")
        doi = str(document.get("doi") or "")
        paper = document.get("paper")
        if isinstance(paper, dict):
            meta = paper.get("meta")
            if isinstance(meta, dict):
                doi = str(meta.get("doi") or doi)
                title = str(meta.get("title") or title)
        entries.append(LibraryEntry(document_id=document_id, title=title, doi=doi))
    return entries


def build_index(entries: Iterable[LibraryEntry]) -> CitationIndex:
    """Index library entries by normalized DOI and title, excluding ambiguity."""

    index = CitationIndex()
    for entry in entries:
        doi_key = normalize_doi(entry.doi)
        if doi_key:
            existing = index.by_doi.get(doi_key)
            if existing is None:
                index.by_doi[doi_key] = entry.document_id
            elif existing != entry.document_id:
                index.ambiguous_doi.add(doi_key)
        title_key = normalize_title(entry.title)
        if title_key:
            existing = index.by_title.get(title_key)
            if existing is None:
                index.by_title[title_key] = entry.document_id
            elif existing != entry.document_id:
                index.ambiguous_title.add(title_key)
    for key in index.ambiguous_doi:
        index.by_doi.pop(key, None)
    for key in index.ambiguous_title:
        index.by_title.pop(key, None)
    return index


def resolve_reference(reference: PaperReference, index: CitationIndex,
                      *, index_number: int = 0) -> ResolvedReference:
    document_id, matched_by = index.resolve(doi=reference.doi, title=reference.title)
    return ResolvedReference(
        index=index_number,
        raw=reference.raw,
        document_id=document_id,
        matched_by=matched_by,  # type: ignore[arg-type]
    )


def resolve_references(
    references: Iterable[PaperReference],
    entries: Iterable[LibraryEntry] | CitationIndex,
) -> ResolveResult:
    """Back-fill ``resolved_document_id`` on a copy of the reference list."""

    index = entries if isinstance(entries, CitationIndex) else build_index(entries)
    resolved: list[PaperReference] = []
    resolutions: list[ResolvedReference] = []
    unresolved = 0
    for position, reference in enumerate(references):
        match = resolve_reference(reference, index, index_number=position)
        document_id = match.document_id
        if document_id is None:
            unresolved += 1
        resolved.append(reference.model_copy(update={"resolved_document_id": document_id}))
        resolutions.append(match)
    notes: list[str] = []
    if index.ambiguous_doi:
        notes.append(f"ambiguous-doi-keys:{len(index.ambiguous_doi)}")
    if index.ambiguous_title:
        notes.append(f"ambiguous-title-keys:{len(index.ambiguous_title)}")
    return ResolveResult(
        references=resolved, resolutions=resolutions, unresolved=unresolved, notes=notes
    )


@dataclass(frozen=True)
class CitationSource:
    """One paper's references, for citation-graph construction."""

    document_id: str
    references: tuple[PaperReference, ...] = ()


class CitationEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    matched_by: Literal["doi", "title"] = "title"


class CitationGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[str] = Field(default_factory=list)
    edges: list[CitationEdge] = Field(default_factory=list)


def build_citation_graph(
    sources: Iterable[CitationSource],
    entries: Iterable[LibraryEntry] | CitationIndex,
) -> CitationGraph:
    """Deterministic, de-duplicated citation graph between library papers."""

    index = entries if isinstance(entries, CitationIndex) else build_index(entries)
    nodes: set[str] = set()
    edges: set[tuple[str, str, str]] = set()
    for source in sources:
        nodes.add(source.document_id)
        for reference in source.references:
            target, matched_by = index.resolve(doi=reference.doi, title=reference.title)
            if target is None or target == source.document_id:
                continue
            nodes.add(target)
            edges.add((source.document_id, target, matched_by or "title"))
    return CitationGraph(
        nodes=sorted(nodes),
        edges=[
            CitationEdge(source=s, target=t, matched_by=matched_by)  # type: ignore[arg-type]
            for s, t, matched_by in sorted(edges)
        ],
    )
