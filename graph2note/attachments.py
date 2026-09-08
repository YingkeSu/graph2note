"""Attachment interface for diagram/flow rendering.

This slice (issue 02) only defines the seam: a diagram/flow block carries
structured semantics (nodes/edges) which the renderer passes to an
``AttachmentWriter``.  The writer answers with a *relative path* that the
renderer embeds as an image reference in the Markdown.

The actual drawing is implemented in issue 05.  Until then a
``PlaceholderAttachmentWriter`` produces deterministic stub paths and
optionally drops a placeholder file into an assets directory so the
end-to-end shape (``.md`` + assets) is testable without any real drawing.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from .ir import Node, Edge


class DiagramSemantics:
    """Structured semantics handed to the drawing layer (issue 05)."""

    __slots__ = ("kind", "nodes", "edges", "caption", "orientation")

    def __init__(
        self,
        kind: str,
        nodes: list[Node],
        edges: list[Edge],
        caption: str = "",
        orientation: str | None = None,
    ) -> None:
        self.kind = kind
        self.nodes = nodes
        self.edges = edges
        self.caption = caption
        self.orientation = orientation


class AttachmentWriter(ABC):
    """Resolve diagram/flow semantics to a relative asset path."""

    @abstractmethod
    def write_diagram(self, doc_id: str, index: int, semantics: DiagramSemantics) -> str:
        """Return a relative path (POSIX separators) embedded in Markdown."""


_SAFE_DOC_ID = re.compile(r"[^A-Za-z0-9._-]")


class PlaceholderAttachmentWriter(AttachmentWriter):
    """Deterministic stub: returns ``assets/<doc>-diagram-<n>.png``.

    Writing is not performed (drawing is issue 05).  The path is a pure
    function of ``(doc_id, index, kind)`` so two renders are byte-identical.
    """

    def _path(self, doc_id: str, index: int, kind: str) -> str:
        safe = _SAFE_DOC_ID.sub("-", doc_id) or "doc"
        return f"assets/{safe}-{kind}-{index}.png"

    def write_diagram(self, doc_id: str, index: int, semantics: DiagramSemantics) -> str:
        return self._path(doc_id, index, semantics.kind)


class FileAssetWriter(PlaceholderAttachmentWriter):
    """Placeholder that additionally drops a stub file into ``assets_dir``.

    The stub has no meaningful image content yet — real drawing lands in
    issue 05 — but its presence lets downstream work (issue 05/06) validate
    the ``.md`` + assets packaging and attachment-completeness checks.
    """

    PLACEHOLDER_PNG = (
        b"\x89PNG\r\n\x1a\n"  # PNG signature (stub only, not a real image)
        b"graph2note-placeholder"
    )

    def __init__(self, assets_dir: str | Path, doc_id: str = "doc") -> None:
        self.assets_dir = Path(assets_dir)
        self.doc_id = doc_id

    def write_diagram(self, doc_id: str, index: int, semantics: DiagramSemantics) -> str:
        rel = self._path(doc_id, index, semantics.kind)
        target = self.assets_dir / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.PLACEHOLDER_PNG)
        return rel


__all__ = [
    "DiagramSemantics",
    "AttachmentWriter",
    "PlaceholderAttachmentWriter",
    "FileAssetWriter",
]
