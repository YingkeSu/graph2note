"""Deterministic paper structure splitting (SPW I-track / P1).

The splitter is a **pure function over extracted text lines**, so it can be
replayed and unit-tested without a PDF:

- :func:`detect_headings` decides which lines are headings using three
  observable signals — numbered section prefixes (``1`` / ``2.1`` / ``2.1.3``),
  canonical section names (``Abstract`` / ``References`` / ``参考文献`` …) and
  font-size heuristics relative to the document's character-weighted body size;
- :func:`split_sections` assembles :class:`~graph2note.papers.model.PaperSection`
  records (level / title / text / 0-based page range) from those headings.

Every threshold is an explicit module constant and every tie-break is total
(larger character weight wins, then smaller font size, then source order), so
the same lines always produce byte-identical sections.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .model import PaperSection
from .textlayer import TextLine, count_chars, round_size

# ---------------------------------------------------------------------------
# Heuristic constants (deterministic, explicit, replayable)
# ---------------------------------------------------------------------------

#: A heading line is never longer than this (long lines are body text).
MAX_HEADING_CHARS = 120

#: Numbered prefix bound: "1" … "12.3.4" fits, a year-like "2024" does not.
MAX_NUMBER_CHARS = 8

#: Deepest section level we ever derive from a dotted number.
MAX_LEVEL = 4

#: A line must be at least this many points larger than the body size to be
#: treated as a font-size heading.
HEADING_SIZE_DELTA = 1.0

#: Canonical (unnumbered) section names → level.
CANONICAL_HEADINGS: dict[str, int] = {
    "abstract": 1,
    "摘要": 1,
    "introduction": 1,
    "引言": 1,
    "references": 1,
    "bibliography": 1,
    "参考文献": 1,
    "conclusion": 1,
    "conclusions": 1,
    "结论": 1,
    "acknowledgments": 1,
    "acknowledgements": 1,
    "致谢": 1,
    "acknowledgement": 1,
    "appendix": 1,
    "附录": 1,
    "目录": 1,
}

_NUMBERED_RE = re.compile(r"^(?P<num>\d{1,2}(?:\.\d{1,2}){0,3})\.?(?:\s+|(?=[\u4e00-\u9fff]))(?P<title>\S.*)$")
_SENTENCE_END_RE = re.compile(r"[.,;:。，；：]$")
_MID_SENTENCE_RE = re.compile(r"[。；;]|\.\s")
_NON_ALNUM_RE = re.compile(r"[\s:：.．\-—–_]+")


@dataclass
class Heading:
    """One detected heading (line index into the ordered line list)."""

    line_index: int
    level: int
    title: str
    page_index: int
    reason: str  # number|name|size

    def as_dict(self) -> dict:
        return {
            "line_index": self.line_index,
            "level": self.level,
            "title": self.title,
            "page_index": self.page_index,
            "reason": self.reason,
        }


def _sentence_like(text: str) -> bool:
    return bool(_SENTENCE_END_RE.search(text) or _MID_SENTENCE_RE.search(text))


def _looks_like_heading_text(text: str) -> bool:
    if not text or len(text) > MAX_HEADING_CHARS:
        return False
    return not _sentence_like(text)


def body_size(lines: list[TextLine]) -> float:
    """Character-weighted mode of the line font sizes (the document body size).

    Weighting by characters means a page dominated by body text wins over a few
    big headings.  Ties break to the smaller size, then lexicographically, so
    the result is total and stable.
    """
    weights: dict[float, int] = {}
    for line in lines:
        chars = count_chars(line.text)
        if not chars:
            continue
        size = round_size(line.size)
        weights[size] = weights.get(size, 0) + chars
    if not weights:
        return 0.0
    return max(sorted(weights), key=lambda size: (weights[size], -size))


def _size_levels(lines: list[TextLine], body: float) -> dict[float, int]:
    """Map each heading-sized font size to a level (largest size → level 1)."""
    sizes = sorted(
        {round_size(line.size) for line in lines if round_size(line.size) >= body + HEADING_SIZE_DELTA},
        reverse=True,
    )
    return {size: min(rank + 1, MAX_LEVEL) for rank, size in enumerate(sizes)}


def _canonical_level(title: str) -> int | None:
    normalized = _NON_ALNUM_RE.sub("", title).lower()
    if not normalized:
        return None
    return CANONICAL_HEADINGS.get(normalized)


def _accept_numbered(line: TextLine, match: re.Match, body: float) -> str | None:
    num = match.group("num")
    title = match.group("title").strip()
    if len(num) > MAX_NUMBER_CHARS or num.count(".") + 1 > MAX_LEVEL:
        return None
    if not title or not any(ch.isalnum() or "\u4e00" <= ch <= "\u9fff" for ch in title):
        return None
    # "1 the results show …" is a numbered sentence / list item, not a heading.
    first = title[0]
    if first.isalpha() and first.islower():
        return None
    if not _looks_like_heading_text(title):
        return None
    # A numbered line is accepted even at body size when it is short or bold;
    # a full-width body-size sentence stays body text.
    if line.size >= body - 0.5 or line.bold or len(title) <= 60:
        return title
    return None


def detect_headings(lines: list[TextLine]) -> list[Heading]:
    """Detect heading lines in reading order (pure, replayable)."""
    ordered = list(lines)
    body = body_size(ordered)
    levels = _size_levels(ordered, body)

    headings: list[Heading] = []
    for index, line in enumerate(ordered):
        title = (line.text or "").strip()
        if not title or len(title) > MAX_HEADING_CHARS:
            continue

        match = _NUMBERED_RE.match(title)
        if match is not None:
            numbered = _accept_numbered(line, match, body)
            if numbered is not None:
                headings.append(Heading(
                    line_index=index,
                    level=min(match.group("num").count(".") + 1, MAX_LEVEL),
                    title=numbered,
                    page_index=line.page_index,
                    reason="number",
                ))
                continue

        canonical = _canonical_level(title)
        if canonical is not None:
            headings.append(Heading(
                line_index=index,
                level=canonical,
                title=title,
                page_index=line.page_index,
                reason="name",
            ))
            continue

        size = round_size(line.size)
        if body and size >= body + HEADING_SIZE_DELTA and _looks_like_heading_text(title):
            headings.append(Heading(
                line_index=index,
                level=levels.get(size, min(2, MAX_LEVEL)),
                title=title,
                page_index=line.page_index,
                reason="size",
            ))
    return headings


def section_text(lines: list[TextLine]) -> str:
    """Join a section's lines into readable plain text (blank lines dropped)."""
    parts = [(line.text or "").strip() for line in lines]
    return "\n".join(part for part in parts if part).strip()


