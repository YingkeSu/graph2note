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
#: An explicit DOI label / resolver URL on the front page.
_DOI_LABEL_RE = re.compile(
    r"(?:doi\s*:?\s*|https?://(?:dx\.)?doi\.org/)\s*(10\.\d{4,9}/[-._;()/:A-Za-z0-9<>]+)",
    re.I,
)
#: A line that reads like a reference/citation, not this paper's metadata.
_CITATION_HINT_RE = re.compile(
    r"(?:et\s+al\.?|in\s+proceedings|proceedings\s+of|journal\s+of|"
    r"conference\s+on|workshop\s+on|symposium|arxiv\s+preprint|"
    r"\(\d{4}[a-z]?\)|\[\d+\]|\bpp\.\s*\d|\bvol\.\s*\d|"
    r"\bdoi:\s*10\.\d{4,9}/[^\s]+,\s*\d{4})",
    re.I,
)
#: Copyright / identifier markers that make a front-page line metadata.
_DOI_METADATA_MARKER_RE = re.compile(
    r"(?:©|\(c\)|copyright|all\s+rights\s+reserved|issn|isbn|arxiv|"
    r"preprint|received|accepted|published|available\s+at)",
    re.I,
)
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
    r"research|inc\.|ltd\.|corp\.|gmbh)",
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
#: Matched case-insensitively on purpose: a capitalized title prefix such as
#: "A Study Of" must be rejected as prose.  A real byline is protected first by
#: `_looks_like_author_line`, so names colliding with a hint word
#: (``Will Smith``, ``Can The``) survive.
_PROSE_LEAD_RE = re.compile(
    r"\b(?:of|the|this|that|these|those|which|who|is|are|was|were|be|been|"
    r"being|has|have|had|for|with|from|into|onto|about|study|survey|review|"
    r"analysis|paper|approach|method|methods|using|based|toward|towards|via|"
    r"we|our|it|its|can|could|will|would|should|not|also|however)\b",
    re.I,
)

#: A title continues on the next line when the current one ends with a
#: connector/colon (real preprints wrap long titles before a noun, e.g.
#: ``… Transformers for`` / ``Language Understanding``).  This is what keeps a
#: wrapped title out of the byline without needing font metrics.
_TITLE_CONTINUES_RE = re.compile(
    r"(?:\b(?:of|for|the|a|an|and|or|in|on|at|to|with|from|by|as|is|are|was|"
    r"were|that|which|toward|towards|via|using|based|under|over|between|into|"
    r"onto|about|against|without|within|through|across|after|before|"
    r"when|where|while)\b|[:\-–—,;])\s*$",
    re.I,
)
#: Footnote / correspondence markers that end the abstract body.
_FOOTNOTE_RE = re.compile(r"^\s*[∗*†‡§¶#]")
#: A canonical abstract label alone on its line.  This (not any line that merely
#: starts with the word) is the reliable front-matter boundary: wrapped titles
#: such as ``… for`` / ``Abstract Meaning Representation`` must stay in the
#: title block.
_ABSTRACT_LABEL_ONLY_RE = re.compile(r"^\s*(?:abstract|摘要)\s*[:：.\-—]?\s*$", re.I)
#: A standalone section number (``1``, ``2.``, ``IV``).
_STANDALONE_NUMBER_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]+)\.?\s*$")
#: A numbered heading on one line (``1 Introduction``).
_NUMBERED_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]+)\.?\s+[A-Z\u4e00-\u9fff]"
)
#: Common section words that start a heading line.
_SECTION_WORD_RE = re.compile(
    r"^\s*(?:abstract|introduction|related\s+work|background|motivation|"
    r"preliminar(?:y|ies)|method(?:s|ology)?|approach|experiment(?:s|al)?|"
    r"result(?:s)?|evaluation|discussion|conclusion(?:s)?|references|"
    r"bibliography|acknowledg(?:e?ments?)|appendix|摘要|引言|相关工作|背景|"
    r"方法|实验|结果|讨论|结论|参考文献|致谢)(?![A-Za-z])",
    re.I,
)
#: Name particles and separators allowed inside a byline candidate.
_NAME_PARTICLES = {
    "de", "van", "von", "der", "la", "le", "el", "da", "di", "dos",
    "del", "bin", "al", "st", "saint", "mac", "mc",
}
#: Organisation names that appear on a byline without a person (``OpenAI``).
_ORG_NAMES = {
    "openai", "google", "deepmind", "meta", "microsoft", "anthropic", "amazon",
    "apple", "nvidia", "ibm", "baidu", "alibaba", "tencent", "bytedance",
    "facebook", "ai", "mit", "stanford", "berkeley", "mozilla", "salesforce",
}
#: Department/affiliation words that never belong to a personal name.
_DEPT_WORDS = {
    "university", "universities", "institute", "institution", "laboratory", "lab",
    "labs", "department", "school", "college", "academy", "research", "group",
    "team", "center", "centre", "language", "inc", "ltd", "corp", "gmbh",
}
#: Organisation/acronym tokens that can stand alone as a byline (``OpenAI``).
_ORG_TOKEN_RE = re.compile(r"^[A-Z][A-Za-z0-9]*[A-Z][A-Za-z0-9]*$|^[A-Z]{2,}$")
_INITIALS_RE = re.compile(r"^(?:[A-Z]\.){1,4}$")

