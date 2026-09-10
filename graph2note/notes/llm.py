"""Text-LLM topic classification over the opencode gateway (issue 02).

The classification seam here is the *planner*: a callable
``planner(prompt, model) -> str``.  Tests inject a planner that returns a
recorded golden reply, so nothing below ever talks to the network offline.

The live default (:func:`_gateway_text`) uses the opencode ``chat/completions``
endpoint with a **text** model (no vision needed).  ``muse`` series is
response-endpoint only and is intentionally not used here.
"""

from __future__ import annotations

import json
import os
import re
from typing import Callable, Iterable, Optional

from .classify import (
    ClassificationScheme,
    DEFAULT_MAX_TOPICS,
    SchemeError,
    classify_documents,
)
from ..llm_settings import resolve_channel

# a non-vision chat/completions model (see docs/llm/opencode-go.md §4)
DEFAULT_TEXT_MODEL = "kimi-k3"
DEFAULT_SESSION = "graph2note-classify"
_BASE = "https://opencode.ai/zen/go/v1"


def build_prompt(entries) -> str:
    lines = [
        "你是文档整理助手。对下面每份文档做主题分类，一级分类不超过 8 个，宜粗不宜细。",
        "输出且只输出一个严格 JSON 对象（无 Markdown 围栏、无其他文字）：",
        '{“topics”: [“类别1”, …], “assignments”: {“类别”: [“document_id”, …]}, “summaries”: {“document_id”: “一句话摘要”}}。',
        "每个 document_id 只写入其最相符的类别；每个类别下给出全部该类别文档。",
        "",
        "文档列表：",
    ]
    for e in entries:
        snippet = re.sub(r"\s+", " ", e.markdown)[:200]
        lines.append(f"- {e.document_id} | 标题: {e.title} | 内容: {snippet}")
    return "\n".join(lines)


def parse_scheme_json(text: str) -> ClassificationScheme:
    """Extract the first top-level JSON object from a model reply and parse it."""
    raw = _extract_first_object(text)
    if raw is None:
        raise SchemeError("model reply contained no classification JSON object")
    try:
        return ClassificationScheme.from_dict(json.loads(raw))
    except (ValueError, TypeError) as e:
        raise SchemeError(f"invalid classification JSON: {e}") from e


def _extract_first_object(text: str):
    """Return the text spanning the first balanced ``{ ... }`` block."""
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


def classify_via_llm(
    entries: Iterable,
    *,
    planner: Optional[Callable[[str, str], str]] = None,
    model: str | None = None,
    max_topics: int = DEFAULT_MAX_TOPICS,
) -> ClassificationScheme:
    """Ask a text model to classify ``entries``; schema-validate the result.

    ``planner`` defaults to the live gateway call; pass one that returns a
    recorded golden reply to stay offline.
    """
    entries = list(entries)
    channel = resolve_channel("classify")
    model = model or channel["model"]
    planner = planner or (lambda prompt, selected_model: _gateway_text(
        prompt, selected_model, provider=channel["provider"]
    ))
    prompt = build_prompt(entries)
    raw = planner(prompt, model)
    scheme = parse_scheme_json(raw)
    validated = classify_documents(entries, classifier=lambda _e: scheme,
                                   max_topics=max_topics)
    validated.runtime = {"provider": channel["provider"], "model": model}
    return validated


def _gateway_text(prompt: str, model: str | None = None, *, provider: str | None = None) -> str:
    """Live provider-aware chat/completions call for a text model."""
    from eval.gateway import load_api_key, post_gateway

    channel = resolve_channel("classify")
    model = model or channel["model"]
    provider = provider or channel["provider"]
    key = load_api_key(provider)
    body = post_gateway(
        {
            "model": model,
            "max_tokens": 4096,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        provider=provider,
        api_key=key,
        session=os.environ.get("GRAPH2NOTE_CLASSIFY_SESSION", DEFAULT_SESSION),
        timeout=180,
        user_agent="graph2note-classify/0.2",
    )
    return body["choices"][0]["message"]["content"]
