"""Reference-section location and entry splitting for paper imports (P2).

Input: the paper's full text (and/or an already-extracted reference section).
Output: the SPEC §2 ``PaperReference`` list plus an explainable provenance trail.

Design rules (acceptance criteria §2):

- **Location first.** ``locate_references_section`` finds the *last* heading
  among ``References`` / ``Bibliography`` / ``Works Cited`` / ``参考文献`` and
  cuts at an appendix/acknowledgement heading.  Nothing is invented when no
  heading exists.
- **Two authoritative styles.** Numbered entries (``[1]`` / ``1.`` / ``1)``)
  split on the numbering; unnumbered entries split on blank lines, else on
  author-start lines.
- **Conservative fallback.** When a block has neither numbering nor reliable
  entry starts, it is *merged* and the entry carries a provenance note — the
  module never silently fabricates entries.
- **Cross-column line breaks** are rejoined, and a hyphenated break is
  de-hyphenated with a ``dehyphenated`` note.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .metadata import (
    FieldProvenance,
    PaperMeta,
    PaperMetaResult,
    PaperText,
    normalize_doi,
    parse_paper_meta,
    split_front_text,
    _YEAR_RE,
)

__all__ = [
    "PaperDocument",
    "PaperReference",
    "ReferenceEntry",
    "ReferenceParse",
    "ReferenceProvenance",
    "ReferenceSection",
    "extract_references",
    "locate_references_section",
    "parse_paper_text",
    "parse_reference_entry",
    "parse_references",
    "split_reference_entries",
]

import re  # noqa: E402

RefStyle = Literal["numbered", "author-year", "unknown"]

_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:\d+\.?\s*)?(references|bibliography|works\s+cited|参考文献)\s*:?\s*$",
    re.I,
)
_APPENDIX_HEADING_RE = re.compile(
    r"^\s*(?:appendix\b.*|acknowledg(?:e)?ments?\b.*|作者简介\s*$|附录\s*$)",
    re.I,
)
_NUMBERED_START_RE = re.compile(r"^\s*(?:\[(\d{1,4})\]|\((\d{1,4})\)|(\d{1,4})[.)])\s+")
_AUTHOR_YEAR_START_RE = re.compile(
    r"^[A-Z][A-Za-z'’\-]+,\s*(?:[A-Z]\.|[A-Z][a-z]+)"
)
_INITIAL_FIRST_START_RE = re.compile(r"^[A-Z]\.\s*[A-Z][a-z]")
_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+", re.I)
_AFFIL_RE = re.compile(
    r"\b(?:universit|institut|laborator|department|school|college|academy|"
    r"research|inc\.|ltd\.|corp\.)\b",
    re.I,
)
_EMAIL_RE = re.compile(r"\S+@\S+")
_INITIAL_RE = re.compile(r"\b[A-Z]\.")
_NAME_TOKEN_RE = re.compile(r"\b[A-Z][a-z]+(?:[-'][A-Za-z]+)?\b")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


class PaperReference(BaseModel):
    """One reference entry (SPEC §2 数据形状)."""

    model_config = ConfigDict(extra="forbid")

    raw: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: str = ""
    resolved_document_id: Optional[str] = None


class ReferenceProvenance(BaseModel):
    """How one reference entry was located/split (goes beside, not inside)."""

    model_config = ConfigDict(extra="forbid")

    index: int
    style: RefStyle = "unknown"
    fragments: int = 1
    notes: list[str] = Field(default_factory=list)


class ReferenceSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str
    start_line: int
    text: str


class ReferenceEntry(BaseModel):
    """Internal richer entry with split provenance and a contract projection."""

    model_config = ConfigDict(extra="forbid")

    index: int = 0
    style: RefStyle = "unknown"
    raw: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: Optional[int] = None
    doi: str = ""
    fragments: int = 1
    notes: list[str] = Field(default_factory=list)

    def reference(self) -> PaperReference:
        return PaperReference(
            raw=self.raw,
            title=self.title,
            authors=list(self.authors),
            year=self.year,
            doi=self.doi,
        )

    def provenance(self) -> ReferenceProvenance:
        return ReferenceProvenance(
            index=self.index, style=self.style, fragments=self.fragments,
            notes=list(self.notes),
        )


class ReferenceParse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    references: list[PaperReference] = Field(default_factory=list)
    entries: list[ReferenceEntry] = Field(default_factory=list)
    provenance: list[ReferenceProvenance] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PaperDocument(BaseModel):
    """Combined deterministic parse output for one paper (P2 surface)."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    meta: PaperMeta = Field(default_factory=PaperMeta)
    meta_provenance: dict[str, FieldProvenance] = Field(default_factory=dict)
    references: list[PaperReference] = Field(default_factory=list)
    references_provenance: list[ReferenceProvenance] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Section location
# ---------------------------------------------------------------------------

