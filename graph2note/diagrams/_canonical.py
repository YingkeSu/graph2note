"""Canonical node/edge/group ordering shared by the render engines.

FR-020 requires the same semantics to render byte-identical output.  The VLM
may return nodes/edges/groups in any order; we canonicalize before laying out so
the result depends only on the graph's *content*, never its order.

Groups are handled in the SPEC §1 JSON shape (``id``/``label``/``kind``/
``nodes``).  They are accepted as plain dicts *and* as pydantic-style objects
exposing ``model_dump()`` so the layout engine can stay decoupled from the
in-flight ``ir.py`` extension (D1) and simply be rewired after that merges.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Mapping

from ..ir import Node, Edge


def group_as_dict(group: Any) -> dict:
    """Normalise a group into a plain dict without importing D1's models."""
    if isinstance(group, Mapping):
        return dict(group)
    dump = getattr(group, "model_dump", None)
    if callable(dump):
        return dict(dump())
    # Last resort: read the SPEC field names off the object.
    return {
        "id": getattr(group, "id", ""),
        "label": getattr(group, "label", ""),
        "kind": getattr(group, "kind", "cluster"),
        "nodes": list(getattr(group, "nodes", []) or []),
    }


def canonical_nodes(nodes: list[Node]) -> list[Node]:
    """Nodes sorted by id (stable, unique-agnostic)."""
    return sorted(nodes, key=lambda n: n.id)


def canonical_edges(edges: list[Edge], node_ids: set[str]) -> list[Edge]:
    """Edges sorted by (src, tgt, label), restricted to known node ids."""
    keep = [e for e in edges if e.from_ in node_ids and e.to in node_ids]
    return sorted(keep, key=lambda e: (e.from_, e.to, e.label))


def canonical_groups(
    groups: list[Any], node_ids: set[str] | None = None
) -> list[dict]:
    """Diagram groups normalised to the SPEC §1 shape, deterministically.

    - sorted by ``id`` (extra keys are a deterministic tie-break);
    - ``nodes`` members are de-duplicated and sorted;
    - ``kind`` falls back to ``"cluster"`` (SPEC default) and unknown kinds are
      preserved verbatim so the validator, not the layout, owns strictness;
    - when ``node_ids`` is given, dangling members are dropped -- mirroring
      :func:`canonical_edges`.  The dropped ids are not returned here; callers
      that need an audit trail can recompute them from the raw input.

    Unknown/extra keys survive the round-trip unchanged, so a pydantic model's
    serialised form can be fed straight through after D1 merges.
    """
    cleaned: list[dict] = []
    for raw in groups:
        item = group_as_dict(raw)
        members = item.get("nodes") or []
        if not isinstance(members, Iterable) or isinstance(members, (str, bytes)):
            members = [members]
        member_ids = {str(m) for m in members}
        if node_ids is not None:
            member_ids &= node_ids
        item["id"] = str(item.get("id", ""))
        item["label"] = str(item.get("label", ""))
        kind = item.get("kind")
        item["kind"] = str(kind) if kind else "cluster"
        item["nodes"] = sorted(member_ids)
        cleaned.append(item)
    return sorted(cleaned, key=_group_sort_key)


def _group_sort_key(group: dict) -> tuple:
    """Total order over groups so equal ids still canonicalise stably."""
    return (
        group["id"],
        group["kind"],
        group["label"],
        tuple(group["nodes"]),
    )