#: A parsed title longer than this (or with "Abstract"/"Introduction" in it)
#: is front-page body text that leaked in, not a title — never persist it.
_MAX_TITLE_CHARS = 300
_MAX_TITLE_WORDS = 45


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


#: PDF text layers often use Unicode ligatures (``Hatﬁeld``); fold them
#: before name matching so a real author is not dropped as non-name-like.
_LIGATURES = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi",
    "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st",
}


def _strip_author_noise(text: str) -> str:
    text = str(text or "")
    for ligature, plain in _LIGATURES.items():
        text = text.replace(ligature, plain)
    text = _EMAIL_RE.sub("", text)
    text = _SUPERSCRIPT_RE.sub("", text)
    return _clean(text)


def _looks_like_sentence_line(line: str) -> bool:
    """True for a prose line that must not be read as an author name list."""

    text = line.strip()
    if len(text) < 40 or not _SENTENCE_STOP_RE.search(text):
        return False
    return bool(_SENTENCE_HINT_RE.search(text))


def _looks_like_name_line(line: str) -> bool:
    """True for a short line whose words all read as name/affiliation tokens.

    Real preprints and conference papers put **one author per line** (``Jacob
    Devlin`` / ``Ming-Wei Chang``) or a single organisation on its own line
    (``OpenAI``).  Those lack the comma/``and`` separator
    :func:`_looks_like_author_line` requires, so the byline parser needs a
    shape test of its own that still rejects prose ('Language Understanding',
    'We report the development …').
    """

    text = _strip_author_noise(line)
    text = re.sub(r"[\d∗*†‡§¶#]+", "", text).strip(" ,;、，&")
    if not text or len(text) > 120 or "@" in text:
        return False
    if _is_header_line(text) or _SENTENCE_STOP_RE.search(text):
        return False
    # A group byline may carry a leading article (``the Ming Li Group``).
    text = re.sub(r"^the\s+", "", text, flags=re.I)
    words = text.split()
    if not words or len(words) > 14:
        return False
    for word in words:
        folded = word.casefold()
        if folded in {"and", "et", "al"} or folded in _NAME_PARTICLES:
            continue
        bare = word.strip(".,;:()[]{}")
        if _NAME_TOKEN_RE.fullmatch(bare):
            continue
        if (_INITIAL_RE.fullmatch(word) or _INITIALS_RE.fullmatch(word)
                or _INITIALS_RE.fullmatch(bare)):
            continue
        if _ORG_TOKEN_RE.match(bare):
            continue
        return False
    return True


def _is_org_only(name: str) -> bool:
    """A single organisation token (``OpenAI``) — kept only if no person name."""

    words = [word for word in re.sub(r"[^\w ]", " ", name).split() if word]
    return len(words) == 1 and bool(_ORG_TOKEN_RE.match(words[0]))


