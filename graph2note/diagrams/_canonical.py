"""Canonical node/edge ordering shared by the render engines.

FR-020 requires the same semantics to render byte-identical output.  The VLM
may return nodes/edges in any order; we canonicalize before laying out so the
result depends only on the graph's *content*, never its order.
"""

from __future__ import annotations

from ..ir import Node, Edge


def canonical_nodes(nodes: list[Node]) -> list[Node]:
    """Nodes sorted by id (stable, unique-agnostic)."""
    return sorted(nodes, key=lambda n: n.id)


def canonical_edges(edges: list[Edge], node_ids: set[str]) -> list[Edge]:
    """Edges sorted by (src, tgt, label), restricted to known node ids."""
    keep = [e for e in edges if e.from_ in node_ids and e.to in node_ids]
    return sorted(keep, key=lambda e: (e.from_, e.to, e.label))
