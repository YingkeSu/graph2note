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

**Single source of truth**

* No ``layout`` argument (direct renderer call / tests): groups are derived
  from the ``groups`` input, ordered by node reading position.
* With ``layout`` (the product chain: D2's engine forwards
  ``RenderOutcome.layout``), this module is a *pure adapter*: node/edge
  labels+notes+styles come from the input, while group **order, kind, members
  and bbox** come verbatim from ``layout["groups"]``.  Nothing is re-sorted or
  re-classified, so the renderer can never disagree with the geometry D2
  computed (review F1/F3).  ``layout["positions"]`` is consumed by the
  matplotlib fallback; graphviz only needs the group metadata.

Normalization is deterministic and defensive:

* nodes are sorted by id, edges by ``(from, to, label, style)`` so input order
  never leaks into layout or rendered bytes (FR-020);
* edges are **not** de-duplicated - ``_canonical.canonical_edges`` keeps exact
  duplicates and the pre-SPW renderer drew them, so dropping them here would
  change ungrouped output (review F2);
* unknown group members are dropped (the IR layer rejects dangling refs; a
  renderer must not crash on stale/hand-built data);
* ``style`` values outside ``solid``/``dashed`` degrade to ``solid``;
* group member lists are de-duplicated and sorted by node id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..attachments import semantics_field

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


# ---------------------------------------------------------------------------
# display-label wrapping (legibility on narrow ranks)
# ---------------------------------------------------------------------------

def _display_units(text: str) -> int:
    return sum(2 if ord(char) > 127 else 1 for char in text)


def _chunks(text: str) -> list[str]:
    """Split into break opportunities: ASCII words stay whole, CJK per char."""
    out: list[str] = []
    buf = ""
    for char in text:
        if ord(char) < 128 and not char.isspace():
            buf += char
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(char)
    if buf:
        out.append(buf)
    return out


def _hard_split(chunk: str, max_units: int) -> list[str]:
    parts: list[str] = []
    current = ""
    units = 0
    for char in chunk:
        width = 2 if ord(char) > 127 else 1
        if current and units + width > max_units:
            parts.append(current)
            current, units = "", 0
        current += char
        units += width
    if current:
        parts.append(current)
    return parts


def wrap_display_label(label: str, max_units: int = 9) -> str:
    """Wrap a mixed CJK/Latin label into ``\\n`` lines, never mid-word (ASCII).

    Long Latin words that exceed ``max_units`` on their own are hard-split as a
    last resort; explicit newlines in the source label are preserved.
    """
    lines: list[str] = []
    for source_line in (label or "").split("\n"):
        current = ""
        units = 0
        for chunk in _chunks(source_line):
            chunk_units = _display_units(chunk)
            if current and units + chunk_units > max_units and not chunk.isspace():
                lines.append(current)
                current, units = "", 0
            if chunk_units > max_units:
                pieces = _hard_split(chunk, max_units)
                if current:
                    lines.append(current)
                    current, units = "", 0
                lines.extend(pieces[:-1])
                current = pieces[-1]
                units = _display_units(current)
                continue
            if not current and chunk.isspace():
                continue  # never start a display line with a space
            current += chunk
            units += chunk_units
        lines.append(current)
    return "\n".join(line.rstrip() for line in lines)


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
    """A visual group (layer band / swim-lane / local cluster).

    ``bbox`` is ``(x0, y0, x1, y1)`` in the normalized ``[0,1]²`` frame when
    the group came from a D2 ``layout`` (authoritative geometry), else ``None``
    and the fallback derives its own box from member positions.
    """

    id: str
    label: str = ""
    kind: str = "cluster"
    nodes: tuple[str, ...] = ()
    bbox: tuple[float, float, float, float] | None = None


@dataclass(frozen=True)
class RenderSemantics:
    """Everything a renderer needs, already normalized."""

    nodes: list[RenderNode] = field(default_factory=list)
    edges: list[RenderEdge] = field(default_factory=list)
    groups: list[RenderGroup] = field(default_factory=list)
    # Normalized positions from D2's layout (None for direct renderer calls).
    positions: dict[str, tuple[float, float]] | None = None

    @property
    def from_layout(self) -> bool:
        return self.positions is not None

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

