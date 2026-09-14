"""Normalized rendering semantics for the D-track hierarchy extension.

The render engines must accept the **SPEC §1 JSON shape** (plain ``dict``s)
without importing the D1 IR models (``graph2note/ir.py``) or D2's layout
output, because D1/D2 land in parallel branches.  This module is the single
adapter between "whatever the caller has" (SPEC-shaped dicts *or* pydantic IR
objects) and the small immutable records the renderers draw from.

Shape consumed here (all fields optional except ``id``)::

    node  = {"id": "n1", "label": "开始", "note": "坑：Tiger VNC 不支持"}
    edge  = {"from": "n1", "to": "n2", "label": "完成", "style": "dashed"}
    group = {"id": "g1", "label": "通信层", "kind": "layer",
             "nodes": ["n1", "n2"]}

Normalization is deterministic and defensive:

* nodes/edges/groups are sorted by a content key, so input order never leaks
  into layout or rendered bytes (FR-020);
* unknown group members are dropped (the IR layer rejects dangling refs; a
  renderer must not crash on stale/hand-built data);
* ``style`` values outside ``solid``/``dashed`` degrade to ``solid``;
* group member lists are de-duplicated and sorted by node id.

Ordering of groups follows the node order (a group's rank is the smallest
canonical index of its members) so hand-written reading order is preserved
when the extractor emits the layers top-to-bottom.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

GROUP_KINDS = ("layer", "lane", "cluster")
EDGE_STYLES = ("solid", "dashed")
_KIND_RANK = {"layer": 0, "lane": 1, "cluster": 2}

# Engine-agnostic, deterministic per-group palette.  The index is the group's
# position in the normalized order, so the same semantics always pick the same
# colours (FR-020).  Soft manuscript-friendly fills + a readable border.
GROUP_FILL = ("#eaf1fb", "#eaf6ec", "#fdf4e5", "#f3ecfa", "#e7f5f4", "#fbecec")
GROUP_LINE = ("#7aa2d4", "#7fb98a", "#d8a95b", "#a98fd0", "#63b0aa", "#d08c88")


def group_colors(index: int) -> tuple[str, str]:
    """(fill, border) for the ``index``-th normalized group, stable."""
    return GROUP_FILL[index % len(GROUP_FILL)], GROUP_LINE[index % len(GROUP_LINE)]


@dataclass(frozen=True)
class RenderNode:
    """A node as the renderers see it (SPEC §1 + ``note``)."""

    id: str
    label: str = ""
    note: str | None = None


@dataclass(frozen=True)
class RenderEdge:
    """A directed edge as the renderers see it (SPEC §1 + ``style``)."""

    from_: str
    to: str
    label: str = ""
    style: str = "solid"

    @property
    def dashed(self) -> bool:
        return self.style == "dashed"


@dataclass(frozen=True)
class RenderGroup:
    """A visual group (layer band / swim-lane / local cluster)."""

    id: str
    label: str = ""
    kind: str = "cluster"
    nodes: tuple[str, ...] = ()


@dataclass(frozen=True)
class RenderSemantics:
    """Everything a renderer needs, already normalized."""

    nodes: list[RenderNode] = field(default_factory=list)
    edges: list[RenderEdge] = field(default_factory=list)
    groups: list[RenderGroup] = field(default_factory=list)

    @property
    def membership(self) -> dict[str, str]:
        """node id -> owning group id (first group in normalized order wins)."""
        return group_membership(self.groups)

    @property
    def has_notes(self) -> bool:
        return any(n.note for n in self.nodes)

    @property
    def has_dashed(self) -> bool:
        return any(e.dashed for e in self.edges)


# ---------------------------------------------------------------------------
# field access: SPEC dict shape or IR object
# ---------------------------------------------------------------------------


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read ``obj`` as a mapping key or an attribute (first match wins)."""
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        for name in names:
            if name in obj:
                return obj[name]
        return default
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value
    return default


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))


