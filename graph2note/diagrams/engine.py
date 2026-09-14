"""Engine selection + deterministic render for diagram semantics (issue 05).

Policy (from Spike 3 conclusion): prefer graphviz/dot when it is available,
else fall back to the pure-Python matplotlib layered renderer.  Both satisfy
FR-020 (same semantics -> byte-identical PNG).  Inputs are canonicalized before
layout so output depends only on graph content, not input order.

Since the SPW round, diagram/flow semantics may carry SPEC §1 visual groups
(``layer``/``lane``/``cluster``).  :func:`prepare_diagram_layout` canonicalizes
the groups and computes the group-aware geometry (rows/lanes/bounding boxes);
the renderers own the drawing.  Renderers may declare an optional ``layout``
keyword -- the engine forwards the prepared geometry only when they accept it,
so D2 and D3 can land independently (see the D2 handoff for the contract).
"""

from __future__ import annotations

import inspect
import os
from dataclasses import dataclass, field

from ..ir import Node, Edge
from . import _canonical, _layout
from . import graphviz_renderer, matplotlib_renderer
from .degrade import crop_image, blank_png


@dataclass
class RenderOutcome:
    engine: str            # "graphviz" | "matplotlib" | "degrade" | "empty"
    path: str
    degraded: bool = False
    notes: list[str] = field(default_factory=list)
    # Group-aware geometry (SPEC §1); None when the block carries no groups.
    layout: dict | None = None


def graphviz_available() -> bool:
    return graphviz_renderer.available()


def engines_available() -> list[str]:
    out = []
    if graphviz_renderer.available():
        out.append("graphviz")
    if matplotlib_renderer.available():
        out.append("matplotlib")
    return out


def prepare_diagram_layout(
    nodes: list[Node],
    edges: list[Edge],
    groups: list | None = None,
    *,
    width: float = 1.0,
    height: float = 1.0,
) -> dict:
    """Canonicalize diagram semantics and compute group-aware geometry.

    Returns the plain dict documented in ``diagrams._layout.grouped_layout``
    (positions, rows, columns, per-group bounding boxes).  With no groups the
    geometry is the existing layered layout, so callers can treat the return
    value as an optional enhancement and never a behaviour change.
    """
    nc = _canonical.canonical_nodes(nodes)
    ids = {n.id for n in nc}
    ec = _canonical.canonical_edges(edges, ids)
    return _layout.grouped_layout(
        [n.id for n in nc],
        [(e.from_, e.to) for e in ec],
        groups,
        width=width,
        height=height,
    )


def _renderer_layout_kwargs(renderer, layout: dict | None) -> dict:
    """Forward geometry only to renderers that opted in via a ``layout`` kwarg."""
    if layout is None:
        return {}
    try:
        params = inspect.signature(renderer).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins/C callables
        return {}
    return {"layout": layout} if "layout" in params else {}


def render_structured(
    nodes: list[Node],
    edges: list[Edge],
    out_path: str,
    *,
    prefer: str = "graphviz",
    orientation: str = "TB",
    groups: list | None = None,
) -> RenderOutcome:
    """Render structured nodes/edges to a deterministic PNG at out_path.

    ``groups`` (optional, SPEC §1 JSON shape) enables group-aware geometry; it
    is forwarded to the renderer only when the renderer accepts ``layout``.
    Omitting it keeps the pre-SPW behaviour byte-for-byte.
    """
    nc = _canonical.canonical_nodes(nodes)
    ids = {n.id for n in nc}
    ec = _canonical.canonical_edges(edges, ids)
    labels = {n.id: n.label for n in nc}
    layout = prepare_diagram_layout(nc, ec, groups) if groups else None

    if prefer == "graphviz" and graphviz_renderer.available():
        kwargs = _renderer_layout_kwargs(graphviz_renderer.render, layout)
        path = graphviz_renderer.render(nc, ec, out_path, orientation=orientation,
                                        **kwargs)
        return RenderOutcome(engine="graphviz", path=path, layout=layout)
    if matplotlib_renderer.available():
        kwargs = _renderer_layout_kwargs(matplotlib_renderer.render, layout)
        path = matplotlib_renderer.render(nc, ec, labels, out_path,
                                          orientation=orientation, **kwargs)
        return RenderOutcome(engine="matplotlib", path=path, layout=layout)

    raise RuntimeError(
        "no diagram engine available (graphviz/dot missing and matplotlib "
        "not installed)"
    )



def render_to_png(
    nodes: list[Node],
    edges: list[Edge],
    source: str | None,
    out_path: str,
    *,
    prefer: str = "graphviz",
    max_embed_width: int = 900,
    orientation: str = "TB",
    groups: list | None = None,
) -> RenderOutcome:
    """Full policy: structured render, else crop original, else empty marker."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if nodes or edges:
        return render_structured(nodes, edges, out_path, prefer=prefer,
                                 orientation=orientation, groups=groups)
    if source:
        path = crop_image(source, out_path, max_width=max_embed_width)
        return RenderOutcome(engine="degrade", path=path, degraded=True,
                             notes=[f"crop of {source!r}"])
    # neither structure nor a source image: deterministic empty marker
    blank_png(out_path)
    return RenderOutcome(engine="empty", path=out_path, degraded=True,
                         notes=["no nodes/edges and no source image"])
