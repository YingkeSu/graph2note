"""Attachment interface for diagram/flow rendering.

A ``diagram``/``flow`` block carries structured semantics (nodes/edges) which
the renderer passes to an ``AttachmentWriter``.  The writer answers with a
*relative path* that the renderer embeds as an image reference in the Markdown.

This is now implemented for real (issue 05):

* ``PlaceholderAttachmentWriter`` - pure-function deterministic stub paths.
* ``FileAssetWriter`` - renders real PNG assets (graphviz preferred,
  matplotlib fallback), or crops the original image when no structure exists,
  then drops the asset into ``assets/`` per the issue-02 path contract.

``missing_attachments`` performs an attachment-completeness check: every image
reference in the Markdown must have a corresponding file in the assets dir.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path

from .ir import Node, Edge


def semantics_field(obj, *names, default=None):
    """Read a SPEC §1 dict key or an IR/object attribute (first match wins).

    The single "dict-or-object" accessor for diagram semantics, shared by the
    export sidecar extraction (``render.py``) and the renderer adapter
    (``diagrams/render_semantics.py``); keeping it here avoids a third copy and
    keeps both call sites free of optional dependencies (no numpy import).
    """
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


class DiagramSemantics:
    """Structured semantics handed to the drawing layer.

    ``groups`` (SPEC §1) is an optional list of visual groups in the SPEC JSON
    shape *or* IR objects; the renderers normalize it.  Keeping the raw shape
    here means the export chain never loses grouping/note/style information on
    its way to the drawing layer.
    """

    __slots__ = ("kind", "nodes", "edges", "caption", "orientation", "source",
                 "groups")

    def __init__(
        self,
        kind: str,
        nodes: list[Node],
        edges: list[Edge],
        caption: str = "",
        orientation: str | None = None,
        source: str | None = None,
        groups: list | None = None,
    ) -> None:
        self.kind = kind
        self.nodes = nodes
        self.edges = edges
        self.caption = caption
        self.orientation = orientation
        # Optional reference to the original manuscript image used only when
        # structured semantics are missing (degrade-to-crop path).
        self.source = source
        # SPEC §1 visual groups (layer/lane/cluster); [] means "flat diagram".
        self.groups = list(groups or [])


class AttachmentWriter(ABC):
    """Resolve diagram/flow semantics to a relative asset path."""

    @abstractmethod
    def write_diagram(self, doc_id: str, index: int, semantics: DiagramSemantics) -> str:
        """Return a relative path (POSIX separators) embedded in Markdown."""


_SAFE_DOC_ID = re.compile(r"[^A-Za-z0-9._-]")


class PlaceholderAttachmentWriter(AttachmentWriter):
    """Deterministic stub: returns ``assets/<doc>-diagram-<n>.png``.

    No drawing is performed.  The path is a pure function of ``(doc_id, index,
    kind)`` so two renders are byte-identical.  Used when no writer is supplied.
    """

    def _path(self, doc_id: str, index: int, kind: str) -> str:
        safe = _SAFE_DOC_ID.sub("-", doc_id) or "doc"
        return f"assets/{safe}-{kind}-{index}.png"

    def write_diagram(self, doc_id: str, index: int, semantics: DiagramSemantics) -> str:
        return self._path(doc_id, index, semantics.kind)


class FileAssetWriter(AttachmentWriter):
    """Render real diagram assets into ``assets_dir`` and return their path.

    Selection (Spike 3 conclusion): if the block has structured nodes/edges,
    render deterministically with graphviz/dot when available, else fall back
    to the pure-Python matplotlib layered renderer.  If the block has *no*
    structure but references an original image (``source``), crop it (degrade
    path, no OCR -> no mojibake).  If neither, emit a deterministic blank
    placeholder so the attachment reference still resolves.

    Uses the issue-02 path contract ``assets/<doc>-<kind>-<index>.png``.
    """

    def __init__(
        self,
        assets_dir: str | Path,
        doc_id: str = "doc",
        prefer: str = "graphviz",
        max_embed_width: int = 900,
    ) -> None:
        self.assets_dir = Path(assets_dir)
        self.doc_id = doc_id
        self.prefer = prefer
        self.max_embed_width = max_embed_width
        # Audit trail: (rel_path, RenderOutcome) per write, deterministic order.
        self.results: list[tuple[str, dict]] = []

    def _path(self, doc_id: str, index: int, kind: str) -> str:
        safe = _SAFE_DOC_ID.sub("-", doc_id) or "doc"
        return f"assets/{safe}-{kind}-{index}.png"

    def write_diagram(self, doc_id: str, index: int, semantics: DiagramSemantics) -> str:
        from .diagrams import engine
        from .diagrams import render_semantics

        rel = self._path(doc_id, index, semantics.kind)
        target = self.assets_dir / rel
        # Normalized once here so the audit trail records exactly the visual
        # semantics that reached the drawing layer (nothing is silently lost).
        sem = render_semantics.normalize(
            semantics.nodes, semantics.edges, semantics.groups
        )
        kwargs = {
            "prefer": self.prefer,
            "max_embed_width": self.max_embed_width,
            "orientation": semantics.orientation or "TB",
            # D1 (IR groups) + D2 (engine.prepare_diagram_layout) are merged on
            # main, so the engine always accepts ``groups=`` now.
            "groups": list(semantics.groups) or None,
        }
        outcome = engine.render_to_png(
            list(semantics.nodes),
            list(semantics.edges),
            semantics.source,
            str(target),
            **kwargs,
        )
        self.results.append((rel, {
            "engine": outcome.engine,
            "degraded": outcome.degraded,
            "path": outcome.path,
            "notes": list(outcome.notes),
            "semantics": {
                "groups": [
                    {"id": g.id, "label": g.label, "kind": g.kind,
                     "nodes": list(g.nodes)}
                    for g in sem.groups
                ],
                "notes": {n.id: n.note for n in sem.nodes if n.note},
                "dashed_edges": [[e.from_, e.to] for e in sem.edges if e.dashed],
            },
        }))
        return rel


# --- attachment completeness ------------------------------------------------


_IMG_REF = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def missing_attachments(markdown: str, assets_dir: str | Path) -> list[str]:
    """Return asset-relative refs in ``markdown`` that have no file present.

    Only relative ``assets/...`` references are checked (absolute/remote URLs
    are ignored).  Used to satisfy the "every image reference has a file"
    acceptance criterion.
    """
    assets = Path(assets_dir)
    missing: list[str] = []
    for raw in _IMG_REF.findall(markdown):
        ref = raw.strip()
        if ref.startswith(("http://", "https://", "/", "data:")):
            continue
        # normalize: ref is relative to the assets dir already (assets/...)
        target = (assets / ref) if ref.startswith("assets/") else (assets / ref)
        if not target.is_file():
            missing.append(ref)
    return missing


__all__ = [
    "DiagramSemantics",
    "AttachmentWriter",
    "PlaceholderAttachmentWriter",
    "FileAssetWriter",
    "missing_attachments",
    "semantics_field",
]
