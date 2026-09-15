"""Weekly digest — periodic summaries over a time-ranged slice of the library.

Originally issue A2 of the ``usable-product-iteration`` round; issue W1 of the
``structure-paper-weekly`` round upgrades the *content structure* (SPEC §3).
Given a date range (本周 / 上周 / 自定义), every library document whose
**effective time** falls in the range is assembled into a deterministic material
bundle and rendered into a four-section Markdown note — three sections of which
are computed by pure functions and one-and-a-half by a **text** LLM call.  It is
an on-demand, repeatable and traceable generation — never a scheduled job.

Design guarantees (see the issue's acceptance criteria):

- **Deterministic four-section skeleton (SPEC §3).**  ``SECTION_DEFS`` fixes the
  order and titles of 本周概览 / 主题脉络 / 重点文档摘录 / 待整理与连续体进展 and
  every generated Markdown document carries all four.  本周概览 and
  重点文档摘录 are fully deterministic (:func:`compute_stats`,
  :func:`select_highlights`); the model only fills narrative paragraphs
  (主题脉络 / 待整理建议) as schema-validated JSON.
- **Explainable material budget.**  :func:`apply_material_budget` is a pure
  function: newest effective time first, plus a guaranteed per-topic quota
  (``TOPIC_FLOOR``); the rule and its thresholds are module constants.
- **Per-section provenance.**  Every section carries ``source_document_ids``
  (model sections only keep ids that exist in the material) and meta.json
  records ``sections: [{key, title, source_document_ids}]`` for W2.

- **Deterministic range -> document mapping.**  ``documents_in_range`` is a pure
  function over records; effective time follows the PRD priority chain
  (``document_time`` > ``capture_time`` > ``import_time``) and falls back to the
  import time when no slot is filled.  PDF page documents are ordinary library
  documents and are included.
- **Deterministic material + fingerprint.**  ``assemble_material`` sorts by
  effective time and builds a SHA-256 fingerprint over the range plus each
  document's id / version / content hash.  The same library state always yields
  the same fingerprint.
- **Fingerprint cache.**  A repeat request for the same fingerprint reuses the
  persisted result and makes **zero** LLM calls (budget discipline); only
  ``force=True`` regenerates and writes a new version.
- **Text channel + purpose session isolation.**  Generation goes through
  :func:`graph2note.notes.llm._gateway_text` (the text chat/completions
  channel) with a digests-only session id, so it never contends with the
  parse / eval / verify sessions.
- **Persisted, listable history.**  Every generated digest is written to
  ``<storage>/digests/<id>.md`` + ``<id>.meta.json`` (range, fingerprint,
  source ids, model, token/cost telemetry) and survives a process restart.

Nothing here talks to the network unless the default (live) planner is used;
tests inject a recorded golden planner.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote

from . import continuity, inbox

# ---------------------------------------------------------------------------
# Explicit bounds / constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 2
GENERATOR_VERSION = "digest-2"
# Bumped whenever the section instructions / output schema change, so a cached
# section written by an older prompt is never reused.
SECTION_PROMPT_VERSION = "digest-sections-1"

# ---------------------------------------------------------------------------
# The deterministic four-section skeleton (SPEC §3).  Order is fixed and is the
# order used by the Markdown output, the meta ``sections`` list and the prompt.
# ---------------------------------------------------------------------------

SECTION_OVERVIEW = "overview"
SECTION_TOPICS = "topics"
SECTION_HIGHLIGHTS = "highlights"
SECTION_PENDING = "pending"

SECTION_DEFS: tuple[tuple[str, str], ...] = (
    (SECTION_OVERVIEW, "本周概览"),
    (SECTION_TOPICS, "主题脉络"),
    (SECTION_HIGHLIGHTS, "重点文档摘录"),
    (SECTION_PENDING, "待整理与连续体进展"),
)
SECTION_TITLES = dict(SECTION_DEFS)
# Sections filled by the model; 概览 and 摘录 are rendered by pure functions.
NARRATIVE_SECTIONS: tuple[str, ...] = (SECTION_TOPICS, SECTION_PENDING)
DIGEST_TITLE = "# 本周小结"

# ---------------------------------------------------------------------------
# Material budget policy (deterministic; see :func:`apply_material_budget`).
# ---------------------------------------------------------------------------

# Maximum documents fed to one digest and per-document content budget.
MAX_DOCS = 60
# Guaranteed per-topic quota that survives the recency cut (「各主题保底配额」).
TOPIC_FLOOR = 2
MAX_DOC_CHARS = 2000
# Above this library size only the cheap significant continuity tier is
# counted; the suggested tier is O(n²) over document pairs.
CONTINUITY_SUGGESTED_MAX_DOCS = 200

# Deterministic 重点文档摘录 policy: at most HIGHLIGHT_LIMIT documents, each
# excerpt at most HIGHLIGHT_CHARS characters (including the ellipsis).
HIGHLIGHT_LIMIT = 5
HIGHLIGHT_CHARS = 240
_HIGHLIGHT_MARKERS = ("重点", "重要", "important", "key", "highlight")

# Statistics that the 待整理 section is allowed to depend on: they scope both
# the model prompt and the section cache fingerprint, so unrelated library
# churn does not invalidate a still-valid 待整理 narrative.
PENDING_STAT_KEYS: tuple[str, ...] = (
    "inbox_pending",
    "inbox_in_range",
    "inbox_reason_counts",
    "continuity_significant",
    "continuity_suggested",
    "continuity_suggested_counted",
)

# Output budget for one digest.  Reasoning-heavy text models (kimi-k3) spend
# part of this budget on reasoning tokens, so it is deliberately larger than a
# plain summary target; the shared text channel defaults to 4096.
MAX_SUMMARY_TOKENS = 8192
# Digests-only gateway session (purpose isolation).  The gateway keeps its own
# per-purpose sessions; digest intentionally owns a distinct id and never reuses
# parse / eval / verify / routeb / diagram.
DEFAULT_SESSION = "graph2note-digest-01"

RANGE_KINDS = ("this_week", "last_week", "custom")
RANGE_LABELS = {"this_week": "本周", "last_week": "上周", "custom": "自定义"}
EMPTY_MESSAGE = "该范围内没有材料"

_RANGE_ALIASES = {
    "this_week": "this_week", "thisweek": "this_week", "this-week": "this_week",
    "week": "this_week", "current_week": "this_week",
    "last_week": "last_week", "lastweek": "last_week", "last-week": "last_week",
    "previous_week": "last_week",
    "custom": "custom", "range": "custom",
}


class RangeError(ValueError):
    """Raised when a digest range specification is invalid."""


# ---------------------------------------------------------------------------
# Range resolution (pure)
# ---------------------------------------------------------------------------


def _as_date(value: Any) -> date | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_range_kind(kind: Any) -> str:
    if isinstance(kind, dict):
        kind = kind.get("kind") or kind.get("range") or "custom"
    text = str(kind or "this_week").strip().lower()
    resolved = _RANGE_ALIASES.get(text)
    if resolved is None:
        raise RangeError(
            f"未知范围类型：{kind!r}（可选 {'、'.join(RANGE_KINDS)}）"
        )
    return resolved


def resolve_range(
    kind: Any = "this_week",
    *,
    from_: Any = None,
    to: Any = None,
    today: date | None = None,
) -> dict[str, str]:
    """Resolve a range spec into ``{kind, from, to, label}`` (ISO dates).

    ``this_week`` / ``last_week`` are **calendar weeks** (Monday..Sunday), so the
    range is stable for the whole week and the fingerprint does not drift day by
    day (fewer needless model calls).
    """
    resolved = normalize_range_kind(kind)
    today = _as_date(today) or date.today()
    if resolved == "this_week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif resolved == "last_week":
        end = today - timedelta(days=today.weekday()) - timedelta(days=1)
        start = end - timedelta(days=6)
    else:
        start, end = _as_date(from_), _as_date(to)
        if start is None or end is None:
            raise RangeError("自定义范围需要提供合法的起止日期（from / to）。")
        if start > end:
            raise RangeError("自定义范围的起始日期不能晚于结束日期。")
    label = RANGE_LABELS[resolved]
    return {
        "kind": resolved,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "label": f"{label}（{start.isoformat()} ~ {end.isoformat()}）",
    }


# ---------------------------------------------------------------------------
# Effective-time selection + document mapping (pure)
# ---------------------------------------------------------------------------


def _slot_value(record: dict[str, Any], metadata: dict[str, Any], field: str):
    raw = metadata.get(field)
    if isinstance(raw, dict):
        value = raw.get("value") or record.get(field)
        source = raw.get("source") or field
    else:
        value = raw if raw is not None else record.get(field)
        source = field
    return (str(value) if value else None), source


def select_effective_time(record: dict[str, Any]) -> dict[str, Any] | None:
    """PRD priority chain, with the import time as the final fallback.

    ``document_time`` > ``capture_time`` > ``import_time``; when none of those
    slots (nor their scalar aliases) is filled the record's ``created_at``
    (the import time) is used.  Returns ``None`` only when even that is absent.
    """
    record = record if isinstance(record, dict) else {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for field in ("document_time", "capture_time", "import_time"):
        value, source = _slot_value(record, metadata, field)
        if value:
            return {"field": field, "value": value, "source": source}
    fallback = record.get("created_at")
    if not fallback:
        return None
    return {"field": "import_time", "value": str(fallback), "source": "import_fallback"}


def documents_in_range(records: Iterable[dict[str, Any]], range_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Pure range -> sorted document-entry mapping (AC1).

    Entries are sorted by (effective date, document_id) so the material bundle is
    byte-for-byte deterministic regardless of store iteration order.
    """
    start = _as_date(range_spec.get("from"))
    end = _as_date(range_spec.get("to"))
    if start is None or end is None:
        raise RangeError("范围缺少合法的起止日期。")
    entries: list[dict[str, Any]] = []
    for record in records or []:
        if not isinstance(record, dict):
            continue
        document_id = str(record.get("document_id") or "")
        if not document_id:
            continue
        effective = select_effective_time(record)
        if not effective:
            continue
        when = _as_date(effective.get("value"))
        if when is None or not (start <= when <= end):
            continue
        entries.append({
            "document_id": document_id,
            "title": str(record.get("title") or document_id),
            "date": when.isoformat(),
            "effective_time": effective,
            "tags": [str(t) for t in (record.get("tags") or [])],
            "topics": [str(t) for t in (record.get("topics") or [])],
        })
    entries.sort(key=lambda entry: (entry["date"], entry["document_id"]))
    return entries


