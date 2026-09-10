"""Canonical parse telemetry and deterministic Dashboard aggregations.

This module is intentionally independent from the parser and storage backends.
It accepts the timing shapes already produced by older versions, normalizes
missing values to ``None``, and aggregates only local data.  A cache hit is a
real telemetry event, but its copied historical token usage is never charged
or counted a second time.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


TELEMETRY_SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_CURRENCY = "USD"


def _text(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value >= 0 else None


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(value, 4) if value >= 0 else None


def _first_number(sources: Iterable[dict[str, Any]], key: str) -> int | None:
    for source in sources:
        if key in source:
            value = _int(source.get(key))
            if value is not None:
                return value
    return None


def _sum_attempts(attempts: list[dict[str, Any]], key: str) -> int | None:
    values = [_int(attempt.get(key)) for attempt in attempts]
    values = [value for value in values if value is not None]
    return sum(values) if values else None


_ATTEMPT_FIELDS = {
    "prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens",
    "latency_seconds", "cached", "retries",
}


def _collect_attempts(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect leaf attempt records from both current and legacy timing JSON."""

    result: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        attempts = node.get("attempts")
        if isinstance(attempts, list):
            for item in attempts:
                visit(item)
            return
        nested = False
        for key in ("meta", "llm", "markdown_stage", "ir_stage", "diagram_stage", "diagram"):
            child = node.get(key)
            if isinstance(child, dict):
                nested = True
                visit(child)
        if not nested and any(key in node for key in _ATTEMPT_FIELDS):
            result.append(node)

    visit(raw)
    return result


def _first_number_or_sum(
    sources: Iterable[dict[str, Any]], attempts: list[dict[str, Any]], key: str
) -> int | None:
    direct = _first_number(sources, key)
    return direct if direct is not None else _sum_attempts(attempts, key)


def _cached_value(raw: dict[str, Any], llm: dict[str, Any], attempts: list[dict[str, Any]]) -> bool | None:
    values: list[bool] = []
    for source in (raw, llm, *attempts):
        if "cached" in source and source.get("cached") is not None:
            values.append(bool(source.get("cached")))
    if not values:
        return None
    return True if any(values) else False