def locate_references_section(full_text: str) -> ReferenceSection | None:
    """Return the trailing reference section, or ``None`` when absent."""

    text = str(full_text or "")
    if not text.strip():
        return None
    lines = text.splitlines()
    index: int | None = None
    for i, line in enumerate(lines):
        if _SECTION_HEADING_RE.match(line):
            index = i  # keep scanning: the last heading is the real section
    if index is None:
        return None
    body_lines: list[str] = []
    for line in lines[index + 1:]:
        if _APPENDIX_HEADING_RE.match(line):
            break
        body_lines.append(line)
    body = "\n".join(body_lines).strip("\n")
    return ReferenceSection(heading=lines[index].strip(), start_line=index, text=body)


# ---------------------------------------------------------------------------
# Entry splitting
# ---------------------------------------------------------------------------

def _group_by_blank_lines(text: str) -> list[list[str]]:
    groups: list[list[str]] = []
    current: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if line.strip():
            current.append(line.strip())
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def _join_fragments(lines: list[str]) -> tuple[str, int]:
    """Join wrapped lines, de-hyphenating cross-column breaks."""

    out = ""
    dehyphenated = 0
    for line in lines:
        piece = line.strip()
        if not piece:
            continue
        if out.endswith("-") and not out.endswith(("--", " -")):
            out = out[:-1] + piece
            dehyphenated += 1
        else:
            out = f"{out} {piece}".strip()
    return _clean(out), dehyphenated


def _numbered_groups(text: str) -> tuple[list[list[str]], str | None]:
    groups: list[list[str]] = []
    current: list[str] | None = None
    preamble: list[str] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _NUMBERED_START_RE.match(line):
            if current is not None:
                groups.append(current)
            current = [line]
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    if current is not None:
        groups.append(current)
    note = "preamble-ignored" if preamble else None
    return groups, note


def _author_year_groups(text: str) -> tuple[list[list[str]], str | None]:
    blank_groups = _group_by_blank_lines(text)
    if len(blank_groups) > 1:
        return blank_groups, "split:blank-line"

    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return [], None
    starts = [
        i for i, line in enumerate(lines)
        if _AUTHOR_YEAR_START_RE.match(line) or _INITIAL_FIRST_START_RE.match(line)
    ]
    if len(starts) <= 1:
        return [lines], "merged-no-separator"
    groups: list[list[str]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        groups.append(lines[start:end])
    return groups, "split:author-start"


def _merge_incomplete(groups: list[list[str]]) -> tuple[list[list[str]], list[list[str]]]:
    """Merge a trailing year-less fragment into the previous entry (conservative)."""

    merged: list[list[str]] = []
    notes: list[list[str]] = []
    for group in groups:
        if merged and not _YEAR_RE.search(" ".join(group)):
            merged[-1].extend(group)
            notes[-1].append("merged-incomplete")
        else:
            merged.append(list(group))
            notes.append([])
    return merged, notes


def split_reference_entries(text: str) -> list[ReferenceEntry]:
    """Split a reference section into entries with explainable provenance."""

    raw_text = str(text or "")
    if not raw_text.strip():
        return []
    first_line = next((line for line in raw_text.splitlines() if line.strip()), "")
    if _NUMBERED_START_RE.match(first_line):
        groups, note = _numbered_groups(raw_text)
        style: RefStyle = "numbered"
        group_notes = [[note] if note else [] for _ in groups]
    else:
        groups, note = _author_year_groups(raw_text)
        style = "author-year"
        groups, group_notes = _merge_incomplete(groups)
        if note:
            group_notes = [list(notes) for notes in group_notes]
            if note == "merged-no-separator" and len(groups) == 1:
                group_notes[0].append(note)

    entries: list[ReferenceEntry] = []
    for index, group in enumerate(groups):
        raw, dehyphenated = _join_fragments(group)
        if not raw:
            continue
        notes = list(group_notes[index]) if index < len(group_notes) else []
        if dehyphenated:
            notes.append("dehyphenated")
        if len(group) > 1:
            notes.append("merged-continuation")
        entry = parse_reference_entry(raw, index=index, style=style, notes=notes)
        entry.fragments = len(group)
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# Single-entry parsing
# ---------------------------------------------------------------------------

def _strip_number(raw: str) -> str:
    return _NUMBERED_START_RE.sub("", raw, count=1).strip()


def _pick_year(text: str) -> Optional[int]:
    match = re.search(r"\((19\d{2}|20\d{2})\)", text)
    if match:
        return int(match.group(1))
    years = _YEAR_RE.findall(text)
    if years:
        return int(years[-1])
    return None


def _parse_author_list(text: str) -> list[str]:
    text = _EMAIL_RE.sub("", text).strip()
    if not text:
        return []
    text = re.sub(r"\bet\s+al\.?", "", text, flags=re.I)
    # Surname-first style: ``Zhang, W., Chen, L.`` -> initials-first names.
    if re.match(r"^[A-Z][A-Za-z'’\-]+,\s*[A-Z]\.", text):
        pairs = re.findall(r"([A-Z][A-Za-z'’\-]+),\s*((?:[A-Z]\.\s*)+)", text)
        if pairs:
            return [f"{_clean(initials)} {surname}" for surname, initials in pairs]
    # Single "Surname, Firstname" pair.
    single = re.match(r"^([A-Z][A-Za-z'’\-]+),\s*([A-Z][a-z]+)\.?$", text)
    if single:
        return [f"{single.group(2)} {single.group(1)}"]
    text = re.sub(r"\s+\band\b\s+", ", ", text, flags=re.I).replace("&", ",")
    authors: list[str] = []
    for part in text.split(","):
        name = _clean(part).strip(". ")
        if not name or name.casefold() in {"and", "et al"}:
            continue
        if _AFFIL_RE.search(name):
            continue
        authors.append(name)
    return authors


def _looks_like_author_segment(text: str) -> bool:
    text = text.strip()
    if not text or len(text) > 220 or _AFFIL_RE.search(text):
        return False
    if not re.search(r"[,;]|\band\b|&", text):
        return False
    tokens = _NAME_TOKEN_RE.findall(text)
    return len(tokens) >= 1 and bool(_INITIAL_RE.search(text) or len(tokens) >= 2)


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[a-z0-9\)\.])\.\s+", text.strip(), maxsplit=1)[0].strip(" .")


