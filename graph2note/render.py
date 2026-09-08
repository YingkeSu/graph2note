"""Deterministic Markdown renderer (FR-006/007/008).

A pure, deterministic function: the same DocumentIR always produces the same
Markdown string, byte for byte.  It never touches the network and never uses
an LLM.  Block rendering rules:

* heading  -> ATX heading (``#``..``######``)
* paragraph -> plain text, original reading order
* list     -> Markdown list (ordered / unordered), nested items supported
* formula  -> inline ``$…$`` or display ``$$…$$``
* table    -> Markdown pipe table
* code     -> fenced code block
* quote    -> block quote
* image    -> ``![alt](src)``
* diagram/flow -> image reference via the attachment interface
                 (drawing delegated to issue 05)

Body special characters (``* # _ ` [ ] < > \\``) are escaped to prevent
structure injection.  Chinese full-width characters and punctuation pass
through unchanged.
"""

from __future__ import annotations

import re

from .attachments import AttachmentWriter, DiagramSemantics, PlaceholderAttachmentWriter
from .ir import DocumentIR, Block, ListItem, TableBlock


# --- escaping --------------------------------------------------------------

# Characters that can inject Markdown structure; backslash-escaped.
_ESCAPE_RE = re.compile(r"([\\`*_{}\[\]<>#])")


def escape_text(text: str) -> str:
    """Escape Markdown-significant characters in body text.

    Only ASCII punctuation is escaped; Chinese full-width characters and
    punctuation are left untouched (no half-width rewriting).
    """
    return _ESCAPE_RE.sub(r"\\\1", text)


# --- block renderers -------------------------------------------------------


def _render_heading(block: Block) -> str:
    level = block.level
    return f"{'#' * level} {escape_text(block.text)}"


def _render_paragraph(block: Block) -> str:
    return escape_text(block.text)


def _render_list_items(items: list[ListItem], ordered: bool, depth: int) -> list[str]:
    lines: list[str] = []
    for item in items:
        marker = "1." if ordered else "-"
        indent = "  " * depth
        if item.items:
            # Blank line keeps a nested list attached to its parent item.
            lines.append(f"{indent}{marker} {escape_text(item.text)}")
            lines.append("")
            lines.extend(_render_list_items(item.items, ordered, depth + 1))
        else:
            lines.append(f"{indent}{marker} {escape_text(item.text)}")
    return lines


def _render_list(block: Block) -> str:
    return "\n".join(_render_list_items(block.items, block.ordered, 0))


def _render_formula(block: Block) -> str:
    latex = block.latex
    if block.inline:
        return f"${latex}$"
    # Display formula on its own lines for clarity and determinism.
    return f"$$\n{latex}\n$$"


# Pipe and the markdown specials, but NOT the backslash we introduce for the
# pipe, otherwise "|" would be double-escaped into "\\|".
_CELL_ESCAPE_RE = re.compile(r"([`*_{}\[\]<>#])")


def _escape_cell(cell: str) -> str:
    cell = cell.replace("|", "\\|").replace("\n", " ")
    return _CELL_ESCAPE_RE.sub(r"\\\1", cell)


def _render_table(block: TableBlock) -> str:
    headers = [_escape_cell(h) for h in block.headers]
    separator = ["---"] * max(len(headers), 1)
    rows = [
        "| " + " | ".join([_escape_cell(c) for c in row]) + " |"
        for row in block.rows
    ]
    out = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    out.extend(rows)
    if block.caption:
        out.append("")
        out.append(f"*{escape_text(block.caption)}*")
    return "\n".join(out)


def _render_code(block: Block) -> str:
    content = block.content
    # Pick a fence longer than any backtick run in the content so code
    # containing ``` is still deterministic and safe.
    runs = [len(m.group(0)) for m in re.finditer(r"`+", content)]
    fence_len = max((max(runs) if runs else 0) + 1, 3)
    fence = "`" * fence_len
    lang = block.language or ""
    return f"{fence}{lang}\n{content}\n{fence}"


def _render_quote(block: Block) -> str:
    text = escape_text(block.text)
    return "\n".join(f"> {line}" for line in text.split("\n"))


def _render_image(block: Block) -> str:
    alt = escape_text(block.alt)
    return f"![{alt}]({block.src})"


def _render_diagram(block: Block, index: int, writer: AttachmentWriter, doc_id: str) -> str:
    semantics = DiagramSemantics(
        kind=block.type,
        nodes=block.nodes,
        edges=block.edges,
        caption=block.caption,
        orientation=getattr(block, "orientation", None),
        source=getattr(block, "source", None),
    )
    path = writer.write_diagram(doc_id, index, semantics)
    caption = escape_text(block.caption)
    return f"![{caption}]({path})"


# --- top-level -------------------------------------------------------------


def render_markdown(
    doc: DocumentIR,
    *,
    doc_id: str = "doc",
    attachment_writer: AttachmentWriter | None = None,
) -> str:
    """Render a validated DocumentIR to Markdown.

    The result is deterministic: identical input gives identical bytes.
    Raises ``IRValidationError`` is NOT raised here — callers must validate
    first (``loads_ir``); this function assumes a valid IR.
    """
    writer = attachment_writer or PlaceholderAttachmentWriter()

    parts: list[str] = []
    for index, block in enumerate(doc.blocks):
        t = block.type
        if t == "heading":
            rendered = _render_heading(block)
        elif t == "paragraph":
            rendered = _render_paragraph(block)
        elif t == "list":
            rendered = _render_list(block)
        elif t == "formula":
            rendered = _render_formula(block)
        elif t == "table":
            rendered = _render_table(block)
        elif t == "code":
            rendered = _render_code(block)
        elif t == "quote":
            rendered = _render_quote(block)
        elif t == "image":
            rendered = _render_image(block)
        elif t in ("diagram", "flow"):
            rendered = _render_diagram(block, index, writer, doc_id)
        else:  # pragma: no cover - schema forbids unknown types
            raise ValueError(f"unknown block type: {t!r}")
        parts.append(rendered)

    if not parts:
        return ""

    return "\n\n".join(parts) + "\n"


__all__ = ["render_markdown", "escape_text"]
