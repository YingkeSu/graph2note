"""Engine selection + deterministic render for diagram semantics (issue 05).

Policy (from Spike 3 conclusion): prefer graphviz/dot when it is available,
else fall back to the pure-Python matplotlib layered renderer.  Both satisfy
FR-020 (same semantics -> byte-identical PNG).  Inputs are canonicalized before
layout so output depends only on graph content, not input order.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..ir import Node, Edge
from . import _canonical
from . import graphviz_renderer, matplotlib_renderer
from .degrade import crop_image, blank_png


@dataclass
class RenderOutcome:
    engine: str            # "graphviz" | "matplotlib" | "degrade" | "empty"
    path: str
    degraded: bool = False
    notes: list[str] = field(default_factory=list)


def graphviz_available() -> bool:
    return graphviz_renderer.available()


def engines_available() -> list[str]:
    out = []
    if graphviz_renderer.available():
        out.append("graphviz")
    if matplotlib_renderer.available():
        out.append("matplotlib")
    return out


def render_structured(
    nodes: list[Node],
    edges: list[Edge],
    out_path: str,
    *,
    prefer: str = "graphviz",
    orientation: str = "TB",
) -> RenderOutcome:
    """Render structured nodes/edges to a deterministic PNG at out_path."""
    nc = _canonical.canonical_nodes(nodes)
    ids = {n.id for n in nc}
    ec = _canonical.canonical_edges(edges, ids)
    labels = {n.id: n.label for n in nc}

    if prefer == "graphviz" and graphviz_renderer.available():
        path = graphviz_renderer.render(nc, ec, out_path, orientation=orientation)
        return RenderOutcome(engine="graphviz", path=path)
    if matplotlib_renderer.available():
        path = matplotlib_renderer.render(nc, ec, labels, out_path,
                                         orientation=orientation)
        return RenderOutcome(engine="matplotlib", path=path)

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
) -> RenderOutcome:
    """Full policy: structured render, else crop original, else empty marker."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if nodes or edges:
        return render_structured(nodes, edges, out_path, prefer=prefer,
                                 orientation=orientation)
    if source:
        path = crop_image(source, out_path, max_width=max_embed_width)
        return RenderOutcome(engine="degrade", path=path, degraded=True,
                             notes=[f"crop of {source!r}"])
    # neither structure nor a source image: deterministic empty marker
    blank_png(out_path)
    return RenderOutcome(engine="empty", path=out_path, degraded=True,
                         notes=["no nodes/edges and no source image"])
