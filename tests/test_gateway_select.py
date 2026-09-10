"""网关选择（GRAPH2NOTE_GATEWAY=opencode|deepseek）的离线单测。

mock urlopen 捕获请求（URL/头/payload），不触网。覆盖单一 choke point：
端点、认证 key、session 头、模型名映射、无会话网关跳过直出验证。
"""

import json

import pytest

from eval import gateway as g


class _FakeResp:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def capture_request(monkeypatch):
    """捕获 post_gateway 发出的 urllib Request，返回 (holder, fake_urlopen)。"""
    holder = {}

    def fake_urlopen(req, timeout=None):
        holder["url"] = req.full_url
        holder["headers"] = {k.lower(): v for k, v in req.headers.items()}
        holder["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResp({"choices": [{"message": {"content": "ok"}}],
                          "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    monkeypatch.setattr(g.urllib.request, "urlopen", fake_urlopen)
    return holder


# ---------------- 网关选择与配置解析 ----------------
# 注意：网关选择支持 .env 回退（与 key 一致），仓库真实 .env 可能配置 deepseek；
# 涉及「默认/opencode」的断言一律显式 setenv，保证测试不依赖本机 .env 内容。

def test_explicit_opencode_gateway(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    assert g.active_gateway_name() == "opencode"
    assert g.chat_completions_url() == "https://opencode.ai/zen/go/v1/chat/completions"


def test_deepseek_gateway_selected_by_env(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    assert g.active_gateway_name() == "deepseek"
    assert g.chat_completions_url() == "https://api.deepseek.com/chat/completions"


def test_gateway_selection_falls_back_to_dotenv(monkeypatch, tmp_path):
    # 进程未 export 时，改 .env 即生效（cwd/.env 优先于仓库根）
    env_file = tmp_path / ".env"
    env_file.write_text('GRAPH2NOTE_GATEWAY=deepseek\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GRAPH2NOTE_GATEWAY", raising=False)
    assert g.active_gateway_name() == "deepseek"


def test_unknown_gateway_raises(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "bogus")
    with pytest.raises(g.GatewayError):
        g.active_gateway_name()


# ---------------- post_gateway：端点 / 头 / 模型映射（choke point） ----------------

def test_opencode_request_carries_session_header(monkeypatch, capture_request):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "op-key")
    g.post_gateway({"model": "glm-5.3-flash"}, session="s1", timeout=5, api_key=None)
    assert capture_request["url"] == "https://opencode.ai/zen/go/v1/chat/completions"
    assert capture_request["headers"]["x-opencode-session"] == "s1"
    assert capture_request["headers"]["authorization"] == "Bearer op-key"
    # opencode 网关不翻译模型名
    assert capture_request["body"]["model"] == "glm-5.3-flash"


def test_deepseek_request_maps_endpoint_model_and_headers(monkeypatch, capture_request):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    g.post_gateway({"model": "glm-5.3-flash"}, session="s1", timeout=5, api_key=None)
    assert capture_request["url"] == "https://api.deepseek.com/chat/completions"
    assert capture_request["headers"]["authorization"] == "Bearer ds-key"
    # 无会话语义：不携带 x-opencode-session
    assert "x-opencode-session" not in capture_request["headers"]
    # parse 默认视觉模型被翻译为官方视觉别名
    assert capture_request["body"]["model"] == "deepseek-v4-flash-vision-exp"


def test_model_mapping_table(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    assert g.map_model("glm-5.3-flash") == "deepseek-v4-flash-vision-exp"
    assert g.map_model("deepseek-v4-flash") == "deepseek-flash"
    assert g.map_model("deepseek-v4-flash-vision-exp") == "deepseek-v4-flash-vision-exp"
    assert g.map_model("some-future-model") == "some-future-model"  # 未知名透传，由网关报错


def test_model_mapping_inactive_on_opencode(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    assert g.map_model("glm-5.3-flash") == "glm-5.3-flash"


# ---------------- load_api_key：按网关取 key ----------------

def test_load_api_key_env_beats_gateway_selection(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-key")
    assert g.load_api_key() == "ds-key"
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "opencode")
    monkeypatch.setenv("OPENCODE_API_KEY", "op-key")
    assert g.load_api_key() == "op-key"


def test_load_api_key_file_fallback_respects_gateway(monkeypatch, tmp_path):
    # 无 env 时按网关读对应 key：.env 文件回退也走 key_env（而非写死 OPENCODE）。
    # 假 .env 同时写入网关键，避免回退触达仓库根真实 .env（cwd 候选优先命中）。
    env_file = tmp_path / ".env"
    env_file.write_text(
        'OPENCODE_API_KEY="file-op"\nDEEPSEEK_API_KEY="file-ds"\n'
        'GRAPH2NOTE_GATEWAY=opencode\n',
        encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("GRAPH2NOTE_GATEWAY", raising=False)

    assert g.load_api_key() == "file-op"
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    assert g.load_api_key() == "file-ds"


# ---------------- 无会话网关跳过直出验证 ----------------

def test_maybe_validate_direct_skipped_on_deepseek(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_GATEWAY", "deepseek")
    monkeypatch.setenv("GRAPH2NOTE_VALIDATE_SESSIONS", "1")

    def boom(*a, **kw):  # pragma: no cover - 一旦触网/被调用即失败
        raise AssertionError("session probe must not run on session-less gateways")

    monkeypatch.setattr(g, "validate_session_direct", boom)
    assert g.maybe_validate_direct("parse") is None
