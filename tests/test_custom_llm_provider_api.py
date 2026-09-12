"""Issue A3: custom provider CRUD over the local web API + settings UI (integration).

Uses FastAPI's TestClient with an injected probe; the optional /models fetch stubs
urllib so CI stays fully offline.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest
from fastapi.testclient import TestClient

from eval import gateway as g
from graph2note.llm_settings import MODEL_PURPOSES, configure_settings_path
from graph2note.webapp import create_app

KEY = "sk-api-secret-abcdef"


class _FakeResp:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _reset_runtime_settings_path(monkeypatch):
    monkeypatch.delenv("GRAPH2NOTE_SETTINGS_FILE", raising=False)
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    yield
    configure_settings_path(None)


def _client(tmp_path, probe=None):
    return TestClient(create_app(storage_dir=tmp_path, llm_probe=probe))


def _create(client, **overrides):
    payload = {"name": "DeepSeek 兼容", "base_url": "https://api.deepseek.com",
               "api_key": KEY, "models": "glm-5.3-flash, deepseek-v4-flash"}
    payload.update(overrides)
    return client.post("/api/llm/providers", json=payload)


def test_provider_crud_api_roundtrip_is_key_safe(tmp_path):
    client = _client(tmp_path)

    before = client.get("/api/llm/settings").json()
    assert before["custom_providers"] == []
    assert [p["id"] for p in before["providers"]] == ["opencode", "deepseek", "kimi"]

    created = _create(client)
    assert created.status_code == 200, created.text
    body = created.json()
    assert KEY not in created.text
    provider = body["custom_providers"][0]
    assert provider == {
        "id": "custom-deepseek", "name": "DeepSeek 兼容",
        "base_url": "https://api.deepseek.com",
        "models": ["glm-5.3-flash", "deepseek-v4-flash"],
        "credential_configured": True,
    }
    assert "notice" in body

    # GET after a restart of the app instance stays secret-free and persistent
    restarted = _client(tmp_path)
    fetched = restarted.get("/api/llm/settings")
    assert KEY not in fetched.text
    assert fetched.json()["custom_providers"] == [provider]

    # assign the custom endpoint to a purpose and confirm it survives a reload
    assigned = client.put("/api/llm/settings", json={"channels": {
        "parse_visual": {"provider": "custom-deepseek", "model": "glm-5.3-flash"},
    }})
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["channels"]["parse_visual"]["provider"] == "custom-deepseek"
    assert _client(tmp_path).get("/api/llm/settings").json()["channels"]["parse_visual"] == {
        "provider": "custom-deepseek", "model": "glm-5.3-flash",
        "purpose": "parse_visual", "label": "解析视觉",
    }

    # edit without a key keeps the stored secret; response still leaks nothing
    updated = client.put("/api/llm/providers/custom-deepseek", json={"name": "改名供应商"})
    assert updated.status_code == 200, updated.text
    assert KEY not in updated.text
    assert updated.json()["custom_providers"][0]["name"] == "改名供应商"
    assert updated.json()["custom_providers"][0]["credential_configured"] is True

    # delete reverts assignments with a readable notice
    deleted = client.delete("/api/llm/providers/custom-deepseek")
    assert deleted.status_code == 200, deleted.text
    deleted_body = deleted.json()
    assert deleted_body["custom_providers"] == []
    assert [item["purpose"] for item in deleted_body["reverted"]] == ["parse_visual"]
    assert "回退默认" in deleted_body["notice"]
    assert deleted.json()["channels"]["parse_visual"]["provider"] == "opencode"


def test_provider_api_validation_and_unknown_provider(tmp_path):
    client = _client(tmp_path)

    assert _create(client, base_url="ftp://api.example.com").status_code == 422
    assert _create(client, models="  ,  ").status_code == 422
    assert _create(client, name="").status_code == 422
    assert client.put("/api/llm/providers/custom-nope", json={"name": "x"}).status_code == 422
    assert client.delete("/api/llm/providers/custom-nope").status_code == 422
    assert client.post("/api/llm/providers/custom-nope/models").status_code == 422
    # nothing was persisted by the rejected creates
    assert client.get("/api/llm/settings").json()["custom_providers"] == []


def test_health_endpoint_probes_custom_channel(tmp_path):
    seen = []

    def probe(provider, purpose, model):
        seen.append((provider, purpose, model))
        return {"status": "auth_failed", "detail": f"401 for {KEY}"}

    client = _client(tmp_path, probe=probe)
    _create(client)
    client.put("/api/llm/settings", json={"channels": {
        "classify": {"provider": "custom-deepseek", "model": "deepseek-v4-flash"},
    }})

    response = client.post("/api/llm/health")
    assert response.status_code == 200
    assert KEY not in response.text
    channels = response.json()["channels"]
    assert {item["purpose"] for item in channels} == set(MODEL_PURPOSES)
    custom = [item for item in channels if item["provider"] == "custom-deepseek"]
    assert len(custom) == 1
    assert custom[0]["status"] == "auth_failed"
    assert "[redacted]" in custom[0]["detail"]
    assert ("custom-deepseek", "classify", "deepseek-v4-flash") in seen


def test_settings_ui_exposes_custom_provider_controls(tmp_path):
    client = _client(tmp_path)
    html = client.get("/").text
    javascript = client.get("/static/app.js").text

    for element_id in ("llm-custom-form", "llm-custom-name", "llm-custom-base",
                       "llm-custom-key", "llm-custom-models", "llm-custom-list"):
        assert f'id="{element_id}"' in html
    assert "自定义供应商" in html
    assert "/api/llm/providers" in javascript
    assert "custom_providers" in javascript
    # The key input is a password field; the JS only sends what the user typed.
    assert 'type="password"' in html
    assert "if (apiKey) body.api_key = apiKey;" in javascript


def test_fetch_models_endpoint_persists_discovered_models(tmp_path, monkeypatch):
    client = _client(tmp_path)
    _create(client)

    def fake_urlopen(req, timeout=None):
        assert req.full_url == "https://api.deepseek.com/models"
        assert req.headers["Authorization"] == f"Bearer {KEY}"
        return _FakeResp({"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})

    monkeypatch.setattr(g.urllib.request, "urlopen", fake_urlopen)
    response = client.post("/api/llm/providers/custom-deepseek/models")
    assert response.status_code == 200, response.text
    assert response.json()["custom_providers"][0]["models"] == [
        "deepseek-chat", "deepseek-reasoner",
    ]
    assert client.get("/api/llm/settings").json()["custom_providers"][0]["models"] == [
        "deepseek-chat", "deepseek-reasoner",
    ]

    def unauthorized(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 401, "err", {},
                                     io.BytesIO(f'{{"detail":"{KEY}"}}'.encode("utf-8")))

    monkeypatch.setattr(g.urllib.request, "urlopen", unauthorized)
    failed = client.post("/api/llm/providers/custom-deepseek/models")
    assert failed.status_code == 422
    assert KEY not in failed.text
