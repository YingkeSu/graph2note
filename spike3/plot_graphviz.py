"""Deterministic graphviz (dot) flowchart renderer (Spike 3).

Renders the same Diagram semantics via the `dot` layout engine.  Deterministic:
identical input graph + same dot version + same attributes -> byte-identical
PNG (FR-020).  Reports whether the CJK labels rendered (no tophat boxes) - this
is a key comparison axis vs matplotlib.
"""
from __future__ import annotations

import os

import graphviz

from ir_model import Diagram

# CJK font name graphviz/dot should resolve via fontconfig.
FONTNAME = "Arial Unicode MS"


def render(diag: Diagram, out_path: str) -> str:
    """Render diagram to PNG at out_path; returns path (deterministic)."""
    d = diag.canonical()
    g = graphviz.Digraph(format="png", engine="dot",
                         graph_attr={}, node_attr={})
    g.attr(rankdir="TB", dpi="120", nodesep="0.4", ranksep="0.5")
    g.attr(label="", labelloc="t")
    for n in d.nodes:
        g.node(n.id, label=n.label or "", shape="box",
               fontname=FONTNAME, fontsize="20", style="rounded")
    for e in d.edges:
        g.edge(e.src, e.tgt, label=e.label or "",
               fontname=FONTNAME, fontsize="14")
    directory = os.path.dirname(os.path.abspath(out_path))
    stem = os.path.splitext(os.path.basename(out_path))[0]
    g.render(filename=stem, directory=directory, format="png",
             cleanup=True, view=False)
    # graphviz writes <directory>/<stem>.png
    png = os.path.join(directory, stem + ".png")
    return png