"""Read graphviz/dot layout geometry via `dot -Tplain` (Spike 3).

dot -Tplain emits node centers + box sizes and edge spline points in points.
We use node center-point straight edges for the crossing metric, matching how
the matplotlib comparison is measured.
"""
from __future__ import annotations

import graphviz

from ir_model import Diagram


def geometry(diag: Diagram) -> dict:
    d = diag.canonical()
    g = graphviz.Digraph(format="plain", engine="dot")
    g.attr(rankdir="TB", dpi="120", nodesep="0.4", ranksep="0.5")
    for n in d.nodes:
        g.node(n.id, label=n.label or "", shape="box", width="1.0", height="0.8",
               fontname="Arial Unicode MS", fontsize="20")
    for e in d.edges:
        g.edge(e.src, e.tgt, label=e.label or "")
    plain = g.pipe(format="plain").decode("utf-8")
    pos = {}          # id -> (x, y)  center (y up, mirror to y-down for fairness)
    pos_size = {}     # id -> (x, y, width, height)
    max_y = 0.0
    node_lines = {}
    for line in plain.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "node":
            nid, x, y, w, h = parts[1], float(parts[2]), float(parts[3]), \
                float(parts[4]), float(parts[5])
            node_lines[nid] = (x, y, w, h)
            max_y = max(max_y, y)
    # mirror y so our top-down crossing metric is orientation-consistent
    for nid, (x, y, w, h) in node_lines.items():
        my = max_y - y
        pos[nid] = (x, my)
        pos_size[nid] = (x, my, w, h)
    return {"pos": pos, "pos_size": pos_size}