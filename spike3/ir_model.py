"""Canonical diagram IR for Spike 3.

We use a tiny, self-contained node/edge model tuned for flowchart semantic
extraction.  It mirrors the Diagram IR shape that issue 02/05 will own (nodes
with id+label, edges with from/to+label), so the spike conclusions translate
directly to the real schema.  Ordering of nodes/edges is canonical so two runs
over the same semantics yield the same diagram (FR-020).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
from typing import Optional


@dataclass
class Node:
    id: str
    label: str


@dataclass
class Edge:
    src: str
    tgt: str
    label: str = ""


@dataclass
class Diagram:
    """Structured semantic carried by a diagram/flow block."""
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": [asdict(n) for n in self.nodes],
            "edges": [asdict(e) for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Diagram":
        def _edge(e: dict) -> Edge:
            return Edge(
                src=str(e.get("src", e.get("from", ""))),
                tgt=str(e.get("tgt", e.get("to", ""))),
                label=str(e.get("label", "")),
            )
        return cls(
            nodes=[Node(id=str(n["id"]), label=str(n.get("label", "")))
                   for n in data.get("nodes", [])],
            edges=[_edge(e) for e in data.get("edges", [])],
        )

    def canonical(self) -> "Diagram":
        """Stable canonical ordering so equivalent diagrams serialize identically.

        Nodes sorted by id, edges sorted by (src, tgt, label).  Labels are part
        of the sort key for edges; a re-order of the same graph is unchanged.
        """
        nodes = sorted(self.nodes, key=lambda n: n.id)
        edges = sorted(self.edges, key=lambda e: (e.src, e.tgt, e.label))
        return Diagram(nodes, edges)


def dump_json(obj, path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def load_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)