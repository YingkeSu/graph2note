"""Deterministic front-page metadata extraction for paper imports (SPW I 轨 P2).

This module is the pure, offline core of the paper metadata feature.  Its input
is a plain data structure — full text + first-page text + (optionally) the
reference section text — and its output is the contract shape from
``.scratch/structure-paper-weekly/SPEC.md`` §2:

- :class:`PaperMeta` (title / authors / year / venue / doi / abstract /
  keywords / source);
- a per-field :class:`FieldProvenance` map (the contract keeps provenance out
  of ``PaperMeta`` itself).

Everything is a pure function of the input text: no clock, no network, no LLM.
Given the same input the byte-level result is identical, so a fixture can be
replayed and asserted.

The LLM enhancement lives in :mod:`graph2note.papers.enhance` and can only
*fill empty fields* after schema validation; it never bypasses this module.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

MetaSource = Literal["text-layer", "vlm", "manual", "none"]
Confidence = Literal["high", "medium", "low"]

__all__ = [
    "Confidence",
    "FieldProvenance",
    "MetaSource",
    "PaperMeta",
    "PaperMetaResult",
    "PaperText",
    "normalize_doi",
    "normalize_title",
    "parse_paper_meta",
    "split_front_text",
]


class PaperMeta(BaseModel):
    """Paper-level metadata (SPEC §2 数据形状)."""

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: str = ""
    doi: str = ""
    abstract: str = ""
    keywords: list[str] = Field(default_factory=list)
    source: MetaSource = "none"

    @field_validator("doi")
    @classmethod
    def _normalize_doi(cls, value: str) -> str:
        # Manual corrections and LLM proposals share the canonical DOI shape.
        return normalize_doi(value) if value else ""


class FieldProvenance(BaseModel):
    """Where one metadata field came from (never stored inside PaperMeta)."""

    model_config = ConfigDict(extra="forbid")

    source: MetaSource = "none"
    confidence: Confidence = "low"
    evidence: str = ""


class PaperText(BaseModel):
    """The contract's pure input: full text + front page + references text.

    P1 produces this shape; P2 never imports P1 code.  ``front_text`` is the
    first page (or the title/author/abstract region); ``references_text`` may
    be empty, in which case the references section is located from
    ``full_text``.
    """

    model_config = ConfigDict(extra="forbid")

    full_text: str = ""
    front_text: str = ""
    references_text: str = ""


class PaperMetaResult(BaseModel):
    """Deterministic metadata plus per-field provenance and human notes."""

    model_config = ConfigDict(extra="forbid")

    meta: PaperMeta = Field(default_factory=PaperMeta)
    provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared normalizers (used by citegraph too — single implementation)
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    """Case/whitespace/punctuation-folded title key (SPEC §2 关联要求)."""

    text = str(title or "").casefold()
    text = text.replace("&", " and ")
    # Keep word characters and CJK; everything else (punctuation) folds to space.
    text = "".join(ch if (ch.isalnum() or ch in "_") else " " for ch in text)
    return " ".join(text.split())


def normalize_doi(doi: str) -> str:
    """Strip ``doi:`` / resolver prefixes and case-fold a DOI."""

    text = str(doi or "").strip()
    text = text.strip().strip("<>")
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text, flags=re.I)
    text = text.strip().rstrip(".,;)")
    return text.casefold()


# ---------------------------------------------------------------------------
# Front-page heuristics
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+", re.I)
_ARXIV_RE = re.compile(r"arXiv[:\s]*(\d{2})(\d{2})\.\d{4,5}", re.I)
_COPYRIGHT_RE = re.compile(r"(?:©|\(c\)|copyright)\s*(\d{4})", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")

_VENUE_RE = re.compile(
    r"\b(?:transactions|proceedings|journal|conference|symposium|workshop|"
    r"letters|magazine|bulletin|annals|preprint|arxiv|"
    r"cvpr|iccv|eccv|icml|iclr|neurips|nips|acl|emnlp|naacl|aaai|ijcai|"
    r"kdd|sigir|wsdm|tkde|tpami)\b",
    re.I,
)
# A venue line must look like publication metadata, not just contain a word
# such as "Journal" that could be part of a title.
_STRONG_VENUE_RE = re.compile(
    r"^(?:ieee|acm\b|proceedings\b|journal\s+of\b|transactions\b|arxiv|"
    r"preprint\b|advances\s+in\b|frontiers\b|lecture\s+notes\b|"
    r"communications\b|annals\b|bulletin\b)",
    re.I,
)
_HEADER_JUNK_RE = re.compile(
    r"^(?:vol\.|volume\b|no\.|issue\b|pp\.|©|\(c\)|copyright\b|received\b|"
    r"accepted\b|published\b|preprint\b|https?://|www\.|issn\b|isbn\b|doi\b|"
    r"arxiv:|\d{4}\s*年|第\s*\d+\s*[卷期])",
    re.I,
)
_AFFIL_RE = re.compile(
    r"\b(?:universit|institut|laborator|department|school|college|academy|"
    r"research|inc\.|ltd\.|corp\.|gmbh)\b",
    re.I,
)
_ABSTRACT_RE = re.compile(r"^\s*(?:abstract|摘要)\b[\s:：—\-–]*", re.I)
#: The same label when a reflowed text layer glues it after the byline
#: (``… Ming Li Abstract—…``).  Both the author boundary and
#: ``_extract_abstract`` use it; the latter only accepts a match preceded by a
#: known author line, so a title that merely contains the word "abstract" is
#: not mistaken for the summary.
_ABSTRACT_INLINE_RE = re.compile(r"(?:abstract|摘要)\b[\s:：—\-–]*", re.I)
_KEYWORDS_RE = re.compile(
    r"^\s*(?:index\s+terms|keywords?|key\s+words|关键词)\s*[:：—\-–]?\s*(.*)$",
    re.I,
)
_STOP_RE = re.compile(
    r"^\s*(?:index\s+terms|keywords?|key\s+words|ccs\s+concepts|关键词|"
    r"(?:\d+|[ivx]+)\.?\s+[a-z\u4e00-\u9fff])",
    re.I,
)
_CJK_NAMES_RE = re.compile(r"^[\u4e00-\u9fff]{2,4}(?:\s*[,，、]\s*[\u4e00-\u9fff]{2,4}){1,10}$")
_INITIAL_RE = re.compile(r"\b[A-Z]\.")
_NAME_TOKEN_RE = re.compile(r"\b[A-Z][a-z]+(?:[-'][A-Za-z]+)?\b")
_EMAIL_RE = re.compile(r"\S+@\S+")
_SUPERSCRIPT_RE = re.compile(r"[\d*†‡§¶#]+")
#: Prose that a reflowed text layer glued onto the author block: sentence-final
#: punctuation plus *lowercase* function words is a sentence, not a name list.
#: The match is deliberately case-sensitive — a byline may legitimately carry
#: a name colliding with a hint word (``Will Smith``, ``Can The``), and only
#: prose spells those words lowercase.
_SENTENCE_STOP_RE = re.compile(r"[.!?。！？]\s*$")
_SENTENCE_HINT_RE = re.compile(
    r"\b(?:the|this|these|those|is|are|was|were|has|have|had|which|that|"
    r"we|our|it|its|can|could|will|would|should|be|been|not|also|however)\b"
)
#: Lowercase prose words that never occur in a byline.  They tell a title that
#: merely contains "abstract" apart from a real author prefix glued to a label.
#: Case-sensitive like `_SENTENCE_HINT_RE`, so a byline carrying a name such as
#: "Will" or "Can" is not read as prose.
_PROSE_LEAD_RE = re.compile(
    r"\b(?:of|the|this|that|these|those|which|who|is|are|was|were|be|been|"
    r"being|has|have|had|for|with|from|into|onto|about|study|survey|review|"
    r"analysis|paper|approach|method|methods|using|based|toward|towards|via|"
    r"we|our|it|its|can|could|will|would|should|not|also|however)\b"
)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def split_front_text(full_text: str, *, max_chars: int = 4000) -> str:
    """Best-effort first-page slice when a caller has no explicit front text."""

    text = str(full_text or "")
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    return text[: cut if cut > 0 else max_chars]


def _paragraphs(text: str) -> list[list[str]]:
    out: list[list[str]] = []
    current: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if line:
            current.append(line)
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def _is_venue_header_line(text: str) -> bool:
    """A venue line carries a year or starts with a known publication name."""

    if not _VENUE_RE.search(text) or len(text.split()) > 40:
        return False
    return bool(_YEAR_RE.search(text) or _STRONG_VENUE_RE.match(text))


def _is_header_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    if _HEADER_JUNK_RE.match(text):
        return True
    return len(text) <= 200 and _is_venue_header_line(text)


def _looks_like_author_line(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 260 or "@" in text:
        return False
    if _is_header_line(text) or _AFFIL_RE.search(text):
        return False
    if _CJK_NAMES_RE.match(text):
        return True
    tokens = _NAME_TOKEN_RE.findall(text)
    if len(tokens) < 2:
        return False
    has_sep = bool(re.search(r"[,;、，]|\band\b|&", text))
    has_initial = bool(_INITIAL_RE.search(text))
    return has_sep and (has_initial or len(text.split()) >= 2)


def _strip_author_noise(text: str) -> str:
    text = _EMAIL_RE.sub("", text)
    text = _SUPERSCRIPT_RE.sub("", text)
    return _clean(text)


def _looks_like_sentence_line(line: str) -> bool:
    """True for a prose line that must not be read as an author name list."""

    text = line.strip()
    if len(text) < 40 or not _SENTENCE_STOP_RE.search(text):
        return False
    return bool(_SENTENCE_HINT_RE.search(text))


def _author_lines_before_abstract(lines: list[str]) -> list[str]:
    """Cut author lines at the abstract start (label or prose sentence).

    Reflowed text-layer paragraphs merge the byline and the abstract into one
    block; everything from the abstract heading onward must never reach
    :func:`_parse_authors`.  When the label is glued after the names on one
    line, that line contributes only its leading name part.
    """

    kept: list[str] = []
    for line in lines:
        match = _ABSTRACT_RE.match(line) or _ABSTRACT_INLINE_RE.search(line)
        if match:
            head = _clean(line[: match.start()])
            # A head carrying prose words means the line was a title, not a
            # byline with a glued label; keep nothing from it.
            if head and not _PROSE_LEAD_RE.search(head):
                kept.append(head)
            break
        # The sentence heuristic only guards *extra* lines: the first line
        # already passed ``_looks_like_author_line`` (it is what opened the
        # author block), so a name such as "Will" must never drop it.
        if kept and _looks_like_sentence_line(line):
            break
        kept.append(line)
    return kept


def _parse_authors(author_lines: list[str]) -> list[str]:
    text = _strip_author_noise(" ".join(_author_lines_before_abstract(author_lines)))
    if not text:
        return []
    if _CJK_NAMES_RE.match(text):
        return [part.strip() for part in re.split(r"[,，、]", text) if part.strip()]
    text = re.sub(r"\s+\band\b\s+", ", ", text, flags=re.I).replace("&", ",")
    authors: list[str] = []
    for part in text.split(","):
        name = _clean(part).strip(". ")
        if not name or name.casefold() in {"and", "et al"}:
            continue
        # Drop affiliation fragments glued onto the author list.
        if _AFFIL_RE.search(name):
            continue
        authors.append(name)
    return authors


def _title_lines(paragraphs: list[list[str]]) -> tuple[list[str], list[str], list[list[str]]]:
    """Split (title, author lines, remaining paragraphs) from front paragraphs."""

    if not paragraphs:
        return [], [], []
    first = paragraphs[0]
    author_at = next((i for i, line in enumerate(first) if _looks_like_author_line(line)), None)
    if author_at is not None and author_at > 0:
        return (
            first[:author_at],
            _author_lines_before_abstract(first[author_at:]),
            paragraphs[1:],
        )
    if author_at == 0:
        return [], _author_lines_before_abstract(first), paragraphs[1:]
    rest = paragraphs[1:]
    if rest and _looks_like_author_line(rest[0][0]):
        return first, _author_lines_before_abstract(rest[0]), rest[1:]
    return first, [], rest


def _extract_abstract(
    paragraphs: list[list[str]], author_lines: Optional[list[str]] = None
) -> tuple[str, str]:
    """Return ``(abstract body, evidence line)`` for the first abstract block.

    The label normally heads its own line, but a reflowed text layer may glue
    it after the byline (``… Ming Li Abstract—…``).  An inline label is only
    accepted when the text before it is one of the known author lines, which
    keeps a title containing the word "abstract" from being mistaken for the
    summary.
    """

    author_keys = {_clean(line) for line in (author_lines or []) if _clean(line)}
    for para in paragraphs:
        for index, line in enumerate(para):
            match = _ABSTRACT_RE.match(line)
            if match is None:
                inline = _ABSTRACT_INLINE_RE.search(line)
                lead = _clean(line[: inline.start()]) if inline else ""
                if inline is None or lead not in author_keys:
                    continue
                match = inline
            body = _clean(line[match.end():])
            pieces = [body] if body else []
            for following in para[index + 1:]:
                if _STOP_RE.match(following):
                    break
                pieces.append(following)
            text = _clean(" ".join(pieces))
            if text:
                return text, line[:200]
    return "", ""


def _extract_keywords(paragraphs: list[list[str]]) -> tuple[list[str], str]:
    for para in paragraphs:
        match = _KEYWORDS_RE.match(para[0])
        if not match:
            continue
        value = match.group(1).strip()
        if not value and len(para) > 1 and not _STOP_RE.match(para[1]):
            value = para[1]
        value = re.split(r"(?<=[.!?])\s+(?=[A-Z])", value)[0]
        parts = [p.strip(" .;") for p in re.split(r"[,;，；、]", value)]
        keywords = [p for p in parts if p]
        if keywords:
            return keywords, para[0][:200]
    return [], ""


def _extract_doi(front_text: str, full_text: str) -> tuple[str, str]:
    doi, evidence = "", ""
    for source in (front_text, full_text):
        match = _DOI_RE.search(source or "")
        if match:
            doi = normalize_doi(match.group(0))
            evidence = match.group(0)[:200]
            break
    return doi, evidence


def _extract_year(
    front_text: str, header_lines: list[str], venue: str
) -> tuple[Optional[int], Confidence, str]:
    match = _ARXIV_RE.search(front_text or "")
    if match:
        return 2000 + int(match.group(1)), "high", match.group(0)[:120]
    match = _COPYRIGHT_RE.search(front_text or "")
    if match:
        return int(match.group(1)), "high", match.group(0)[:120]
    for line in header_lines:
        ym = _YEAR_RE.search(line)
        if ym:
            return int(ym.group(1)), "high", line[:200]
    if venue:
        ym = _YEAR_RE.search(venue)
        if ym:
            return int(ym.group(1)), "high", venue[:200]
    ym = _YEAR_RE.search(front_text or "")
    if ym:
        return int(ym.group(1)), "medium", ym.group(0)
    return None, "low", ""


def _clean_venue(line: str) -> str:
    text = _clean(line)
    text = re.sub(r"\s*[,，]\s*(?:19|20)\d{2}\s*$", "", text)
    text = text.strip(" .;:：")
    return text


def _extract_venue(header_lines: list[str], front_text: str) -> tuple[str, Confidence, str]:
    for line in header_lines:
        if _ARXIV_RE.search(line):
            # An arXiv identifier line names the archive, not the full header.
            return "arXiv", "high", line[:200]
        if _VENUE_RE.search(line):
            return _clean_venue(line), "high", line[:200]
    match = re.search(r"(?im)^\s*(arxiv\s+preprint)\b.*$", front_text or "")
    if match:
        return _clean(match.group(1)), "medium", match.group(0)[:200]
    return "", "low", ""


def _provenance(source: MetaSource, confidence: Confidence, evidence: str) -> FieldProvenance:
    return FieldProvenance(source=source, confidence=confidence, evidence=evidence or "")


def parse_paper_meta(
    front_text: str,
    *,
    full_text: str = "",
    source: MetaSource = "text-layer",
) -> PaperMetaResult:
    """Parse ``PaperMeta`` from the first-page text, deterministically.

    ``source`` records the channel the text came from (``text-layer`` for a
    born-digital extraction, ``vlm`` for the scanned fallback).  When no front
    text is available the result is an empty ``none``-sourced meta.
    """

    text = str(front_text or "")
    if not text.strip():
        empty = PaperMeta(source="none")
        provenance = {
            field: _provenance("none", "low", "") for field in _META_FIELDS
        }
        return PaperMetaResult(meta=empty, provenance=provenance, notes=["front-text-empty"])

    notes: list[str] = []
    paragraphs = _paragraphs(text)
    header_lines: list[str] = []
    if paragraphs:
        first = paragraphs[0]
        k = 0
        while k < len(first) and _is_header_line(first[k]):
            k += 1
        header_lines = first[:k]
        if k >= len(first):
            paragraphs = paragraphs[1:]
        else:
            paragraphs = [first[k:]] + paragraphs[1:]

    title_block, author_lines, _rest = _title_lines(paragraphs)
    title = _clean(" ".join(title_block)).rstrip(".")
    authors = _parse_authors(author_lines)
    abstract, abstract_evidence = _extract_abstract(paragraphs, author_lines)
    keywords, keywords_evidence = _extract_keywords(paragraphs)
    doi, doi_evidence = _extract_doi(text, full_text)
    venue, venue_confidence, venue_evidence = _extract_venue(header_lines, text)
    year, year_confidence, year_evidence = _extract_year(text, header_lines, venue)

    if not title:
        notes.append("title-not-found")
    if not authors:
        notes.append("authors-not-found")
    if not abstract:
        notes.append("abstract-not-found")
    if not keywords:
        notes.append("keywords-not-found")
    if not venue:
        notes.append("venue-not-found")
    if year is None:
        notes.append("year-not-found")

    meta = PaperMeta(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        abstract=abstract,
        keywords=keywords,
        source=source if any([title, authors, year, venue, doi, abstract, keywords]) else "none",
    )
    provenance = {
        "title": _provenance(source, "high" if title else "low",
                             _clean(" ".join(title_block))[:200] if title else ""),
        "authors": _provenance(source, "high" if authors else "low",
                               _clean(" ".join(author_lines))[:200] if authors else ""),
        "year": _provenance(source, year_confidence, year_evidence),
        "venue": _provenance(source, venue_confidence, venue_evidence),
        "doi": _provenance(source, "high" if doi else "low", doi_evidence),
        "abstract": _provenance(source, "high" if abstract else "low", abstract_evidence),
        "keywords": _provenance(source, "high" if keywords else "low", keywords_evidence),
        "source": _provenance(source, "high", ""),
    }
    return PaperMetaResult(meta=meta, provenance=provenance, notes=notes)


_META_FIELDS = ("title", "authors", "year", "venue", "doi", "abstract", "keywords", "source")
