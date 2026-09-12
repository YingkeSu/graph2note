"""Library-level collection organization (auto-organization issue 02).

Closes the loop **similar notes -> collection (folder)**:

1. deterministic candidate generation (:mod:`graph2note.similarity`, zero LLM);
2. one text-model call over the whole library proposing a
   :class:`~graph2note.notes.classify.ClassificationScheme` (topic -> collection
   name, assignments -> document membership, summaries -> one-line reason);
3. schema validation via :func:`validate_scheme` (a scheme that references an
   unknown document or exceeds ``DEFAULT_MAX_TOPICS`` is rejected before it can
   touch the store);
4. a human confirmation step, then a deterministic, idempotent apply that writes
   machine-owned memberships to ``record['auto_collections']``.

Provenance split (PRD requirement): ``manual_collections`` are user-owned and
are **never** auto-changed or removed; auto memberships are additive and live in
their own bucket.  ``collections`` stays the effective list the rest of the app
already consumes (collection tree, graph edges, Obsidian export folders).

The planner seam is ``planner(prompt, model) -> str | (str, usage)`` exactly like
A1 auto-tagging, so tests inject recorded golden replies and never hit the
network.  Plans are cached under ``<storage>/collection-plan.json`` keyed by a
library fingerprint, so a dry-run and the following ``--yes`` reuse one call.

No API key is ever read, stored, logged or serialised here; the live planner
resolves the key inside the gateway layer at call time only.
"""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable

from .collections import apply_topic_defaults, collection_id_for, ensure_collection
from .notes.classify import (
    DEFAULT_MAX_TOPICS,
    ClassificationScheme,
    SchemeError,
    rule_classify,
    validate_scheme,
)
from .notes.llm import parse_scheme_json
from .similarity import (
    DEFAULT_MAX_CHARS,
    DEFAULT_SHINGLE_SIZE,
    DEFAULT_SIMILARITY_THRESHOLD,
    pairwise_similarity,
)

DEFAULT_MAX_CANDIDATES = 40        # top-N similar pairs handed to the prompt
DEFAULT_MAX_DOCUMENTS = 200        # explicit document cap in the prompt
DEFAULT_DOC_EXCERPT_CHARS = 120    # first-paragraph budget per document
DEFAULT_SUMMARY_LIMIT = 60         # one-line reason length cap
DEFAULT_SESSION = "graph2note-collections"
DEFAULT_TIMEOUT = 180
PLAN_FILENAME = "collection-plan.json"
TELEMETRY_FILENAME = "collection-organize.json"

Planner = Callable[[str, str | None], Any]


# ---------------------------------------------------------------------------
# prompt + planner seam
# ---------------------------------------------------------------------------


def first_paragraph(markdown: Any, limit: int = DEFAULT_DOC_EXCERPT_CHARS) -> str:
    """Return the first non-empty, non-heading Markdown line (truncated)."""

    import re

    text = "" if markdown is None else str(markdown)
    for line in text.splitlines():
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line).strip()
        if line:
            if len(line) > limit:
                line = line[: max(limit - 1, 0)].rstrip() + "…"
            return line
    return ""


def _collection_lines(collections: Iterable[dict[str, Any]]) -> list[str]:
    lines = []
    for item in collections:
        name = str(item.get("name") or item.get("collection_id") or "").strip()
        if not name:
            continue
        count = item.get("document_count")
        lines.append(f"- {name}（{count} 篇）" if count is not None else f"- {name}")
    return lines or ["- （暂无既有集合，可新建）"]


def _candidate_lines(candidates: Iterable[tuple[str, str, float]],
                     max_candidates: int) -> list[str]:
    lines = []
    for document_a, document_b, score in list(candidates)[:max_candidates]:
        lines.append(f"- {document_a} ~ {document_b}（相似度 {score:.3f}）")
    return lines or ["- （没有达到阈值的相似候选对）"]


