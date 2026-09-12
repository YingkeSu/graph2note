"""Weekly digest — periodic summaries over a time-ranged slice of the library.

This is issue A2 of the ``usable-product-iteration`` round.  Given a date range
(本周 / 上周 / 自定义), every library document whose **effective time** falls in
the range is assembled into a deterministic material bundle and summarized into
one Markdown note by a single **text** LLM call.  It is an on-demand, repeatable
and traceable generation — never a scheduled job.

Design guarantees (see the issue's acceptance criteria):

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

# ---------------------------------------------------------------------------
# Explicit bounds / constants
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1
GENERATOR_VERSION = "digest-1"

# Maximum documents fed to one digest and per-document content budget.
MAX_DOCS = 60
MAX_DOC_CHARS = 2000
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
    """SHA-256 over (range bounds, document ids, versions, content hashes)."""
    payload = {
        "schema": SCHEMA_VERSION,
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


def assemble_material(
    records: Iterable[dict[str, Any]],
    range_spec: dict[str, Any],
) -> dict[str, Any]:
    """Deterministic material bundle: sorted docs + fingerprint + prompt."""
    by_id: dict[str, dict[str, Any]] = {}
    for record in records or []:
        if isinstance(record, dict) and record.get("document_id"):
            by_id.setdefault(str(record["document_id"]), record)
    entries = documents_in_range(records, range_spec)

    omitted = 0
    if len(entries) > MAX_DOCS:
        omitted = len(entries) - MAX_DOCS
        entries = entries[-MAX_DOCS:]

    documents: list[dict[str, Any]] = []
    for entry in entries:
        record = by_id.get(entry["document_id"], {})
        content = _document_content(record)
        documents.append({
            **entry,
            "version_id": _document_version(record),
            "content": _truncate(content),
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "truncated": len((content or "").strip()) > MAX_DOC_CHARS,
        })

    fingerprint = compute_fingerprint(range_spec, documents)
    return {
        "range": range_spec,
        "documents": documents,
        "fingerprint": fingerprint,
        "omitted": omitted,
        "prompt": build_prompt(range_spec, documents),
    }


def build_prompt(range_spec: dict[str, Any], documents: list[dict[str, Any]]) -> str:
    lines = [
        "你是文档整理助手。请根据下面的材料写一份 Markdown 每周小结。",
        "要求：",
        "1. 说明这段时间里写了什么、围绕哪些主题、有哪些进展。",
        "2. 只依据材料内容，不要编造材料中没有的信息。",
        "3. 使用与材料一致的语言（以中文为主），用 Markdown 标题和列表组织。",
        "4. 不要输出资料来源清单，系统会自动附在末尾。",
        "",
        f"时间范围：{range_spec.get('label') or range_spec.get('from')}",
        "",
        "材料：",
    ]
    for doc in documents:
        lines.append(
            f'<document id="{doc["document_id"]}" date="{doc["date"]}">'
        )
        lines.append(f'标题：{doc["title"]}')
        if doc.get("tags"):
            lines.append("标签：" + "、".join(doc["tags"]))
        if doc.get("topics"):
            lines.append("主题：" + "、".join(doc["topics"]))
        lines.append("内容：")
        lines.append(doc.get("content") or "（无内容）")
        lines.append("</document>")
    return "\n".join(lines)


_PUBLIC_DOC_FIELDS = (
    "document_id", "title", "date", "effective_time", "tags", "topics", "truncated",
)


def public_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the assembled content from API-facing source entries."""
    return [
        {key: doc.get(key) for key in _PUBLIC_DOC_FIELDS if key in doc}
        for doc in documents
    ]


def render_digest_markdown(text: str, documents: list[dict[str, Any]]) -> str:
    """Append the deterministic source list (title + linked document id)."""
    body = (text or "").strip()
    lines = [body, "", "---", "", "## 来源", ""]
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


def load_digest(storage_dir: str | Path, digest_id: str) -> dict[str, Any] | None:
    """Return ``{meta, markdown}`` for one persisted digest, or ``None``."""
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
    return {"meta": meta, "markdown": markdown}


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
) -> dict[str, Any]:
    """Write ``<id>.md`` + ``<id>.meta.json`` and return the meta."""
    directory = digests_dir(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    created_at = created_at or datetime.now().isoformat(timespec="seconds")
    fingerprint = material["fingerprint"]
    digest_id = _new_digest_id(storage_dir, created_at, fingerprint)
    documents = material["documents"]
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
        "model": model,
        "provider": provider,
        "session": session,
        "usage": usage or {},
        "llm_calls": 1,
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
    """Assemble material, reuse the fingerprint cache, or call the text model once.

    ``records`` is the full set of library records (as returned by
    ``get_document``) already filtered by the caller if desired; the pure
    :func:`documents_in_range` does the range filtering.

    Returns ``{status, generated, cached, llm_calls, range, fingerprint,
    documents, message, digest, markdown}``.  ``status`` is one of
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
            "message": EMPTY_MESSAGE,
            "digest": None,
            "markdown": "",
        }

    fingerprint = material["fingerprint"]
    if not force:
        cached = find_cached(storage_dir, fingerprint)
        if cached is not None:
            stored = load_digest(storage_dir, cached["digest_id"]) or {"meta": cached, "markdown": ""}
            return {
                "status": "ok",
                "generated": False,
                "cached": True,
                "llm_calls": 0,
                "range": cached.get("range") or range_spec,
                "fingerprint": fingerprint,
                "documents": public,
                "message": "命中指纹缓存，未重新调用模型。",
                "digest": cached,
                "markdown": stored.get("markdown") or "",
            }

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

    call = planner or _live
    started = time.time()
    try:
        raw = call(material["prompt"], model or "")
    except Exception as exc:  # noqa: BLE001 - surfaced as a status, never a crash
        return {
            "status": "error",
            "generated": False,
            "cached": False,
            "llm_calls": 0,
            "range": range_spec,
            "fingerprint": fingerprint,
            "documents": public,
            "message": f"模型生成失败：{exc}",
            "digest": None,
            "markdown": "",
        }

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
            "message": "模型返回了空小结。",
            "digest": None,
            "markdown": "",
        }

    markdown = render_digest_markdown(text, material["documents"])
    meta = save_digest(
        storage_dir,
        range_spec=range_spec,
        material=material,
        markdown=markdown,
        model=reply_model or model,
        provider=reply_provider or provider,
        session=session,
        usage=normalize_usage(usage),
        elapsed=time.time() - started,
        created_at=created_at,
    )
    return {
        "status": "ok",
        "generated": True,
        "cached": False,
        "llm_calls": 1,
        "range": range_spec,
        "fingerprint": fingerprint,
        "documents": public,
        "message": "",
        "digest": meta,
        "markdown": markdown,
    }


__all__ = [
    "SCHEMA_VERSION",
    "GENERATOR_VERSION",
    "MAX_DOCS",
    "MAX_DOC_CHARS",
    "MAX_SUMMARY_TOKENS",
    "DEFAULT_SESSION",
    "RANGE_KINDS",
    "EMPTY_MESSAGE",
    "RangeError",
    "assemble_material",
    "build_prompt",
    "compute_fingerprint",
    "digest_session",
    "digests_dir",
    "documents_in_range",
    "find_cached",
    "generate_digest",
    "list_digests",
    "load_digest",
    "normalize_range_kind",
    "normalize_usage",
    "public_documents",
    "render_digest_markdown",
    "resolve_digest_channel",
    "resolve_range",
    "save_digest",
    "select_effective_time",
]
