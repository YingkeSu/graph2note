"""Deterministic graphviz/dot renderer (issue 05 preferred engine).

Preferred because dot's auto-layout gives zero node overlap / zero crossings
even on cyclic flowcharts (see Spike 3 report).  Requires *both* the python
``graphviz`` package and the system ``dot`` binary; availability is checked by
``available()`` so callers can fall back cleanly.  Importing this module never
raises when graphviz is missing.
"""

from __future__ import annotations

import os
import shutil

try:
    import graphviz
    _GV_PKG = True
except Exception:  # pragma: no cover - env without python graphviz
    graphviz = None
    _GV_PKG = False

# CJK font name dot should resolve via fontconfig (Spike 3 verified on macOS).
FONTNAME = "Arial Unicode MS"


def available() -> bool:
    """True if python graphviz package AND the dot binary are both present."""
    return _GV_PKG and shutil.which("dot") is not None


def render(nodes, edges, out_path: str, *, orientation: str = "TB") -> str:
    """Render canonical node ids/edge pairs to a deterministic PNG."""
    if not available():
        raise RuntimeError("graphviz/dot is not available")

    g = graphviz.Digraph(format="png", engine="dot")
    rankdir = {"LR": "LR", "TB": "TB", "RL": "RL", "BT": "BT"}.get(
        orientation, "TB"
    )
    g.attr(rankdir=rankdir, dpi="120", nodesep="0.4", ranksep="0.5")
    g.attr(label="", labelloc="t")
    for n in nodes:
        g.node(n.id, label=n.label or "", shape="box",
               fontname=FONTNAME, fontsize="20", style="rounded")
    for e in edges:
        g.edge(e.from_, e.to, label=e.label or "",
               fontname=FONTNAME, fontsize="14")

    directory = os.path.dirname(os.path.abspath(out_path))
    stem = os.path.splitext(os.path.basename(out_path))[0]
    g.render(filename=stem, directory=directory, format="png",
             cleanup=True, view=False)
    png = os.path.join(directory, stem + ".png")
    return png
