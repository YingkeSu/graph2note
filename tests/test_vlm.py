"""VLM JSON extraction + gateway cache tests (offline)."""

import json

import pytest

from graph2note import vlm


def test_parse_plain_json_object():
    obj = {"document_type": "note", "blocks": []}
    assert vlm.parse_ir_json(json.dumps(obj)) == obj


def test_parse_json_code_fence():
    body = '```json\n{"blocks": []}\n```'
    assert vlm.parse_ir_json(body) == {"blocks": []}


def test_parse_prose_then_json():
    body = '好的，这是解析结果：\n{"document_type": "note", "blocks": [{"type": "paragraph", "text": "hi"}]}\n以上。'
    out = vlm.parse_ir_json(body)
    assert out["blocks"][0]["type"] == "paragraph"


def test_parse_empty_returns_none():
    assert vlm.parse_ir_json("") is None
    assert vlm.parse_ir_json("   ") is None


def test_parse_invalid_returns_none():
    assert vlm.parse_ir_json("not json here") is None
    assert vlm.parse_ir_json('{"unclosed": ') is None


def test_parse_array_returns_none():
    # A JSON array is not a valid IR object -> None -> triggers retry path.
    assert vlm.parse_ir_json("[1, 2, 3]") is None


def test_cache_roundtrip(tmp_path):
    src = tmp_path / "img.jpg"
    src.write_bytes(b"\xff\xd8\xff\xe0fakepngbytes")
    cache = vlm.VlmCache(str(tmp_path / "cache"))
    assert cache.get(str(src), "m") is None
    cache.put(str(src), "m", '{"blocks": []}', {"model": "m"})
    got = cache.get(str(src), "m")
    assert got is not None


@pytest.mark.parametrize(
    "gateway,key_env,key_val",
    [
        ("opencode", "OPENCODE_API_KEY", "sk-test-op"),
        ("deepseek", "DEEPSEEK_API_KEY", "sk-test-ds"),
    ],
)
def test_load_api_key_absent_env_only(monkeypatch, gateway, key_env, key_val):
    # We only verify that an env var is honored per active gateway; no key
    # is required offline. Gateway is set explicitly so the repo's real .env
    # (which may switch gateways) cannot leak into the assertion.
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", gateway)
    monkeypatch.setenv(key_env, key_val)
    assert vlm.load_api_key() == key_val