def split_sections(lines: list[TextLine]) -> list[PaperSection]:
    """Split ordered text lines into ``PaperSection`` records with page ranges.

    Text before the first heading becomes a leading section with an empty title
    (论文前置内容：标题/作者/摘要区), so no text is ever silently dropped.
    """
    ordered = sorted(lines, key=lambda line: line.order)
    if not ordered:
        return []
    headings = detect_headings(ordered)
    by_index = {heading.line_index: heading for heading in headings}

    # group by heading boundaries, preserving reading order
    groups: list[tuple[Heading | None, list[TextLine]]] = []
    current_heading: Heading | None = None
    current_lines: list[TextLine] = []
    for index, line in enumerate(ordered):
        heading = by_index.get(index)
        if heading is not None:
            groups.append((current_heading, current_lines))
            current_heading, current_lines = heading, []
        else:
            current_lines.append(line)
    groups.append((current_heading, current_lines))

    sections: list[PaperSection] = []
    for heading, group_lines in groups:
        text = section_text(group_lines)
        if heading is None:
            if not text:  # no front matter at all
                continue
            sections.append(PaperSection(
                level=1, title="", text=text,
                page_start=group_lines[0].page_index,
                page_end=group_lines[-1].page_index,
            ))
            continue
        if group_lines:
            page_start = group_lines[0].page_index
            page_end = group_lines[-1].page_index
        else:
            page_start = page_end = heading.page_index
        sections.append(PaperSection(
            level=heading.level, title=heading.title, text=text,
            page_start=page_start, page_end=page_end,
        ))
    return sections


__all__ = [
    "CANONICAL_HEADINGS",
    "HEADING_SIZE_DELTA",
    "MAX_HEADING_CHARS",
    "MAX_LEVEL",
    "MAX_NUMBER_CHARS",
    "Heading",
    "body_size",
    "detect_headings",
    "section_text",
    "split_sections",
]
