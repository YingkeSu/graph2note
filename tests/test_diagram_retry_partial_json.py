"""X2 — 抽取重试缺口：半截 JSON（``finish_reason=length`` + 非空内容）也要触发
一次预算升级重试。

D5a reviewer run 2 的 01：1 次 HTTP 调用，8000 预算 -> ``length`` +
``content_len=524``（半截 JSON）-> ``parse_fail``，没有第二次尝试。本文件把
``extract_diagram_image`` 的重试条件逐条锁住：

  ① 空正文 + length            -> 升级重试（既有行为，不回归）；
  ② 非空 length + 不可解析      -> 升级重试（X2 新增）；
  ③ 非空 length + 可解析        -> 不重试（避免浪费）；
  ④ 非 length 的 parse_fail     -> 不重试（不引入同参重试）；
  ⑤ 重试后仍失败 -> 降级 parse_fail + attempts 2 / retried=true。

全部离线（fake ``_post``），无网络。
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from graph2note import diagram, vlm  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG01 = ROOT / "test-images" / "01-requirements-arch.jpg"

GOOD_JSON = json.dumps({"nodes": [{"id": "n1", "label": "输入"},
                                 {"id": "n2", "label": "输出"}],
                        "edges": [{"from": "n1", "to": "n2", "label": ""}]})
# 半截 JSON：长度耗尽把最后一个大括号/引号截掉了，try_parse_json 必然失败。
TRUNCATED_JSON = '{"nodes": [{"id": "n1", "label": "\u8f93\u5165"}, {"id": "n2", "lab'


def _reply(content, finish):
    return {"choices": [{"message": {"content": content}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 1,
                      "total_tokens": 101},
            "cost": "0"}


@pytest.fixture
def patch_gateway(monkeypatch):
    """Install a scripted ``_post`` and a key loader; return the call log."""

    def install(handler):
        calls = []

        def fake_post(payload, *, key, sess, timeout, provider=None):
            calls.append(payload)
            return handler(payload, len(calls))

        monkeypatch.setattr("graph2note.diagram._post", fake_post)
        monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
        return calls

    return install


def test_truncated_json_at_attempt0_upgrades_and_recovers(patch_gateway):
    """② 非空 length + 不可解析 -> 升级预算重试；第二次成功则 ok。

    这正是 D5a run 2 的 01 场景：修好之后同一次运行应出现第二次调用。
    """

    def handler(payload, call_no):
        if payload["max_tokens"] == diagram.DIAGRAM_MAX_TOKENS:
            return _reply(TRUNCATED_JSON, "length")
        return _reply(GOOD_JSON, "stop")

    calls = patch_gateway(handler)
    res = diagram.extract_diagram_image(str(IMG01), session="s")

    assert res["ok"] is True and res["verdict"] == "ok"
    assert len(calls) == 2
    assert calls[0]["max_tokens"] == diagram.DIAGRAM_MAX_TOKENS
    assert calls[1]["max_tokens"] == diagram.DIAGRAM_RETRY_TOKENS
    assert res["meta"]["retried"] is True
    assert [a["finish_reason"] for a in res["meta"]["attempts"]] == ["length", "stop"]
    assert res["meta"]["attempts"][0]["content_len"] == len(TRUNCATED_JSON)
    assert res["nodes"] == [{"id": "n1", "label": "输入"},
                            {"id": "n2", "label": "输出"}]


def test_truncated_json_still_failing_after_upgrade_degrades(patch_gateway):
    """⑤ 重试后仍失败：降级 parse_fail，attempts=2、retried=true。"""

    calls = patch_gateway(lambda payload, call_no: _reply(TRUNCATED_JSON, "length"))
    res = diagram.extract_diagram_image(str(IMG01), session="s")

    assert res["ok"] is False and res["verdict"] == "parse_fail"
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == diagram.DIAGRAM_RETRY_TOKENS
    assert res["meta"]["retried"] is True
    assert len(res["meta"]["attempts"]) == 2
    assert [a["attempt"] for a in res["meta"]["attempts"]] == [0, 1]
    assert all(a["finish_reason"] == "length" for a in res["meta"]["attempts"])


def test_empty_length_still_upgrades_once(patch_gateway):
    """① 空正文 + length -> 升级重试（既有行为不回归）。"""

    def handler(payload, call_no):
        if call_no == 1:
            return _reply("", "length")
        return _reply(GOOD_JSON, "stop")

    calls = patch_gateway(handler)
    res = diagram.extract_diagram_image(str(IMG01), session="s")

    assert res["ok"] is True
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == diagram.DIAGRAM_RETRY_TOKENS
    assert res["meta"]["retried"] is True


def test_parseable_truncated_json_is_used_without_retry(patch_gateway):
    """③ 非空 length + 可解析 -> 直接用，不重试（避免浪费）。"""

    complete_but_flagged = json.dumps({"nodes": [{"id": "n1", "label": "A"}],
                                       "edges": []})
    calls = patch_gateway(lambda payload, call_no: _reply(complete_but_flagged,
                                                          "length"))
    res = diagram.extract_diagram_image(str(IMG01), session="s")

    assert res["ok"] is True and res["verdict"] == "ok"
    assert len(calls) == 1
    assert res["meta"]["retried"] is False
    assert res["meta"]["attempts"][0]["finish_reason"] == "length"


def test_non_length_parse_fail_does_not_retry(patch_gateway):
    """④ 非 length 的 parse_fail -> 不重试（不引入同参重试）。"""

    calls = patch_gateway(lambda payload, call_no: _reply("不是 JSON 的文字解释", "stop"))
    res = diagram.extract_diagram_image(str(IMG01), session="s")

    assert res["ok"] is False and res["verdict"] == "parse_fail"
    assert len(calls) == 1
    assert res["meta"]["retried"] is False
    assert len(res["meta"]["attempts"]) == 1


def test_empty_non_length_content_does_not_retry(patch_gateway):
    """空正文 + 非 length -> 立即降级（旧约定，不回归）。"""

    calls = patch_gateway(lambda payload, call_no: _reply("", "stop"))
    res = diagram.extract_diagram_image(str(IMG01), session="s")

    assert res["ok"] is False and res["verdict"] == "empty"
    assert len(calls) == 1
    assert res["meta"]["retried"] is False


def test_retry_attempt_carries_the_upgraded_system_prompt(patch_gateway):
    """升级重试同时带「直接输出严格 JSON」约束，避免第二次又被 reasoning 吃满。"""

    calls = patch_gateway(
        lambda payload, call_no: _reply(TRUNCATED_JSON, "length"))
    diagram.extract_diagram_image(str(IMG01), session="s")

    first = calls[0]["messages"][0]["content"]
    second = calls[1]["messages"][0]["content"]
    assert second.startswith(first)
    assert second != first
    assert diagram.DIAGRAM_MAX_TOKENS < calls[1]["max_tokens"]
