"""Deterministic, read-only relationship graph projections."""

from __future__ import annotations

from typing import Any, Iterable
from urllib.parse import quote


EDGE_SOURCES = ("topic", "tag", "manual")
_NODE_ORDER = {"document": 0, "topic": 1, "tag": 2, "collection": 3}
_NODE_PREFIXES = tuple(f"{kind}:" for kind in _NODE_ORDER)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = _text(value)
        if value and value not in result:
            result.append(value)
    return result


def _scheme_value(scheme: Any, key: str, default: Any):
    if scheme is None:
        return default
    if isinstance(scheme, dict):
        return scheme.get(key, default)
    return getattr(scheme, key, default)


def _node_id(kind: str, value: Any) -> str:
    return f"{kind}:{_text(value)}"


def _route(kind: str, value: Any) -> str:
    encoded = quote(_text(value), safe="")
    routes = {
        "document": f"#doc/{encoded}",
        "topic": f"#library/topic/{encoded}",
        "tag": f"#library/tag/{encoded}",
        "collection": f"#library/collection/{encoded}",
    }
    return routes.get(kind, "#library")


def _node(kind: str, value: Any, label: Any = None) -> dict[str, Any]:
    value = _text(value)
    result: dict[str, Any] = {
        "id": _node_id(kind, value),
        "kind": kind,
        "label": _text(label) or value,
        "route": _route(kind, value),
    }
    field = {
        "document": "document_id",
        "topic": "topic",
        "tag": "tag",
        "collection": "collection_id",
    }.get(kind)
    if field:
        result[field] = value
    return result


def _canonical_reference(value: Any, default_kind: str = "document") -> str:
    value = _text(value)
    if not value:
        return ""
    if value.startswith(_NODE_PREFIXES):
        return value
    return _node_id(default_kind, value)


def _topics_for_record(record: dict[str, Any], scheme: Any) -> list[str]:
    document_id = _text(record.get("document_id"))
    topics = _unique(record.get("topics") or [])
    assignments = _scheme_value(scheme, "assignments", {}) or {}
    if isinstance(assignments, dict):
        topics.extend(
            _text(topic)
            for topic, document_ids in assignments.items()
            if document_id in (document_ids or [])
        )
    return _unique(topics)


def _collection_memberships(record: dict[str, Any]) -> list[str]:
    """Collection ids a record belongs to for graph projection.

    Manual memberships plus auto-organization assignments (issue 02);
    topic-derived collections stay out of the graph as before.
    """

    return _unique(
        list(record.get("manual_collections") or [])
        + list(record.get("auto_collections") or [])
    )


def _manual_relation_specs(record: dict[str, Any]) -> list[tuple[str, str]]:
    """Read persisted manual links and the public manual collection seam."""

    current = _canonical_reference(record.get("document_id"))
    result: list[tuple[str, str]] = []
    raw = record.get("manual_relations")
    if raw is None:
        raw = record.get("relations")
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, (str, int)):
        raw = [raw]
    for relation in raw or []:
        if isinstance(relation, (str, int)):
            source, target = current, _canonical_reference(relation)
        elif isinstance(relation, dict):
            raw_source = _text(relation.get("source"))
            explicit_from = relation.get("from") or relation.get("from_id")
            provenance = _text(relation.get("kind") or "manual").casefold()
            if raw_source.casefold() in {"topic", "tag", "manual", "inferred"}:
                provenance = raw_source.casefold()
            elif raw_source and not explicit_from:
                explicit_from = raw_source
            if provenance not in {"manual", "user", "user_manual"}:
                continue
            source = _canonical_reference(
                explicit_from or current
            )
            target = _canonical_reference(
                relation.get("to")
                or relation.get("to_id")
                or relation.get("target")
                or relation.get("target_id")
                or relation.get("document_id")
            )
        else:
            continue
        if source and target and source != target:
            result.append((source, target))
    for relation in record.get("related_documents") or []:
        target = _canonical_reference(relation)
        if target and target != current:
            result.append((current, target))
    return result