# Single shared accessor (defined in ``attachments`` so ``render.py`` and the
# renderer adapter use exactly one implementation) - see review F6.
_get = semantics_field


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
    restriction ``_canonical.canonical_edges`` applies before layout.  Exact
    duplicates are kept: ``_canonical`` keeps them and the pre-SPW renderer
    drew them, so de-duplicating here would change ungrouped output (F2).
    """
    out: list[RenderEdge] = []
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
        out.append(RenderEdge(
            from_=src, to=dst,
            label=_text(_get(raw, "label", default="")),
            style=style,
        ))
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
        kind = _normalize_kind(_get(raw, "kind", default="cluster"))
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


def _normalize_kind(kind: Any) -> str:
    text = _text(kind) or "cluster"
    return text if text in GROUP_KINDS else "cluster"


def groups_from_layout(layout: dict, node_ids: set[str] | None = None) -> list[RenderGroup]:
    """Adapter for D2's ``RenderOutcome.layout`` (the geometry source).

    Group **order, kind, members and bbox** are taken verbatim from
    ``layout["groups"]``; nothing is re-sorted or re-classified (review F3).
    The only defensive step is dropping members that are not in ``nodes[]``.
    """
    out: list[RenderGroup] = []
    for raw in (layout or {}).get("groups") or []:
        group_id = _text(_get(raw, "id"))
        if not group_id:
            continue
        members: list[str] = []
        for member in _get(raw, "members", "nodes", default=[]) or []:
            member_id = _text(member)
            if not member_id:
                continue
            if node_ids is not None and member_id not in node_ids:
                continue
            if member_id not in members:
                members.append(member_id)
        bbox_raw = _get(raw, "bbox")
        bbox = None
        if isinstance(bbox_raw, dict):
            try:
                bbox = (float(bbox_raw["x0"]), float(bbox_raw["y0"]),
                        float(bbox_raw["x1"]), float(bbox_raw["y1"]))
            except (KeyError, TypeError, ValueError):
                bbox = None
        kind = _text(_get(raw, "kind", default="cluster")) or "cluster"
        out.append(RenderGroup(
            id=group_id,
            label=_text(_get(raw, "label", default="")),
            # D2 preserves unknown kinds verbatim; do the same so the renderer
            # cannot disagree with the geometry owner.
            kind=kind,
            nodes=tuple(members),
            bbox=bbox,
        ))
    return out


def positions_from_layout(layout: dict) -> dict[str, tuple[float, float]]:
    """Adapter for ``layout["positions"]`` (``{id: {x, y}}`` -> ``(x, y)``)."""
    out: dict[str, tuple[float, float]] = {}
    for node_id, point in ((layout or {}).get("positions") or {}).items():
        try:
            out[str(node_id)] = (float(point["x"]), float(point["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    return out


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
    layout: dict | None = None,
) -> RenderSemantics:
    """Normalize a SPEC-shaped (or IR-object) diagram into render semantics.

    With ``layout`` (D2's prepared geometry) this is a pure adapter: group
    order/kind/members/bbox and node positions come from the layout, so the
    renderer cannot diverge from the geometry owner.
    """
    norm_nodes = normalize_nodes(nodes)
    node_ids = {n.id for n in norm_nodes}
    norm_edges = normalize_edges(edges, node_ids)
    if layout:
        return RenderSemantics(
            nodes=norm_nodes,
            edges=norm_edges,
            groups=groups_from_layout(layout, node_ids),
            positions=positions_from_layout(layout),
        )
    return RenderSemantics(
        nodes=norm_nodes,
        edges=norm_edges,
        groups=normalize_groups(groups, node_ids),
    )


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
    "wrap_display_label",
    "RenderNode",
    "RenderEdge",
    "RenderGroup",
    "RenderSemantics",
    "normalize_nodes",
    "normalize_edges",
    "normalize_groups",
    "groups_from_layout",
    "positions_from_layout",
    "group_membership",
    "normalize",
    "from_block",
]