def parse_reference_entry(
    raw: str,
    *,
    index: int = 0,
    style: RefStyle = "unknown",
    notes: list[str] | None = None,
) -> ReferenceEntry:
    """Best-effort field extraction for one (already split) entry."""

    notes = list(notes or [])
    body = _strip_number(raw)
    doi = ""
    doi_match = _DOI_RE.search(body)
    if doi_match:
        doi = normalize_doi(doi_match.group(0))
    year = _pick_year(body)

    authors: list[str] = []
    title = ""
    paren_year = re.search(r"\((19\d{2}|20\d{2})\)", body)
    if paren_year:
        authors = _parse_author_list(body[: paren_year.start()])
        rest = body[paren_year.end():].lstrip(". ")
        title = _first_sentence(rest)
    else:
        segments = re.split(r"(?<![A-Z])\.\s+", body)
        if segments and _looks_like_author_segment(segments[0]):
            authors = _parse_author_list(segments[0])
            title = _first_sentence(segments[1]) if len(segments) > 1 else ""
        elif segments:
            title = _first_sentence(segments[0])

    if not authors:
        notes.append("authors-unparsed")
    if year is None:
        notes.append("year-not-found")
    return ReferenceEntry(
        index=index,
        style=style,
        raw=raw,
        title=title,
        authors=authors,
        year=year,
        doi=doi,
        fragments=1,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Public parse entry points
# ---------------------------------------------------------------------------

def parse_references(text: str) -> ReferenceParse:
    """Parse a references section (or a full text containing one).

    If a ``References``-style heading is present anywhere in ``text``, only the
    trailing section is parsed; otherwise the whole input is treated as the
    reference list.
    """

    raw = str(text or "")
    notes: list[str] = []
    section = locate_references_section(raw)
    if section is not None:
        body = section.text
        notes.append(f"section:{section.heading}")
    else:
        body = raw
        notes.append("section-not-found:treating-input-as-references")
    entries = split_reference_entries(body)
    return ReferenceParse(
        references=[entry.reference() for entry in entries],
        entries=entries,
        provenance=[entry.provenance() for entry in entries],
        notes=notes,
    )


def extract_references(text: str) -> list[PaperReference]:
    """Contract projection: just the ``list[PaperReference]``."""

    return parse_references(text).references


def parse_paper_text(paper: PaperText | dict[str, Any] | str, *,
                     source: str = "text-layer") -> PaperDocument:
    """Run the full deterministic P2 parse over the contract input shape."""

    if isinstance(paper, PaperText):
        data = paper
    elif isinstance(paper, dict):
        data = PaperText.model_validate(paper)
    else:
        data = PaperText(full_text=str(paper or ""))
    front = data.front_text or split_front_text(data.full_text)
    notes: list[str] = []
    if not data.front_text and data.full_text:
        notes.append("front-text-derived-from-full-text")
    meta_result: PaperMetaResult = parse_paper_meta(
        front, full_text=data.full_text, source=source  # type: ignore[arg-type]
    )
    notes.extend(meta_result.notes)
    references_text = data.references_text
    if not references_text:
        section = locate_references_section(data.full_text)
        if section is not None:
            references_text = section.text
            notes.append(f"references-section:{section.heading}")
        else:
            notes.append("references-section-not-found")
    reference_parse = parse_references(references_text) if references_text else ReferenceParse()
    notes.extend(reference_parse.notes)
    return PaperDocument(
        meta=meta_result.meta,
        meta_provenance=meta_result.provenance,
        references=reference_parse.references,
        references_provenance=reference_parse.provenance,
        notes=notes,
    )
