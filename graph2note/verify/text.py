"""Block-level text helpers used by the cross-validation diff (issue 10).

Pure functions over the IR block types — no network, no PIL.  The key here is a
*normalized* text key: whitespace (incl. newlines) is collapsed entirely and
case folded, so the same content written with slightly different spacing/format
still compares equal.  Chinese punctuation and full-width characters are kept
byte-for-byte (SPEC: no half-width rewriting), which matters because a model
that drops or rewrites a punctuation mark shows up as a genuine *diff*, not a
normalization artifact.
"""

from __future__ import annotations

import difflib
import re

from ..ir import (
    Block,
    CodeBlock,
    FlowBlock,
    DiagramBlock,
    FormulaBlock,
    HeadingBlock,
    ImageBlock,
    ListBlock,
    ParagraphBlock,
    QuoteBlock,
    TableBlock,
)

_WS = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Collapse all whitespace and case-fold, keeping CJK/full-width glyphs."""
    return _WS.sub("", text).strip().lower()


def block_text(block: Block) -> str:
    """The canonical comparison text of a block (presentation-free)."""
    t = block.type
    if t == "heading":
        return str(block.text)
    if t == "paragraph":
        return str(block.text)
    if t == "quote":
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
        return list_items_text(block)
    if t in ("diagram", "flow"):
        parts = [str(block.caption)] if block.caption else []
        parts.extend(n.label for n in block.nodes)
        parts.extend(f"{e.from_}->{e.to}{':' + e.label if e.label else ''}"
                     for e in block.edges)
        return " | ".join(parts)
    return str(block)


def list_items_text(block: ListBlock) -> str:
    def walk(item) -> list[str]:
        out = [str(item.text)] if (item.text or "").strip() else []
        for sub in item.items:
            out.extend(walk(sub))
        return out

    parts: list[str] = []
    for it in block.items:
        parts.extend(walk(it))
    return " | ".join(parts)


def normalized_key(block: Block) -> str:
    """Block type + normalized text, the identity we match on."""
    return f"{block.type}:{normalize(block_text(block))}"


def block_similarity(a: Block, b: Block) -> float:
    """[0..1] text similarity between two blocks.

    Different block types never match (a heading is never "the same" as a
    paragraph, even if text overlaps).  Same-type blocks use SequenceMatcher
    ratio on the normalized text.
    """
    if a.type != b.type:
        return 0.0
    na, nb = normalize(block_text(a)), normalize(block_text(b))
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


__all__ = ["normalize", "block_text", "list_items_text",
           "normalized_key", "block_similarity"]