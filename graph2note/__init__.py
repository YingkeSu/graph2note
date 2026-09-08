"""graph2note — Manuscript Compiler.

Track A (issue 02): Document IR schema + deterministic Markdown renderer.
"""

from .ir import (
    DocumentIR,
    Block,
    HeadingBlock,
    ParagraphBlock,
    ListBlock,
    ListItem,
    FormulaBlock,
    TableBlock,
    CodeBlock,
    QuoteBlock,
    ImageBlock,
    DiagramBlock,
    FlowBlock,
    Node,
    Edge,
    IRValidationError,
    loads_ir,
    dumps_ir,
)
from .render import render_markdown
from .attachments import (
    AttachmentWriter,
    PlaceholderAttachmentWriter,
    FileAssetWriter,
)

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
    "render_markdown",
    "AttachmentWriter",
    "PlaceholderAttachmentWriter",
    "FileAssetWriter",
]

__version__ = "0.1.0"
