"""用途隔离 session：产品管线(parse)/verify 对统一配置的正确委托（离线、不触网）。"""

import pytest

from eval import gateway as g
import graph2note.vlm as vlm


def test_vlm_parse_resolves_purpose_default():
    assert vlm.resolve_session("glm-5.3-flash") == "graph2note-parse-01"


def test_vlm_parse_respects_purpose_env(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_SESSION_PARSE", "my-parse")
    assert vlm.resolve_session("glm-5.3-flash") == "my-parse"


def test_vlm_parse_legacy_env_override(monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_SESSION_PARSE", "")
    monkeypatch.setenv("GRAPH2NOTE_OPENCODE_SESSION", "old-route")
    assert vlm.resolve_session("glm-5.3-flash") == "old-route"


def test_router_default_session_is_none_then_parse_purpose():
    # router 默认 session=None → vlm.call_ir 内部解析到 parse 用途会话
    from graph2note.router import RouteARouter
    import inspect
    sig = inspect.signature(RouteARouter.__init__)
    assert sig.parameters["session"].default is None
    assert vlm.resolve_session("glm-5.3-flash") == "graph2note-parse-01"


def test_verify_session_base_is_isolated():
    # verify 用途独立默认（graph2note-verify-01），非 parse/eval
    base = g.resolve_session_for("verify")
    assert base == "graph2note-verify-01"
    assert base != g.resolve_session_for("parse")
    assert base != g.resolve_session_for("eval")


def test_three_purposes_fully_isolated():
    assert g.DEFAULT_PURPOSE_SESSIONS == {
        "parse": "graph2note-parse-01",
        "eval": "graph2note-eval-01",
        "verify": "graph2note-verify-01",
    }