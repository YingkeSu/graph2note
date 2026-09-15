"""Optional, schema-validated LLM enhancement for ``PaperMeta`` (P2).

The deterministic parser in :mod:`graph2note.papers.metadata` is always the
baseline.  This module is an **opt-in** boost:

- a proposal only ever *fills an empty field* — it can never overwrite what the
  deterministic text-layer pass found;
- every proposal must pass :func:`validate_meta_proposal` (``extra="forbid"``,
  type + range checks), otherwise it is dropped entirely;
- a missing key or a transport error degrades to the deterministic result plus
  an honest note — with no ``.env`` key the whole chain still succeeds offline;
- the planner is injectable, so tests never touch the network.

Nothing here is imported on the deterministic path.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .metadata import FieldProvenance, PaperMeta, PaperMetaResult, normalize_doi

__all__ = [
    "MetaProposal",
    "Planner",
    "apply_meta_proposal",
    "build_prompt",
    "enhance_meta",
    "live_planner",
    "parse_meta_reply",
    "validate_meta_proposal",
]

Planner = Callable[[str, Optional[str]], "tuple[str, dict[str, Any]] | str"]

DEFAULT_SESSION = "papers-meta"
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_CHARS = 4000
_PROPOSAL_FIELDS = ("title", "authors", "year", "venue", "doi", "abstract", "keywords")


class MetaProposal(BaseModel):
    """A partial ``PaperMeta`` from a model; strict, all fields optional."""

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = None
    authors: Optional[list[str]] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[list[str]] = None

    @field_validator("year")
    @classmethod
    def _year_range(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return None
        if not (1500 <= int(value) <= 2100):
            raise ValueError("year out of range")
        return int(value)

    @field_validator("title", "venue", "abstract", "doi")
    @classmethod
    def _clean_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("authors", "keywords")
    @classmethod
    def _clean_list(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("expected a list")
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned or None

    @field_validator("doi")
    @classmethod
    def _clean_doi(cls, value: Optional[str]) -> Optional[str]:
        return normalize_doi(value) if value else None


def _extract_first_object(text: str) -> Optional[str]:
    """Return the span of the first balanced ``{ ... }`` JSON object."""

    start = None
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text or ""):
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


def parse_meta_reply(text: str) -> Optional[dict[str, Any]]:
    """Extract the first JSON object from a model reply (no schema check yet)."""

    raw = _extract_first_object(text or "")
    if raw is None:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def validate_meta_proposal(raw: Any) -> Optional[MetaProposal]:
    """Schema-validate a proposal; ``None`` means "drop it, keep baseline"."""

    if raw is None:
        return None
    if isinstance(raw, MetaProposal):
        return raw
    if not isinstance(raw, dict):
        return None
    try:
        return MetaProposal.model_validate(raw)
    except (ValidationError, TypeError, ValueError):
        return None


def build_prompt(
    front_text: str,
    *,
    meta: Optional[PaperMeta] = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> str:
    """Deterministic prompt; the model may only fill missing fields."""

    known = meta or PaperMeta()
    return (
        "你是学术论文元数据抽取助手。仅输出一个 JSON 对象，键为 "
        "title/authors/year/venue/doi/abstract/keywords；缺失则省略或用 null，"
        "不要编造未出现的信息，不要输出解释或 Markdown 代码块。\n"
        f"已确定字段（不要修改）：title={known.title!r}, authors={known.authors!r}, "
        f"year={known.year!r}, venue={known.venue!r}, doi={known.doi!r}。\n"
        "首页文本如下：\n"
        f"{str(front_text or '')[:max_chars]}"
    )


def apply_meta_proposal(
    result: PaperMetaResult,
    proposal: MetaProposal,
    *,
    source: str = "vlm",
) -> tuple[PaperMetaResult, list[str]]:
    """Fill only the empty fields of ``result``; report which were applied."""

    meta = result.meta.model_copy(deep=True)
    provenance = {key: value.model_copy(deep=True) for key, value in result.provenance.items()}
    applied: list[str] = []
    for field in _PROPOSAL_FIELDS:
        proposed = getattr(proposal, field)
        if proposed in (None, "", []):
            continue
        current = getattr(meta, field)
        if current not in (None, "", []):
            continue
        setattr(meta, field, proposed)
        provenance[field] = FieldProvenance(
            source=source,  # type: ignore[arg-type]
            confidence="medium",
            evidence="llm-proposal",
        )
        applied.append(field)
    if applied and result.meta.source == "none":
        meta.source = source  # type: ignore[assignment]
        provenance["source"] = FieldProvenance(
            source=source, confidence="medium", evidence="llm-proposal"  # type: ignore[arg-type]
        )
    notes = list(result.notes)
    notes.append(f"llm-fields:{','.join(applied)}" if applied else "llm-no-new-fields")
    return PaperMetaResult(meta=meta, provenance=provenance, notes=notes), applied


def _normalize_planner_result(result: Any) -> str:
    text: Any = result
    if isinstance(result, tuple) and len(result) == 2:
        text = result[0]
    elif isinstance(result, dict):
        text = result.get("text", result.get("content", ""))
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    return text


def enhance_meta(
    result: PaperMetaResult,
    *,
    planner: Optional[Planner],
    model: Optional[str] = None,
    front_text: str = "",
    max_chars: int = DEFAULT_MAX_CHARS,
    source: str = "vlm",
) -> PaperMetaResult:
    """Run the optional LLM proposal; never raise, never bypass the baseline."""

    if planner is None:
        return result.model_copy(update={"notes": list(result.notes) + ["llm-planner-absent"]})
    prompt = build_prompt(front_text, meta=result.meta, max_chars=max_chars)
    try:
        reply = _normalize_planner_result(planner(prompt, model))
    except Exception as exc:  # noqa: BLE001 - offline/no-key degradation is the point
        return result.model_copy(
            update={"notes": list(result.notes) + [f"llm-enhance-failed:{type(exc).__name__}"]}
        )
    payload = parse_meta_reply(reply)
    proposal = validate_meta_proposal(payload)
    if proposal is None:
        return result.model_copy(
            update={"notes": list(result.notes) + ["llm-proposal-invalid"]}
        )
    enhanced, _applied = apply_meta_proposal(result, proposal, source=source)
    return enhanced


def live_planner(
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    session: str = DEFAULT_SESSION,
    timeout: float = DEFAULT_TIMEOUT,
) -> Planner:
    """Build the production planner over the opencode-style gateway seam."""

    def _plan(prompt: str, selected_model: Optional[str]) -> tuple[str, dict[str, Any]]:
        from eval.gateway import GatewayError, load_api_key, post_gateway

        from ..llm_settings import resolve_channel

        channel = resolve_channel("ir_text")
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
            user_agent="graph2note-papers-meta/0.1",
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(
                f"论文元数据响应缺少 choices[0].message.content：{exc}"
            ) from exc
        return content, body.get("usage") or {}

    return _plan
