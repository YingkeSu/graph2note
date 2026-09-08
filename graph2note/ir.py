"""Document IR — the central, machine-verifiable data contract.

The IR is a typed, ordered sequence of blocks plus a ``document_type``.
It is the single legal output of the parsing layer and the single legal
input of the renderer.  Anything that fails validation here is rejected
before it can be rendered (FR-005).
"""

from __future__ import annotations

import json
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------


class HeadingBlock(BaseModel):
    type: Literal["heading"]
    level: int = Field(ge=1, le=6)
    text: str


class ParagraphBlock(BaseModel):
    type: Literal["paragraph"]
    text: str


class ListItem(BaseModel):
    """A single list item; may nest further items for sub-lists."""

    text: str = ""
    items: list["ListItem"] = Field(default_factory=list)


class ListBlock(BaseModel):
    type: Literal["list"]
    ordered: bool = False
    items: list[ListItem] = Field(default_factory=list)


class FormulaBlock(BaseModel):
    type: Literal["formula"]
    latex: str
    inline: bool = False


class CodeBlock(BaseModel):
    type: Literal["code"]
    language: Optional[str] = None
    content: str


class TableBlock(BaseModel):
    type: Literal["table"]
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    caption: str = ""


class QuoteBlock(BaseModel):
    type: Literal["quote"]
    text: str


class ImageBlock(BaseModel):
    type: Literal["image"]
    src: str
    alt: str = ""


class Node(BaseModel):
    id: str
    label: str = ""


class Edge(BaseModel):
    """A directed connection between two nodes.

    The JSON field is ``from`` (mapped from the python field ``from_``).
    """

    model_config = ConfigDict(populate_by_name=True)

    from_: str = Field(alias="from")
    to: str
    label: str = ""


class _DiagramMixin(BaseModel):
    """Structured nodes/edges semantics shared by diagram and flow.

    ``source`` is an optional, backward-compatible reference to the original
    manuscript image, used only on the degrade path (when nodes/edges are
    missing the renderer crops and embeds the source instead).
    """

    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    caption: str = ""
    source: Optional[str] = None


class DiagramBlock(_DiagramMixin):
    type: Literal["diagram"]


class FlowBlock(_DiagramMixin):
    type: Literal["flow"]
    orientation: Literal["LR", "TB", "RL", "BT"] = "LR"


Block = Union[
    HeadingBlock,
    ParagraphBlock,
    ListBlock,
    FormulaBlock,
    TableBlock,
    CodeBlock,
    QuoteBlock,
    ImageBlock,
    DiagramBlock,
    FlowBlock,
]

_LIST_ITEM_ADAPTER = TypeAdapter(ListItem)


class DocumentIR(BaseModel):
    """Top-level document contract."""

    model_config = ConfigDict(extra="forbid")

    document_type: str = "note"
    # Forward-compatible version marker; P1 renderers may key off it.
    version: int = 1
    blocks: list[Block] = Field(default_factory=list)


# Resolve the forward reference on ListItem.
DocumentIR.model_rebuild()
ListItem.model_rebuild()

# A TypeAdapter with our strict "forbid extra keys" behaviour.
_DOC_ADAPTER = TypeAdapter(DocumentIR)


# ---------------------------------------------------------------------------
# Errors & helpers
# ---------------------------------------------------------------------------


class IRValidationError(ValueError):
    """Raised (with a human-readable message) when IR is invalid."""


def loads_ir(raw: str | bytes) -> DocumentIR:
    """Parse and validate a JSON string into a DocumentIR.

    Rejects invalid JSON, unknown block types, missing fields, wrong types
    and unexpected extra keys with a readable ``IRValidationError``.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IRValidationError(
            f"invalid JSON: {exc.msg} at line {exc.lineno} col {exc.colno}"
        ) from exc

    if not isinstance(data, dict):
        raise IRValidationError(
            f"IR root must be a JSON object, got {type(data).__name__}"
        )

    try:
        return _DOC_ADAPTER.validate_python(data)
    except Exception as exc:  # pydantic ValidationError
        raise IRValidationError(_format_validation_error(exc)) from exc


def _format_validation_error(exc: Exception) -> str:
    lines = []
    for err in getattr(exc, "errors", lambda: [])():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        lines.append(f"  at '{loc}': {err.get('msg')}")
    # Fallback if not a pydantic ValidationError shape.
    if not lines:
        lines.append(str(exc))
    return "document IR failed validation:\n" + "\n".join(lines)


def dumps_ir(doc: DocumentIR) -> str:
    """Serialize a validated IR back to JSON (canonical field order)."""
    return doc.model_dump_json(indent=2)


__all__ = [
    "DocumentIR",
    "Block",
    "HeadingBlock",
    "ParagraphBlock",
    "ListBlock",
    "ListItem",
    "FormulaBlock",
    "TableBlock",
    "CodeBlock",
    "QuoteBlock",
    "ImageBlock",
    "DiagramBlock",
    "FlowBlock",
    "Node",
    "Edge",
    "IRValidationError",
    "loads_ir",
    "dumps_ir",
]