def build_organize_prompt(
    records: Iterable[dict[str, Any]],
    *,
    collections: Iterable[dict[str, Any]] = (),
    candidates: Iterable[tuple[str, str, float]] = (),
    max_topics: int = DEFAULT_MAX_TOPICS,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    excerpt_chars: int = DEFAULT_DOC_EXCERPT_CHARS,
) -> str:
    """Build the library classification prompt (all limits explicit)."""

    records = list(records)
    lines = [
        "你是笔记库整理助手。请把下面的文档归入主题集合（集合名即导出文件夹名）。",
        "规则：",
        f"1. 一级集合不超过 {max_topics} 个，宜粗不宜细。",
        "2. 优先并入「现有集合」中的集合；只有确实无法归入任何现有集合时才新建。",
        "3. 每篇文档至少归入一个集合；summaries 是给用户看的一句话归类理由。",
        "4. 只输出一个严格 JSON 对象（无 Markdown 围栏、无其他文字）：",
        '{"topics": ["集合名", …], "assignments": {"集合名": ["document_id", …]}, '
        '"summaries": {"document_id": "一句话理由"}}',
        "",
        "现有集合（优先复用同名集合）：",
    ]
    lines.extend(_collection_lines(collections))
    lines.extend([
        "",
        "内容相似候选对（Jaccard 相似度，供参考，不必完全按此归组）：",
    ])
    lines.extend(_candidate_lines(candidates, max_candidates))
    lines.extend(["", "文档列表："])
    for record in records[:max_documents]:
        document_id = record.get("document_id")
        title = record.get("title") or ""
        tags = "、".join(str(tag) for tag in (record.get("tags") or []))
        excerpt = first_paragraph(
            record.get("current_markdown") or record.get("markdown") or "",
            excerpt_chars,
        )
        lines.append(
            f"- {document_id} | 标题: {title} | 标签: {tags or '（无）'} | 首段: {excerpt}"
        )
    if len(records) > max_documents:
        lines.append(f"（其余 {len(records) - max_documents} 篇文档省略）")
    return "\n".join(lines)


def normalize_usage(usage: Any) -> dict[str, Any]:
    """Keep the same four usage fields A1 records (plus reasoning tokens)."""

    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    reasoning = usage.get("reasoning_tokens")
    if reasoning is None and isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": reasoning,
        "total_tokens": usage.get("total_tokens"),
    }


def _normalize_planner_result(result: Any) -> tuple[str, dict[str, Any]]:
    usage: dict[str, Any] = {}
    text: Any = result
    if isinstance(result, tuple) and len(result) == 2:
        text, raw_usage = result
        if isinstance(raw_usage, dict):
            usage = raw_usage
    elif isinstance(result, dict):
        text = result.get("text", result.get("content", ""))
        if isinstance(result.get("usage"), dict):
            usage = result["usage"]
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return text, usage


def rule_scheme(records: Iterable[dict[str, Any]]) -> ClassificationScheme:
    """Offline deterministic fallback classifier (reuses ``rule_classify``)."""

    entries = [
        SimpleNamespace(
            document_id=record.get("document_id"),
            title=record.get("title") or "",
            markdown=record.get("current_markdown") or record.get("markdown") or "",
        )
        for record in records
    ]
    return rule_classify(entries)


def offline_planner(records: Iterable[dict[str, Any]]) -> Planner:
    """Planner that replays the deterministic rule classifier (no LLM)."""

    payload = json.dumps(rule_scheme(records).to_dict(), ensure_ascii=False)

    def _plan(prompt: str, model: str | None = None) -> str:
        return payload

    return _plan


@dataclass
class OrganizeResult:
    """One plan attempt: a validated scheme (or an exception) + usage."""

    scheme: ClassificationScheme | None
    prompt: str = ""
    raw: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    provider: str | None = None
    estimated_tokens: int = 0


