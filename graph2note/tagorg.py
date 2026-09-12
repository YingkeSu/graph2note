"""LLM-proposed tag governance: synonym merges + coarse theme groups.

Upgrades tag governance from 「逐个手工合并」 to the closed loop

    LLM 推断治理方案 -> schema/引用完整性校验 -> 人确认 -> 确定性应用

This mirrors :mod:`graph2note.autotag` (the A1 auto-tagging module): the model
seam is a *planner* callable ``planner(prompt, model) -> str | (str, usage)``;
tests inject a recorded golden reply so nothing here talks to the network
offline.  The plan is a strict pydantic structure; illegal output (references a
tag that is not in the vocabulary, or a merge cycle ``A -> B`` + ``B -> A``) is
rejected as a whole, never partially applied.

The deterministic application layer :func:`apply_governance_plan` is a pure
function over ``(vocabulary, records, plan, accepted)``:

* merges go through the existing ``tags.merge_vocabulary_tags`` (aliases and
  document memberships follow);
* accepted theme groups are written into vocabulary **schema v2** (top-level
  ``groups``); a tag belongs to at most one group (validated before apply);
* the report is JSON-serializable and its side effects are idempotent — a second
  apply of the same plan skips already-merged sources instead of double-merging.

Nothing here writes files; persistence (vocabulary + records + telemetry) is the
caller's job (CLI / webapp) and keeps this module testable offline.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, Field, ValidationError

from .autotag import _extract_first_object, _normalize_planner_result, _usage_fields
from .tags import (
    TagError,
    merge_vocabulary_tags,
    normalize_tag,
    resolve_tag,
    vocabulary_entries,
)

DEFAULT_SESSION = "graph2note-tagorg"
DEFAULT_TIMEOUT = 120
MAX_OUTPUT_TOKENS = 4096
MAX_PROMPT_TAGS = 400
MAX_GROUPS = 8
# Rough token estimate for the dry-run budget report.  The vocabulary is mostly
# CJK labels, so characters and tokens are close to 1:1; we still round up.
CHARS_PER_TOKEN = 1.5

Planner = Callable[[str, str | None], Any]


class TagGovernanceError(ValueError):
    """Raised when a proposed governance plan violates the contract."""


class TagMergeSuggestion(BaseModel):
    source: str
    target: str
    reason: str = ""


class TagGroupSuggestion(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)


class TagGovernancePlan(BaseModel):
    """A machine-validated governance plan (canonical names after validation)."""

    merges: list[TagMergeSuggestion] = Field(default_factory=list)
    groups: list[TagGroupSuggestion] = Field(default_factory=list)


@dataclass
class GovernanceInferenceResult:
    """One inference attempt: validated plan (or ``None``) + usage + prompt."""

    plan: TagGovernancePlan | None
    warning: str | None = None
    raw: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------


def _vocabulary_lines(entries: list[dict[str, Any]]) -> list[str]:
    ordered = sorted(
        entries,
        key=lambda item: (-int(item.get("count") or 0), str(item.get("tag") or "").casefold()),
    )
    lines: list[str] = []
    for entry in ordered[:MAX_PROMPT_TAGS]:
        name = entry.get("tag")
        if not name:
            continue
        count = int(entry.get("count") or 0)
        aliases = [str(alias) for alias in (entry.get("aliases") or []) if str(alias).strip()]
        suffix = f"（别名：{'、'.join(aliases)}）" if aliases else ""
        lines.append(f"- {name}{suffix} ×{count}")
    return lines


def build_prompt(vocabulary: dict[str, Any], counts: dict[str, int] | None = None) -> str:
    """Build the governance prompt from the full canonical vocabulary."""

    entries = vocabulary_entries(vocabulary, counts or {})
    lines = [
        "你是标签词表治理助手。审阅整个标签词表，产出一份治理方案：",
        "1) merges：把同义/近义/大小写或中英混用的标签合并。source 是被合并掉的标签，",
        "   target 是保留的规范标签；target 必须也是词表中已存在的标签（不要新建）。",
        "2) groups：把全部标签归入不超过 8 个一级主题分组，宜粗不宜细；",
        "   组名优先复用词表中的高频标签；一个标签最多属于一个分组；",
        "   每个分组至少包含 2 个标签，能合并的标签不要再放进分组。",
        "禁止成环：不能同时给出 A -> B 与 B -> A。",
        "不要输出解释、不要 Markdown 围栏。",
        "",
        "输出且只输出一个严格 JSON 对象：",
        '{"merges": [{"source": "标签A", "target": "标签B", "reason": "同义"}],',
        ' "groups": [{"name": "主题名", "tags": ["标签1", "标签2"]}]}',
        "",
        "标签词表（规范标签 / 别名 ×文档数）：",
    ]
    vocab_lines = _vocabulary_lines(entries)
    lines.extend(vocab_lines or ["- （词表为空，无需治理）"])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _resolve_or_error(vocabulary: dict[str, Any], value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TagGovernanceError(f"{field_name} 不能为空")
    try:
        return resolve_tag(vocabulary, value)
    except TagError as exc:
        raise TagGovernanceError(f"引用不存在的标签（{field_name}）：{value}") from exc


def _detect_cycle(edges: dict[str, str]) -> list[str] | None:
    """Return one cycle path (``[a, b, a]``) when ``edges`` is cyclic."""

    color: dict[str, int] = {}

    def visit(node: str, stack: list[str]) -> list[str] | None:
        color[node] = 1
        stack.append(node)
        nxt = edges.get(node)
        if nxt is not None and nxt in edges:
            if color.get(nxt) == 1:
                index = stack.index(nxt)
                return stack[index:] + [nxt]
            if color.get(nxt) != 2:
                found = visit(nxt, stack)
                if found:
                    return found
        stack.pop()
        color[node] = 2
        return None

    for node in list(edges):
        if color.get(node) != 2:
            found = visit(node, [])
            if found:
                return found
    return None


def validate_governance_plan(raw: Any, vocabulary: dict[str, Any]) -> TagGovernancePlan:
    """Validate a raw model payload against the vocabulary and canonicalize it.

    Raises :class:`TagGovernanceError` when the whole plan must be rejected:
    a merge references a tag absent from the vocabulary, merges form a cycle,
    the same tag is merged twice, a group references an absent tag, a tag sits
    in two groups, or there are more than :data:`MAX_GROUPS` groups.
    """

    if isinstance(raw, TagGovernancePlan):
        payload = raw
    else:
        try:
            payload = TagGovernancePlan.model_validate(raw)
        except (ValidationError, TypeError, ValueError) as exc:
            raise TagGovernanceError(f"治理方案结构不合法：{exc}") from exc

    # --- merges: reference integrity, no duplicate source, no cycle ----------
    edges: dict[str, str] = {}
    merges: list[TagMergeSuggestion] = []
    for item in payload.merges:
        source = _resolve_or_error(vocabulary, item.source, field_name="merge.source")
        target = _resolve_or_error(vocabulary, item.target, field_name="merge.target")
        if source == target:
            # A self-merge is redundant, not harmful; drop it silently.
            continue
        if source in edges:
            raise TagGovernanceError(f"同一标签被建议多次合并：{source}")
        edges[source] = target
        merges.append(TagMergeSuggestion(
            source=source, target=target, reason=str(item.reason or "").strip(),
        ))
    cycle = _detect_cycle(edges)
    if cycle:
        raise TagGovernanceError("合并建议成环：" + " → ".join(cycle))

    # --- groups: <= MAX_GROUPS, valid names, resolvable members, one group ---
    if len(payload.groups) > MAX_GROUPS:
        raise TagGovernanceError(
            f"主题分组超过 {MAX_GROUPS} 个一级类目（收到 {len(payload.groups)} 个）"
        )
    groups: list[TagGroupSuggestion] = []
    seen_names: set[str] = set()
    seen_tags: set[str] = set()
    for item in payload.groups:
        try:
            name = normalize_tag(item.name)
        except TagError as exc:
            raise TagGovernanceError(f"主题分组名不合法：{item.name}") from exc
        if name in seen_names:
            raise TagGovernanceError(f"主题分组名重复：{name}")
        seen_names.add(name)
        members: list[str] = []
        for tag in item.tags:
            canonical = _resolve_or_error(vocabulary, tag, field_name=f"group[{name}]")
            if canonical in seen_tags:
                raise TagGovernanceError(f"标签重复归属多个主题组：{canonical}")
            seen_tags.add(canonical)
            if canonical not in members:
                members.append(canonical)
        if not members:
            raise TagGovernanceError(f"主题分组没有标签：{name}")
        groups.append(TagGroupSuggestion(name=name, tags=members))

    return TagGovernancePlan(merges=merges, groups=groups)


def parse_plan_reply(text: str, vocabulary: dict[str, Any]) -> tuple[TagGovernancePlan | None, str | None]:
    """Extract ``{merges, groups}`` from a model reply and validate it."""

    if not isinstance(text, str):
        return None, "模型未返回治理方案 JSON"
    raw = _extract_first_object(text)
    if raw is None:
        return None, "模型未返回合法的 JSON 对象"
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None, "模型返回的 JSON 无法解析"
    try:
        return validate_governance_plan(payload, vocabulary), None
    except TagGovernanceError as exc:
        return None, str(exc)


# ---------------------------------------------------------------------------
# Inference (planner seam)
# ---------------------------------------------------------------------------


def infer_governance(
    vocabulary: dict[str, Any],
    counts: dict[str, int] | None = None,
    *,
    planner: Planner,
    model: str | None = None,
) -> GovernanceInferenceResult:
    """Ask the planner for a governance plan; never raise on an illegal reply."""

    prompt = build_prompt(vocabulary, counts)
    text, usage = _normalize_planner_result(planner(prompt, model))
    plan, warning = parse_plan_reply(text, vocabulary)
    return GovernanceInferenceResult(
        plan=plan,
        warning=warning,
        raw=text[:4000],
        usage=_usage_fields(usage),
        prompt=prompt,
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
                "max_tokens": MAX_OUTPUT_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            provider=use_provider,
            api_key=key,
            session=session,
            timeout=timeout,
            user_agent="graph2note-tagorg/0.1",
        )
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(f"治理方案响应缺少 choices[0].message.content：{exc}") from exc
        return content, body.get("usage") or {}

    return _plan


def estimate_budget(prompt: str, *, calls: int = 1) -> dict[str, Any]:
    """Deterministic dry-run budget for one governance inference."""

    chars = len(prompt or "")
    prompt_tokens = max(1, math.ceil(chars / CHARS_PER_TOKEN))
    return {
        "calls": calls,
        "prompt_chars": chars,
        "estimated_prompt_tokens": prompt_tokens,
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "estimated_total_tokens": prompt_tokens + MAX_OUTPUT_TOKENS,
    }


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------


def plan_summary(plan: TagGovernancePlan, counts: dict[str, int] | None = None) -> dict[str, Any]:
    """Enrich a plan with per-label document counts for the CLI/API payload."""

    counts = counts or {}
    return {
        "merges": [
            {
                "source": merge.source,
                "target": merge.target,
                "reason": merge.reason,
                "source_count": int(counts.get(merge.source, 0)),
                "target_count": int(counts.get(merge.target, 0)),
            }
            for merge in plan.merges
        ],
        "groups": [
            {
                "name": group.name,
                "size": len(group.tags),
                "tags": [
                    {"tag": tag, "count": int(counts.get(tag, 0))} for tag in group.tags
                ],
            }
            for group in plan.groups
        ],
        "merge_count": len(plan.merges),
        "group_count": len(plan.groups),
    }


def vocabulary_fingerprint(vocabulary: dict[str, Any]) -> str:
    """Stable hash of canonical labels + aliases + groups (staleness check)."""

    tags = vocabulary.get("tags") if isinstance(vocabulary, dict) else {}
    groups = vocabulary.get("groups") if isinstance(vocabulary, dict) else {}
    payload = {
        "tags": {
            str(name): sorted(str(alias) for alias in ((details or {}).get("aliases") or []))
            for name, details in sorted((tags or {}).items())
        },
        "groups": {
            str(name): sorted(str(tag) for tag in ((details or {}).get("tags") or []))
            for name, details in sorted((groups or {}).items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


# ---------------------------------------------------------------------------
# Deterministic apply
# ---------------------------------------------------------------------------

def _accepted_sets(accepted: Any, plan: TagGovernancePlan) -> tuple[set[str], set[str] | None]:
    """Normalize the ``accepted`` selection into (merge sources, group names)."""

    if accepted is None:
        return {merge.source for merge in plan.merges}, None
    if not isinstance(accepted, dict):
        raise TagGovernanceError("accepted 必须是对象")
    raw_merges = accepted.get("merges")
    sources: set[str] = set()
    if raw_merges is None:
        sources = {merge.source for merge in plan.merges}
    else:
        for item in raw_merges:
            if isinstance(item, str):
                sources.add(item)
            elif isinstance(item, dict) and item.get("source"):
                sources.add(str(item["source"]))
    raw_groups = accepted.get("groups")
    if raw_groups is None:
        return sources, None
    return sources, {str(name) for name in raw_groups}


def ensure_accepted_resolvable(
    vocabulary: dict[str, Any], plan: TagGovernancePlan, accepted: Any = None,
) -> None:
    """Raise when an accepted merge can no longer resolve (concurrent rename)."""

    sources, _ = _accepted_sets(accepted, plan)
    for merge in plan.merges:
        if merge.source not in sources:
            continue
        try:
            resolve_tag(vocabulary, merge.source)
            resolve_tag(vocabulary, merge.target)
        except TagError as exc:
            raise TagGovernanceError(
                f"标签已被并发改名或删除，无法应用：{merge.source} → {merge.target}"
            ) from exc


def _ordered_merges(merges: list[TagMergeSuggestion]) -> list[TagMergeSuggestion]:
    """Sink-first order so ``A -> B`` + ``B -> C`` both land on ``C``."""

    pending = list(merges)
    ordered: list[TagMergeSuggestion] = []
    while pending:
        sources = {merge.source for merge in pending}
        ready = [merge for merge in pending if merge.target not in sources]
        if not ready:
            # A cycle would have been rejected at validation; do not spin.
            ordered.extend(pending)
            break
        for merge in ready:
            pending.remove(merge)
            ordered.append(merge)
    return ordered


def apply_governance_plan(
    vocabulary: dict[str, Any],
    records: list[dict[str, Any]],
    plan: Any,
    accepted: Any = None,
) -> dict[str, Any]:
    """Deterministically apply an accepted subset of ``plan`` in place.

    ``vocabulary`` and each record in ``records`` are mutated; the returned
    report is JSON-serializable.  Merges reuse ``merge_vocabulary_tags`` (so
    aliases and document memberships stay consistent); group tags are resolved
    again *after* the merges, so a merged label follows its canonical target.
    A second application of the same plan is a no-op (merged sources no longer
    resolve and are reported as skipped).
    """

    if not isinstance(plan, TagGovernancePlan):
        plan = TagGovernancePlan.model_validate(plan)
    sources, accepted_groups = _accepted_sets(accepted, plan)

    labels_before = len(vocabulary.get("tags") or {})
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for merge in _ordered_merges(plan.merges):
        if merge.source not in sources:
            skipped.append({"source": merge.source, "target": merge.target, "reason": "未接受"})
            continue
        documents = sum(
            1 for record in records if merge.source in (record.get("tags") or [])
        )
        try:
            source_name, target_name, changed = merge_vocabulary_tags(
                vocabulary, records, merge.source, merge.target,
            )
        except TagError as exc:
            skipped.append({
                "source": merge.source, "target": merge.target, "reason": str(exc),
            })
            continue
        if source_name == target_name or not changed:
            # Already merged (idempotent re-apply) or a redundant alias-of-target.
            skipped.append({
                "source": merge.source, "target": merge.target,
                "reason": "已应用或无需合并",
            })
            continue
        applied.append({
            "source": source_name,
            "target": target_name,
            "reason": merge.reason,
            "documents": documents,
            "changed": bool(changed),
        })

    group_out: dict[str, dict[str, list[str]]] = {}
    groups_report: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for group in plan.groups:
        if accepted_groups is not None and group.name not in accepted_groups:
            continue
        members: list[str] = []
        group_skipped: list[str] = []
        for tag in group.tags:
            try:
                canonical = resolve_tag(vocabulary, tag)
            except TagError:
                group_skipped.append(tag)
                continue
            if canonical in assigned:
                group_skipped.append(tag)
                continue
            assigned.add(canonical)
            members.append(canonical)
        if not members:
            continue
        group_out[group.name] = {"tags": members}
        groups_report.append({"name": group.name, "tags": members, "skipped": group_skipped})

    vocabulary["version"] = 2
    vocabulary["groups"] = group_out

    labels_after = len(vocabulary.get("tags") or {})
    return {
        "merges": applied,
        "skipped_merges": skipped,
        "groups": groups_report,
        "labels_before": labels_before,
        "labels_after": labels_after,
        "merged": len(applied),
        "changed": bool(applied) or labels_before != labels_after,
    }


# ---------------------------------------------------------------------------
# Telemetry log (token usage of every inference)
# ---------------------------------------------------------------------------


def governance_log_path(store) -> Any:
    from pathlib import Path

    root = getattr(store, "root", None)
    if root is None:
        return None
    return Path(root) / "tag-governance.json"


def load_governance_log(store) -> dict[str, Any]:
    path = governance_log_path(store)
    if path is None or not path.is_file():
        return {"version": 1, "events": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "events": []}
    if not isinstance(data, dict):
        return {"version": 1, "events": []}
    data.setdefault("version", 1)
    if not isinstance(data.get("events"), list):
        data["events"] = []
    return data


def record_governance_event(store, event: dict[str, Any]) -> None:
    """Append one inference/apply event (best effort; never raises)."""

    path = governance_log_path(store)
    if path is None:
        return
    try:
        data = load_governance_log(store)
        safe = copy.deepcopy(event)
        data["events"].append(safe)
        data["events"] = data["events"][-200:]
        data["last_event"] = safe
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        # Telemetry must never block the governance run.
        pass


__all__ = [
    "DEFAULT_SESSION",
    "MAX_GROUPS",
    "MAX_OUTPUT_TOKENS",
    "GovernanceInferenceResult",
    "Planner",
    "TagGovernanceError",
    "TagGovernancePlan",
    "TagGroupSuggestion",
    "TagMergeSuggestion",
    "apply_governance_plan",
    "build_prompt",
    "ensure_accepted_resolvable",
    "estimate_budget",
    "governance_log_path",
    "infer_governance",
    "live_planner",
    "load_governance_log",
    "parse_plan_reply",
    "plan_summary",
    "record_governance_event",
    "validate_governance_plan",
    "vocabulary_fingerprint",
]
