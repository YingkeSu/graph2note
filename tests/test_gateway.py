"""eval.gateway 提速修复的离线单测（R1/R2/R4/R3；mock transport，不触网）。"""

import os

import pytest

from eval import gateway as g


# ---------------- R1：session 配置与告警阈值 ----------------

def test_resolve_sessions_eval_default_purpose_isolated():
    # eval 用途默认独立会话（不再与 parse 共享 spike-01 → 避免并发争用）
    s = g.resolve_sessions("glm-5.3-flash")
    assert s[0] == "graph2note-eval-01"
    assert s == ["graph2note-eval-01"]


def test_resolve_sessions_env_override_and_dedup(monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION", "custom-main")
    monkeypatch.setenv("OPENCODE_SESSIONS", "a,b,a,graph2note-eval-01")
    s = g.resolve_sessions("glm-5.3-flash")
    assert s == ["custom-main", "a", "b", "graph2note-eval-01"]


# ---------------- 用途隔离：配置解析与 session 选择 --------------

def test_default_purpose_sessions_are_distinct():
    assert g.resolve_session_for("parse") == "graph2note-parse-01"
    assert g.resolve_session_for("eval") == "graph2note-eval-01"
    assert g.resolve_session_for("verify") == "graph2note-verify-01"
    assert g.resolve_session_for("routeb") == "graph2note-routeb-01"
    # parse/eval/verify/routeb 各自独立，互不相同
    parsed = {g.resolve_session_for(p) for p in g.PURPOSES}
    assert len(parsed) == 4


def test_resolve_session_for_case_insensitive():
    assert g.resolve_session_for("Parse") == g.resolve_session_for("parse")


def test_resolve_session_for_unknown_purpose_raises():
    with pytest.raises(ValueError):
        g.resolve_session_for("bogus")


def test_purpose_env_overrides_default(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_SESSION_PARSE", "my-parse-sess")
    assert g.resolve_session_for("parse") == "my-parse-sess"
    monkeypatch.setenv("GRAPH2NOTE_SESSION_VERIFY", "my-verify-sess")
    assert g.resolve_session_for("verify") == "my-verify-sess"
    # 互不影响
    assert g.resolve_session_for("eval") == "graph2note-eval-01"


def test_purpose_env_beats_legacy(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_SESSION_PARSE", "dedicated")
    monkeypatch.setenv("OPENCODE_SESSION", "legacy")
    monkeypatch.setenv("GRAPH2NOTE_OPENCODE_SESSION", "legacy2")
    assert g.resolve_session_for("parse") == "dedicated"


def test_legacy_envs_override_default(monkeypatch):
    monkeypatch.setenv("OPENCODE_SESSION", "legacy")
    assert g.resolve_session_for("parse") == "legacy"
    assert g.resolve_session_for("eval") == "legacy"
    monkeypatch.setenv("GRAPH2NOTE_OPENCODE_SESSION", "legacy2")
    assert g.resolve_session_for("verify") == "legacy2"


def test_purpose_env_name():
    assert g.purpose_session_env("parse") == "GRAPH2NOTE_SESSION_PARSE"
    assert g.purpose_session_env("eval") == "GRAPH2NOTE_SESSION_EVAL"
    assert g.purpose_session_env("verify") == "GRAPH2NOTE_SESSION_VERIFY"


# ---------------- 会话直出验证（mock _raw_call，不触网） ----------------

def _val_resp(reasoning, content="ok", status="ok"):
    meta = {
        "status": status, "error": None, "model": "glm-5.3-flash", "session": "s",
        "max_tokens": 64, "latency_seconds": 1.0, "prompt_tokens": 1,
        "completion_tokens": 1, "total_tokens": 2, "reasoning_tokens": reasoning,
        "finish_reason": "stop", "cost": "0", "prep": {}, "warnings": [],
    }
    return content, meta


def test_validate_session_direct_low_reasoning_true(monkeypatch, tmp_path):
    g.reset_direct_validation_cache()
    calls = {"n": 0}

    def fake(*a, **kw):
        calls["n"] += 1
        return _val_resp(50)

    monkeypatch.setattr(g, "_raw_call", fake)
    rec = g.validate_session_direct("parse")
    assert rec["direct"] is True
    assert rec["reasoning_tokens"] == 50
    assert rec["purpose"] == "parse"
    assert rec["session"] == "graph2note-parse-01"
    assert calls["n"] == 1
    # 进程级缓存：第二次不再触网（仍只 1 次 _raw_call）
    g.validate_session_direct("parse")
    assert calls["n"] == 1


def test_validate_session_direct_high_reasoning_false(monkeypatch):
    g.reset_direct_validation_cache()
    monkeypatch.setattr(g, "_raw_call", lambda *a, **kw: _val_resp(900))
    rec = g.validate_session_direct("eval", threshold=800)
    assert rec["direct"] is False  # reasoning 900 > 阈值 → 非直出
    assert rec["reasoning_tokens"] == 900


def test_validate_session_direct_empty_content_low_reasoning_is_direct(monkeypatch):
    # 探针预算很小时，低推理 + 内容字节 0 是预算没留出内容位的伪影，非推理吃满预算 → direct
    g.reset_direct_validation_cache()
    monkeypatch.setattr(g, "_raw_call", lambda *a, **kw: _val_resp(50, content=""))
    rec = g.validate_session_direct("verify")
    assert rec["direct"] is True
    assert rec["content_len"] == 0


def test_validate_session_direct_reasoning_runaway_false(monkeypatch):
    # issue-12 签名：无内容 且 reasoning 填满整个 max_tokens（推理独占预算）→ 非直出
    g.reset_direct_validation_cache()
    monkeypatch.setattr(g, "_raw_call", lambda *a, **kw: _val_resp(64, content=""))
    rec = g.validate_session_direct("parse")
    assert rec["direct"] is False
    assert rec["reasoning_tokens"] == 64


def test_validate_session_direct_error_false(monkeypatch):
    g.reset_direct_validation_cache()
    monkeypatch.setattr(g, "_raw_call", lambda *a, **kw: _val_resp(None, status="error", content=""))
    rec = g.validate_session_direct("eval")
    assert rec["direct"] is False


def test_validate_session_direct_probe_image_written(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    p = g.probe_image_path()
    assert os.path.exists(p)
    assert os.path.getsize(p) > 0


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

# ---------------- 会话健康巡检（proxy：纯 session_health 聚合） ----------------

def test_session_health_all_ok():
    rows = [
        {"purpose": "parse", "direct": True},
        {"purpose": "eval", "direct": True},
        {"purpose": "verify", "direct": True},
    ]
    ok, bad = g.session_health(rows)
    assert ok is True
    assert bad == []


def test_session_health_any_degraded():
    rows = [
        {"purpose": "parse", "direct": True},
        {"purpose": "eval", "direct": False},
        {"purpose": "verify", "direct": True},
    ]
    ok, bad = g.session_health(rows)
    assert ok is False
    assert bad == ["eval"]


def test_session_health_empty_records():
    ok, bad = g.session_health([])
    assert ok is True
    assert bad == []