def _opt_text(value: Any) -> str | None:
    if value is None:
        return None
    text = _text(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# normalization
# ---------------------------------------------------------------------------


def normalize_nodes(nodes: Any) -> list[RenderNode]:
    """SPEC-shaped nodes -> deterministic ``list[RenderNode]`` (sorted by id)."""
    out: list[RenderNode] = []
    for raw in nodes or []:
        node_id = _text(_get(raw, "id"))
        if not node_id:
            continue
        out.append(RenderNode(
            id=node_id,
            label=_text(_get(raw, "label", default="")),
            note=_opt_text(_get(raw, "note")),
        ))
    out.sort(key=lambda n: n.id)
    return out


def normalize_edges(edges: Any, node_ids: set[str] | None = None) -> list[RenderEdge]:
    """SPEC-shaped edges -> deterministic ``list[RenderEdge]``.

    ``node_ids`` (when given) restricts edges to known nodes - the same
    restriction ``_canonical.canonical_edges`` applies before layout.
    """
    out: list[RenderEdge] = []
    seen: set[tuple[str, str, str, str]] = set()
    for raw in edges or []:
        src = _text(_get(raw, "from", "from_"))
        dst = _text(_get(raw, "to"))
        if not src or not dst:
            continue
        if node_ids is not None and (src not in node_ids or dst not in node_ids):
            continue
        style = _text(_get(raw, "style", default="solid")) or "solid"
        if style not in EDGE_STYLES:
            style = "solid"
        edge = RenderEdge(
            from_=src, to=dst,
            label=_text(_get(raw, "label", default="")),
            style=style,
        )
        key = (edge.from_, edge.to, edge.label, edge.style)
        if key in seen:
            continue
        seen.add(key)
        out.append(edge)
    out.sort(key=lambda e: (e.from_, e.to, e.label, e.style))
    return out


def normalize_groups(groups: Any, node_ids: set[str] | None = None) -> list[RenderGroup]:
    """SPEC-shaped groups -> deterministic ``list[RenderGroup]``.

    Members that are unknown (or not part of ``node_ids`` when given) are
    dropped; a group whose members all drop away is kept only if it carries a
    label worth drawing?  No - an empty group has no geometry to draw, so it
    is dropped as well (deterministic no-op).
    """
    order = {nid: index for index, nid in enumerate(sorted(node_ids or ()))}
    out: list[RenderGroup] = []
    for raw in groups or []:
        group_id = _text(_get(raw, "id"))
        if not group_id:
            continue
        kind = _text(_get(raw, "kind", default="cluster")) or "cluster"
        if kind not in GROUP_KINDS:
            kind = "cluster"
        members: set[str] = set()
        for member in _get(raw, "nodes", default=[]) or []:
            member_id = _text(member)
            if not member_id:
                continue
            if node_ids is not None and member_id not in node_ids:
                continue
            members.add(member_id)
        if not members:
            continue
        out.append(RenderGroup(
            id=group_id,
            label=_text(_get(raw, "label", default="")),
            kind=kind,
            nodes=tuple(sorted(members)),
        ))
    out.sort(key=lambda g: _group_order_key(g, order))
    return out


def _group_order_key(group: RenderGroup, order: dict[str, int]) -> tuple:
    indexes = [order.get(nid, len(order)) for nid in group.nodes]
    return (_KIND_RANK.get(group.kind, 2), min(indexes, default=len(order)),
            group.label, group.id)


def group_membership(groups: list[RenderGroup]) -> dict[str, str]:
    """Map every member node id to exactly one owning group (first wins).

    A node listed in two groups would otherwise be declared twice in the
    graphviz clusters; the deterministic rule is "the first normalized group
    owns it".
    """
    owner: dict[str, str] = {}
    for group in groups:
        for nid in group.nodes:
            owner.setdefault(nid, group.id)
    return owner


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def normalize(
    nodes: Any,
    edges: Any,
    groups: Any = None,
) -> RenderSemantics:
    """Normalize a SPEC-shaped (or IR-object) diagram into render semantics."""
    norm_nodes = normalize_nodes(nodes)
    node_ids = {n.id for n in norm_nodes}
    norm_edges = normalize_edges(edges, node_ids)
    norm_groups = normalize_groups(groups, node_ids)
    return RenderSemantics(nodes=norm_nodes, edges=norm_edges, groups=norm_groups)


def from_block(block: Any) -> RenderSemantics:
    """Normalize a whole ``diagram``/``flow`` block (SPEC §1 JSON dict or object)."""
    return normalize(
        _get(block, "nodes", default=[]),
        _get(block, "edges", default=[]),
        _get(block, "groups", default=[]),
    )


__all__ = [
    "GROUP_KINDS",
    "EDGE_STYLES",
    "GROUP_FILL",
    "GROUP_LINE",
    "group_colors",
    "RenderNode",
    "RenderEdge",
    "RenderGroup",
    "RenderSemantics",
    "normalize_nodes",
    "normalize_edges",
    "normalize_groups",
    "group_membership",
    "normalize",
    "from_block",
]
