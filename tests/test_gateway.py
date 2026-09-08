"""eval.gateway 提速修复的离线单测（R1/R2/R4/R3；mock transport，不触网）。"""

import os

import pytest

from eval import gateway as g


# ---------------- R1：session 配置与告警阈值 ----------------

def test_resolve_sessions_default_per_model():
    s = g.resolve_sessions("glm-5.3-flash")
    assert s[0] == "graph2note-spike-01"
    # 默认无备选 → 单元素
    assert s == ["graph2note-spike-01"]


def test_resolve_sessions_env_override_and_dedup(monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION", "custom-main")
    monkeypatch.setenv("OPENCODE_SESSIONS", "a,b,a,graph2note-spike-01")
    s = g.resolve_sessions("glm-5.3-flash")
    assert s == ["custom-main", "a", "b", "graph2note-spike-01"]


def test_warnings_for_below_threshold():
    assert g.warnings_for(100, 3500) == []
    assert g.warnings_for(None, 3500) == []


def test_warnings_for_high_and_capped():
    w = g.warnings_for(900, 3500)
    assert "reasoning_high" in w
    # 思考吃满预算 → capped 告警
    w2 = g.warnings_for(3500, 3500)
    assert "reasoning_high" in w2 and "reasoning_runaway_capped" in w2


def test_cache_namespace_stable_and_sensitive(monkeypatch):
    ns1 = g.cache_namespace()
    assert len(ns1) == 12
    monkeypatch.setenv("OPENCODE_FIRST_MAX_TOKENS", "9000")
    assert g.cache_namespace() != ns1


# ---------------- R2/R4：策略状态机（mock _raw_call） ----------------

def _fake_raw(script):
    """返回一个按调用序号依次返回 script[i] 的假 _raw_call。"""
    it = iter(script)

    def _f(*args, **kwargs):
        return next(it)
    return _f


def _ok(content="正文", reasoning=None, finish="stop"):
    meta = {
        "status": "ok", "error": None, "model": "glm-5.3-flash", "session": "s",
        "max_tokens": 3500, "latency_seconds": 7.0, "prompt_tokens": 1000,
        "completion_tokens": 300, "total_tokens": 1300, "reasoning_tokens": reasoning,
        "finish_reason": finish, "cost": "0", "prep": {}, "warnings": g.warnings_for(reasoning, 3500),
    }
    return content, meta


def test_policy_first_call_success_no_retry(monkeypatch):
    monkeypatch.setattr(g, "_raw_call", _fake_raw([_ok("正文", reasoning=50)]))
    content, meta = g.transcribe_with_policy("img.jpg", "glm-5.3-flash", sessions=["s1"], api_key="k")
    assert content == "正文"
    assert meta["retried"] is False
    assert len(meta["attempts"]) == 1
    assert meta["attempts"][0]["attempt_kind"] == "first_direct"
    assert meta["attempts"][0]["reasoning_tokens"] == 50


def test_policy_empty_escalates_and_switches(monkeypatch):
    # 首调空内容(length)，第二档换 session/升预算成功 → retried
    first = _ok("", reasoning=3490, finish="length")
    second = _ok("正文", reasoning=400, finish="stop")
    second[1]["session"] = "s2"
    second[1]["max_tokens"] = 10000
    calls = {"n": 0}

    def fake(*a, **kw):
        i = calls["n"]
        calls["n"] += 1
        if i == 0:
            m = dict(first[1]); m["session"] = kw["session"]; m["max_tokens"] = kw["max_tokens"]
            return "", m
        m = dict(second[1]); m["session"] = kw["session"]; m["max_tokens"] = kw["max_tokens"]
        return "正文", m

    monkeypatch.setattr(g, "_raw_call", fake)
    content, meta = g.transcribe_with_policy("img.jpg", "glm-5.3-flash", sessions=["s1", "s2"], api_key="k")
    assert content == "正文"
    assert meta["retried"] is True
    assert len(meta["attempts"]) == 2
    assert meta["attempts"][0]["session"] == "s1"
    assert meta["attempts"][1]["session"] == "s2"           # 换 session
    assert meta["attempts"][1]["max_tokens"] == 10000       # 升预算
    assert meta["attempts"][0]["warnings"] == ["reasoning_high"]


def test_policy_timeout_no_retry(monkeypatch):
    # R4：超时不隐性双倍调用 —— 只发生 1 次调用
    tm = {"status": "timeout", "error": "socket timeout", "model": "m", "session": "s1",
          "max_tokens": 3500, "latency_seconds": 120.0, "prompt_tokens": None,
          "completion_tokens": None, "total_tokens": None, "reasoning_tokens": None,
          "finish_reason": None, "cost": None, "prep": {}, "warnings": []}
    count = {"n": 0}

    def fake(*a, **kw):
        count["n"] += 1
        return "", dict(tm, session=kw["session"])

    monkeypatch.setattr(g, "_raw_call", fake)
    content, meta = g.transcribe_with_policy("img.jpg", "m", sessions=["s1", "s2"], api_key="k")
    assert count["n"] == 1
    assert meta["status"] == "timeout"
    assert meta["retried"] is False


def test_policy_all_empty_marks_empty(monkeypatch):
    a = _ok("", reasoning=300, finish="length")
    b = _ok("", reasoning=200, finish="length")

    def fake(*a_, **kw):
        m = dict(a[1], session=kw["session"], max_tokens=kw["max_tokens"])
        return "", m

    monkeypatch.setattr(g, "_raw_call", fake)
    content, meta = g.transcribe_with_policy("img.jpg", "m", sessions=["s1"], api_key="k")
    assert content == ""
    assert meta["status"] == "empty"
    assert meta["retried"] is True


def test_transcribe_image_raises_on_failure(monkeypatch):
    bad = {"status": "error", "error": "boom", "model": "m", "session": "s", "max_tokens": 3500,
           "latency_seconds": 1.0, "prompt_tokens": None, "completion_tokens": None,
           "total_tokens": None, "reasoning_tokens": None, "finish_reason": None,
           "cost": None, "prep": {}, "warnings": []}
    monkeypatch.setattr(g, "_raw_call", lambda *a, **kw: ("", dict(bad, session=kw["session"])))
    with pytest.raises(g.GatewayError):
        g.transcribe_image("img.jpg", "m", session="s", api_key="k")


# ---------------- R3：降采样 ----------------

def test_prepare_image_downscales(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    img = tmp_path / "big.png"
    Image.new("RGB", (2000, 1000), (200, 200, 200)).save(img, "PNG")
    out, prep = g.prepare_image(str(img))
    assert out != str(img)                          # 生成了降采样临时文件
    assert prep["resized"]["resized"] is True
    assert prep["resized"]["width"] == 1024
    assert prep["resized"]["height"] == 512
    assert prep["resized"]["bytes"] > 0
    assert os.path.getsize(out) < os.path.getsize(str(img))
    os.remove(out)


def test_prepare_image_small_untouched(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    img = tmp_path / "small.png"
    Image.new("RGB", (512, 512), (0, 0, 0)).save(img, "PNG")
    out, prep = g.prepare_image(str(img))
    assert out == str(img)
    assert prep["resized"]["resized"] is False


def test_prepare_image_disabled(tmp_path):
    out, prep = g.prepare_image(__file__, enabled=False)
    assert out == __file__
    assert "skipped" in prep