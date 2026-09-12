"""Issue A3: arbitrary OpenAI-compatible custom providers (offline, stub HTTP).

Covers provider CRUD, OpenAI Chat Completions request assembly (URL/Bearer/verbatim
model passthrough), write-only API keys, health probes, visual+text routing and the
delete-time channel fallback.  All HTTP is stubbed — CI never touches the network.
"""

from __future__ import annotations

import io
import json
import logging
import urllib.error
from pathlib import Path

import pytest

from eval import gateway as g
from graph2note.llm_settings import (
    CUSTOM_PROVIDER_PREFIX,
    LLMSettingsStore,
    SettingsError,
    configure_settings_path,
    probe_channel,
)

KEY = "sk-custom-secret-123456"
NEW_KEY = "sk-custom-rotated-654321"
MODELS = ["glm-5.3-flash", "deepseek-v4-flash"]  # both names are mapped on the deepseek gate
IMAGE = Path(__file__).resolve().parents[1] / "test-images" / "01-requirements-arch.jpg"


class _FakeResp:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(url: str, code: int, body: str = "{}") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "err", {}, io.BytesIO(body.encode("utf-8")))


def _capture(monkeypatch):
    holder: dict = {}

    def fake_urlopen(req, timeout=None):
        holder["url"] = req.full_url
        holder["headers"] = {k.lower(): v for k, v in req.headers.items()}
        holder["body"] = json.loads(req.data.decode("utf-8")) if req.data else None
        return _FakeResp({"choices": [{"message": {"content": "ok"}}],
                          "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(g.urllib.request, "urlopen", fake_urlopen)
    return holder


@pytest.fixture(autouse=True)
def _reset_runtime_settings_path():
    yield
    configure_settings_path(None)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    path = tmp_path / "llm-settings.json"
    configure_settings_path(path)
    return LLMSettingsStore(path)


def _add(store, **overrides):
    payload = {"name": "DeepSeek 兼容", "base_url": "https://api.deepseek.com/",
               "api_key": KEY, "models": list(MODELS)}
    payload.update(overrides)
    return store.add_provider(payload)


# ---------------- AC1: add → list → assign → resolve ----------------


def test_add_provider_appears_in_list_and_is_assignable(store):
    snapshot = _add(store)

    provider = snapshot["providers"][-1]
    assert provider["id"] == "custom-deepseek"
    assert provider["kind"] == "custom"
    assert provider["base_url"] == "https://api.deepseek.com"
    assert provider["capabilities"]["parse_visual"]["models"] == MODELS
    assert provider["capabilities"]["classify"]["models"] == MODELS

    updated = store.update({"channels": {
        "parse_visual": {"provider": "custom-deepseek", "model": "glm-5.3-flash"},
    }})
    assert updated["channels"]["parse_visual"]["provider"] == "custom-deepseek"
    assert store.resolve("parse_visual") == {
        "provider": "custom-deepseek", "model": "glm-5.3-flash",
    }
    # transport resolves the same entry without a restart
    assert g.chat_completions_url("custom-deepseek") == "https://api.deepseek.com/chat/completions"
    assert g.gateway_config("custom-deepseek")["models"] == MODELS
    assert g.available_providers()["custom-deepseek"]["custom"] is True


def test_custom_channel_rejects_model_outside_provider_list(store):
    _add(store)
    with pytest.raises(SettingsError):
        store.update({"channels": {
            "classify": {"provider": "custom-deepseek", "model": "not-in-list"},
        }})


# ---------------- AC2: request assembly ----------------


def test_custom_request_url_bearer_and_verbatim_model(store, monkeypatch):
    _add(store)
    captured = _capture(monkeypatch)

    g.post_gateway({"model": "glm-5.3-flash"}, provider="custom-deepseek",
                   session="ignored", timeout=5)

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["authorization"] == f"Bearer {KEY}"
    assert "x-opencode-session" not in captured["headers"]
    # glm-5.3-flash is deepseek-mapped on the built-in gate; custom passes it verbatim.
    assert captured["body"]["model"] == "glm-5.3-flash"


def test_text_gateway_request_assembly_for_custom(store, monkeypatch):
    _add(store)
    captured = _capture(monkeypatch)

    g.transcribe_text("hello", "deepseek-v4-flash", provider="custom-deepseek")

    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["authorization"] == f"Bearer {KEY}"
    assert captured["body"]["model"] == "deepseek-v4-flash"


def test_custom_provider_never_applies_deepseek_map_model(store, monkeypatch):
    _add(store)
    assert g.map_model("glm-5.3-flash", "custom-deepseek") == "glm-5.3-flash"
    assert g.map_model("deepseek-v4-flash", "custom-deepseek") == "deepseek-v4-flash"

    # built-in deepseek mapping is untouched
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    assert g.map_model("glm-5.3-flash") == "deepseek-v4-flash-vision-exp"
    assert g.map_model("glm-5.3-flash", "deepseek") == "deepseek-v4-flash-vision-exp"


def test_custom_base_url_trailing_slash_is_normalized(store, monkeypatch):
    _add(store, base_url="https://api.example.com/v1//")
    captured = _capture(monkeypatch)
    g.post_gateway({"model": "m"}, provider="custom-deepseek", session="s", timeout=5)
    assert captured["url"] == "https://api.example.com/v1/chat/completions"


# ---------------- AC3: API key safety ----------------


def test_api_key_is_write_only_and_never_in_public_views(store):
    snapshot = _add(store)
    assert KEY not in json.dumps(snapshot)
    assert snapshot["custom_providers"][0]["credential_configured"] is True
    assert "api_key" not in snapshot["custom_providers"][0]
    # local storage keeps the plaintext (documented .env-level assumption)
    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["custom_providers"][0]["api_key"] == KEY
    # stored file is owner-only
    assert store.path.stat().st_mode & 0o777 == 0o600

    # editing without a key keeps the stored secret
    updated = store.update_provider("custom-deepseek", {"name": "改名"})
    assert KEY not in json.dumps(updated)
    assert g.load_api_key("custom-deepseek") == KEY
    # providing a key rotates it
    store.update_provider("custom-deepseek", {"api_key": NEW_KEY})
    assert g.load_api_key("custom-deepseek") == NEW_KEY
    # still write-only after rotation
    store.update_provider("custom-deepseek", {"models": ["m-only"]})
    assert g.load_api_key("custom-deepseek") == NEW_KEY


def test_probe_details_and_transport_errors_are_redacted(store, monkeypatch, caplog):
    _add(store)

    probed = probe_channel(
        "custom-deepseek", "classify", "glm-5.3-flash",
        probe=lambda *_: {"status": "auth_failed", "detail": f"401 rejected key {KEY}"},
    )
    assert probed["status"] == "auth_failed"
    assert KEY not in json.dumps(probed)
    assert "[redacted]" in probed["detail"]

    def boom(req, timeout=None):
        raise _http_error(req.full_url, 500, f'{{"detail":"upstream saw {KEY}"}}')

    monkeypatch.setattr(g.urllib.request, "urlopen", boom)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(g.GatewayError) as excinfo:
            g.post_gateway({"model": "m"}, provider="custom-deepseek", session="s", timeout=5)
    assert KEY not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)
    assert KEY not in caplog.text


def test_settings_and_telemetry_payloads_never_contain_the_key(store):
    from graph2note.telemetry import normalize_telemetry

    _add(store)
    store.update({"channels": {
        "parse_visual": {"provider": "custom-deepseek", "model": "glm-5.3-flash"},
    }})

    snapshot_blob = json.dumps(store.snapshot(), ensure_ascii=False)
    assert "custom-deepseek" in snapshot_blob
    assert KEY not in snapshot_blob
    assert "api_key" not in store.snapshot()["custom_providers"][0]

    telemetry = normalize_telemetry({
        "llm": {"provider": "custom-deepseek", "model": "glm-5.3-flash",
                "prompt_tokens": 3, "completion_tokens": 1},
    })
    telemetry_blob = json.dumps(telemetry, ensure_ascii=False)
    assert telemetry["provider"] == "custom-deepseek"
    assert KEY not in telemetry_blob


def test_missing_custom_key_is_reported_without_network(store, monkeypatch):
    _add(store, api_key="")

    def boom(*_a, **_k):  # pragma: no cover - must not run
        raise AssertionError("no HTTP call without a key")

    monkeypatch.setattr(g.urllib.request, "urlopen", boom)
    result = probe_channel("custom-deepseek", "classify", "glm-5.3-flash")
    assert result["status"] == "missing_credentials"
    assert "API Key" in result["detail"]
    with pytest.raises(g.GatewayError):
        g.load_api_key("custom-deepseek")


# ---------------- AC4: health probe 200 / 401 ----------------


def test_health_probe_custom_available(store, monkeypatch):
    _add(store)
    captured = _capture(monkeypatch)
    result = probe_channel("custom-deepseek", "classify", "deepseek-v4-flash")
    assert result["status"] == "available"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["authorization"] == f"Bearer {KEY}"
    assert captured["body"]["max_tokens"] == 1


def test_health_probe_custom_auth_failure_is_readable(store, monkeypatch):
    _add(store)

    def unauthorized(req, timeout=None):
        raise _http_error(req.full_url, 401, '{"error":"invalid api key"}')

    monkeypatch.setattr(g.urllib.request, "urlopen", unauthorized)
    result = probe_channel("custom-deepseek", "classify", "deepseek-v4-flash")
    assert result["status"] == "auth_failed"
    assert "401" in result["detail"]
    assert KEY not in json.dumps(result)


def test_probe_rejects_model_outside_provider_list(store):
    _add(store)
    result = probe_channel("custom-deepseek", "classify", "nope")
    assert result["status"] == "request_failed"
    assert result["detail"] == "配置无效"


# ---------------- AC5: visual + text routing ----------------


def test_visual_pipeline_routes_to_custom_provider(store, monkeypatch):
    from graph2note import vlm

    _add(store)
    store.update({"channels": {
        "parse_visual": {"provider": "custom-deepseek", "model": "glm-5.3-flash"},
        "ir_text": {"provider": "custom-deepseek", "model": "deepseek-v4-flash"},
    }})
    calls = []

    def fake_post(payload, **kwargs):
        calls.append((payload, kwargs))
        content = "# 标题\n普通正文" if isinstance(payload["messages"][-1]["content"], list) else "{}"
        return {"choices": [{"message": {"content": content}, "finish_reason": "stop"}], "usage": {}}

    monkeypatch.setattr(vlm, "load_api_key", lambda *_a, **_k: KEY)
    monkeypatch.setattr(vlm, "post_gateway", fake_post)

    _content, meta = vlm.call_ir(str(IMAGE), model=None)

    assert meta["provider"] == "custom-deepseek"
    assert meta["model"] == "glm-5.3-flash"
    assert meta["ir_provider"] == "custom-deepseek"
    assert meta["ir_model"] == "deepseek-v4-flash"
    assert calls[0][1]["provider"] == "custom-deepseek"
    assert all(call[1]["provider"] == "custom-deepseek" for call in calls)


def test_text_classification_routes_to_custom_provider(store, monkeypatch):
    from graph2note.notes import llm

    _add(store)
    store.update({"channels": {
        "classify": {"provider": "custom-deepseek", "model": "deepseek-v4-flash"},
    }})
    captured = {}

    monkeypatch.setattr("eval.gateway.load_api_key", lambda provider=None: KEY)

    def fake_post(payload, **kwargs):
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {"choices": [{"message": {"content": "{}"}}]}

    monkeypatch.setattr("eval.gateway.post_gateway", fake_post)

    assert llm._gateway_text("classify me") == "{}"
    assert captured["kwargs"]["provider"] == "custom-deepseek"
    assert captured["payload"]["model"] == "deepseek-v4-flash"


# ---------------- AC6: delete / edit fallback ----------------


def test_delete_provider_reverts_assignments_with_notice(store):
    _add(store)
    store.update({"channels": {
        "parse_visual": {"provider": "custom-deepseek", "model": "glm-5.3-flash"},
        "classify": {"provider": "custom-deepseek", "model": "deepseek-v4-flash"},
    }})

    result = store.delete_provider("custom-deepseek")

    assert "custom-deepseek" not in [p["id"] for p in result["providers"]]
    assert result["custom_providers"] == []
    assert {item["purpose"] for item in result["reverted"]} == {"parse_visual", "classify"}
    assert "回退默认" in result["notice"]
    assert store.resolve("parse_visual")["provider"] != "custom-deepseek"
    assert store.resolve("classify")["provider"] != "custom-deepseek"
    assert "custom-deepseek" not in json.dumps(store.snapshot()["providers"])


def test_update_provider_model_removal_reverts_stale_assignment(store):
    _add(store)
    store.update({"channels": {
        "classify": {"provider": "custom-deepseek", "model": "deepseek-v4-flash"},
    }})

    result = store.update_provider("custom-deepseek", {"models": ["glm-5.3-flash"]})

    assert [item["purpose"] for item in result["reverted"]] == ["classify"]
    assert "回退默认" in result["notice"]
    assert store.resolve("classify")["provider"] != "custom-deepseek"


def test_delete_provider_without_assignments_has_clean_notice(store):
    _add(store)
    result = store.delete_provider("custom-deepseek")
    assert result["reverted"] == []
    assert "无用途指派受影响" in result["notice"]


def test_unknown_provider_operations_raise(store):
    with pytest.raises(SettingsError):
        store.update_provider("custom-nope", {"name": "x"})
    with pytest.raises(SettingsError):
        store.delete_provider("custom-nope")
    with pytest.raises(SettingsError):
        store.refresh_provider_models("custom-nope")
    with pytest.raises(g.GatewayError):
        g.gateway_config("custom-nope")


# ---------------- validation ----------------


@pytest.mark.parametrize("bad", [
    {"base_url": "ftp://api.example.com/v1"},
    {"base_url": ""},
    {"base_url": "https:// api.example.com/v1"},
    {"models": []},
    {"models": "  ,  "},
    {"name": ""},
])
def test_invalid_provider_payloads_are_rejected(store, bad):
    payload = {"name": "n", "base_url": "https://api.example.com/v1",
               "api_key": KEY, "models": ["m"]}
    payload.update(bad)
    with pytest.raises(SettingsError):
        store.add_provider(payload)
    assert not store.path.exists()


def test_builtin_provider_id_cannot_be_shadowed(store):
    with pytest.raises(SettingsError):
        store.add_provider({"id": "deepseek", "name": "x",
                            "base_url": "https://x.example/v1", "models": ["m"]})
    snapshot = _add(store)
    assert snapshot["custom_providers"][0]["id"].startswith(CUSTOM_PROVIDER_PREFIX)
    assert g.gateway_config("deepseek")["base"] == "https://api.deepseek.com"


# ---------------- optional bonus: /models discovery ----------------


def test_refresh_models_reads_openai_and_ollama_shapes(store, monkeypatch):
    _add(store)

    monkeypatch.setattr(g.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp({"data": [{"id": "b"}, {"id": "a"}]}))
    snapshot = store.refresh_provider_models("custom-deepseek")
    assert snapshot["custom_providers"][0]["models"] == ["a", "b"]

    monkeypatch.setattr(g.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp({"models": [{"name": "m2"}, {"name": "m1"}]}))
    snapshot = store.refresh_provider_models("custom-deepseek")
    assert snapshot["custom_providers"][0]["models"] == ["m1", "m2"]


def test_refresh_models_failure_is_a_settings_error(store, monkeypatch):
    _add(store)

    def unauthorized(req, timeout=None):
        raise _http_error(req.full_url, 401, f'{{"detail":"{KEY}"}}')

    monkeypatch.setattr(g.urllib.request, "urlopen", unauthorized)
    with pytest.raises(SettingsError) as excinfo:
        store.refresh_provider_models("custom-deepseek")
    assert KEY not in str(excinfo.value)
    assert "401" in str(excinfo.value)


def test_refresh_models_falls_back_channels_when_model_disappears(store, monkeypatch):
    _add(store)
    store.update({"channels": {
        "classify": {"provider": "custom-deepseek", "model": "deepseek-v4-flash"},
    }})
    monkeypatch.setattr(g.urllib.request, "urlopen",
                        lambda req, timeout=None: _FakeResp({"data": [{"id": "glm-5.3-flash"}]}))
    snapshot = store.refresh_provider_models("custom-deepseek")
    assert snapshot["custom_providers"][0]["models"] == ["glm-5.3-flash"]
    assert [item["purpose"] for item in snapshot["reverted"]] == ["classify"]
    assert store.resolve("classify")["provider"] != "custom-deepseek"