def normalize_telemetry(
    raw: dict[str, Any] | None,
    *,
    model: str | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    """Normalize a timing payload into the version-level telemetry contract."""

    raw = raw if isinstance(raw, dict) else {}
    llm = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
    attempts = _collect_attempts(raw)
    resolved_model = _text(llm.get("model") or raw.get("model") or model)
    resolved_provider = _text(
        llm.get("provider") or raw.get("provider") or raw.get("vendor") or provider
    )
    cached = _cached_value(raw, llm, attempts)
    sources = (llm, raw)

    if cached is True:
        prompt_tokens = completion_tokens = reasoning_tokens = total_tokens = None
        latency_seconds = _float(raw.get("cache_latency_seconds"))
        retries = 0
    else:
        prompt_tokens = _first_number_or_sum(sources, attempts, "prompt_tokens")
        completion_tokens = _first_number_or_sum(sources, attempts, "completion_tokens")
        reasoning_tokens = _first_number_or_sum(sources, attempts, "reasoning_tokens")
        total_tokens = _first_number_or_sum(sources, attempts, "total_tokens")
        latency_seconds = _float(raw.get("total_seconds"))
        if latency_seconds is None:
            latency_seconds = _float(llm.get("sum_llm_latency_seconds"))
        if latency_seconds is None:
            latency_seconds = _float(raw.get("latency_seconds"))
        if latency_seconds is None:
            values = [_float(attempt.get("latency_seconds")) for attempt in attempts]
            values = [value for value in values if value is not None]
            latency_seconds = round(sum(values), 4) if values else None
        retries = _first_number((llm, raw), "retries")
        if retries is None and attempts:
            retries = max(len(attempts) - 1, 0)

    has_usage = any(value is not None for value in (
        prompt_tokens, completion_tokens, reasoning_tokens, total_tokens
    ))
    has_telemetry = bool(raw)
    if cached is True:
        status = "cached"
        cost_status = "cached"
    elif not has_usage and latency_seconds is None and retries is None:
        status = "unavailable"
        cost_status = "usage_unavailable"
    else:
        status = "available"
        cost_status = "not_calculated"
    return {
        "schema_version": TELEMETRY_SCHEMA_VERSION,
        "provider": resolved_provider,
        "model": resolved_model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "latency_seconds": latency_seconds,
        "retries": retries,
        "cached": cached,
        "attempts": len(attempts) if attempts else None,
        "has_usage": has_usage,
        "has_telemetry": has_telemetry,
        "status": status,
        "cost_status": cost_status,
    }


def normalize_price_table(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a local model price map without contacting any service."""

    if not isinstance(raw, dict):
        return {"currency": DEFAULT_CURRENCY, "models": {}}
    source = raw.get("models") if isinstance(raw.get("models"), dict) else raw
    models: dict[str, dict[str, float]] = {}
    for model, values in source.items():
        if model == "currency" or not isinstance(values, dict):
            continue
        normalized: dict[str, float] = {}
        aliases = {
            "input_per_million": ("input_per_million", "prompt_per_million"),
            "output_per_million": ("output_per_million", "completion_per_million"),
            "reasoning_per_million": ("reasoning_per_million",),
        }
        for name, keys in aliases.items():
            for key in keys:
                value = _float(values.get(key))
                if value is not None:
                    normalized[name] = value
                    break
        if normalized:
            models[str(model)] = normalized
    return {
        "currency": _text(raw.get("currency")) or DEFAULT_CURRENCY,
        "models": models,
    }


def load_price_table() -> dict[str, Any]:
    """Load a local JSON price table from env, or return an empty table."""

    configured = os.environ.get("GRAPH2NOTE_PRICING_JSON") or os.environ.get("GRAPH2NOTE_PRICE_TABLE")
    if not configured:
        return normalize_price_table(None)
    try:
        path = Path(configured)
        text = path.read_text(encoding="utf-8") if path.is_file() else configured
        return normalize_price_table(json.loads(text))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return normalize_price_table(None)


def _price_for(price_table: dict[str, Any], model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    return (normalize_price_table(price_table).get("models") or {}).get(model)


def _event_cost(telemetry: dict[str, Any], price_table: dict[str, Any]) -> tuple[float | None, str]:
    if telemetry.get("cached") is True:
        return 0.0, "cached"
    if not telemetry.get("has_usage"):
        return None, "usage_unavailable"
    price = _price_for(price_table, telemetry.get("model"))
    if not price:
        return None, "no_price_config"
    prompt = telemetry.get("prompt_tokens")
    completion = telemetry.get("completion_tokens")
    if prompt is None or completion is None:
        return None, "tokens_incomplete"
    if "input_per_million" not in price or "output_per_million" not in price:
        return None, "no_price_config"
    cost = prompt * price["input_per_million"] / 1_000_000
    cost += completion * price["output_per_million"] / 1_000_000
    reasoning_rate = price.get("reasoning_per_million")
    if reasoning_rate is not None:
        reasoning = telemetry.get("reasoning_tokens")
        if reasoning is None:
            return None, "tokens_incomplete"
        cost += reasoning * reasoning_rate / 1_000_000
    return round(cost, 8), "priced"


def _parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _version_telemetry(version: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    raw = version.get("telemetry")
    if not isinstance(raw, dict) or "schema_version" not in raw:
        raw = version.get("timing_json") if isinstance(version.get("timing_json"), dict) else raw
    return normalize_telemetry(
        raw,
        model=version.get("model") or record.get("model"),
        provider=version.get("provider") or record.get("provider"),
    )


def _events(records: list[dict[str, Any]], timezone: ZoneInfo) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for record in records:
        versions = record.get("versions")
        if not isinstance(versions, list) or not versions:
            versions = [{
                "created_at": record.get("created_at"),
                "model": record.get("model"),
                "telemetry": record.get("telemetry"),
                "timing_json": record.get("timing_json"),
            }]
        for index, version in enumerate(versions):
            version = version if isinstance(version, dict) else {}
            when = _parse_datetime(
                version.get("created_at") or record.get("created_at"), timezone
            )
            events.append({
                "document_id": _text(record.get("document_id")) or "",
                "version_index": index,
                "when": when,
                "telemetry": _version_telemetry(version, record),
            })
    return events


def _aggregate(events: list[dict[str, Any]], price_table: dict[str, Any]) -> dict[str, Any]:
    usage_events = [event for event in events if event["telemetry"].get("has_usage")]
    telemetry_events = [event for event in events if event["telemetry"].get("has_telemetry")]
    result: dict[str, Any] = {}
    for field in ("prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"):
        values = [_int(event["telemetry"].get(field)) for event in usage_events]
        values = [value for value in values if value is not None]
        result[field] = sum(values) if values else None
    costs: list[tuple[float | None, str]] = [
        _event_cost(event["telemetry"], price_table) for event in telemetry_events
    ]
    numeric_costs = [cost for cost, _ in costs if cost is not None]
    result["cost"] = round(sum(numeric_costs), 8) if numeric_costs else None
    statuses = {status for _, status in costs}
    if not costs:
        result["cost_status"] = "usage_unavailable"
    elif statuses <= {"cached", "priced"}:
        result["cost_status"] = "cached" if statuses == {"cached"} else "priced"
    elif "priced" in statuses or "cached" in statuses:
        result["cost_status"] = "partial"
    elif "no_price_config" in statuses:
        result["cost_status"] = "no_price_config"
    else:
        result["cost_status"] = "usage_unavailable"
    return result


def _bucket_stats(events: list[dict[str, Any]], price_table: dict[str, Any], key: str) -> list[dict[str, Any]]:
    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        when = event.get("when")
        if when is None or not event["telemetry"].get("has_usage"):
            continue
        period = when.date().isoformat() if key == "day" else when.strftime("%Y-%m")
        buckets[period].append(event)
    result = []
    for period in sorted(buckets):
        result.append({"period": period, **_aggregate(buckets[period], price_table)})
    return result


def build_stats(
    records: Iterable[dict[str, Any]],
    *,
    now: datetime | None = None,
    price_table: dict[str, Any] | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Build the deterministic Dashboard payload from document records."""

    records = [record for record in records if isinstance(record, dict)]
    records.sort(key=lambda record: _text(record.get("document_id")) or "")
    zone = ZoneInfo(timezone)
    now = now or datetime.now(zone)
    if now.tzinfo is None:
        now = now.replace(tzinfo=zone)
    now = now.astimezone(zone)
    prices = normalize_price_table(price_table)
    events = _events(records, zone)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())

    first_dates: dict[str, date | None] = {}
    for event in sorted(events, key=lambda item: (
        item["document_id"], item["when"] is None, item["when"] or now,
        item["version_index"],
    )):
        first_dates.setdefault(
            event["document_id"], event["when"].date() if event["when"] else None
        )

    def count_pages(predicate) -> int:
        return sum(1 for event in events if event["when"] and predicate(event["when"].date()))

    today_docs = sum(1 for value in first_dates.values() if value == today)
    week_docs = sum(1 for value in first_dates.values() if value and week_start <= value <= today)
    trend_counter = Counter(value.isoformat() for value in first_dates.values() if value)

    topic_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    topic_order: dict[str, int] = {}
    tag_order: dict[str, int] = {}
    for record in records:
        topics = _unique_texts(record.get("topics") or [])
        if topics:
            topic_counter.update(topics)
            for topic in topics:
                topic_order.setdefault(topic, len(topic_order))
        else:
            topic_counter["未分类"] += 1
            topic_order.setdefault("未分类", len(topic_order))
        tags = _unique_texts(record.get("tags") or [])
        tag_counter.update(tags)
        for tag in tags:
            tag_order.setdefault(tag, len(tag_order))

    telemetry_events = [event for event in events if event["telemetry"].get("has_telemetry")]
    missing_count = len(events) - len(telemetry_events)
    latencies = [
        event["telemetry"]["latency_seconds"]
        for event in telemetry_events
        if event["telemetry"].get("latency_seconds") is not None
    ]
    retry_events = [event for event in telemetry_events if event["telemetry"].get("retries") is not None]
    retry_count = sum(1 for event in retry_events if event["telemetry"].get("retries", 0) > 0)
    quality_status = (
        "no_documents" if not records else
        "unavailable" if not telemetry_events else
        "partial" if missing_count else "complete"
    )

    model_groups: defaultdict[tuple[str, str | None], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        telemetry = event["telemetry"]
        model_groups[(_text(telemetry.get("model")) or "未知模型", telemetry.get("provider"))].append(event)
    model_usage = []
    for (model, provider), group in sorted(model_groups.items(), key=lambda item: (item[0][0].casefold(), item[0][1] or "")):
        model_usage.append({
            "model": model,
            "provider": provider,
            "events": len(group),
            "cached_hits": sum(1 for event in group if event["telemetry"].get("cached") is True),
            "retries": sum(event["telemetry"].get("retries") or 0 for event in group),
            **_aggregate(group, prices),
        })

    return {
        "empty_library": not records,
        "currency": prices["currency"],
        "periods": {
            "today": {"pages": count_pages(lambda value: value == today), "new_documents": today_docs},
            "week": {"pages": count_pages(lambda value: week_start <= value <= today), "new_documents": week_docs},
            "total": {"pages": len(events), "new_documents": len(records)},
        },
        "new_documents_trend": [
            {"date": period, "count": trend_counter[period]}
            for period in sorted(trend_counter)
        ],
        "classification_distribution": [
            {"topic": topic, "count": count}
            for topic, count in sorted(topic_counter.items(), key=lambda item: (-item[1], topic_order[item[0]]))
        ],
        "top_tags": [
            {"tag": tag, "count": count}
            for tag, count in sorted(tag_counter.items(), key=lambda item: (-item[1], tag_order[item[0]]))
        ],
        "model_usage": model_usage,
        "token_usage_by_day": _bucket_stats(events, prices, "day"),
        "token_usage_by_month": _bucket_stats(events, prices, "month"),
        "quality": {
            "status": quality_status,
            "total_events": len(events),
            "telemetry_events": len(telemetry_events),
            "missing_telemetry_events": missing_count,
            "average_latency_seconds": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "retry_rate": retry_count / len(retry_events) if retry_events else None,
            "retry_events": len(retry_events),
        },
    }


def _unique_texts(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return result


__all__ = [
    "DEFAULT_TIMEZONE",
    "TELEMETRY_SCHEMA_VERSION",
    "build_stats",
    "load_price_table",
    "normalize_price_table",
    "normalize_telemetry",
]
