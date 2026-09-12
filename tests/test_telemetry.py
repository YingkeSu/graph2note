"""Offline contracts for issue 06 telemetry persistence and Dashboard stats."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from graph2note import pipeline
from graph2note.router import RouteARouter
from graph2note.store import FileDocumentStore
from graph2note.telemetry import build_stats, normalize_telemetry
from graph2note.webapp import create_app

from tests.static_assets import static_js


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2024, 4, 10, 15, 0, tzinfo=TZ)


def _timing(
    model: str,
    *,
    provider: str | None = "fixture",
    prompt: int | None = 100,
    completion: int | None = 40,
    reasoning: int | None = 10,
    total: int | None = 150,
    latency: float = 10.0,
    retries: int = 0,
    cached: bool = False,
):
    return {
        "total_seconds": latency,
        "cached": cached,
        "llm": {
            "model": model,
            "provider": provider,
            "retries": retries,
            "sum_llm_latency_seconds": latency,
            "attempts": [{
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "reasoning_tokens": reasoning,
                "total_tokens": total,
                "latency_seconds": latency,
                "cached": cached,
            }],
        },
    }


def _records():
    return [
        {
            "document_id": "d1",
            "title": "数学 A",
            "created_at": "2024-04-08T09:00:00",
            "topics": ["数学"],
            "tags": ["重点"],
            "versions": [
                {"version_id": "v1", "created_at": "2024-04-08T09:00:00", "timing_json": _timing("m1", retries=1)},
                {"version_id": "v2", "created_at": "2024-04-10T09:00:00", "timing_json": _timing(
                    "m2", provider=None, prompt=200, completion=80, reasoning=20,
                    total=300, latency=4.0,
                )},
            ],
        },
        {
            "document_id": "d2",
            "title": "物理 B",
            "created_at": "2024-04-09T09:00:00",
            "topics": ["物理"],
            "tags": ["重点", "草稿"],
            "versions": [{
                "version_id": "v1",
                "created_at": "2024-04-09T09:00:00",
                "timing_json": _timing("m1", cached=True),
            }],
        },
        {
            "document_id": "d3",
            "title": "旧记录",
            "created_at": "2024-04-07T09:00:00",
            "topics": [],
            "tags": [],
            "versions": [{"version_id": "v1", "created_at": "2024-04-07T09:00:00", "model": "old-model"}],
        },
    ]


def _prices():
    return {
        "currency": "USD",
        "models": {
            "m1": {
                "input_per_million": 1.0,
                "output_per_million": 2.0,
                "reasoning_per_million": 3.0,
            },
        },
    }


def test_normalize_telemetry_keeps_missing_fields_explicit_and_cache_hits_free():
    normalized = normalize_telemetry(_timing("m1"), model="fallback")
    assert normalized["schema_version"] == 1
    assert normalized["model"] == "m1"
    assert normalized["provider"] == "fixture"
    assert normalized["total_tokens"] == 150
    assert normalized["has_usage"] is True
    assert normalized["has_telemetry"] is True

    cached = normalize_telemetry(_timing("m1", cached=True))
    assert cached["cached"] is True
    assert cached["prompt_tokens"] is None
    assert cached["total_tokens"] is None
    assert cached["cost_status"] == "cached"

    missing = normalize_telemetry({}, model="old-model")
    assert missing["model"] == "old-model"
    assert missing["has_telemetry"] is False
    assert missing["prompt_tokens"] is None
    assert missing["cost_status"] == "usage_unavailable"


def test_normalize_telemetry_reads_nested_gateway_attempts():
    raw = {
        "total_seconds": 2.5,
        "llm": {
            "model": "m1",
            "attempts": [{
                "attempt": 0,
                "meta": {
                    "markdown_stage": {
                        "attempts": [{
                            "prompt_tokens": 11,
                            "completion_tokens": 7,
                            "reasoning_tokens": 2,
                            "total_tokens": 20,
                            "latency_seconds": 1.2,
                            "cached": False,
                        }],
                    },
                    "ir_stage": {"attempts": [{"status": "ok"}]},
                },
            }],
        },
    }
    normalized = normalize_telemetry(raw)
    assert normalized["prompt_tokens"] == 11
    assert normalized["completion_tokens"] == 7
    assert normalized["reasoning_tokens"] == 2
    assert normalized["total_tokens"] == 20
    assert normalized["attempts"] == 1


def test_pipeline_writes_flattened_usage_to_timing_artifact(tmp_path):
    reply = json.dumps({
        "document_type": "note",
        "blocks": [{"type": "paragraph", "text": "offline"}],
    })

    def caller(image_path, model, recover=False):
        return reply, {
            "status": "ok",
            "provider": "fixture-gateway",
            "latency_seconds": 1.2,
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "reasoning_tokens": 2,
            "total_tokens": 20,
            "cached": False,
        }

    result = pipeline.parse_document(
        str(tmp_path / "page.png"),
        str(tmp_path / "out"),
        model="m1",
        router=RouteARouter("m1", caller=caller),
        preprocess=False,
    )
    persisted = json.loads((tmp_path / "out" / "timing.json").read_text())
    attempt = persisted["llm"]["attempts"][0]
    assert result.timing_json["cached"] is False
    assert attempt["provider"] == "fixture-gateway"
    assert attempt["total_tokens"] == 20
    assert persisted["cached"] is False


def test_stats_snapshot_covers_periods_categories_tokens_costs_and_quality():
    stats = build_stats(_records(), now=NOW, price_table=_prices())

    assert stats["empty_library"] is False
    assert stats["periods"] == {
        "today": {"pages": 1, "new_documents": 0},
        "week": {"pages": 3, "new_documents": 2},
        "total": {"pages": 4, "new_documents": 3},
    }
    assert stats["new_documents_trend"] == [
        {"date": "2024-04-07", "count": 1},
        {"date": "2024-04-08", "count": 1},
        {"date": "2024-04-09", "count": 1},
    ]
    assert stats["classification_distribution"] == [
        {"topic": "数学", "count": 1},
        {"topic": "物理", "count": 1},
        {"topic": "未分类", "count": 1},
    ]
    assert stats["top_tags"] == [
        {"tag": "重点", "count": 2},
        {"tag": "草稿", "count": 1},
    ]
    assert stats["quality"]["telemetry_events"] == 3
    assert stats["quality"]["missing_telemetry_events"] == 1
    assert stats["quality"]["average_latency_seconds"] == 7.0
    assert stats["quality"]["retry_rate"] == 1 / 3

    models = {item["model"]: item for item in stats["model_usage"]}
    assert models["m1"]["total_tokens"] == 150
    assert models["m1"]["cost"] == 0.00021
    assert models["m1"]["cost_status"] == "priced"
    assert models["m2"]["total_tokens"] == 300
    assert models["m2"]["cost"] is None
    assert models["m2"]["cost_status"] == "no_price_config"
    assert stats["token_usage_by_day"] == [
        {"period": "2024-04-08", "prompt_tokens": 100, "completion_tokens": 40,
         "reasoning_tokens": 10, "total_tokens": 150, "cost": 0.00021,
         "cost_status": "priced"},
        {"period": "2024-04-10", "prompt_tokens": 200, "completion_tokens": 80,
         "reasoning_tokens": 20, "total_tokens": 300, "cost": None,
         "cost_status": "no_price_config"},
    ]
    assert stats["token_usage_by_month"][0]["period"] == "2024-04"
    assert stats["token_usage_by_month"][0]["total_tokens"] == 450
    assert stats["token_usage_by_month"][0]["cost_status"] == "partial"


def test_empty_and_legacy_records_are_explicitly_available_or_unavailable():
    empty = build_stats([], now=NOW, price_table=_prices())
    assert empty["empty_library"] is True
    assert empty["periods"]["total"]["pages"] == 0
    assert empty["quality"]["average_latency_seconds"] is None
    assert empty["quality"]["retry_rate"] is None

    old = build_stats([{
        "document_id": "legacy",
        "title": "Legacy",
        "created_at": "2024-04-09T09:00:00",
        "topics": [],
        "tags": [],
        "versions": [{"version_id": "v1", "created_at": "2024-04-09T09:00:00", "model": "old"}],
    }], now=NOW, price_table=_prices())
    assert old["empty_library"] is False
    assert old["quality"]["missing_telemetry_events"] == 1
    assert old["quality"]["average_latency_seconds"] is None
    assert old["quality"]["retry_rate"] is None
    assert old["model_usage"][0]["cost_status"] == "usage_unavailable"


def test_version_telemetry_persists_across_file_store_reload_and_stats_api(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    store.save_document(
        document_id="doc-a",
        title="A",
        source_job_id="job-a",
        model="m1",
        markdown="# A\n",
        ir_json="{}",
        original_path="",
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json=_timing("m1"),
    )
    reloaded = FileDocumentStore(store.root)
    version = reloaded.get_document("doc-a")["versions"][0]
    assert version["telemetry"]["model"] == "m1"
    client = TestClient(create_app(
        document_store=reloaded,
        storage_dir=reloaded.root,
        price_table=_prices(),
    ))
    response = client.get("/api/stats?as_of=2024-04-10T15:00:00+08:00")
    assert response.status_code == 200
    payload = response.json()
    assert payload["periods"]["total"]["pages"] == 1
    assert payload["model_usage"][0]["cost"] == 0.00021
    html = client.get("/").text
    javascript = static_js()
    assert 'id="nav-dashboard"' in html
    assert 'id="dashboard-zone"' in html
    assert "/api/stats" in javascript