# ---------------------------------------------------------------------------
# Material assembly + fingerprint (pure)
# ---------------------------------------------------------------------------


def _document_content(record: dict[str, Any]) -> str:
    markdown = record.get("current_markdown")
    if not markdown:
        versions = record.get("versions") or []
        latest = versions[-1] if versions else {}
        markdown = latest.get("markdown") if isinstance(latest, dict) else ""
    return markdown or ""


def _document_version(record: dict[str, Any]) -> str:
    latest = record.get("latest_version_id")
    if latest:
        return str(latest)
    versions = record.get("versions") or []
    if versions and isinstance(versions[-1], dict):
        return str(versions[-1].get("version_id") or "")
    return ""


def _truncate(text: str, limit: int = MAX_DOC_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n…（已截断）"


def compute_fingerprint(range_spec: dict[str, Any], documents: list[dict[str, Any]]) -> str:
    """SHA-256 over (generator version, range bounds, ids, versions, hashes).

    ``GENERATOR_VERSION`` is part of the payload so a digest written by an older
    generator is never reused as a cache hit even when the material is identical.
    """
    payload = {
        "schema": SCHEMA_VERSION,
        "generator": GENERATOR_VERSION,
        "from": str(range_spec.get("from") or ""),
        "to": str(range_spec.get("to") or ""),
        "documents": [
            {
                "document_id": d["document_id"],
                "version_id": d.get("version_id") or "",
                "content_hash": d.get("content_hash") or "",
            }
            for d in documents
        ],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Material budget (pure) — 有效时间优先 + 各主题保底配额
# ---------------------------------------------------------------------------


def _entry_label_set(entry: dict[str, Any]) -> list[str]:
    """Sorted 主题/标签 labels of one entry (topics ∪ tags, deduplicated)."""
    labels: list[str] = []
    for key in ("topics", "tags"):
        for value in entry.get(key) or []:
            text = str(value).strip()
            if text and text not in labels:
                labels.append(text)
    return sorted(labels)


def _entry_sort_key(entry: dict[str, Any]) -> tuple[str, str]:
    return (str(entry.get("date") or ""), str(entry.get("document_id") or ""))


def apply_material_budget(
    entries: list[dict[str, Any]],
    *,
    max_docs: int = MAX_DOCS,
    topic_floor: int = TOPIC_FLOOR,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministic material budget: recency first, per-topic floor guaranteed.

    Rule (pure, no IO, no model):

    1. **有效时间优先** — the baseline keeps the ``max_docs`` newest documents
       (by effective date, then document id).
    2. **各主题保底配额** — every 主题/标签 label (``topics`` ∪ ``tags``) keeps its
       ``topic_floor`` newest documents even if they fall outside the baseline;
       the overflow this creates is paid by dropping the *oldest* documents that
       are not protected by any floor.

    Returns ``(selected, report)``; ``selected`` is sorted oldest → newest and the
    report explains the取舍 (kept/omitted ids, per-topic counts, guarantees).
    """
    ordered = sorted(entries or [], key=_entry_sort_key)
    total = len(ordered)
    cap = max(0, int(max_docs))
    floor = max(0, int(topic_floor))

    by_topic: dict[str, list[dict[str, Any]]] = {}
    for entry in ordered:
        for label in _entry_label_set(entry):
            by_topic.setdefault(label, []).append(entry)

    if total <= cap:
        selected = list(ordered)
        guaranteed_ids: list[str] = []
    else:
        selected = list(ordered[total - cap:]) if cap else []
        guaranteed: list[dict[str, Any]] = []
        guaranteed_seen: set[str] = set()
        if floor:
            for label in sorted(by_topic):
                for entry in by_topic[label][-floor:]:
                    document_id = str(entry["document_id"])
                    if document_id not in guaranteed_seen:
                        guaranteed_seen.add(document_id)
                        guaranteed.append(entry)
            guaranteed.sort(key=_entry_sort_key)
            if len(guaranteed) > cap:
                guaranteed = guaranteed[-cap:] if cap else []
                guaranteed_seen = {str(e["document_id"]) for e in guaranteed}
        selected_ids = {str(e["document_id"]) for e in selected}
        for entry in guaranteed:
            document_id = str(entry["document_id"])
            if document_id not in selected_ids:
                selected.append(entry)
                selected_ids.add(document_id)
        selected.sort(key=_entry_sort_key)
        while len(selected) > cap:
            victim = next(
                (e for e in selected if str(e["document_id"]) not in guaranteed_seen),
                selected[0],
            )
            selected.remove(victim)
        guaranteed_ids = sorted(guaranteed_seen)

    kept_ids = [str(e["document_id"]) for e in selected]
    per_topic_kept = {
        label: sum(1 for e in selected if label in _entry_label_set(e))
        for label in sorted(by_topic)
    }
    report = {
        "max_docs": cap,
        "topic_floor": floor,
        "total": total,
        "kept": len(selected),
        "omitted": total - len(selected),
        "kept_ids": kept_ids,
        "guaranteed_ids": guaranteed_ids,
        "topics": sorted(by_topic),
        "per_topic_kept": per_topic_kept,
    }
    return selected, report


# ---------------------------------------------------------------------------
# Deterministic statistics (pure, never calls a model)
# ---------------------------------------------------------------------------


def _inbox_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Library-wide Inbox backlog (pure projection, no model)."""
    items = inbox.build_inbox(records)
    return {"inbox_pending": len(items)}


def _continuity_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Continuity pairs (pure, zero LLM); the O(n²) tier is size-capped."""
    counted = len(records) <= CONTINUITY_SUGGESTED_MAX_DOCS
    pairs = continuity.detect_continuity(records, include_suggested=counted)
    significant = sum(1 for p in pairs if p.get("tier") == continuity.SIGNIFICANT)
    suggested = sum(1 for p in pairs if p.get("tier") == continuity.SUGGESTED)
    return {
        "continuity_significant": significant,
        "continuity_suggested": suggested,
        "continuity_suggested_counted": counted,
    }


def _stats_for(
    entries: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    range_spec: dict[str, Any],
) -> dict[str, Any]:
    start = _as_date(range_spec.get("from"))
    end = _as_date(range_spec.get("to"))
    parsed = failed = new_documents = tagged = 0
    topics: set[str] = set()
    tags: set[str] = set()
    inbox_in_range = 0
    reason_counts: dict[str, int] = {}
    for entry in entries:
        record = by_id.get(entry["document_id"], {})
        if (_document_content(record) or "").strip():
            parsed += 1
        else:
            failed += 1
        for value in entry.get("topics") or []:
            text = str(value).strip()
            if text:
                topics.add(text)
        if entry.get("tags"):
            tagged += 1
        for value in entry.get("tags") or []:
            text = str(value).strip()
            if text:
                tags.add(text)
        created = _as_date(record.get("created_at"))
        if created is not None and start is not None and end is not None and start <= created <= end:
            new_documents += 1
        reasons = inbox.inbox_reasons(record)
        if reasons:
            inbox_in_range += 1
            for reason in reasons:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
    count = len(entries)
    return {
        "document_count": count,
        "new_document_count": new_documents,
        "parsed_count": parsed,
        "failed_count": failed,
        "parse_success_rate": round(parsed * 100.0 / count, 1) if count else None,
        "topic_count": len(topics),
        "topics": sorted(topics),
        "tag_count": len(tags),
        "tags": sorted(tags),
        "tagged_count": tagged,
        "inbox_in_range": inbox_in_range,
        "inbox_reason_counts": {key: reason_counts[key] for key in sorted(reason_counts)},
        # budget fields are filled by :func:`assemble_material`; the defaults keep
        # :func:`compute_stats` a complete, standalone pure function.
        "omitted_count": 0,
        "max_docs": MAX_DOCS,
        "topic_floor": TOPIC_FLOOR,
    }


def compute_stats(
    records: Iterable[dict[str, Any]],
    range_spec: dict[str, Any],
    *,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Deterministic 本周概览 / 待整理 statistics for one range (pure).

    Everything here is computed from the records by pure functions — the model
    never sees or produces these numbers.  ``entries`` lets
    :func:`assemble_material` reuse the range mapping it already built.
    """
    recs = [r for r in records or [] if isinstance(r, dict)]
    by_id: dict[str, dict[str, Any]] = {}
    for record in recs:
        if record.get("document_id"):
            by_id.setdefault(str(record["document_id"]), record)
    ranged = documents_in_range(recs, range_spec) if entries is None else list(entries)
    stats = _stats_for(ranged, by_id, range_spec)
    stats.update(_inbox_stats(recs))
    stats.update(_continuity_stats(recs))
    return stats


# ---------------------------------------------------------------------------
# 重点文档摘录 (deterministic selection + excerpt budget)
# ---------------------------------------------------------------------------


def _highlight_rank(doc: dict[str, Any]) -> tuple[int, int, int, str]:
    labels = [str(t).strip().casefold() for t in (doc.get("tags") or []) + (doc.get("topics") or [])]
    marked = any(
        marker in label for label in labels for marker in _HIGHLIGHT_MARKERS
    )
    when = _as_date(doc.get("date")) or date.min
    return (
        0 if marked else 1,
        -len(doc.get("content") or ""),
        -when.toordinal(),
        str(doc.get("document_id") or ""),
    )


def select_highlights(
    documents: list[dict[str, Any]],
    *,
    limit: int = HIGHLIGHT_LIMIT,
) -> list[dict[str, Any]]:
    """Deterministic 重点文档 selection (pure).

    Explicit 重点/important/key labels come first, then longer content (more
    material to excerpt), then the newest effective time, then document id.
    """
    return sorted(documents or [], key=_highlight_rank)[: max(0, int(limit))]


def document_excerpt(text: str, *, limit: int = HIGHLIGHT_CHARS) -> str:
    """Deterministic per-document excerpt, ``len(result) <= limit`` always."""
    body = (text or "").strip()
    limit = max(0, int(limit))
    if len(body) <= limit:
        return body
    if limit == 0:
        return ""
    return body[: limit - 1].rstrip() + "…"


def render_highlights_body(documents: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """Render the deterministic 重点文档摘录 body + its exact source ids."""
    if not documents:
        return "（本期没有可摘录的文档）", []
    lines: list[str] = []
    ids: list[str] = []
    for index, doc in enumerate(documents, start=1):
        document_id = str(doc["document_id"])
        ids.append(document_id)
        lines.append(f"### {index}. {doc.get('title') or document_id}")
        meta = [f"日期：{doc.get('date') or '未知'}"]
        if doc.get("tags"):
            meta.append("标签：" + "、".join(str(t) for t in doc["tags"]))
        if doc.get("topics"):
            meta.append("主题：" + "、".join(str(t) for t in doc["topics"]))
        lines.append("- " + " ｜ ".join(meta))
        link = f"#doc/{quote(document_id, safe='')}"
        lines.append(f"- 来源：[{doc.get('title') or document_id}]({link})（`{document_id}`）")
        excerpt = document_excerpt(doc.get("content") or "")
        if excerpt:
            lines.append("")
            for line in excerpt.splitlines():
                lines.append(f"> {line}".rstrip())
        lines.append("")
    return "\n".join(lines).strip(), ids


# ---------------------------------------------------------------------------
# Deterministic section bodies
# ---------------------------------------------------------------------------


def render_overview_body(stats: dict[str, Any]) -> str:
    """本周概览 body — deterministic statistics only, never the model."""
    count = int(stats.get("document_count") or 0)
    parsed = int(stats.get("parsed_count") or 0)
    rate = stats.get("parse_success_rate")
    rate_text = f"{float(rate):.1f}%" if rate is not None else "无材料"
    lines = [
        f"- 材料文档：{count} 篇（本周新增 {int(stats.get('new_document_count') or 0)} 篇）",
        f"- 解析成功：{parsed}/{count}（{rate_text}），失败 {int(stats.get('failed_count') or 0)} 篇",
        f"- 主题标签：{int(stats.get('topic_count') or 0)} 个主题 / "
        f"{int(stats.get('tag_count') or 0)} 个标签（覆盖 {int(stats.get('tagged_count') or 0)} 篇）",
    ]
    omitted = int(stats.get("omitted_count") or 0)
    if omitted:
        kept = int(stats.get("document_count") or 0) - omitted
        lines.append(
            f"- 材料裁剪：本期共 {count} 篇，按「有效时间优先 + 每主题保底 "
            f"{int(stats.get('topic_floor') or 0)} 篇」保留 {kept} 篇，省略 {omitted} 篇"
        )
    return "\n".join(lines)


def render_pending_stats_body(stats: dict[str, Any]) -> str:
    """待整理与连续体进展 deterministic statistics block."""
    lines = [
        f"- Inbox 积压：库内 {int(stats.get('inbox_pending') or 0)} 篇待整理"
        f"（本期 {int(stats.get('inbox_in_range') or 0)} 篇）",
    ]
    reason_counts = stats.get("inbox_reason_counts") or {}
    if reason_counts:
        detail = "、".join(
            f"{inbox.REASON_LABELS.get(reason, reason)} {int(title_count)}"
            for reason, title_count in sorted(reason_counts.items())
        )
        lines.append(f"  - 原因：{detail}")
    counted_note = "" if stats.get("continuity_suggested_counted", True) else "（库规模超阈值，仅统计显著对）"
    lines.append(
        f"- 连续体：可直接合并 {int(stats.get('continuity_significant') or 0)} 对，"
        f"待确认 {int(stats.get('continuity_suggested') or 0)} 对{counted_note}"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section fingerprints (bonus: per-section cache) + assembly
# ---------------------------------------------------------------------------


def _section_fingerprint(
    section: str,
    range_spec: dict[str, Any],
    documents: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> str:
    """Fingerprint of one narrative section's own material.

    Only the fields the section actually depends on are hashed — document
    identity and *content* (not version id), so a version bump with unchanged
    text keeps the section cache valid.  An empty material set yields ``""``,
    which never hits the section cache.
    """
    if not documents:
        return ""
    payload = {
        "prompt_version": SECTION_PROMPT_VERSION,
        "section": section,
        "from": str(range_spec.get("from") or ""),
        "to": str(range_spec.get("to") or ""),
        "documents": [
            {"document_id": d["document_id"], "content_hash": d.get("content_hash") or ""}
            for d in documents
        ],
        "extra": extra or {},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def section_fingerprints(
    range_spec: dict[str, Any],
    organized_documents: list[dict[str, Any]],
    pending_documents: list[dict[str, Any]],
    stats: dict[str, Any],
) -> dict[str, str]:
    """Per-section material fingerprints for the narrative sections."""
    pending_scope = {key: stats.get(key) for key in PENDING_STAT_KEYS if key in stats}
    return {
        SECTION_TOPICS: _section_fingerprint(SECTION_TOPICS, range_spec, organized_documents),
        SECTION_PENDING: _section_fingerprint(
            SECTION_PENDING, range_spec, pending_documents, extra=pending_scope
        ),
    }


# Reasons that put a document into the 待整理 material even though it carries a
# topic/tag label (explicit "needs organization" marker / low-confidence signal).
_PENDING_FLAG_REASONS = ("explicit", "low_confidence")


def _is_pending(doc: dict[str, Any]) -> bool:
    """待整理 material: no 主题/标签 label at all, or an explicit review flag.

    The Inbox projection (:mod:`graph2note.inbox`) also reports ``no_tag`` for a
    topiced-but-untagged document; that document still has a 主题脉络, so it stays
    in the topics material.  The Inbox *statistics* keep the projection verbatim.
    """
    reasons = {str(reason) for reason in (doc.get("inbox_reasons") or [])}
    if reasons.intersection(_PENDING_FLAG_REASONS):
        return True
    return not (doc.get("topics") or doc.get("tags"))


def assemble_material(
    records: Iterable[dict[str, Any]],
    range_spec: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic material bundle: budgeted docs + statistics + prompt."""
    recs = [r for r in records or [] if isinstance(r, dict)]
    by_id: dict[str, dict[str, Any]] = {}
    for record in recs:
        if record.get("document_id"):
            by_id.setdefault(str(record["document_id"]), record)
    entries = documents_in_range(recs, range_spec)
    selected, budget = apply_material_budget(entries)

    documents: list[dict[str, Any]] = []
    for entry in selected:
        record = by_id.get(entry["document_id"], {})
        content = _document_content(record)
        documents.append({
            **entry,
            "version_id": _document_version(record),
            "inbox_reasons": inbox.inbox_reasons(record),
            "content": _truncate(content),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "truncated": len((content or "").strip()) > MAX_DOC_CHARS,
        })

    stats = compute_stats(recs, range_spec, entries=entries)
    stats.update({
        "omitted_count": budget["omitted"],
        "max_docs": budget["max_docs"],
        "topic_floor": budget["topic_floor"],
    })
    pending_documents = [d for d in documents if _is_pending(d)]
    organized_documents = [d for d in documents if not _is_pending(d)]
    fingerprints = section_fingerprints(
        range_spec, organized_documents, pending_documents, stats
    )
    fingerprint = compute_fingerprint(range_spec, documents)
    return {
        "range": range_spec,
        "documents": documents,
        "entries": entries,
        "highlights": select_highlights(documents),
        "stats": stats,
        "budget": budget,
        "pending_documents": pending_documents,
        "organized_documents": organized_documents,
        "section_fingerprints": fingerprints,
        "fingerprint": fingerprint,
        "omitted": budget["omitted"],
        "prompt": build_prompt(
            range_spec,
            documents,
            stats=stats,
            sections=NARRATIVE_SECTIONS,
            pending_documents=pending_documents,
        ),
    }


def _document_block(doc: dict[str, Any]) -> list[str]:
    lines = [f'<document id="{doc["document_id"]}" date="{doc["date"]}">']
    lines.append(f'标题：{doc["title"]}')
    if doc.get("tags"):
        lines.append("标签：" + "、".join(str(t) for t in doc["tags"]))
    if doc.get("topics"):
        lines.append("主题：" + "、".join(str(t) for t in doc["topics"]))
    lines.append("内容：")
    lines.append(doc.get("content") or "（无内容）")
    lines.append("</document>")
    return lines


def build_prompt(
    range_spec: dict[str, Any],
    documents: list[dict[str, Any]],
    *,
    stats: dict[str, Any] | None = None,
    sections: Iterable[str] | None = None,
    pending_documents: list[dict[str, Any]] | None = None,
) -> str:
    """Sectioned JSON prompt for the narrative sections (schema-validated reply).

    Material is scoped per section: 主题脉络 sees the documents that carry a
    主题/标签 label, 待整理 sees the label-less / flagged documents plus the
    deterministic statistics.  Only the requested ``sections`` are asked for,
    which is what makes the per-section cache able to skip exactly the sections
    that did not change.
    """
    requested = [key for key in (sections or NARRATIVE_SECTIONS) if key in NARRATIVE_SECTIONS]
    pending = (
        [d for d in documents if _is_pending(d)]
        if pending_documents is None
        else list(pending_documents)
    )
    organized = [d for d in documents if not _is_pending(d)]
    example = ", ".join(
        f'"{key}": {{"markdown": "…", "source_document_ids": ["doc-id"]}}'
        for key in requested
    )
    lines = [
        "你是文档整理助手。请为本期周报填写下面指定的分节，只输出 JSON。",
        "JSON 格式：",
        '{"sections": {' + example + "}}",
        "要求：",
        "1. 只依据材料内容，不要编造材料中没有的信息。",
        "2. 不要输出周报标题、不要输出「来源」清单（系统自动生成）；Markdown 标题从三级（###）开始。",
        "3. source_document_ids 只能取自材料的 document id，逐条列出本节实际依据的文档；没有把握时给空列表。",
        "4. 只输出上面 JSON 里出现的分节，不要新增分节。",
        "",
        f"时间范围：{range_spec.get('label') or range_spec.get('from')}",
        "",
    ]
    if SECTION_TOPICS in requested:
        lines.append("主题脉络（按主题/标签聚合要点）：")
        lines.append("主题材料：")
        lines.extend(_material_block(organized))
        lines.append("")
    if SECTION_PENDING in requested:
        lines.append("待整理与连续体进展（结合统计给出少量可执行建议）：")
        lines.append("待整理统计：")
        lines.extend(
            render_pending_stats_body(stats).splitlines() if stats else ["（无统计）"]
        )
        lines.append("待整理材料：")
        lines.extend(_material_block(pending))
        lines.append("")
    lines.append(f"请只输出 JSON，其中只包含：{'、'.join(requested) or '（无）'}。")
    return "\n".join(lines)


def _material_block(documents: list[dict[str, Any]]) -> list[str]:
    if not documents:
        return ["（本节没有材料）"]
    lines: list[str] = []
    for doc in documents:
        lines.extend(_document_block(doc))
    return lines


def _valid_ids(value: Any, allowed: set[str]) -> list[str]:
    """Keep only known document ids, deduplicated and order-preserving."""
    if isinstance(value, str):
        candidates: list[Any] = [value]
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    elif isinstance(value, set):
        candidates = sorted(str(item) for item in value)
    else:
        return []
    out: list[str] = []
    for item in candidates:
        if item is None or isinstance(item, bool):
            continue
        text = str(item).strip()
        if text and text in allowed and text not in out:
            out.append(text)
    return out


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _extract_json(text: str) -> Any | None:
    body = (text or "").strip()
    candidates: list[str] = []
    fenced = _JSON_FENCE_RE.search(body)
    if fenced:
        candidates.append(fenced.group(1).strip())
    candidates.append(body)
    start, end = body.find("{"), body.rfind("}")
    if 0 <= start < end:
        candidates.append(body[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (ValueError, TypeError):
            continue
    return None


def parse_section_reply(
    text: str,
    *,
    allowed_ids: Iterable[str],
    sections: Iterable[str],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Validate a sectioned JSON reply; returns ``(bodies, mode)``.

    ``mode`` is ``"json"`` when at least one requested section validated, else
    ``"text"`` — the caller then treats the raw reply as unstructured prose.
    Unknown / dangling ``source_document_ids`` are dropped, never invented.
    """
    allowed = {str(item) for item in allowed_ids}
    data = _extract_json(text)
    bodies: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict):
        container = data.get("sections") if isinstance(data.get("sections"), dict) else data
        for key in sections:
            raw = container.get(key) if isinstance(container, dict) else None
            if isinstance(raw, str):
                body, ids = raw, []
            elif isinstance(raw, dict):
                body = str(raw.get("markdown") or raw.get("text") or raw.get("content") or "")
                ids = _valid_ids(
                    raw.get("source_document_ids", raw.get("document_ids")), allowed
                )
            else:
                continue
            body = body.strip()
            if not body and not ids:
                continue
            bodies[key] = {"markdown": body, "source_document_ids": ids}
    if bodies:
        return bodies, "json"
    return {}, "text"


def build_sections(
    material: dict[str, Any],
    bodies: dict[str, dict[str, Any]],
    modes: dict[str, str],
) -> list[dict[str, Any]]:
    """Assemble the ordered four-section document from bodies + deterministic parts."""
    stats = material.get("stats") or {}
    range_ids = [str(e["document_id"]) for e in material.get("entries") or []]
    highlights_body, highlight_ids = render_highlights_body(material.get("highlights") or [])

    topics = bodies.get(SECTION_TOPICS) or {}
    topics_body = (topics.get("markdown") or "").strip() or "（本期没有带主题/标签的文档）"
    pending = bodies.get(SECTION_PENDING) or {}
    pending_extra = (pending.get("markdown") or "").strip()
    pending_body = render_pending_stats_body(stats)
    if pending_extra:
        pending_body = f"{pending_body}\n\n{pending_extra}"

    return [
        {
            "key": SECTION_OVERVIEW,
            "title": SECTION_TITLES[SECTION_OVERVIEW],
            "markdown": render_overview_body(stats),
            "source_document_ids": range_ids,
            "generated_by": "deterministic",
        },
        {
            "key": SECTION_TOPICS,
            "title": SECTION_TITLES[SECTION_TOPICS],
            "markdown": topics_body,
            "source_document_ids": list(topics.get("source_document_ids") or []),
            "generated_by": modes.get(SECTION_TOPICS, "empty"),
        },
        {
            "key": SECTION_HIGHLIGHTS,
            "title": SECTION_TITLES[SECTION_HIGHLIGHTS],
            "markdown": highlights_body,
            "source_document_ids": highlight_ids,
            "generated_by": "deterministic",
        },
        {
            "key": SECTION_PENDING,
            "title": SECTION_TITLES[SECTION_PENDING],
            "markdown": pending_body,
            "source_document_ids": list(pending.get("source_document_ids") or []),
            "generated_by": modes.get(SECTION_PENDING, "deterministic"),
        },
    ]


def public_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The W2 contract view of sections: key / title / source_document_ids."""
    return [
        {
            "key": section["key"],
            "title": section["title"],
            "source_document_ids": list(section.get("source_document_ids") or []),
        }
        for section in sections
    ]


def meta_sections(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Validated ``sections`` of one digest meta; ``[]`` for legacy metas."""
    raw = (meta or {}).get("sections")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        ids = item.get("source_document_ids")
        out.append({
            "key": key,
            "title": str(item.get("title") or SECTION_TITLES.get(key) or key),
            "source_document_ids": [str(i) for i in ids] if isinstance(ids, list) else [],
        })
    return out


_PUBLIC_DOC_FIELDS = (
    "document_id", "title", "date", "effective_time", "tags", "topics", "truncated",
)


def public_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the assembled content from API-facing source entries."""
    return [
        {key: doc.get(key) for key in _PUBLIC_DOC_FIELDS if key in doc}
        for doc in documents
    ]


def render_digest_markdown(
    range_spec: dict[str, Any],
    sections: list[dict[str, Any]],
    documents: list[dict[str, Any]],
) -> str:
    """Render the four-section digest Markdown + the deterministic source list.

    The section order/titles come from ``sections`` (built by
    :func:`build_sections`), so the skeleton is fixed by data, not by the model.
    """
    label = (range_spec or {}).get("label") or (range_spec or {}).get("from") or ""
    lines = [DIGEST_TITLE, ""]
    if label:
        lines.extend([f"时间范围：{label}", ""])
    for section in sections:
        lines.extend([f"## {section['title']}", ""])
        body = (section.get("markdown") or "").strip()
        lines.append(body or "_（本节没有可归纳的内容）_")
        lines.append("")
    lines.extend(["---", "", "## 来源", ""])
    for doc in documents:
        document_id = doc["document_id"]
        link = f"#doc/{quote(document_id, safe='')}"
        lines.append(f'- [{doc["title"]}]({link})（`{document_id}`）')
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Persistence (the only IO in this module)
# ---------------------------------------------------------------------------


def digests_dir(storage_dir: str | Path) -> Path:
    return Path(storage_dir) / "digests"


def _meta_path(storage_dir: str | Path, digest_id: str) -> Path:
    return digests_dir(storage_dir) / f"{digest_id}.meta.json"


def _markdown_path(storage_dir: str | Path, digest_id: str) -> Path:
    return digests_dir(storage_dir) / f"{digest_id}.md"


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\-]", "-", value or "")


def list_digests(storage_dir: str | Path) -> list[dict[str, Any]]:
    """All persisted digest metas, newest first (restart-safe)."""
    directory = digests_dir(storage_dir)
    if not directory.is_dir():
        return []
    metas: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.meta.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(meta, dict) and meta.get("digest_id"):
            metas.append(meta)
    metas.sort(key=lambda meta: (str(meta.get("created_at") or ""), meta["digest_id"]), reverse=True)
    return metas


def _sections_path(storage_dir: str | Path, digest_id: str) -> Path:
    return digests_dir(storage_dir) / f"{digest_id}.sections.json"


def load_digest(storage_dir: str | Path, digest_id: str) -> dict[str, Any] | None:
    """Return ``{meta, markdown, sections}`` for one digest, or ``None``.

    ``sections`` is the validated ``{key, title, source_document_ids}`` list; a
    legacy meta written before W1 has no ``sections`` key and yields ``[]``
    instead of raising (backward compatibility for W2).
    """
    meta_path = _meta_path(storage_dir, digest_id)
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    markdown_path = _markdown_path(storage_dir, digest_id)
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
    return {"meta": meta, "markdown": markdown, "sections": meta_sections(meta)}


def load_section_bodies(storage_dir: str | Path, digest_id: str) -> dict[str, Any]:
    """Raw per-section cache payload of one digest (``{}`` when absent)."""
    path = _sections_path(storage_dir, digest_id)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_section_bodies(
    storage_dir: str | Path,
    digest_id: str,
    *,
    bodies: dict[str, dict[str, Any]],
    fingerprints: dict[str, str],
) -> Path:
    """Persist the *narrative* section bodies + fingerprints (section cache).

    Only the model-authored body is stored — never the composed section (the
    deterministic statistics are always recomputed for the current library
    state), and only for sections that actually have material to key on.
    """
    entries: dict[str, Any] = {}
    for key, body in (bodies or {}).items():
        fingerprint = fingerprints.get(str(key), "")
        if key not in NARRATIVE_SECTIONS or not fingerprint:
            continue
        markdown = str((body or {}).get("markdown") or "").strip()
        if not markdown:
            continue
        entries[str(key)] = {
            "title": SECTION_TITLES.get(str(key), str(key)),
            "fingerprint": fingerprint,
            "markdown": markdown,
            "source_document_ids": list((body or {}).get("source_document_ids") or []),
        }
    path = _sections_path(storage_dir, digest_id)
    if not entries:
        if path.exists():
            path.unlink()
        return path
    digests_dir(storage_dir).mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"digest_id": digest_id, "sections": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def find_cached_section(
    storage_dir: str | Path,
    section_key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    """Newest persisted narrative section with the same section fingerprint.

    This is the W1 bonus over the whole-report cache: when only one section's
    material changed, the untouched section is reused with **zero** extra model
    calls for it.
    """
    if not fingerprint:
        return None
    for meta in list_digests(storage_dir):
        payload = load_section_bodies(storage_dir, str(meta.get("digest_id") or ""))
        entry = (payload.get("sections") or {}).get(section_key)
        if not isinstance(entry, dict):
            continue
        if entry.get("fingerprint") != fingerprint:
            continue
        markdown = (entry.get("markdown") or "").strip()
        if not markdown:
            continue
        ids = entry.get("source_document_ids")
        return {
            "markdown": markdown,
            "source_document_ids": [str(i) for i in ids] if isinstance(ids, list) else [],
            "digest_id": meta.get("digest_id"),
        }
    return None


def find_cached(storage_dir: str | Path, fingerprint: str) -> dict[str, Any] | None:
    """Newest persisted digest with the same fingerprint (budget cache)."""
    for meta in list_digests(storage_dir):
        if meta.get("fingerprint") == fingerprint:
            return meta
    return None


def _new_digest_id(storage_dir: str | Path, created_at: str, fingerprint: str) -> str:
    base = "dg-" + (re.sub(r"[^0-9]", "", created_at) or "0")
    digest_id = f"{base}-{fingerprint[:8]}"
    suffix = 1
    while _meta_path(storage_dir, digest_id).exists():
        suffix += 1
        digest_id = f"{base}-{fingerprint[:8]}-{suffix}"
    return digest_id


def save_digest(
    storage_dir: str | Path,
    *,
    range_spec: dict[str, Any],
    material: dict[str, Any],
    markdown: str,
    model: str | None,
    provider: str | None,
    session: str | None,
    usage: dict[str, Any] | None,
    elapsed: float,
    created_at: str | None = None,
    sections: list[dict[str, Any]] | None = None,
    section_fingerprints: dict[str, str] | None = None,
    llm_mode: str = "json",
    llm_calls: int = 1,
) -> dict[str, Any]:
    """Write ``<id>.md`` + ``<id>.meta.json`` and return the meta.

    ``sections`` is the W2 contract (``[{key, title, source_document_ids}]``);
    ``llm_calls`` records the *actual* model calls of this generation, which can
    be 0 when every narrative section was reused from the section cache.
    """
    directory = digests_dir(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    created_at = created_at or datetime.now().isoformat(timespec="seconds")
    fingerprint = material["fingerprint"]
    digest_id = _new_digest_id(storage_dir, created_at, fingerprint)
    documents = material["documents"]
    stats = material.get("stats") or {}
    meta = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR_VERSION,
        "digest_id": digest_id,
        "created_at": created_at,
        "range": range_spec,
        "fingerprint": fingerprint,
        "document_ids": [d["document_id"] for d in documents],
        "documents": [
            {
                "document_id": d["document_id"],
                "title": d["title"],
                "date": d["date"],
                "effective_time": d.get("effective_time"),
            }
            for d in documents
        ],
        "document_count": len(documents),
        "omitted_documents": material.get("omitted", 0),
        "sections": public_sections(sections or []),
        "section_fingerprints": dict(section_fingerprints or {}),
        "section_details": {
            section["key"]: {
                "generated_by": section.get("generated_by"),
                "chars": len(section.get("markdown") or ""),
            }
            for section in (sections or [])
        },
        "stats": stats,
        "budget": material.get("budget") or {},
        "llm_mode": llm_mode,
        "model": model,
        "provider": provider,
        "session": session,
        "usage": usage or {},
        "llm_calls": int(llm_calls),
        "elapsed": round(float(elapsed or 0.0), 3),
        "content_chars": len(markdown or ""),
    }
    _markdown_path(storage_dir, digest_id).write_text(markdown or "", encoding="utf-8")
    _meta_path(storage_dir, digest_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


# ---------------------------------------------------------------------------
# Channel / session resolution + live seam
# ---------------------------------------------------------------------------


def digest_session() -> str:
    """Digests-only gateway session (purpose isolation).

    Priority: ``GRAPH2NOTE_SESSION_DIGEST`` (gateway convention) >
    ``GRAPH2NOTE_DIGEST_SESSION`` (feature env) > :data:`DEFAULT_SESSION`.
    """
    for env in ("GRAPH2NOTE_SESSION_DIGEST", "GRAPH2NOTE_DIGEST_SESSION"):
        value = os.environ.get(env, "").strip()
        if value:
            return value
    return DEFAULT_SESSION


def resolve_digest_channel() -> dict[str, str | None]:
    """Provider + text model for digests (reuses the configured text channels)."""
    from .llm_settings import resolve_channel

    for purpose in ("classify", "ir_text"):
        try:
            channel = resolve_channel(purpose)
        except Exception:
            continue
        model = (channel or {}).get("model")
        if model:
            return {"provider": channel.get("provider"), "model": model, "purpose": purpose}
    from .notes.llm import DEFAULT_TEXT_MODEL

    return {"provider": None, "model": DEFAULT_TEXT_MODEL, "purpose": "classify"}


def _normalize_reply(reply: Any) -> tuple[str, dict, str | None, str | None]:
    if isinstance(reply, str):
        return reply, {}, None, None
    if isinstance(reply, dict):
        text = reply.get("text") or reply.get("content") or ""
        usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
        return text, usage, reply.get("model"), reply.get("provider")
    raise TypeError(f"unsupported digest planner reply type: {type(reply)!r}")


def normalize_usage(usage: Any) -> dict[str, int]:
    """Keep integer token fields; derive ``total_tokens`` when missing."""
    if not isinstance(usage, dict):
        return {}
    out: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"):
        value = usage.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            out[key] = int(value)
        except (TypeError, ValueError):
            continue
    details = usage.get("completion_tokens_details")
    if "reasoning_tokens" not in out and isinstance(details, dict):
        value = details.get("reasoning_tokens")
        if value is not None:
            try:
                out["reasoning_tokens"] = int(value)
            except (TypeError, ValueError):
                pass
    if "total_tokens" not in out and "prompt_tokens" in out and "completion_tokens" in out:
        out["total_tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _demote_headings(text: str) -> str:
    """Push Markdown headings one level down so they nest under a section."""
    lines = []
    for line in (text or "").splitlines():
        match = re.match(r"^(#{1,5})(\s+)(.*)$", line)
        lines.append(f"#{match.group(1)}{match.group(2)}{match.group(3)}" if match else line)
    return "\n".join(lines).strip()


def generate_digest(
    records: Iterable[dict[str, Any]],
    range_spec: dict[str, Any],
    *,
    storage_dir: str | Path,
    planner: Optional[Callable[[str, str], Any]] = None,
    force: bool = False,
    model: str | None = None,
    provider: str | None = None,
    session: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Assemble material, reuse the caches, or fill the narrative sections once.

    ``records`` is the full set of library records (as returned by
    ``get_document``) already filtered by the caller if desired; the pure
    :func:`documents_in_range` does the range filtering.

    Cache ladder:

    1. whole-report fingerprint hit -> **zero** model calls (unchanged from A2);
    2. per-section fingerprint hit -> that narrative section is reused even
       though the whole-report fingerprint changed (W1 bonus);
    3. otherwise one model call fills every still-missing narrative section.

    ``force=True`` bypasses the whole ladder (both caches) and asks again.

    Returns ``{status, generated, cached, llm_calls, range, fingerprint,
    documents, sections, message, digest, markdown}``.  ``status`` is one of
    ``ok`` / ``empty`` / ``error``.
    """
    material = assemble_material(records, range_spec)
    public = public_documents(material["documents"])
    if not material["documents"]:
        return {
            "status": "empty",
            "generated": False,
            "cached": False,
            "llm_calls": 0,
            "range": range_spec,
            "fingerprint": material["fingerprint"],
            "documents": [],
            "sections": [],
            "message": EMPTY_MESSAGE,
            "digest": None,
            "markdown": "",
        }

    fingerprint = material["fingerprint"]
    if not force:
        cached = find_cached(storage_dir, fingerprint)
        if cached is not None:
            stored = load_digest(storage_dir, cached["digest_id"]) or {
                "meta": cached, "markdown": "", "sections": [],
            }
            return {
                "status": "ok",
                "generated": False,
                "cached": True,
                "llm_calls": 0,
                "range": cached.get("range") or range_spec,
                "fingerprint": fingerprint,
                "documents": public,
                "sections": stored.get("sections") or [],
                "message": "命中指纹缓存，未重新调用模型。",
                "digest": cached,
                "markdown": stored.get("markdown") or "",
            }

    fingerprints = material["section_fingerprints"]
    bodies: dict[str, dict[str, Any]] = {}
    modes: dict[str, str] = {}
    if not force:
        for key in NARRATIVE_SECTIONS:
            cached_section = find_cached_section(storage_dir, key, fingerprints.get(key, ""))
            if cached_section is not None:
                bodies[key] = {
                    "markdown": cached_section["markdown"],
                    "source_document_ids": cached_section["source_document_ids"],
                }
                modes[key] = "section-cache"
    missing = [key for key in NARRATIVE_SECTIONS if key not in bodies]

    channel = resolve_digest_channel()
    model = model or channel.get("model")
    provider = provider if provider is not None else channel.get("provider")
    session = session or digest_session()

    def _live(prompt: str, selected_model: str) -> dict[str, Any]:
        from .notes.llm import _gateway_text_usage

        # temperature is omitted: some text models (e.g. kimi-k3) reject an
        # explicit 0 and accept only their own default.  max_tokens is raised so
        # reasoning-heavy models still have room for the summary body.
        return _gateway_text_usage(
            prompt,
            selected_model,
            provider=channel.get("provider"),
            session=session,
            temperature=None,
            max_tokens=MAX_SUMMARY_TOKENS,
        )

    llm_calls = 0
    usage: dict[str, Any] = {}
    reply_model: str | None = None
    reply_provider: str | None = None
    llm_mode = "section-cache"
    started = time.time()
    if missing:
        call = planner or _live
        prompt = build_prompt(
            range_spec,
            material["documents"],
            stats=material["stats"],
            sections=missing,
            pending_documents=material["pending_documents"],
        )
        try:
            raw = call(prompt, model or "")
        except Exception as exc:  # noqa: BLE001 - surfaced as a status, never a crash
            return {
                "status": "error",
                "generated": False,
                "cached": False,
                "llm_calls": 0,
                "range": range_spec,
                "fingerprint": fingerprint,
                "documents": public,
                "sections": [],
                "message": f"模型生成失败：{exc}",
                "digest": None,
                "markdown": "",
            }
        llm_calls = 1
        text, usage, reply_model, reply_provider = _normalize_reply(raw)
        if not (text or "").strip():
            return {
                "status": "error",
                "generated": False,
                "cached": False,
                "llm_calls": 1,
                "range": range_spec,
                "fingerprint": fingerprint,
                "documents": public,
                "sections": [],
                "message": "模型返回了空小结。",
                "digest": None,
                "markdown": "",
            }
        allowed = [str(d["document_id"]) for d in material["documents"]]
        parsed, reply_mode = parse_section_reply(
            text, allowed_ids=allowed, sections=missing
        )
        llm_mode = reply_mode
        if reply_mode == "json":
            for key in missing:
                if key in parsed:
                    bodies[key] = parsed[key]
                    modes[key] = "model"
        else:
            # Unstructured reply: keep the prose (demoted) in the first
            # requested section and attribute it to the material it was shown.
            target = missing[0]
            bodies[target] = {
                "markdown": _demote_headings(text),
                "source_document_ids": list(allowed),
            }
            modes[target] = "text-fallback"
            llm_mode = "text-fallback"
    for key in NARRATIVE_SECTIONS:
        bodies.setdefault(key, {"markdown": "", "source_document_ids": []})
    modes.setdefault(SECTION_TOPICS, "empty")
    # 待整理 always has its deterministic statistics, even without model prose
    modes.setdefault(SECTION_PENDING, "deterministic")

    sections = build_sections(material, bodies, modes)
    markdown = render_digest_markdown(range_spec, sections, material["documents"])
    meta = save_digest(
        storage_dir,
        range_spec=range_spec,
        material=material,
        markdown=markdown,
        model=reply_model or model,
        provider=reply_provider or provider,
        session=session,
        usage=normalize_usage(usage),
        elapsed=time.time() - started if llm_calls else 0.0,
        created_at=created_at,
        sections=sections,
        section_fingerprints=fingerprints,
        llm_mode=llm_mode,
        llm_calls=llm_calls,
    )
    save_section_bodies(
        storage_dir,
        meta["digest_id"],
        bodies=bodies,
        fingerprints=fingerprints,
    )
    return {
        "status": "ok",
        "generated": True,
        "cached": False,
        "llm_calls": llm_calls,
        "range": range_spec,
        "fingerprint": fingerprint,
        "documents": public,
        "sections": public_sections(sections),
        "message": "" if llm_calls else "分节材料未变，未重新调用模型。",
        "digest": meta,
        "markdown": markdown,
    }


__all__ = [
    "SCHEMA_VERSION",
    "GENERATOR_VERSION",
    "SECTION_PROMPT_VERSION",
    "SECTION_OVERVIEW",
    "SECTION_TOPICS",
    "SECTION_HIGHLIGHTS",
    "SECTION_PENDING",
    "SECTION_DEFS",
    "SECTION_TITLES",
    "NARRATIVE_SECTIONS",
    "DIGEST_TITLE",
    "PENDING_STAT_KEYS",
    "MAX_DOCS",
    "TOPIC_FLOOR",
    "MAX_DOC_CHARS",
    "CONTINUITY_SUGGESTED_MAX_DOCS",
    "HIGHLIGHT_LIMIT",
    "HIGHLIGHT_CHARS",
    "MAX_SUMMARY_TOKENS",
    "DEFAULT_SESSION",
    "RANGE_KINDS",
    "EMPTY_MESSAGE",
    "RangeError",
    "apply_material_budget",
    "assemble_material",
    "build_prompt",
    "build_sections",
    "compute_fingerprint",
    "compute_stats",
    "digest_session",
    "digests_dir",
    "document_excerpt",
    "documents_in_range",
    "find_cached",
    "find_cached_section",
    "generate_digest",
    "list_digests",
    "load_digest",
    "load_section_bodies",
    "meta_sections",
    "normalize_range_kind",
    "normalize_usage",
    "parse_section_reply",
    "public_documents",
    "public_sections",
    "render_digest_markdown",
    "render_highlights_body",
    "render_overview_body",
    "render_pending_stats_body",
    "resolve_digest_channel",
    "resolve_range",
    "save_digest",
    "save_section_bodies",
    "section_fingerprints",
    "select_effective_time",
    "select_highlights",
]
