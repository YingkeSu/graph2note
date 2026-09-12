"""Deterministic document-similarity candidates (auto-organization issue 02).

Covers auto-organization PRD capability 2's *candidate* half: given the parsed
library, produce the most-similar document pairs **without any LLM**.  The
result feeds the library-level classifier prompt (``collection_organize``) and
is deliberately exposed as a standalone pure function so issue 03 (continuity
merge) can reuse it for content-level association.

Algorithm (no embeddings — an intentional repository-wide decision, see
``unifiedsearch.py``):

1. normalize the Markdown (drop code fences / inline code, unwrap links, keep
   image alt text, strip URLs);
2. tokenize into lowercase ASCII alphanumeric words plus single CJK/kana/hangul
   characters (so Chinese notes shingle without a word segmenter);
3. shingle consecutive tokens with an explicit width (``DEFAULT_SHINGLE_SIZE``);
4. score a pair by Jaccard similarity of its shingle sets.

Every knob is explicit: ``shingle_size``, ``threshold`` and ``max_chars`` are
parameters with documented defaults.  The real 43-document library is only 903
pairs, so the O(n^2) scan needs no index structure.

The functions here are pure: same input -> same output, no I/O, no globals.
"""

from __future__ import annotations

import re
from itertools import combinations
from typing import Any, Iterable

DEFAULT_SHINGLE_SIZE = 3
# Tuned against the real 43-note library: related notes (same course / same
# manuscript) score ~0.08-0.55 with 3-char shingles; unrelated notes < 0.05.
DEFAULT_SIMILARITY_THRESHOLD = 0.08
# Explicit truncation budget per document (title + body), in characters.
DEFAULT_MAX_CHARS = 8000

__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_SHINGLE_SIZE",
    "DEFAULT_SIMILARITY_THRESHOLD",
    "jaccard_similarity",
    "normalize_markdown",
    "pairwise_scores",
    "pairwise_similarity",
    "shingles",
    "tokenize_markdown",
]

# ASCII words/numbers, or a single CJK / kana / hangul codepoint.
_TOKEN_RE = re.compile(
    r"[0-9a-z]+|[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)
_FENCE_RE = re.compile(r"```.*?```", re.S)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_RE = re.compile(r"https?://\S+")


def normalize_markdown(text: Any) -> str:
    """Strip the Markdown scaffolding that only adds token noise.

    Kept semantics: fenced/inline code is dropped, links keep their label,
    images keep their alt text, bare URLs are dropped.  The caller decides the
    truncation budget separately so normalization stays pure and reusable.
    """

    raw = "" if text is None else str(text)
    raw = _FENCE_RE.sub(" ", raw)
    raw = _INLINE_CODE_RE.sub(" ", raw)
    raw = _IMAGE_RE.sub(r"\1", raw)
    raw = _LINK_RE.sub(r"\1", raw)
    raw = _URL_RE.sub(" ", raw)
    return raw


def tokenize_markdown(text: Any, *, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Lowercase token stream for ``text``, truncated to ``max_chars`` first."""

    if max_chars is not None and max_chars >= 0:
        text = ("" if text is None else str(text))[:max_chars]
    normalized = normalize_markdown(text)
    return _TOKEN_RE.findall(normalized.lower())


def shingles(tokens: Iterable[str], width: int = DEFAULT_SHINGLE_SIZE) -> set[str]:
    """Return the set of ``width``-token shingles (contiguous token n-grams).

    A document shorter than ``width`` yields a single shingle holding all of its
    tokens, so short notes can still match; an empty document yields no
    shingles.
    """

    tokens = list(tokens)
    if not tokens:
        return set()
    if width <= 1:
        return set(tokens)
    if len(tokens) <= width:
        return {" ".join(tokens)}
    return {" ".join(tokens[i:i + width]) for i in range(len(tokens) - width + 1)}


def jaccard_similarity(left: set[str], right: set[str]) -> float:
    """Jaccard index of two shingle sets (0.0 when both are empty)."""

    if not left and not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _field(doc: Any, name: str) -> str:
    if isinstance(doc, dict) or hasattr(doc, "get"):
        value = doc.get(name)  # type: ignore[union-attr]
    else:
        value = getattr(doc, name, None)
    return "" if value is None else str(value)


def _document_id(doc: Any) -> str:
    document_id = _field(doc, "document_id").strip()
    return document_id


def _document_text(doc: Any, *, max_chars: int) -> str:
    title = _field(doc, "title")
    body = _field(doc, "markdown") or _field(doc, "current_markdown")
    return f"{title}\n{body}"


def _shingle_map(
    docs: list[Any], *, shingle_size: int, max_chars: int
) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for doc in docs:
        document_id = _document_id(doc)
        if not document_id or document_id in out:
            # Duplicate/blank ids cannot form a meaningful pair; keep the first.
            continue
        tokens = tokenize_markdown(_document_text(doc, max_chars=max_chars),
                                   max_chars=max_chars)
        out[document_id] = shingles(tokens, shingle_size)
    return out


def pairwise_scores(
    docs: Iterable[Any],
    *,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[tuple[str, str, float]]:
    """Score every unordered document pair (all pairs, no threshold filter).

    Returns ``[(doc_a, doc_b, score)]`` sorted by score descending then by id,
    so the output is a deterministic snapshot.  Fewer than two usable documents
    yields ``[]`` (empty-library safe).
    """

    docs = list(docs)
    shingle_map = _shingle_map(docs, shingle_size=shingle_size, max_chars=max_chars)
    ids = sorted(shingle_map)
    pairs: list[tuple[str, str, float]] = []
    for left, right in combinations(ids, 2):
        score = jaccard_similarity(shingle_map[left], shingle_map[right])
        pairs.append((left, right, round(score, 6)))
    pairs.sort(key=lambda item: (-item[2], item[0], item[1]))
    return pairs


def pairwise_similarity(
    docs: Iterable[Any],
    *,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[tuple[str, str, float]]:
    """Candidate pairs whose Jaccard score is ``>= threshold``.

    Same deterministic ordering as :func:`pairwise_scores`; an empty library or
    a single document returns ``[]``.
    """

    return [
        pair for pair in pairwise_scores(
            docs, shingle_size=shingle_size, max_chars=max_chars
        )
        if pair[2] >= threshold
    ]