def _personal_name_tokens(name: str) -> list[str]:
    """Capitalised tokens of ``name`` that are neither org nor department words."""

    tokens = re.findall(r"[A-Za-z][A-Za-z'\-]*", name or "")
    return [
        token for token in tokens
        if token.casefold() not in _ORG_NAMES
        and token.casefold() not in _DEPT_WORDS
        and token.casefold() not in _NAME_PARTICLES
        and token.casefold() not in {"and", "the", "of", "et", "al"}
    ]


def _is_affiliation_like(name: str) -> bool:
    """True for an affiliation/organisation candidate, not a personal name.

    ``Google AI Language`` is an affiliation even though it is not matched by
    ``_AFFIL_RE``; ``the Ming Li Group`` carries a personal name (``Ming Li``)
    and must survive.  Only used to prune a byline that already contains
    personal names, so a paper whose *only* byline is ``OpenAI`` keeps it.
    """

    if _AFFIL_RE.search(name or ""):
        return True
    words = [w.casefold() for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", name or "")]
    if not words:
        return False
    has_org = any(w in _ORG_NAMES for w in words)
    has_dept = any(w in _DEPT_WORDS for w in words)
    if not (has_org or has_dept):
        return False
    return len(_personal_name_tokens(name)) < 2


def _looks_like_byline_paragraph(paragraph: list[str]) -> bool:
    """True when the paragraph right after the title is a byline block.

    Used only for the paragraph *following* the title paragraph, so it can
    accept a run of separate name lines that :func:`_looks_like_author_line`
    (built for comma lists) would reject.
    """

    if not paragraph:
        return False
    head = paragraph[0].strip()
    if _ABSTRACT_RE.match(head) or _is_header_line(head):
        return False
    if _looks_like_author_line(head):
        return True
    if _looks_like_sentence_line(head):
        return False
    return any(_looks_like_name_line(line) for line in paragraph)


def _title_end_index(front: list[str]) -> int:
    """Number of leading lines that form the title (wrapped-title aware)."""

    end = 1
    while end < len(front) and _TITLE_CONTINUES_RE.search(front[end - 1]):
        end += 1
    return min(end, len(front))


def _title_is_plausible(title: str) -> bool:
    """Shape gate: a title must not be a 2 KB front-page block.

    The front-page heuristics can still over-claim on unusual layouts; a title
    that is implausibly long or contains a body heading is dropped (empty) so
    it is never persisted as ``record.title`` and the caller can degrade
    honestly instead of showing a wall of front matter.
    """

    text = _clean(title)
    if not text:
        return False
    if len(text) > _MAX_TITLE_CHARS or len(text.split()) > _MAX_TITLE_WORDS:
        return False
    if len(re.findall(r"[.!?。！？]", text)) > 1:
        return False
    if _SECTION_WORD_RE.search(text):
        return False
    return True


def _is_abstract_boundary_line(line: str, previous: str | None) -> bool:
    """True when a front-block line is the abstract heading, not a title wrap.

    A wrapped title can start a line with ``Abstract`` (``Abstract Meaning
    Representation``, ``Abstract Syntax Trees``) so only a standalone label, or
    a label followed by a sentence-like body, ends the title block.
    """

    if _ABSTRACT_LABEL_ONLY_RE.match(line):
        return True
    match = _ABSTRACT_RE.match(line)
    if match is None:
        return False
    tail = _clean(line[match.end():])
    if not tail:
        return True
    if previous and _TITLE_CONTINUES_RE.search(previous):
        return False
    return bool(_SENTENCE_STOP_RE.search(tail)) or len(tail.split()) >= 6


def _is_abstract_stop(line: str) -> bool:
    """True when the abstract body ended and a new block began."""

    text = line.strip()
    if not text:
        return True
    if _STOP_RE.match(text) or _HEADER_JUNK_RE.match(text):
        return True
    if _FOOTNOTE_RE.match(text):
        return True
    if _STANDALONE_NUMBER_RE.match(text) or _NUMBERED_HEADING_RE.match(text):
        return True
    return bool(_SECTION_WORD_RE.match(text))


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
            # Keep the head when it still reads as a byline (``Will Smith,
            # Can The``).  Only drop it as a title when it is *not* author-like
            # and carries prose words (``A Study Of``), which would otherwise
            # let the label inside a title become the abstract.
            if head and (
                _looks_like_author_line(head) or not _PROSE_LEAD_RE.search(head)
            ):
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
    """Names from the byline block, one-per-line and comma-list aware.

    The real text layer puts each author on its own line as often as it puts a
    comma-separated list on one line, so both shapes are parsed.  Affiliation
    / email / header fragments are dropped, and a single organisation token
    (``OpenAI`` on its own) is kept only when it is the *only* byline — a paper
    that lists people keeps the people and drops the org affiliation lines.
    """

    lines = _author_lines_before_abstract(author_lines)
    candidates: list[str] = []
    for line in lines:
        cleaned = re.sub(r"[\d∗*†‡§¶#]+", "", _strip_author_noise(line)).strip()
        if not cleaned or "@" in cleaned or _is_header_line(cleaned):
            continue
        if _CJK_NAMES_RE.match(cleaned):
            candidates.extend(
                part.strip() for part in re.split(r"[,，、]", cleaned) if part.strip()
            )
            continue
        for part in re.split(r"\s*(?:[,;、，]|&|\band\b)\s*", cleaned, flags=re.I):
            name = _clean(part).strip(". ")
            if not name or name.casefold() in {"and", "et al"}:
                continue
            if _AFFIL_RE.search(name):
                continue
            if not _looks_like_name_line(name):
                continue
            candidates.append(name)
    candidates = list(dict.fromkeys(candidates))
    # A paper that lists people keeps the people and drops affiliation / org
    # lines (``Google AI Language``, ``OpenAI``); a paper whose only byline is
    # an organisation keeps it (GPT-4 → ``OpenAI``).
    if any(len(_personal_name_tokens(name)) >= 2 for name in candidates):
        candidates = [name for name in candidates if not _is_affiliation_like(name)]
    return candidates


def _title_lines(paragraphs: list[list[str]]) -> tuple[list[str], list[str], list[list[str]]]:
    """Split (title, author lines, remaining paragraphs) from front paragraphs.

    The abstract label is a hard boundary: everything from it onward is the
    summary and must never be absorbed into the title (the real-library
    regression put a 2 KB title+byline+abstract block into ``record.title``).
    Within the front block the title is the leading line(s) — a wrapped title
    continues while the previous line ends with a connector — and the byline is
    either a comma list inside the block, a separate byline paragraph, or a
    run of one-name-per-line entries.
    """

    if not paragraphs:
        return [], [], []
    first = paragraphs[0]
    abstract_at = next(
        (i for i, line in enumerate(first)
         if _is_abstract_boundary_line(line, first[i - 1] if i else None)),
        None)
    header_at = next(
        (i for i, line in enumerate(first) if i > 0 and _is_header_line(line)), None)
    block_end = min(
        [index for index in (abstract_at, header_at) if index is not None],
        default=len(first),
    )
    front = first[:block_end]
    tail = [first[block_end:]] if block_end < len(first) else []
    rest = tail + paragraphs[1:]
    if not front:
        return [], [], rest

    author_at = next(
        (i for i, line in enumerate(front) if _looks_like_author_line(line)), None)
    if author_at is not None and author_at > 0:
        return (
            front[:author_at],
            _author_lines_before_abstract(front[author_at:]),
            rest,
        )
    if author_at == 0:
        return [], _author_lines_before_abstract(front), rest

    # No comma-separated byline inside the block: either a dedicated byline
    # paragraph follows the title paragraph, or the byline shares the block as
    # one-name-per-line lines (real preprints).
    if rest and _looks_like_byline_paragraph(rest[0]):
        return front, _author_lines_before_abstract(rest[0]), rest[1:]

    title_end = _title_end_index(front)
    if title_end < len(front):
        return front[:title_end], _author_lines_before_abstract(front[title_end:]), rest
    return front, [], rest


def _abstract_block(
    para: list[str],
    index: int,
    line: str,
    match: "re.Match[str]",
    following_paragraphs: tuple[list[str], ...] = (),
    author_keys: Optional[set[str]] = None,
) -> tuple[str, str]:
    """Body of an abstract whose label matched in ``line`` plus its evidence.

    When the label heads its own paragraph (``Abstract`` then a blank line) the
    body is taken from the following paragraph, up to the first stop line — but
    never from an author byline (a title that is exactly the word ``Abstract``
    must not absorb the author paragraph).
    """

    body = _clean(line[match.end():])
    pieces = [body] if body else []
    for following in para[index + 1:]:
        if _is_abstract_stop(following):
            return _clean(" ".join(pieces)), line[:200]
        pieces.append(following)
    if not pieces:
        for nxt in following_paragraphs:
            if not nxt:
                continue
            head = _clean(nxt[0])
            if (author_keys and head in author_keys) or _looks_like_author_line(head):
                return "", line[:200]
            for following in nxt:
                if _is_abstract_stop(following):
                    return _clean(" ".join(pieces)), line[:200]
                pieces.append(following)
            if pieces:
                break
    return _clean(" ".join(pieces)), line[:200]


def _extract_abstract(
    paragraphs: list[list[str]],
    author_lines: Optional[list[str]] = None,
    title_lines: Optional[list[str]] = None,
) -> tuple[str, str]:
    """Return ``(abstract body, evidence line)`` for the first abstract block.

    The label normally heads its own line, but a reflowed text layer may glue
    it after the byline (``… Ming Li Abstract—…``).  Candidates are ranked so
    that a title cannot shadow the real summary:

    1. a canonical label that heads its own paragraph (``index == 0``);
    2. a canonical label appearing mid-paragraph;
    3. an inline label glued after a known author line.

    The paragraph-head tier matters because ``_looks_like_author_line`` can
    claim a title line (``Neural Networks, Deep Learning for``), leaving its
    wrapped ``Abstract …`` line neither in ``title_lines`` nor in
    ``author_lines`` — only a real summary that heads its own paragraph can
    outrank it.  A byline whose second line starts with the label is likewise
    mid-paragraph, so this tiering keeps the later real summary.

    ``title_lines`` are skipped (except when they head their own paragraph),
    so a wrapped title such as ``Code Models for`` / ``Abstract Syntax Trees``
    is not mined for a summary; a title that is exactly the word ``Abstract``
    still lets the real summary paragraph through.
    """

    author_keys = {_clean(line) for line in (author_lines or []) if _clean(line)}
    title_keys = {_clean(line) for line in (title_lines or []) if _clean(line)}
    head_candidate: Optional[tuple[str, str]] = None
    mid_candidate: Optional[tuple[str, str]] = None
    inline_candidate: Optional[tuple[str, str]] = None
    for para_index, para in enumerate(paragraphs):
        following_paragraphs = tuple(paragraphs[para_index + 1: para_index + 2])
        for index, line in enumerate(para):
            if index > 0 and _clean(line) in title_keys:
                continue
            match = _ABSTRACT_RE.match(line)
            if match is None:
                inline = _ABSTRACT_INLINE_RE.search(line)
                lead = _clean(line[: inline.start()]) if inline else ""
                if inline is None or lead not in author_keys:
                    continue
                if inline_candidate is None:
                    inline_candidate = _abstract_block(
                        para, index, line, inline, following_paragraphs, author_keys)
                continue
            block = _abstract_block(
                para, index, line, match, following_paragraphs, author_keys)
            if not block[0]:
                continue
            if index == 0:
                if head_candidate is None:
                    head_candidate = block
            elif mid_candidate is None:
                mid_candidate = block
    for candidate in (head_candidate, mid_candidate, inline_candidate):
        if candidate is not None and candidate[0]:
            return candidate
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


def _doi_line_is_metadata(line: str) -> bool:
    """True only for a front-page line that presents the paper's own DOI.

    A ``doi:`` label is not enough — reference lists use it too, and a bare DOI
    inside body prose is a citation.  Rule:

    - citation/reference lines never qualify;
    - an explicit ``doi:`` / ``doi.org`` label qualifies when the line also
      carries a metadata marker (©/copyright/ISSN/…), or when nothing but the
      label+DOI is on it;
    - a bare DOI qualifies only when the whole line is essentially just the
      DOI/URL (no prose).
    """

    if _CITATION_HINT_RE.search(line):
        return False
    labeled = _DOI_LABEL_RE.search(line) is not None
    has_marker = _DOI_METADATA_MARKER_RE.search(line) is not None
    residual = _DOI_LABEL_RE.sub(" ", line)
    residual = _DOI_RE.sub(" ", residual)
    residual = re.sub(r"https?://\S+|www\.\S+", " ", residual)
    prose = len(re.findall(r"[A-Za-z]{2,}", residual))
    if labeled:
        return has_marker or prose == 0
    return prose == 0


_DOI_CONTINUATION_HEAD_RE = re.compile(r"^[0-9A-Za-z._/();:<>-]")


def _doi_match_at_line_end(line: str):
    match = _DOI_RE.search(line)
    if match is None or line[match.end():].strip():
        return None
    return match


def _joins_as_wrapped_doi(line: str, next_line: str) -> bool:
    """Whether ``next_line`` looks like the continuation of a wrapped DOI.

    Conservative on purpose: only a break right after a DOI separator or a
    next line that *starts* with a separator is treated as a wrap.  A line
    that ended on an alphanumeric and is followed by another alphanumeric
    token is ambiguous, so it is **not** joined (a complete short DOI such as
    ``10.1000/182`` followed by a year must not become ``10.1000/1822023``).
    """

    if not next_line or not _DOI_CONTINUATION_HEAD_RE.match(next_line):
        return False
    stripped = line.rstrip()
    if stripped and stripped[-1] in "/.-_:":
        return True
    return next_line[0] in ".-_/"


def _iter_front_doi_lines(text: str):
    """Front-page lines with a wrapped DOI re-joined before matching."""

    raw = [line.strip() for line in str(text or "").splitlines()]
    index = 0
    while index < len(raw):
        line = raw[index]
        while index + 1 < len(raw):
            match = _doi_match_at_line_end(line)
            if match is None or not _joins_as_wrapped_doi(line, raw[index + 1]):
                break
            candidate = line + raw[index + 1]
            longer = _DOI_RE.search(candidate)
            if longer is None or longer.end() <= match.end():
                break
            line = candidate
            index += 1
        yield line
        index += 1


def _extract_doi(front_text: str) -> tuple[str, str]:
    """DOI from the paper's own front-matter region — never a bibliography hit.

    A DOI is evidence only when it appears on a front-page line that reads as
    metadata (see :func:`_doi_line_is_metadata`).  A DOI wrapped across a line
    break is re-joined first, so a truncated fragment is not persisted; there
    is no registry check and no minimum-length heuristic (short/alpha-only
    DOIs such as ``10.1000/182`` are legitimate).  No reliable evidence ⇒
    empty.
    """

    for line in _iter_front_doi_lines(front_text):
        if not line:
            continue
        labeled = _DOI_LABEL_RE.search(line)
        bare = _DOI_RE.search(line)
        if labeled is None and bare is None:
            continue
        if not _doi_line_is_metadata(line):
            continue
        raw = labeled.group(1) if labeled is not None else bare.group(0)
        return normalize_doi(raw), line[:200]
    return "", ""


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
    if title and not _title_is_plausible(title):
        # A leaked front-page block is not a title: drop it (never persist it)
        # and let the caller degrade to the filename with an honest note.
        notes.append("title-untrusted")
        title = ""
        title_block = []
    authors = _parse_authors(author_lines)
    abstract, abstract_evidence = _extract_abstract(paragraphs, author_lines, title_block)
    keywords, keywords_evidence = _extract_keywords(paragraphs)
    doi, doi_evidence = _extract_doi(text)
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
    if not doi:
        notes.append("doi-not-found")
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
