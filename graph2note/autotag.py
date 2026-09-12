"""Automatic tag inference from a parsed document (usable-product-iteration A1).

Closes the loop ``parse -> infer tags (vocabulary-first) -> attach to document
-> editor review -> backfill``.  The inference seam is a *planner* callable
``planner(prompt, model) -> str | (str, usage)``; tests inject a planner that
returns a recorded golden reply, so nothing here ever talks to the network
offline (mirrors the knowledge-workspace issue-02 classification seam).

Design notes
------------
* The vocabulary (canonical names + aliases) is always passed into the prompt so
  the model prefers reusing existing tags; whatever it returns is normalized
  through :func:`validate_tag_inference` and persisted through the store's
  ``add_auto_tags`` (which reuses aliases via ``ensure_tag``).
* :func:`after_ingest` is the **single post-ingest hook** every入库 entry wires:
  single-image parse, PDF page commit and (future) R1 repair rerun.  It never
  raises: a failed/illegal inference is recorded as an ``auto_tag`` warning on
  the record and the parse commit still succeeds.
* :func:`backfill` is the存量 budget path: ``dry_run`` reports the pending
  document count and the estimated inference calls, and a real run performs
  exactly that many calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from .tags import TagError, validate_tag_inference

DEFAULT_MAX_CHARS = 4000
DEFAULT_SESSION = "graph2note-autotag"
DEFAULT_TIMEOUT = 120
MAX_PROMPT_TAGS = 80

# A planner returns the model text, optionally paired with its token usage.
Planner = Callable[[str, str | None], Any]


@dataclass
class TagInferenceResult:
    """One inference attempt: validated raw tags (or ``None``) + usage."""

    tags: list[str] | None
    warning: str | None = None
    raw: str = ""
    usage: dict[str, Any] = field(default_factory=dict)


def _vocabulary_lines(vocabulary: dict[str, Any]) -> list[str]:
    tags = vocabulary.get("tags") if isinstance(vocabulary, dict) else None
    if not isinstance(tags, dict):
        return []
    lines: list[str] = []
    for name in sorted(tags, key=str.casefold)[:MAX_PROMPT_TAGS]:
        entry = tags.get(name) or {}
        aliases = entry.get("aliases") if isinstance(entry, dict) else None
        aliases = [str(alias) for alias in (aliases or []) if str(alias).strip()]
        if aliases:
            lines.append(f"- {name}（别名：{'、'.join(aliases)}）")
        else:
            lines.append(f"- {name}")
    return lines


def build_prompt(markdown: str, vocabulary: dict[str, Any], *,
                 max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """Build the tag-inference prompt with an explicit truncation budget."""

    text = markdown or ""
    truncated = len(text) > max_chars
    excerpt = text[:max_chars]
    lines = [
        "你是文档标签整理助手。阅读文档正文，给出 3-8 个可用于检索的细粒度标签。",
        "优先复用「现有词表」中的规范标签或别名；只有确实无法复用时才新增标签。",
        "新增标签用简洁名词短语，不带 # 前缀；不要输出解释、不要 Markdown 围栏。",
        "",
        "现有词表（规范标签 / 别名）：",
    ]
    vocab_lines = _vocabulary_lines(vocabulary)
    lines.extend(vocab_lines or ["- （词表为空，可新增标签）"])
    lines.extend([
        "",
        "输出且只输出一个严格 JSON 对象：",
        '{"tags": ["标签1", "标签2"]}',
        "",
        f"文档正文（{'已截断，' if truncated else ''}最多 {max_chars} 字符）：",
        excerpt,
    ])
    return "\n".join(lines)


def _extract_first_object(text: str) -> str | None:
    """Return the span of the first balanced ``{ ... }`` JSON object."""

    start = None
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if start is None:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if start is not None and depth == 0:
                return text[start:i + 1]
    return None


def parse_tag_reply(text: str) -> list[str] | None:
    """Extract ``{tags: [...]}`` from a model reply and schema-validate it."""

    if not isinstance(text, str):
        return None
    raw = _extract_first_object(text)
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return validate_tag_inference(payload)


def _normalize_planner_result(result: Any) -> tuple[str, dict[str, Any]]:
    """Accept ``str`` / ``(text, usage)`` / ``{"text", "usage"}`` planner output."""

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


def _usage_fields(usage: dict[str, Any]) -> dict[str, Any]:
    details = usage.get("completion_tokens_details") if isinstance(usage, dict) else None
    reasoning = usage.get("reasoning_tokens")
    if reasoning is None and isinstance(details, dict):
        reasoning = details.get("reasoning_tokens")
    return {
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "reasoning_tokens": reasoning,
        "total_tokens": usage.get("total_tokens"),
    }


def infer_tags(
    markdown: str,
    vocabulary: dict[str, Any],
    *,
    planner: Planner,
    model: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> TagInferenceResult:
    """Ask the planner for tags; never raise on an illegal model reply.

    A planner/transport exception is re-raised to the caller only in
    :func:`after_ingest`, which converts it into a recorded warning.  Here we
    keep the pure parsing contract explicit: ``tags is None`` means the reply
    was not a valid ``{tags: [...]}`` object.
    """

    prompt = build_prompt(markdown, vocabulary, max_chars=max_chars)
    text, usage = _normalize_planner_result(planner(prompt, model))
    tags = parse_tag_reply(text)
    warning = None if tags is not None else "模型未返回合法的 {tags: [...]} JSON"
    return TagInferenceResult(
        tags=tags,
        warning=warning,
        raw=text[:2000],
        usage=_usage_fields(usage),
    )


def live_planner(
    *,
    provider: str | None = None,
    model: str | None = None,
    session: str = DEFAULT_SESSION,
    timeout: float = DEFAULT_TIMEOUT,
) -> Planner:
    """Build the production planner over the opencode-style gateway seam."""

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
                "max_tokens": 1024,
                "messages": [{"role": "user", "content": prompt}],
            },
            provider=use_provider,
            api_key=key,
            session=session,
            timeout=timeout,
            user_agent="graph2note-autotag/0.1",
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(f"tags 推断响应缺少 choices[0].message.content：{exc}") from exc
        return content, body.get("usage") or {}

    return _plan


def _record_payload(
    *,
    status: str,
    tags: list[str] | None = None,
    warning: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    inferences: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "tags": list(tags or []),
        "warning": warning,
        "model": model,
        "provider": provider,
        "inferences": list(inferences or []),
    }


def after_ingest(
    store,
    document_id: str,
    markdown: str,
    *,
    inferrer: "TagInferrer | None" = None,
    model: str | None = None,
    provider: str | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Unified post-ingest auto-tag hook; failures never block the parse.

    Callers (single-image parse, PDF page commit, R1 repair rerun) invoke this
    *after* the document is durably committed.  When ``inferrer`` is ``None`` it
    is a no-op (auto-tagging disabled); otherwise exactly one inference call is
    made and the result/warning is persisted on the record's ``auto_tag`` field.
    """

    if inferrer is None:
        return _record_payload(status="disabled")
    pool = inferrer if isinstance(inferrer, TagInferrer) else TagInferrer(planner=inferrer)
    use_model = model or pool.model
    use_provider = provider or pool.provider
    try:
        vocabulary = store.tag_vocabulary()
    except Exception:
        vocabulary = {"version": 1, "tags": {}}
    try:
        result = infer_tags(
            markdown, vocabulary, planner=pool.planner,
            model=use_model, max_chars=pool.max_chars if max_chars == DEFAULT_MAX_CHARS else max_chars,
        )
    except Exception as exc:  # transport/planner failure -> warning, not raise
        payload = _record_payload(
            status="failed", warning=f"自动打标失败：{exc}",
            model=use_model, provider=use_provider,
            inferences=[{"status": "error", "error": str(exc)[:300]}],
        )
        _persist(store, document_id, payload)
        return payload

    inference = {"status": "ok" if result.tags is not None else "invalid", **result.usage}
    if result.tags is None:
        payload = _record_payload(
            status="failed", warning=f"自动打标失败：{result.warning}",
            model=use_model, provider=use_provider, inferences=[inference],
        )
        _persist(store, document_id, payload)
        return payload

    try:
        record = store.add_auto_tags(document_id, {"tags": result.tags})
    except (TagError, TypeError, ValueError) as exc:
        payload = _record_payload(
            status="failed", warning=f"自动打标入库失败：{exc}",
            model=use_model, provider=use_provider, inferences=[inference],
        )
        _persist(store, document_id, payload)
        return payload

    payload = _record_payload(
        status="ok", tags=(record or {}).get("tags") or [],
        model=use_model, provider=use_provider, inferences=[inference],
    )
    _persist(store, document_id, payload)
    return payload


