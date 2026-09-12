"""Pure text/structure helpers for the IR block-level diff engine (issue S1).

Everything here is a deterministic, side-effect-free function over a single
:class:`~graph2note.ir.Block` — no network, no file IO, no model calls.

Two distinct notions are exposed and intentionally kept apart:

* :func:`content_key` — a *strict identity* of a block's content.  Two blocks
  with equal keys are the same block (only their position may differ), which is
  what the diff engine turns into ``unchanged`` / ``moved``.
* :func:`block_similarity` — a *graded* similarity in ``[0, 1]`` used to decide
  whether two non-identical blocks are the "same block, edited"
  (``modified``) or two unrelated blocks (``removed`` + ``added``).

Similarity is a normalized token-overlap rate (Sørensen–Dice over token
multisets).  Text blocks contribute their text tokens; formula / diagram /
flow / table blocks contribute their structural fields (latex, nodes, edges,
caption, orientation, headers, rows, …) as required by the issue so that a
structural edit is not hidden by a text-length difference.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

from ..ir import Block, ListBlock

_WS = re.compile(r"\s+")
_ASCII = re.compile(r"[a-z0-9_]+")
_CJK_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

# Kinds whose "content" is plain text read from `.text`.
_TEXT_TYPES = frozenset({"heading", "paragraph", "quote"})
_STRUCTURED_TYPES = frozenset({"diagram", "flow"})


# ---------------------------------------------------------------------------
# Normalization / tokenization
# ---------------------------------------------------------------------------


def normalize(text: str) -> str:
    """Case- and whitespace-normalized form used for equality and tokens.

    ``NFKC`` folds full-width/half-width variants so that a re-parse which only
    flips character width does not show up as a content change.
    """
    text = unicodedata.normalize("NFKC", text or "")
    return _WS.sub(" ", text).strip().lower()


def tokenize(text: str) -> list[str]:
    """Split normalized text into ASCII word tokens + CJK unigrams/bigrams.

    CJK bigrams give the overlap measure some sensitivity to word order while
    unigrams keep very short runs comparable.
    """
    norm = normalize(text)
    tokens = _ASCII.findall(norm)
    for run in _CJK_RUN.findall(norm):
        tokens.extend(run)
        tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def token_overlap(a: list[str], b: list[str]) -> float:
    """Sørensen–Dice overlap of two token multisets, in ``[0, 1]``.

    ``1.0`` when both are empty (two empty blocks are "the same" nothing),
    ``0.0`` when exactly one is empty.
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    ca, cb = Counter(a), Counter(b)
    inter = sum(min(ca[tok], cb[tok]) for tok in ca.keys() & cb.keys())
    return 2.0 * inter / (len(a) + len(b))


# ---------------------------------------------------------------------------
# Canonical block text / structure
# ---------------------------------------------------------------------------


def list_text(block: ListBlock) -> str:
    """Flatten a (possibly nested) list into one `` | ``-joined string."""

    def walk(item) -> list[str]:
        out = [item.text] if (item.text or "").strip() else []
        for sub in item.items:
            out.extend(walk(sub))
        return out

    parts: list[str] = []
    for item in block.items:
        parts.extend(walk(item))
    return " | ".join(parts)


def structure_text(block: Block) -> str:
    """Structural canonical text of a diagram/flow block.

    ``source`` is deliberately excluded: it is a provenance path pointing into
    a version-specific asset directory, not block semantics, so including it
    would report every re-parse as a modification.
    """
    parts: list[str] = []
    if block.type == "flow":
        parts.append(f"orientation:{block.orientation}")
    if block.caption:
        parts.append(f"caption:{block.caption}")
    for node in block.nodes:
        parts.append(f"node:{node.id}:{node.label}")
    for edge in block.edges:
        parts.append(f"edge:{edge.from_}->{edge.to}:{edge.label}")
    return " | ".join(parts)


def src_basename(src: str) -> str:
    base = (src or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base


def block_text(block: Block) -> str:
    """Presentation-free canonical text of a block (used for previews/keys)."""
    t = block.type
    if t in _TEXT_TYPES:
        return str(block.text)
    if t == "formula":
        return str(block.latex)
    if t == "code":
        return str(block.content)
    if t == "table":
        parts = list(block.headers)
        for row in block.rows:
            parts.extend(row)
        if block.caption:
            parts.append(block.caption)
        return " | ".join(parts)
    if t == "image":
        return str(block.alt or block.src)
    if t == "list":
        return list_text(block)
    if t in _STRUCTURED_TYPES:
        return structure_text(block)
    return str(block)


def _structural_flags(block: Block) -> str:
    """Non-text structural discriminators folded into :func:`content_key`."""
    t = block.type
    if t == "formula":
        return "inline" if block.inline else "display"
    if t == "list":
        return "ordered" if block.ordered else "unordered"
    if t == "code":
        return normalize(block.language or "")
    if t == "flow":
        return block.orientation
    return ""


def content_key(block: Block) -> str:
    """Strict identity key: block type + normalized content + structural flags."""
    base = f"{block.type}:{normalize(block_text(block))}"
    flags = _structural_flags(block)
    return f"{base}|{flags}" if flags else base


def block_tokens(block: Block) -> list[str]:
    """Tokens fed to the overlap measure, per block type.

    Formula / diagram / flow / table tokens come from their structural fields
    (latex, nodes, edges, caption, orientation, headers, rows, …) as the issue
    requires, so structural edits are visible to similarity.
    """
    t = block.type
    if t == "formula":
        return tokenize(block.latex) + ["inline" if block.inline else "display"]
    if t == "list":
        toks = tokenize(list_text(block))
        toks.append("ordered" if block.ordered else "unordered")
        return toks
    if t == "code":
        toks = tokenize(block.content)
        if block.language:
            toks.append(f"lang:{normalize(block.language)}")
        return toks
    if t == "table":
        parts = list(block.headers) + [c for row in block.rows for c in row]
        if block.caption:
            parts.append(block.caption)
        return tokenize(" ".join(parts))
    if t == "image":
        toks = tokenize(block.alt)
        toks.append(f"src:{normalize(src_basename(block.src))}")
        return toks
    if t in _STRUCTURED_TYPES:
        toks = tokenize(structure_text(block))
        if t == "flow":
            toks.append(f"orientation:{block.orientation}")
        return toks
    return tokenize(block_text(block))


def block_similarity(a: Block, b: Block) -> float:
    """Graded similarity in ``[0, 1]`` between two blocks.

    Different block types never match (a heading is never "the same" as a
    paragraph).  Identical content scores ``1.0`` exactly; otherwise the score
    is the token-overlap rate of the two blocks' features.
    """
    if a.type != b.type:
        return 0.0
    if content_key(a) == content_key(b):
        return 1.0
    return token_overlap(block_tokens(a), block_tokens(b))


def preview(block: Block, limit: int = 80) -> str:
    """One-line, length-bounded preview for CLI/UI consumption."""
    text = _WS.sub(" ", block_text(block)).strip()
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


__all__ = [
    "normalize",
    "tokenize",
    "token_overlap",
    "list_text",
    "structure_text",
    "src_basename",
    "block_text",
    "content_key",
    "block_tokens",
    "block_similarity",
    "preview",
]