def build_graph(
    records: Iterable[dict[str, Any]],
    *,
    scheme: Any = None,
) -> dict[str, Any]:
    """Project records into stable navigable nodes and provenance-aware edges.

    Edge ``source`` is restricted to ``topic``, ``tag`` and ``manual``.  The
    function is pure from the caller's perspective: it does not mutate input,
    access the network, or invoke an AI/model service.
    """

    usable = [
        record for record in records
        if isinstance(record, dict) and _text(record.get("document_id"))
    ]
    usable.sort(key=lambda record: _text(record["document_id"]))
    nodes: dict[str, dict[str, Any]] = {}

    def add_node(kind: str, value: Any, label: Any = None) -> str:
        value = _text(value)
        if not value:
            return ""
        node_id = _node_id(kind, value)
        if node_id not in nodes:
            nodes[node_id] = _node(kind, value, label)
        elif label and nodes[node_id]["label"] == value:
            nodes[node_id]["label"] = _text(label)
        return node_id

    for record in usable:
        add_node("document", record["document_id"], record.get("title"))

    scheme_topics = _unique(_scheme_value(scheme, "topics", []) or [])
    assignments = _scheme_value(scheme, "assignments", {}) or {}
    if isinstance(assignments, dict):
        scheme_topics = _unique([*scheme_topics, *assignments.keys()])
    for topic in scheme_topics:
        add_node("topic", topic)

    document_topics: dict[str, list[str]] = {}
    document_tags: dict[str, list[str]] = {}
    for record in usable:
        document_id = _text(record["document_id"])
        topics = _topics_for_record(record, scheme)
        document_topics[document_id] = topics
        for topic in topics:
            add_node("topic", topic)
        tags = _unique(record.get("tags") or [])
        document_tags[document_id] = tags
        for tag in tags:
            add_node("tag", tag)
        names = record.get("collection_names") or {}
        if not isinstance(names, dict):
            names = {}
        for collection_id in _collection_memberships(record):
            add_node("collection", collection_id, names.get(collection_id, collection_id))

    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_edge(from_id: str, to_id: str, source: str, **details: Any) -> None:
        if source not in EDGE_SOURCES or from_id not in nodes or to_id not in nodes:
            return
        key = (source, from_id, to_id)
        if key in edges:
            return
        edge = {
            "id": f"{source}:{from_id}->{to_id}",
            "from": from_id,
            "to": to_id,
            "source": source,
            "from_route": nodes[from_id]["route"],
            "to_route": nodes[to_id]["route"],
        }
        edge.update({key: value for key, value in details.items() if value is not None})
        edges[key] = edge

    for record in usable:
        document_id = _text(record["document_id"])
        document_node = _node_id("document", document_id)
        for topic in document_topics[document_id]:
            add_edge(document_node, _node_id("topic", topic), "topic",
                     document_id=document_id, topic=topic)
        for tag in document_tags[document_id]:
            add_edge(document_node, _node_id("tag", tag), "tag",
                     document_id=document_id, tag=tag)
        names = record.get("collection_names") or {}
        if not isinstance(names, dict):
            names = {}
        for collection_id in _collection_memberships(record):
            add_edge(document_node, _node_id("collection", collection_id), "manual",
                     document_id=document_id, collection_id=collection_id,
                     collection=names.get(collection_id, collection_id))
        for from_id, to_id in _manual_relation_specs(record):
            add_edge(from_id, to_id, "manual", document_id=document_id, target_id=to_id)

    sorted_edges = sorted(
        edges.values(),
        key=lambda edge: (EDGE_SOURCES.index(edge["source"]), edge["from"], edge["to"]),
    )
    degrees = {node_id: 0 for node_id in nodes}
    for edge in sorted_edges:
        degrees[edge["from"]] += 1
        degrees[edge["to"]] += 1

    sorted_nodes = []
    for node in sorted(
        nodes.values(),
        key=lambda item: (_NODE_ORDER.get(item["kind"], 99), item["label"].casefold(), item["id"]),
    ):
        node = dict(node)
        node["degree"] = degrees[node["id"]]
        node["isolated"] = node["degree"] == 0
        sorted_nodes.append(node)

    kind_counts = {
        "documents": 0,
        "topics": 0,
        "tags": 0,
        "collections": 0,
    }
    for node in sorted_nodes:
        kind_counts[f"{node['kind']}s"] += 1
    return {
        "nodes": sorted_nodes,
        "edges": sorted_edges,
        "sources": [source for source in EDGE_SOURCES if any(
            edge["source"] == source for edge in sorted_edges
        )],
        "empty": not sorted_nodes,
        "counts": {"nodes": len(sorted_nodes), "edges": len(sorted_edges), **kind_counts},
        "clusters": _build_clusters(usable, document_topics),
        "filters": {
            "collections": _collection_filters(usable),
            "tags": _tag_filters(usable),
            "sources": [source for source in EDGE_SOURCES if any(
                edge["source"] == source for edge in sorted_edges
            )],
        },
    }


def _build_clusters(
    usable: list[dict[str, Any]],
    document_topics: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Projection-only topic clusters used by the graph view's convergence mode.

    Documents are grouped by their first topic (a deterministic projection of an
    existing field, no new inference).  Every document appears in exactly one
    cluster; documents without topics land in a single ``unclustered`` bucket.
    Cluster nodes are **not** part of ``nodes`` — existing consumers keep seeing
    only document/topic/tag/collection nodes.
    """

    buckets: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for record in usable:
        document_id = _text(record["document_id"])
        topics = document_topics.get(document_id) or []
        if topics:
            key = _node_id("topic", topics[0])
            labels.setdefault(key, topics[0])
        else:
            key = "topic:__unclustered__"
            labels.setdefault(key, "未归类")
        buckets.setdefault(key, []).append(document_id)

    clusters: list[dict[str, Any]] = []
    ordered = sorted(
        buckets.items(), key=lambda item: (item[0] == "topic:__unclustered__", item[0])
    )
    for key, document_ids in ordered:
        unclustered = key == "topic:__unclustered__"
        clusters.append({
            "id": f"cluster:{key}",
            "topic": None if unclustered else labels[key],
            "label": labels[key],
            "route": "#library" if unclustered else _route("topic", labels[key]),
            "documents": list(document_ids),
            "size": len(document_ids),
            "unclustered": unclustered,
        })
    return clusters


def _collection_filters(usable: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names: dict[str, str] = {}
    counts: dict[str, int] = {}
    for record in usable:
        record_names = record.get("collection_names") or {}
        if not isinstance(record_names, dict):
            record_names = {}
        for collection_id in _collection_memberships(record):
            names.setdefault(collection_id, str(record_names.get(collection_id, collection_id)))
            counts[collection_id] = counts.get(collection_id, 0) + 1
    return [
        {
            "id": collection_id,
            "label": names[collection_id],
            "count": counts[collection_id],
            "route": _route("collection", collection_id),
        }
        for collection_id in sorted(counts, key=lambda cid: (names[cid].casefold(), cid))
    ]


def _tag_filters(usable: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for record in usable:
        for tag in _unique(record.get("tags") or []):
            counts[tag] = counts.get(tag, 0) + 1
    return [
        {
            "id": tag,
            "label": tag,
            "count": counts[tag],
            "route": _route("tag", tag),
        }
        for tag in sorted(counts, key=lambda value: (value.casefold(), value))
    ]


__all__ = ["EDGE_SOURCES", "build_graph"]
