"""Topic classification — documents -> a validated :class:`ClassificationScheme`.

The scheme is a machine-checkable structure (category labels + per-document
assignment + a one-line summary per document) that the vault exporter consumes
to (a) tag each note in its frontmatter and (b) build one MOC per topic.

The *classifier* is a plugin seam: a deterministic keyword/rule classifier is
the default (pure function, offline), and a gateway text-model path is provided
in :mod:`graph2note.notes.llm`. Whatever the origin, every scheme must pass
:func:`validate_scheme` before it may enter an export — an invalid scheme is
rejected (it never reaches the vault).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

from .exporter import ExportEntry

DEFAULT_MAX_TOPICS = 8  # PRD: small corpus (<20) <= 8 first-level categories


class SchemeError(ValueError):
    """Raised when a classification scheme fails schema validation."""


@dataclass
class ClassificationScheme:
    """Machine-checkable classification result.

    ``topics``: ordered first-level category labels (<= ``max_topics``).
    ``assignments``: topic -> [document_id] membership (a doc may have several).
    ``summaries``: document_id -> one-line summary.
    """

    topics: list = field(default_factory=list)
    assignments: dict = field(default_factory=dict)
    summaries: dict = field(default_factory=dict)
    version: int = 1
    # Runtime audit metadata is intentionally excluded from the serialized
    # classification contract; it records which configured channel produced it.
    runtime: dict = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {
            "topics": list(self.topics),
            "assignments": {t: list(ds) for t, ds in self.assignments.items()},
            "summaries": dict(self.summaries),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClassificationScheme":
        return cls(
            topics=list(data.get("topics", [])),
            assignments={
                str(t): list(ds) for t, ds in (data.get("assignments") or {}).items()
            },
            summaries={str(k): str(v) for k, v in (data.get("summaries") or {}).items()},
            version=data.get("version", 1),
        )


def topics_for_document(scheme: ClassificationScheme, document_id: str) -> list[str]:
    return [t for t, docs in scheme.assignments.items() if document_id in docs]


def validate_scheme(
    scheme: ClassificationScheme,
    document_ids: Iterable[str],
    *,
    max_topics: int = DEFAULT_MAX_TOPICS,
) -> ClassificationScheme:
    """Validate a scheme; return it unchanged or raise :class:`SchemeError`.

    Rules (schema):
    - topics: a list of non-empty unique strings, count <= ``max_topics``.
    - every assignment key is one of ``topics``.
    - every assigned document_id actually exists in the document set.
    - every document is assigned at least one topic (unless the set is empty).
    - every document has a one-line summary (unless the set is empty).
    """
    idset = set(document_ids)
    errors = []

    topics = []
    if not isinstance(scheme.topics, list):
        errors.append("'topics' must be a list")
    else:
        seen = set()
        for t in scheme.topics:
            s = str(t).strip()
            if s and s not in seen:
                seen.add(s)
                topics.append(s)
        if len(topics) > max_topics:
            errors.append(f"too many topics ({len(topics)} > {max_topics})")

    assignments = scheme.assignments or {}
    if not isinstance(assignments, dict):
        errors.append("'assignments' must be an object")
        assignments = {}
    topic_set = set(topics)
    for t, docs in assignments.items():
        if t not in topic_set:
            errors.append(f"assignment references unknown topic {t!r}")
        for d in (docs or []):
            if d not in idset:
                errors.append(f"assignment {t!r} references unknown document {d!r}")

    if idset:
        assigned = {d for docs in assignments.values() for d in (docs or [])}
        for d in sorted(idset):
            if d not in assigned and topics:
                errors.append(f"document {d!r} is not assigned any topic")
        summaries = scheme.summaries or {}
        for d in sorted(idset):
            if not summaries.get(d):
                errors.append(f"document {d!r} is missing a one-line summary")

    if errors:
        raise SchemeError("invalid classification scheme:\n" + "\n".join(errors))

    return ClassificationScheme(
        topics=topics,
        assignments={t: list(ds) for t, ds in assignments.items()},
        summaries={str(k): str(v) for k, v in (scheme.summaries or {}).items()},
        version=scheme.version,
        runtime=dict(scheme.runtime or {}),
    )


# ---------------------------------------------------------------------------
# Default deterministic classifier (offline fallback)
# ---------------------------------------------------------------------------

# keyword -> topic labels; matched (case-insensitively) against title+body.
DEFAULT_RULES: dict[str, list[str]] = {
    "数学": ["方程", "代数", "几何", "函数", "积分", "导数", "极限",
            "矩阵", "概率", "统计", "arithmetic", "algebra", "geometry",
            "calculus", "matrix", "equation"],
    "物理": ["力学", "电磁", "量子", "热力", "能量", "光学", "物理",
            "physics", "mechanics", "quantum", "energy"],
    "计算机": ["算法", "数据结构", "代码", "编程", "数据库", "分布式",
              "并发", "python", "algorithm", "database"],
    "笔记": ["笔记", "备忘", "总结", "要点", "note", "summary", "memo"],
}

_UNCLASSIFIED = "杂项"


def _summarize(entry: ExportEntry, limit: int = 60) -> str:
    text = entry.markdown.strip()
    if not text:
        return entry.title or entry.document_id
    first = ""
    for line in text.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        if line:
            first = line
            break
    first = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", first).strip()
    if len(first) > limit:
        first = first[: limit - 1].rstrip() + "…"
    return first or (entry.title or entry.document_id)


def rule_classify(
    entries: Iterable[ExportEntry],
    rule_map: Optional[dict[str, list[str]]] = None,
) -> ClassificationScheme:
    """Deterministic keyword classifier (offline, reproducible).

    Each document scans its title+markdown body against ``rule_map`` keywords;
    matched labels become its topics; docs matching nothing are binned into a
    single ``杂项``/misc category so every note is covered by some MOC.
    """
    entries = list(entries)
    rules = rule_map if rule_map is not None else DEFAULT_RULES
    topics_order = list(rules.keys())
    assignments: dict[str, list[str]] = {t: [] for t in topics_order}
    assignments[_UNCLASSIFIED] = []
    summaries: dict[str, str] = {}

    untagged = False
    for e in entries:
        corpus = (e.title + " " + e.markdown).lower()
        matched = [t for t in topics_order if any(k.lower() in corpus for k in rules[t])]
        if not matched:
            untagged = True
            matched = [_UNCLASSIFIED]
        summaries[e.document_id] = _summarize(e)
        for t in matched:
            assignments[t].append(e.document_id)

    if untagged:
        topics_order = topics_order + [_UNCLASSIFIED]
    scheme = ClassificationScheme(
        topics=topics_order,
        assignments=assignments,
        summaries=summaries,
        version=1,
    )
    # keep only topics that actually have members (tidy list + validatable)
    scheme.assignments = {t: ds for t, ds in scheme.assignments.items() if ds}
    scheme.topics = [t for t in scheme.topics if t in scheme.assignments]
    return scheme


def classify_documents(
    entries: Iterable[ExportEntry],
    *,
    classifier: Optional[Callable] = None,
    max_topics: int = DEFAULT_MAX_TOPICS,
) -> ClassificationScheme:
    """Run a classifier and gate its output through schema validation."""
    entries = list(entries)
    classifier = classifier or rule_classify
    scheme = classifier(entries) if callable(classifier) else classifier
    return validate_scheme(scheme, [e.document_id for e in entries],
                           max_topics=max_topics)


def apply_scheme(store, scheme: ClassificationScheme) -> dict:
    """Persist topics onto each DocumentRecord (07 store); return id->topics."""
    by_doc: dict[str, list[str]] = {}
    for t, docs in scheme.assignments.items():
        for d in docs:
            by_doc.setdefault(d, []).append(t)
    for d, topics in sorted(by_doc.items()):
        store.set_topics(d, topics)
    return by_doc
