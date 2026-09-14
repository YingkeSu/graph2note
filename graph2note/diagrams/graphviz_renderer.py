"""Deterministic graphviz/dot renderer (issue 05 preferred engine).

Preferred because dot's auto-layout gives zero node overlap / zero crossings
even on cyclic flowcharts (see Spike 3 report).  Requires *both* the python
``graphviz`` package and the system ``dot`` binary; availability is checked by
``available()`` so callers can fall back cleanly.  Importing this module never
raises when graphviz is missing.

D-track (SPEC §1) additions
---------------------------
* ``groups`` (SPEC JSON shape or IR objects) become ``cluster_*`` subgraphs.
  ``kind=layer`` additionally pins its members to ``rank=same`` so a layer band
  stays a single horizontal row; ``lane``/``cluster`` keep the visual grouping.
* ``node.note`` renders as a smaller second line *inside* the node box via an
  HTML-like label (plain dot labels cannot mix font sizes).
* ``edge.style == "dashed"`` draws a dashed edge (weak/annotation link).

Backward compatibility: with no groups, no notes and no dashed edges the DOT
source (and therefore the PNG) is byte-identical to the pre-D-track renderer.
"""

from __future__ import annotations

import os
import shutil

from . import render_semantics as rs

try:
    import graphviz
    _GV_PKG = True
except Exception:  # pragma: no cover - env without python graphviz
    graphviz = None
    _GV_PKG = False

# CJK font name dot should resolve via fontconfig (Spike 3 verified on macOS).
FONTNAME = "Arial Unicode MS"

# Font sizes (SPEC §1 "渲染" rule: group label >= node note, note smaller than
# the primary node label).  Kept as module constants so tests can assert the
# ordering without parsing the DOT source.
NODE_FONTSIZE = 20
EDGE_FONTSIZE = 14
NOTE_FONTSIZE = 14
GROUP_FONTSIZE = 20

NOTE_COLOR = "#555b6b"

# Readability strategy (T-audit phase-1: text was ~3px tall after the reading
# pane scaled a very wide drawing to fit).  dot's `size`/`dpi` only rescale the
# whole drawing, so the one real lever is *content width per text unit*: a
# hierarchy diagram wraps long labels at this many display units (CJK = 2) so a
# rank stays narrow and the post-fit text is bigger.  Applied only when the
# block carries groups/notes (the D-track hierarchy path), so ungrouped output
# stays byte-identical to the legacy renderer.
LABEL_WRAP_UNITS = 12


def available() -> bool:
    """True if python graphviz package AND the dot binary are both present."""
    return _GV_PKG and shutil.which("dot") is not None


# ---------------------------------------------------------------------------
# DOT construction (pure; separated from rendering so tests can inspect source)
# ---------------------------------------------------------------------------


def _xml(text: str) -> str:
    """Escape text for a dot HTML-like label (XML rules, plus <BR/> for \\n)."""
    escaped = (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<BR/>")


def wrap_label(label: str, max_units: int = LABEL_WRAP_UNITS) -> str:
    """Wrap a mixed CJK/Latin label into ``\\n``-separated display lines."""
    return rs.wrap_display_label(label, max_units)


def html_label(label: str, note: str) -> str:
    """HTML-like label: primary label + a smaller ``note`` line."""
    return (
        "<" + _xml(label or "")
        + f'<BR ALIGN="LEFT"/><FONT POINT-SIZE="{NOTE_FONTSIZE}"'
        + f' COLOR="{NOTE_COLOR}">{_xml(note)}</FONT>>'
    )


def node_attrs(node: rs.RenderNode, *, wrap: bool = False) -> dict:
    """Attribute dict for one node (key order matches the legacy call)."""
    label = wrap_label(node.label) if wrap else (node.label or "")
    note = wrap_label(node.note) if (wrap and node.note) else node.note
    attrs = {
        "label": html_label(label, note) if node.note else label,
        "shape": "box",
        "fontname": FONTNAME,
        "fontsize": str(NODE_FONTSIZE),
        "style": "rounded",
    }
    return attrs


def build_digraph(
    nodes,
    edges,
    *,
    groups=None,
    orientation: str = "TB",
):
    """Build the deterministic ``graphviz.Digraph`` for the given semantics."""
    sem = rs.normalize(nodes, edges, groups)
    g = graphviz.Digraph(format="png", engine="dot")
    rankdir = {"LR": "LR", "TB": "TB", "RL": "RL", "BT": "BT"}.get(
        orientation, "TB"
    )
    g.attr(rankdir=rankdir, dpi="120", nodesep="0.4", ranksep="0.5")
    g.attr(label="", labelloc="t")

    by_id = {n.id: n for n in sem.nodes}
    membership = sem.membership
    # Hierarchy blocks (groups or notes) wrap labels for reading-pane legibility;
    # a plain flat block keeps the legacy, unwrapped output byte-for-byte.
    wrap = bool(sem.groups) or sem.has_notes

    # Clusters first: a node owned by a group must be declared inside that
    # cluster's subgraph so dot draws the enclosing box around it.
    for index, group in enumerate(sem.groups):
        members = [nid for nid in group.nodes if membership.get(nid) == group.id]
        if not members:
            continue
        fill, line = rs.group_colors(index)
        with g.subgraph(name=f"cluster_{group.id}") as cluster:
            cluster.attr(
                label=group.label,
                fontname=FONTNAME,
                fontsize=str(GROUP_FONTSIZE),
                fontcolor=line,
                color=line,
                style="rounded,filled",
                fillcolor=fill,
                penwidth="1.4",
            )
            if group.kind == "layer":
                # A layer is a horizontal band: pin every member to one rank.
                cluster.attr(rank="same")
            for node_id in members:
                cluster.node(node_id, **node_attrs(by_id[node_id], wrap=wrap))

    for node in sem.nodes:
        if node.id in membership:
            continue
        g.node(node.id, **node_attrs(node, wrap=wrap))

    for edge in sem.edges:
        attrs = {
            "label": edge.label or "",
            "fontname": FONTNAME,
            "fontsize": str(EDGE_FONTSIZE),
        }
        if edge.dashed:
            attrs["style"] = "dashed"
        g.edge(edge.from_, edge.to, **attrs)

    return g


def render(nodes, edges, out_path: str, *, groups=None, orientation: str = "TB") -> str:
    """Render canonical node ids/edge pairs to a deterministic PNG."""
    if not available():
        raise RuntimeError("graphviz/dot is not available")

    g = build_digraph(nodes, edges, groups=groups, orientation=orientation)

    directory = os.path.dirname(os.path.abspath(out_path))
    stem = os.path.splitext(os.path.basename(out_path))[0]
    g.render(filename=stem, directory=directory, format="png",
             cleanup=True, view=False)
    png = os.path.join(directory, stem + ".png")
    return png


__all__ = [
    "FONTNAME",
    "NODE_FONTSIZE",
    "EDGE_FONTSIZE",
    "NOTE_FONTSIZE",
    "GROUP_FONTSIZE",
    "LABEL_WRAP_UNITS",
    "available",
    "wrap_label",
    "html_label",
    "node_attrs",
    "build_digraph",
    "render",
]