def _persist(store, document_id: str, payload: dict[str, Any]) -> None:
    try:
        store.set_auto_tag_meta(document_id, payload)
    except Exception:
        # Telemetry persistence is best-effort; the tags themselves are stored
        # by add_auto_tags, so a metadata write failure must not raise either.
        pass


@dataclass
class TagInferrer:
    """Bundled planner + model/provider/max_chars seam for callers."""

    planner: Planner
    model: str | None = None
    provider: str | None = None
    max_chars: int = DEFAULT_MAX_CHARS


def pending_documents(store, *, limit: int | None = None) -> list[dict]:
    """Existing documents that never completed an auto-tag inference.

    A document counts as pending when its ``auto_tag`` status is not ``ok`` and
    it has non-empty Markdown (empty pages have nothing to label).  The result
    is deterministic and is the basis of the dry-run budget.
    """

    pending: list[dict] = []
    for summary in store.list_documents():
        record = store.get_document(summary["document_id"])
        if not record:
            continue
        if (record.get("auto_tag") or {}).get("status") == "ok":
            continue
        if not (record.get("current_markdown") or "").strip():
            continue
        pending.append(record)
    if limit is not None and limit >= 0:
        pending = pending[:limit]
    return pending


def backfill(
    store,
    *,
    inferrer: "TagInferrer | None" = None,
    dry_run: bool = True,
    limit: int | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> dict[str, Any]:
    """Backfill auto tags for existing documents under an explicit budget.

    ``dry_run`` reports ``pending`` (documents) and ``estimated_calls`` (one
    inference per pending document) without calling the model.  A real run
    performs exactly ``estimated_calls`` inferences, so the reported budget and
    the observed call count match.
    """

    documents = pending_documents(store, limit=limit)
    report: dict[str, Any] = {
        "dry_run": bool(dry_run),
        "pending": len(documents),
        "estimated_calls": len(documents),
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "total_tokens": 0,
        "documents": [],
        "budget_exhausted": False,
    }
    if dry_run or inferrer is None:
        return report

    for record in documents:
        document_id = record["document_id"]
        before = store.get_document(document_id) or {}
        result = after_ingest(
            store, document_id, record.get("current_markdown") or "",
            inferrer=inferrer, max_chars=max_chars,
        )
        report["processed"] += 1
        if result.get("status") == "ok":
            report["succeeded"] += 1
        else:
            report["failed"] += 1
        for inference in result.get("inferences") or []:
            report["total_tokens"] += int(inference.get("total_tokens") or 0)
        report["documents"].append({
            "document_id": document_id,
            "title": record.get("title") or before.get("title"),
            "status": result.get("status"),
            "tags": result.get("tags") or [],
            "warning": result.get("warning"),
        })
    return report


__all__ = [
    "DEFAULT_MAX_CHARS",
    "DEFAULT_SESSION",
    "Planner",
    "TagInferenceResult",
    "TagInferrer",
    "after_ingest",
    "backfill",
    "build_prompt",
    "infer_tags",
    "live_planner",
    "parse_tag_reply",
    "pending_documents",
]