def plan_collections(
    records: Iterable[dict[str, Any]],
    *,
    planner: Planner,
    model: str | None = None,
    provider: str | None = None,
    collections: Iterable[dict[str, Any]] = (),
    candidates: Iterable[tuple[str, str, float]] = (),
    max_topics: int = DEFAULT_MAX_TOPICS,
    max_documents: int = DEFAULT_MAX_DOCUMENTS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> OrganizeResult:
    """Ask the planner for a scheme and gate it through ``validate_scheme``.

    Raises :class:`SchemeError` when the reply is not a valid scheme (unknown
    document, unknown topic, over the topic cap, missing summary, …).  The raw
    reply is retained on the result only for debugging; it is never persisted.
    """

    records = list(records)
    prompt = build_organize_prompt(
        records, collections=collections, candidates=candidates,
        max_topics=max_topics, max_documents=max_documents,
        max_candidates=max_candidates,
    )
    text, usage = _normalize_planner_result(planner(prompt, model))
    scheme = parse_scheme_json(text)
    document_ids = [record["document_id"] for record in records]
    validated = validate_scheme(scheme, document_ids, max_topics=max_topics)
    return OrganizeResult(
        scheme=validated,
        prompt=prompt,
        raw=text[:4000],
        usage=normalize_usage(usage),
        model=model,
        provider=provider,
        estimated_tokens=max(len(prompt) // 4, 1),
    )


def live_organize_planner(
    *,
    provider: str | None = None,
    model: str | None = None,
    session: str = DEFAULT_SESSION,
    timeout: float = DEFAULT_TIMEOUT,
) -> Planner:
    """Production planner over the opencode-style gateway (text model)."""

    def _plan(prompt: str, selected_model: str | None) -> tuple[str, dict[str, Any]]:
        from eval.gateway import GatewayError, load_api_key, post_gateway

        from .llm_settings import resolve_channel

        channel = resolve_channel("classify")
        use_provider = provider or channel["provider"]
        use_model = selected_model or model or channel["model"]
        key = load_api_key(use_provider)
        body = post_gateway(
            {
                "model": use_model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": prompt}],
            },
            provider=use_provider,
            api_key=key,
            session=session,
            timeout=timeout,
            user_agent="graph2note-collections/0.1",
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(
                f"归类响应缺少 choices[0].message.content：{exc}"
            ) from exc
        return content, body.get("usage") or {}

    return _plan


# ---------------------------------------------------------------------------
# plan cache
# ---------------------------------------------------------------------------


def _store_root(store: Any) -> Path | None:
    root = getattr(store, "root", None)
    return Path(root) if root else None


def plan_cache_path(store: Any) -> Path | None:
    root = _store_root(store)
    return root / PLAN_FILENAME if root else None


def load_cached_plan(store: Any) -> dict[str, Any] | None:
    path = plan_cache_path(store)
    if path is None or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_cached_plan(store: Any, plan: dict[str, Any]) -> None:
    path = plan_cache_path(store)
    if path is None:
        return
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_records(store: Any) -> list[dict[str, Any]]:
    records = []
    for summary in store.list_documents():
        record = store.get_document(summary["document_id"])
        if record is not None:
            records.append(record)
    records.sort(key=lambda record: record["document_id"])
    return records


def _library_fingerprint(
    records: Iterable[dict[str, Any]], params: dict[str, Any]
) -> str:
    """Hash the library content + plan parameters (never the resulting plan).

    Registry membership is intentionally excluded: the plan creates collections,
    so including them would invalidate the cache immediately after an apply.
    ``--force`` (CLI) / ``force`` (API) regenerates when the user wants a fresh
    look at the current registry.
    """

    digest = hashlib.sha256()
    digest.update(json.dumps(params, sort_keys=True, ensure_ascii=False).encode())
    for record in records:
        digest.update(str(record.get("document_id", "")).encode())
        digest.update(str(record.get("title") or "").encode())
        digest.update((record.get("current_markdown") or "")[:500].encode())
    return digest.hexdigest()[:16]


def build_plan(
    store: Any,
    *,
    planner: Planner | None = None,
    offline: bool = False,
    force: bool = False,
    model: str | None = None,
    provider: str | None = None,
    shingle_size: int = DEFAULT_SHINGLE_SIZE,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_topics: int = DEFAULT_MAX_TOPICS,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    use_cache: bool = True,
) -> tuple[dict[str, Any], bool]:
    """Return ``(plan, from_cache)``; calls the planner at most once per library.

    ``use_cache=False`` neither reads nor writes the plan cache (read-only
    measurement runs), so the planner is always called in that mode.
    """

    params = {
        "shingle_size": int(shingle_size),
        "threshold": float(threshold),
        "max_chars": int(max_chars),
        "max_topics": int(max_topics),
        "max_candidates": int(max_candidates),
    }
    records = _load_records(store)
    fingerprint = _library_fingerprint(records, params)
    candidates = pairwise_similarity(
        [
            {"document_id": r["document_id"], "title": r.get("title") or "",
             "markdown": r.get("current_markdown") or ""}
            for r in records
        ],
        shingle_size=shingle_size, threshold=threshold, max_chars=max_chars,
    )
    cached = load_cached_plan(store) if use_cache else None
    if (cached and not force and cached.get("fingerprint") == fingerprint
            and cached.get("params") == params):
        return cached, True

    if offline:
        planner = offline_planner(records)
        model = model or "rule-classifier"
        provider = provider or "offline"
    elif planner is None:
        planner = live_organize_planner(provider=provider, model=model)
    result = plan_collections(
        records, planner=planner, model=model, provider=provider,
        collections=store.list_collections(), candidates=candidates,
        max_topics=max_topics, max_candidates=max_candidates,
    )
    plan = {
        "version": 1,
        "fingerprint": fingerprint,
        "params": params,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "provider": provider,
        "usage": result.usage,
        "estimated_tokens": result.estimated_tokens,
        "scheme": result.scheme.to_dict() if result.scheme else None,
        "candidates": [list(pair) for pair in candidates],
        "rejected": [],
    }
    if use_cache:
        save_cached_plan(store, plan)
    return plan, False


# ---------------------------------------------------------------------------
# suggestion projection + deterministic apply
# ---------------------------------------------------------------------------


def _manual_documents(records: Iterable[dict[str, Any]]) -> set[str]:
    return {
        record["document_id"]
        for record in records
        if (record.get("manual_collections") or [])
    }


def suggestion_groups(
    store: Any,
    plan: dict[str, Any],
    *,
    records: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Group the plan's assignments by topic, annotated with live status.

    Status per document: ``already`` (membership present), ``confirmation_required``
    (the document also has a manual membership, so the user must confirm),
    ``pending`` (writable as auto), or ``missing`` (unknown id — only possible
    against a stale cache; skipped).
    """

    scheme = plan.get("scheme") or {}
    assignments = scheme.get("assignments") or {}
    summaries = scheme.get("summaries") or {}
    topics = scheme.get("topics") or list(assignments)
    rejected = set(plan.get("rejected") or [])
    records = list(records) if records is not None else _load_records(store)
    by_id = {record["document_id"]: record for record in records}

    groups = []
    for topic in topics:
        documents = []
        for document_id in assignments.get(topic) or []:
            if document_id in rejected:
                continue
            record = by_id.get(document_id)
            if record is None:
                continue
            cid = collection_id_for(topic)
            if cid in (record.get("collections") or []):
                status = "already"
            elif record.get("manual_collections"):
                status = "confirmation_required"
            else:
                status = "pending"
            documents.append({
                "document_id": document_id,
                "title": record.get("title") or document_id,
                "summary": summaries.get(document_id) or "",
                "status": status,
            })
        if not documents:
            continue
        groups.append({
            "topic": topic,
            "collection_id": collection_id_for(topic),
            "document_count": len(documents),
            "documents": documents,
        })
    return groups


def _assignment_decisions(
    records: Iterable[dict[str, Any]],
    plan: dict[str, Any],
    *,
    accept: Iterable[str] | None = None,
    include_manual: bool = True,
) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Pure planning step: ``[(document_id, topic, collection_id)]`` to write.

    Skips rejected/unknown documents, respects the explicit ``accept`` subset and
    leaves manual documents out unless the caller explicitly confirms them.  A
    document already holding the collection is skipped, which is what makes the
    apply idempotent.
    """

    records = list(records)
    by_id = {record["document_id"]: record for record in records}
    manual_ids = _manual_documents(records)
    accepted_ids = set(accept) if accept is not None else None
    rejected_ids = set(plan.get("rejected") or [])
    decisions: list[tuple[str, str, str]] = []
    skipped_manual: list[str] = []
    for topic, document_ids in (plan.get("scheme") or {}).get("assignments", {}).items():
        collection_id = collection_id_for(topic)
        for document_id in document_ids or []:
            if document_id not in by_id or document_id in rejected_ids:
                continue
            if accepted_ids is not None and document_id not in accepted_ids:
                continue
            if collection_id in (by_id[document_id].get("collections") or []):
                continue
            if document_id in manual_ids and not include_manual:
                skipped_manual.append(document_id)
                continue
            decisions.append((document_id, topic, collection_id))
    return decisions, skipped_manual


def project_assignments(
    records: Iterable[dict[str, Any]],
    plan: dict[str, Any],
    *,
    accept: Iterable[str] | None = None,
    include_manual: bool = True,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure, snapshot-able projection of a confirmed plan onto records.

    Returns ``{"records": [...], "changes": [...]}`` without touching any
    store: each record is deep-copied, the collection registry is deep-copied
    (auto collections are registered under their deterministic slug), auto
    memberships are appended and the effective ``collections`` list is
    recomputed.  Running it twice yields identical output.
    """

    records = deepcopy(list(records))
    registry = deepcopy(registry) if registry is not None else {"version": 1, "collections": {}}
    decisions, skipped_manual = _assignment_decisions(
        records, plan, accept=accept, include_manual=include_manual
    )
    by_id = {record["document_id"]: record for record in records}
    added: dict[str, list[tuple[str, str]]] = {}
    for document_id, topic, collection_id in decisions:
        added.setdefault(document_id, []).append((topic, collection_id))
    for document_id, pairs in added.items():
        for topic, _collection_id in pairs:
            ensure_collection(registry, topic)
        record = by_id[document_id]
        auto = list(record.get("auto_collections") or [])
        for _topic, collection_id in pairs:
            if collection_id not in auto:
                auto.append(collection_id)
        record["auto_collections"] = auto
    for record in records:
        apply_topic_defaults(record, registry)
    changes = [
        {
            "document_id": document_id,
            "added": [collection_id for _topic, collection_id in pairs],
            "collections": by_id[document_id]["collections"],
            "auto_collections": by_id[document_id]["auto_collections"],
            "manual_collections": by_id[document_id]["manual_collections"],
        }
        for document_id, pairs in sorted(added.items())
    ]
    return {"records": records, "changes": changes, "skipped_manual": sorted(set(skipped_manual))}


def apply_assignments(
    store: Any,
    plan: dict[str, Any],
    *,
    accept: Iterable[str] | None = None,
    include_manual: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Deterministically write auto memberships for the confirmed documents.

    ``accept`` is the explicit confirmation set (``None`` means "every document
    the plan proposes").  Manual documents are written only when
    ``include_manual`` is set — the caller's explicit confirmation.  Manual
    memberships are never touched; re-applying is idempotent.

    The decision step is the shared pure :func:`_assignment_decisions`; use
    :func:`project_assignments` when a pure snapshot is wanted.
    """

    records = _load_records(store)
    decisions, skipped_manual = _assignment_decisions(
        records, plan, accept=accept, include_manual=include_manual
    )
    applied: list[str] = []
    if not dry_run:
        for document_id, topic, _collection_id in decisions:
            store.add_auto_collections(document_id, [topic])
            applied.append(document_id)
    else:
        applied = [document_id for document_id, _topic, _cid in decisions]
    return {"applied": sorted(set(applied)), "skipped_manual": sorted(set(skipped_manual))}


# ---------------------------------------------------------------------------
# telemetry
# ---------------------------------------------------------------------------


def telemetry_path(store: Any) -> Path | None:
    root = _store_root(store)
    return root / TELEMETRY_FILENAME if root else None


def write_telemetry(store: Any, *, plan: dict[str, Any], applied: int,
                    dry_run: bool) -> dict[str, Any] | None:
    """Persist the last run's provider/model/tokens (no secrets)."""

    path = telemetry_path(store)
    if path is None:
        return None
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "fingerprint": plan.get("fingerprint"),
        "model": plan.get("model"),
        "provider": plan.get("provider"),
        "usage": plan.get("usage") or {},
        "estimated_tokens": plan.get("estimated_tokens"),
        "candidate_count": len(plan.get("candidates") or []),
        "topics": len((plan.get("scheme") or {}).get("topics") or []),
        "applied": int(applied),
        "dry_run": bool(dry_run),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# orchestration used by the CLI + Web API
# ---------------------------------------------------------------------------


def suggestions_payload(store: Any, plan: dict[str, Any], *,
                        from_cache: bool | None = None) -> dict[str, Any]:
    """Project a plan into the UI/API payload (grouped, status-annotated)."""

    records = _load_records(store)
    groups = suggestion_groups(store, plan, records=records)
    # A document may belong to several proposed collections; the budget/confirm
    # counts are per-document, so the dry-run number equals the --yes writes.
    doc_status: dict[str, str] = {}
    for group in groups:
        for doc in group["documents"]:
            document_id = doc["document_id"]
            previous = doc_status.get(document_id)
            if previous is None or (previous != "pending" and doc["status"] == "pending"):
                doc_status[document_id] = doc["status"]
    statuses = list(doc_status.values())
    usage = plan.get("usage") or {}
    return {
        "status": "ok",
        "fingerprint": plan.get("fingerprint"),
        "generated_at": plan.get("generated_at"),
        "model": plan.get("model"),
        "provider": plan.get("provider"),
        "from_cache": bool(from_cache) if from_cache is not None else False,
        "usage": usage,
        "total_tokens": int(usage.get("total_tokens") or 0),
        "estimated_tokens": plan.get("estimated_tokens"),
        "candidate_count": len(plan.get("candidates") or []),
        "topics": (plan.get("scheme") or {}).get("topics") or [],
        "groups": groups,
        "pending_count": sum(1 for s in statuses if s in ("pending", "confirmation_required")),
        "pending_auto_count": statuses.count("pending"),
        "confirmation_required_count": statuses.count("confirmation_required"),
        "already_count": statuses.count("already"),
        "rejected_count": len(plan.get("rejected") or []),
        "rejected": list(plan.get("rejected") or []),
    }


def generate_suggestions(
    store: Any,
    *,
    planner: Planner | None = None,
    offline: bool = False,
    force: bool = False,
    dry_run: bool = True,
    include_manual: bool = True,
    model: str | None = None,
    provider: str | None = None,
    use_cache: bool = True,
    **params: Any,
) -> dict[str, Any]:
    """Build/reuse the plan and (unless dry-run) apply it.

    Returns the same shape as :func:`suggestions_payload` plus ``applied`` /
    ``skipped_manual`` / ``estimated_calls`` / ``calls_made``.
    """

    plan, from_cache = build_plan(
        store, planner=planner, offline=offline, force=force,
        model=model, provider=provider, use_cache=use_cache, **params,
    )
    records = _load_records(store)
    outcome = {"applied": [], "skipped_manual": []}
    if not dry_run:
        outcome = apply_assignments(
            store, plan, accept=None, include_manual=include_manual,
        )
    payload = suggestions_payload(store, plan, from_cache=from_cache)
    payload["dry_run"] = bool(dry_run)
    payload["estimated_calls"] = 0 if from_cache else 1
    payload["calls_made"] = 0 if from_cache else 1
    payload["applied"] = outcome["applied"]
    payload["applied_count"] = len(outcome["applied"])
    payload["skipped_manual"] = outcome["skipped_manual"]
    payload["documents"] = len(records)
    payload["new_collections"] = [
        topic for topic in payload["topics"]
        if collection_id_for(topic) not in {
            item.get("collection_id") for item in store.list_collections()
        }
    ]
    if use_cache:
        write_telemetry(store, plan=plan, applied=len(outcome["applied"]), dry_run=dry_run)
    return payload


def suggestions_for_store(store: Any) -> dict[str, Any]:
    """Return the cached suggestions (or an explicit empty state)."""

    plan = load_cached_plan(store)
    if plan is None:
        return {"status": "none", "groups": [], "pending_count": 0, "rejected": []}
    payload = suggestions_payload(store, plan, from_cache=True)
    return payload


def apply_suggestions(
    store: Any,
    *,
    accept: Iterable[str] | None = None,
    reject: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Confirm an explicit subset of the cached suggestions and write auto memberships.

    ``accept`` is the explicit confirmation set.  A request that omits it
    (``None``) records only the ``reject`` list and writes **no** memberships.
    Unlike :func:`apply_assignments` (where ``None`` means "the whole plan",
    used by the CLI ``--yes`` path), the review API must never silently fall
    back to a full apply: an ``ignore`` action used to do exactly that and also
    appended auto memberships to manually organized documents.  Callers that
    intend to accept documents must send an explicit ``accept`` list (an empty
    list is a valid "accept nothing" confirmation).
    """

    plan = load_cached_plan(store)
    if plan is None:
        return {"status": "none", "applied": [], "groups": [], "pending_count": 0}
    rejected = list(dict.fromkeys(list(plan.get("rejected") or []) + list(reject or [])))
    plan["rejected"] = rejected
    save_cached_plan(store, plan)
    outcome: dict[str, list[str]] = {"applied": [], "skipped_manual": []}
    if accept is not None:
        outcome = apply_assignments(store, plan, accept=accept, include_manual=True)
    write_telemetry(store, plan=plan, applied=len(outcome["applied"]), dry_run=False)
    payload = suggestions_payload(store, plan, from_cache=True)
    payload["applied"] = outcome["applied"]
    payload["applied_count"] = len(outcome["applied"])
    payload["skipped_manual"] = outcome["skipped_manual"]
    return payload


__all__ = [
    "DEFAULT_DOC_EXCERPT_CHARS",
    "DEFAULT_MAX_CANDIDATES",
    "DEFAULT_MAX_DOCUMENTS",
    "DEFAULT_SESSION",
    "OrganizeResult",
    "Planner",
    "apply_assignments",
    "apply_suggestions",
    "build_organize_prompt",
    "build_plan",
    "first_paragraph",
    "generate_suggestions",
    "live_organize_planner",
    "load_cached_plan",
    "normalize_usage",
    "offline_planner",
    "plan_cache_path",
    "plan_collections",
    "project_assignments",
    "rule_scheme",
    "save_cached_plan",
    "suggestion_groups",
    "suggestions_for_store",
    "suggestions_payload",
    "telemetry_path",
    "write_telemetry",
]
