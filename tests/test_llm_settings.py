"""Issue 16: provider/model settings stay local, validated, and secret-free."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from graph2note.llm_settings import (
    LLMSettingsStore,
    MODEL_PURPOSES,
    SettingsError,
    configure_settings_path,
    probe_channel,
)

from tests.static_assets import static_js  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_runtime_settings_path():
    yield
    configure_settings_path(None)


def test_settings_snapshot_lists_registered_channels_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    store = LLMSettingsStore(tmp_path / "llm-settings.json")

    snapshot = store.snapshot()

    assert tuple(snapshot["purposes"]) == MODEL_PURPOSES
    assert {item["id"] for item in snapshot["providers"]} == {"opencode", "deepseek", "kimi"}
    assert snapshot["channels"]["parse_visual"]["provider"] == "opencode"
    assert snapshot["channels"]["parse_visual"]["model"] == "glm-5.3-flash"
    for provider in snapshot["providers"]:
        assert "api_key" not in provider
        assert "secret" not in provider


def test_builtin_keys_are_entered_in_app_and_saved_locally(tmp_path, monkeypatch):
    from eval.gateway import load_api_key
    from graph2note.webapp import create_app

    monkeypatch.setenv("DEEPSEEK_API_KEY", "legacy-env-key")
    settings_path = tmp_path / "llm-settings.json"
    client = TestClient(create_app(storage_dir=tmp_path))
    key = "test-local-key-12345"
    response = client.put("/api/llm/builtin-providers/deepseek/key", json={"api_key": key})
    assert response.status_code == 200
    assert key not in response.text
    assert next(p for p in response.json()["providers"] if p["id"] == "deepseek")["credential_configured"]
    assert load_api_key("deepseek") == key
    assert settings_path.stat().st_mode & 0o777 == 0o600
    assert json.loads(settings_path.read_text())["builtin_api_keys"]["deepseek"] == key

    # A later model change preserves the key, and a restarted app reads it.
    client.put("/api/llm/settings", json={"channels": {
        "classify": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    }})
    restarted = TestClient(create_app(storage_dir=tmp_path))
    assert key not in restarted.get("/api/llm/settings").text
    assert load_api_key("deepseek") == key
    assert restarted.put("/api/llm/builtin-providers/unknown/key", json={"api_key": key}).status_code == 422


@pytest.mark.parametrize("gateway", ["opencode", "deepseek", "kimi"])
def test_diagram_default_channel_is_deepseek_vision_for_every_gateway(
    tmp_path, monkeypatch, gateway
):
    """X1 (裁决 a): diagram 默认通道固定 deepseek 视觉，其余 purpose 随 GRAPH2NOTE_GATEWAY。"""
    from eval.gateway import map_model

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", gateway)
    path = tmp_path / "llm-settings.json"
    configure_settings_path(path)
    store = LLMSettingsStore(path)

    # diagram 默认走 deepseek 网关的 diagram 默认模型（"glm-5.3-flash"），
    # 线上经 DEEPSEEK_MODEL_MAP 落到官方视觉别名；与活动网关无关。
    assert store.resolve("diagram") == {"provider": "deepseek", "model": "glm-5.3-flash"}
    assert map_model("glm-5.3-flash", "deepseek") == "deepseek-v4-flash-vision-exp"
    # 其他 purpose 不受 X1 影响（不回归）：仍随活动网关的默认。
    for purpose in ("parse_visual", "ir_text", "classify"):
        assert store.resolve(purpose)["provider"] == gateway


def test_explicit_diagram_channel_still_beats_the_deepseek_default(tmp_path, monkeypatch):
    """显式配置的 diagram 通道（含 kimi 视觉）优先于 X1 默认，不被静默改写。"""
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "kimi")
    path = tmp_path / "llm-settings.json"
    configure_settings_path(path)
    store = LLMSettingsStore(path)

    store.update({"channels": {"diagram": {"provider": "kimi", "model": "kimi-k2.6"}}})
    assert LLMSettingsStore(path).resolve("diagram") == {
        "provider": "kimi", "model": "kimi-k2.6",
    }


def test_default_diagram_channel_routes_the_live_extractor_to_deepseek(tmp_path, monkeypatch):
    """端到端：kimi 网关下未显式配置时，抽取实际以 provider=deepseek 发出。"""
    from pathlib import Path

    from graph2note import diagram, vlm

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "kimi")
    configure_settings_path(tmp_path / "llm-settings.json")
    image = Path(__file__).resolve().parents[1] / "test-images" / "01-requirements-arch.jpg"
    captured = {}

    monkeypatch.setattr(vlm, "load_api_key", lambda *_args, **_kwargs: "fixture")

    def fake_post(_payload, **kwargs):
        captured.update(kwargs)
        captured["model"] = _payload["model"]
        return {"choices": [{"message": {"content": '{"nodes":[{"id":"a","label":"A"}],"edges":[]}'}}]}

    monkeypatch.setattr(diagram, "_post", fake_post)
    result = diagram.extract_diagram_image(str(image), model=None)

    assert result["meta"]["provider"] == "deepseek"
    assert result["meta"]["model"] == "glm-5.3-flash"
    assert captured["provider"] == "deepseek"
    assert result["verdict"] == "ok"


def test_settings_update_rejects_unknown_values_and_persists_valid_values(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    path = tmp_path / "llm-settings.json"
    store = LLMSettingsStore(path)
    before = store.resolve("parse_visual")

    with pytest.raises(SettingsError):
        store.update({"channels": {
            "parse_visual": {"provider": "missing", "model": "glm-5.3-flash"},
        }})
    assert store.resolve("parse_visual") == before
    assert not path.exists()

    store.update({"channels": {
        "parse_visual": {"provider": "deepseek", "model": "glm-5.3-flash"},
    }})
    assert LLMSettingsStore(path).resolve("parse_visual") == {
        "provider": "deepseek", "model": "glm-5.3-flash",
    }


def test_health_probe_is_injectable_and_classifies_auth_request_and_missing(monkeypatch):
    calls = []

    def fake_probe(provider, purpose, model):
        calls.append((provider, purpose, model))
        if purpose == "ir_text":
            return {"status": "auth_failed", "detail": "401 from fixture"}
        if purpose == "diagram":
            raise RuntimeError("connection refused")
        return {"status": "available"}

    monkeypatch.setenv("OPENCODE_API_KEY", "fixture-only")
    assert probe_channel("opencode", "parse_visual", "glm-5.3-flash", probe=fake_probe)["status"] == "available"
    assert probe_channel("opencode", "ir_text", "deepseek-v4-flash", probe=fake_probe)["status"] == "auth_failed"
    assert probe_channel("opencode", "diagram", "glm-5.3-flash", probe=fake_probe)["status"] == "request_failed"
    monkeypatch.delenv("OPENCODE_API_KEY")
    monkeypatch.setattr("graph2note.llm_settings._dotenv_get", lambda _key: "")
    assert probe_channel("opencode", "classify", "kimi-k3")["status"] == "missing_credentials"
    assert calls == [
        ("opencode", "parse_visual", "glm-5.3-flash"),
        ("opencode", "ir_text", "deepseek-v4-flash"),
        ("opencode", "diagram", "glm-5.3-flash"),
    ]


def test_runtime_resolution_changes_router_without_restart(tmp_path, monkeypatch):
    from graph2note import pipeline
    from graph2note.llm_settings import configure_settings_path

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    path = tmp_path / "llm-settings.json"
    store = LLMSettingsStore(path)
    configure_settings_path(path)
    store.update({"channels": {
        "parse_visual": {"provider": "deepseek", "model": "glm-5.3-flash"},
    }})

    first = pipeline.make_router()
    assert first.model == "glm-5.3-flash"
    assert first.provider == "deepseek"

    store.update({"channels": {
        "parse_visual": {"provider": "opencode", "model": "deepseek-v4-flash-vision-exp"},
    }})
    second = pipeline.make_router()
    assert second.provider == "opencode"
    assert second.model == "deepseek-v4-flash-vision-exp"


def test_settings_api_health_and_next_parse_use_persisted_channel(tmp_path, monkeypatch):
    from graph2note.router import RouteARouter
    from graph2note.webapp import create_app

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "fixture-only")
    selected = []
    health_calls = []

    def factory(_image_path, model):
        selected.append(model)
        return RouteARouter(model, caller=lambda *_args, **_kwargs: (
            '{"document_type":"note","blocks":[{"type":"paragraph","text":"ok"}]}', {}
        ))

    def fake_probe(provider, purpose, model):
        health_calls.append((provider, purpose, model))
        return {"status": "available"}

    app = create_app(storage_dir=tmp_path, router_factory=factory, llm_probe=fake_probe)
    client = TestClient(app)
    before = client.get("/api/llm/settings").json()
    assert set(before["channels"]) == set(MODEL_PURPOSES)
    assert "OPENCODE_API_KEY" not in json.dumps(before)

    changed = client.put("/api/llm/settings", json={"channels": {
        "parse_visual": {"provider": "deepseek", "model": "glm-5.3-flash"},
        "ir_text": {"provider": "deepseek", "model": "deepseek-v4-flash"},
        "diagram": {"provider": "deepseek", "model": "glm-5.3-flash"},
        "classify": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    }})
    assert changed.status_code == 200, changed.text
    assert changed.json()["channels"]["parse_visual"]["provider"] == "deepseek"

    invalid = client.put("/api/llm/settings", json={"channels": {
        "parse_visual": {"provider": "unknown", "model": "glm-5.3-flash"},
    }})
    assert invalid.status_code == 422
    assert client.get("/api/llm/settings").json()["channels"]["parse_visual"]["provider"] == "deepseek"

    health = client.post("/api/llm/health")
    assert health.status_code == 200
    assert {item["status"] for item in health.json()["channels"]} == {"available"}
    assert len(health_calls) == 4

    image = (tmp_path / "fixture.png")
    from PIL import Image
    Image.new("RGB", (32, 32), "white").save(image)
    uploaded = client.post("/api/parse", files={"file": ("fixture.png", image.read_bytes(), "image/png")})
    assert uploaded.status_code == 200
    assert uploaded.json()["provider"] == "deepseek"
    assert uploaded.json()["model"] == "glm-5.3-flash"
    restarted = TestClient(create_app(storage_dir=tmp_path, router_factory=factory, llm_probe=fake_probe))
    assert restarted.get("/api/llm/settings").json()["channels"]["classify"] == {
        "provider": "deepseek", "model": "deepseek-v4-flash",
        "purpose": "classify", "label": "分类归纳",
    }
    html = client.get("/").text
    javascript = static_js()
    assert 'id="nav-settings"' in html
    assert 'id="settings-zone"' in html
    assert 'id="llm-health-button"' in html
    assert "/api/llm/settings" in javascript
    assert "/api/llm/health" in javascript


def test_classification_gateway_reads_selected_provider_and_model(tmp_path, monkeypatch):
    from graph2note.llm_settings import configure_settings_path
    from graph2note.notes import llm

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    path = tmp_path / "llm-settings.json"
    store = LLMSettingsStore(path)
    configure_settings_path(path)
    store.update({"channels": {
        "classify": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    }})
    captured = {}

    monkeypatch.setattr("eval.gateway.load_api_key", lambda provider=None: "fixture")

    def fake_post(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr("eval.gateway.post_gateway", fake_post)
    assert llm._gateway_text("classify me") == "{}"
    assert captured["kwargs"]["provider"] == "deepseek"
    assert captured["payload"]["model"] == "deepseek-v4-flash"


def test_classification_result_records_effective_channel(tmp_path, monkeypatch):
    from graph2note.llm_settings import configure_settings_path
    from graph2note.notes import llm
    from graph2note.notes.exporter import ExportEntry

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    path = tmp_path / "llm-settings.json"
    store = LLMSettingsStore(path)
    configure_settings_path(path)
    store.update({"channels": {
        "classify": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    }})
    entry = ExportEntry(
        document_id="d1", title="note", markdown="正文", parsed_at="", updated_at="",
        original_path="", source_ext=".jpg", preprocessed_path="",
    )
    scheme = llm.classify_via_llm(
        [entry],
        planner=lambda _prompt, _model: '{"topics":["笔记"],"assignments":{"笔记":["d1"]},"summaries":{"d1":"正文"}}',
    )
    assert scheme.runtime == {"provider": "deepseek", "model": "deepseek-v4-flash"}
    assert "runtime" not in scheme.to_dict()


def test_parse_ir_and_diagram_stages_use_their_own_selected_channels(tmp_path, monkeypatch):
    from pathlib import Path

    from graph2note import diagram, vlm
    from graph2note.llm_settings import configure_settings_path

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    monkeypatch.setenv("GRAPH2NOTE_IR_MODE", "parser")
    path = tmp_path / "llm-settings.json"
    store = LLMSettingsStore(path)
    configure_settings_path(path)
    store.update({"channels": {
        "parse_visual": {"provider": "deepseek", "model": "glm-5.3-flash"},
        "ir_text": {"provider": "opencode", "model": "deepseek-v4-flash"},
        "diagram": {"provider": "deepseek", "model": "glm-5.3-flash"},
    }})
    image = Path(__file__).resolve().parents[1] / "test-images" / "01-requirements-arch.jpg"
    calls = []

    def fake_post(payload, **kwargs):
        calls.append((payload, kwargs))
        if isinstance(payload["messages"][-1]["content"], list):
            content = "# 标题\n普通正文"
        else:
            content = "{}"
        return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(vlm, "load_api_key", lambda *_args, **_kwargs: "fixture")
    monkeypatch.setattr(vlm, "post_gateway", fake_post)
    _content, meta = vlm.call_ir(str(image), model=None)
    assert meta["provider"] == "deepseek"
    assert meta["ir_provider"] == "opencode"
    assert meta["ir_model"] == "deepseek-v4-flash"
    assert calls[0][1]["provider"] == "deepseek"

    diagram_calls = {}

    def fake_diagram_post(_payload, **kwargs):
        diagram_calls.update(kwargs)
        return {"choices": [{"message": {"content": '{"nodes":[{"id":"a","label":"A"}],"edges":[]}'}}]}

    monkeypatch.setattr(diagram, "_post", fake_diagram_post)
    result = diagram.extract_diagram_image(str(image), model=None)
    assert result["meta"]["provider"] == "deepseek"
    assert result["meta"]["model"] == "glm-5.3-flash"
    assert diagram_calls["provider"] == "deepseek"


def test_route_b_reads_selected_ir_text_channel(tmp_path, monkeypatch):
    from graph2note.llm_settings import configure_settings_path
    from graph2note.route_b import route_b_chain

    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    path = tmp_path / "llm-settings.json"
    store = LLMSettingsStore(path)
    configure_settings_path(path)
    store.update({"channels": {
        "ir_text": {"provider": "deepseek", "model": "deepseek-v4-flash"},
    }})
    captured = {}

    monkeypatch.setattr("eval.gateway.load_api_key", lambda provider=None: "fixture")

    def fake_post(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {
            "choices": [{"message": {"content": "# 标题\n\n正文"}, "finish_reason": "stop"}],
            "usage": {},
        }

    monkeypatch.setattr("eval.gateway.post_gateway", fake_post)
    result = route_b_chain(
        "fixture.jpg",
        ocr_caller=lambda _path: ("标题 正文", {"chars": 5}),
        max_retries=0,
    )

    assert result.document.blocks
    assert captured["kwargs"]["provider"] == "deepseek"
    assert captured["payload"]["model"] == "deepseek-v4-flash"
    assert result.attempts[1]["meta"]["provider"] == "deepseek"
