"""Offline tests for the UI screenshot visual-QA dev command (issue 04).

No network, no real credentials: every check injects a ``call_fn`` that returns
a gateway-shaped body (recorded golden reviews under tests/golden/visualqa/).
The real Kimi call path is exercised only by the explicit ``visual-qa ui`` CLI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note import visualqa
from graph2note.visualqa import (
    Budget,
    InvalidReviewOutput,
    ScenarioSpec,
    VisualQAError,
    check_ui,
    capture_screenshot,
    fingerprint_file,
    fingerprint_scenario,
    match_issues_to_planted,
    parse_ui_review,
    render_report_from_record,
    save_raw_record,
)

pytest.importorskip("PIL")

from eval.gateway import GatewayError, GatewayTimeout  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "visualqa"

NORMAL_REVIEW = json.loads((GOLDEN / "ui-normal.review.json").read_text(encoding="utf-8"))
DEFECT_REVIEW = json.loads((GOLDEN / "ui-defect.review.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_png(path: Path, *, overlap: bool = False) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (480, 320), (245, 245, 245))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        font = ImageFont.load_default()
    d.text((20, 20), "Graph2Note", fill=(20, 20, 20), font=font)
    if overlap:
        # planted defect #1: two title lines overlapping
        d.text((20, 60), "标题重叠样例", fill=(20, 20, 20), font=font)
        d.text((20, 66), "第二行遮挡第一行", fill=(120, 20, 20), font=font)
        # planted defect #2: bottom text clipped by the canvas edge
        d.text((20, 306), "底部文字被裁掉", fill=(20, 20, 20), font=font)
    else:
        d.text((20, 60), "标题正常", fill=(20, 20, 20), font=font)
        d.text((20, 260), "底部完整", fill=(20, 20, 20), font=font)
    im.save(path)
    return path


def _body_from_review(review: dict, *, usage: dict | None = None,
                      finish_reason: str = "stop") -> dict:
    return {
        "model": "kimi-k2.6",
        "choices": [{
            "message": {"role": "assistant", "content": json.dumps(review, ensure_ascii=False)},
            "finish_reason": finish_reason,
        }],
        "usage": usage or {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def _call_returning(body_or_fn):
    def call(payload, *, provider, session, timeout, api_key):
        return body_or_fn(payload) if callable(body_or_fn) else body_or_fn
    return call


def _spec(**kwargs) -> ScenarioSpec:
    params = {"scene": "library-empty",
              "viewport": {"width": 1440, "height": 1000},
              "expectations": ["空文档库应显示新建引导"]}
    params.update(kwargs)
    return ScenarioSpec(**params)


# ---------------------------------------------------------------------------
# fingerprint / prompt / parsing
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_and_content_sensitive(tmp_path):
    p = _make_png(tmp_path / "a.png")
    assert fingerprint_file(p) == fingerprint_file(p)
    assert fingerprint_file(p).startswith("sha256:")
    spec = _spec()
    assert fingerprint_scenario(spec) == fingerprint_scenario(spec)
    changed = _spec(expectations=["另一条预期"])
    assert fingerprint_scenario(spec) != fingerprint_scenario(changed)


def test_ui_prompt_records_scenario_viewport_and_interaction_guard(tmp_path):
    spec = _spec(expectations=["新解析按钮可见", "空状态有引导文案"])
    text = visualqa.build_ui_user_prompt(spec)
    assert "library-empty" in text
    assert "1440x1000" in text
    assert "新解析按钮可见" in text
    assert "不推断未经操作的交互结果" in visualqa.UI_SYSTEM
    messages = visualqa.build_ui_messages(str(_make_png(tmp_path / "shot.png")), spec)
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert any(part["type"] == "image_url" for part in messages[1]["content"])
    assert any("library-empty" in part["text"] for part in messages[1]["content"]
               if part["type"] == "text")


def test_parse_ui_review_normalizes_and_validates():
    parsed = parse_ui_review(json.dumps(NORMAL_REVIEW, ensure_ascii=False))
    assert parsed["issues"] == []
    assert len(parsed["observations"]) == len(NORMAL_REVIEW["observations"])
    assert parsed["limitations"]

    raw = {"issues": [
        {"severity": "高", "evidence": "文字重叠", "uncertainty": "低", "suggestion": "加行高"},
        {"severity": "info", "evidence": "间距偏小", "suggestion": "可接受"},
    ]}
    parsed = parse_ui_review(json.dumps(raw, ensure_ascii=False))
    assert parsed["issues"][0]["severity"] == "high"
    assert parsed["issues"][0]["uncertainty"] == "low"
    assert parsed["issues"][1]["severity"] == "info"
    assert parsed["issues"][0]["region"] is None


@pytest.mark.parametrize("bad", [
    "not json at all",
    "[1, 2, 3]",
    '{"observations": []}',                     # missing issues
    '{"issues": "nope"}',                       # issues not a list
    '{"issues": [{"evidence": "x"}]}',          # missing suggestion
    '{"issues": [{"suggestion": "x"}]}',        # missing evidence
    '{"issues": "[]"}',
])
def test_parse_ui_review_rejects_invalid(bad):
    with pytest.raises(InvalidReviewOutput):
        parse_ui_review(bad)


# ---------------------------------------------------------------------------
# check_ui happy paths
# ---------------------------------------------------------------------------


def test_check_ui_complete_no_issues(tmp_path):
    shot = _make_png(tmp_path / "normal.png")
    report = check_ui(str(shot), _spec(), call_fn=_call_returning(_body_from_review(NORMAL_REVIEW)))
    assert report["status"] == "complete"
    assert report["verdict"] == "no_issues_found"
    assert report["issues"] == []
    assert report["limitations"]                      # 不以截图推断交互
    assert report["input"]["screenshot_fingerprint"].startswith("sha256:")
    assert report["input"]["scenario_fingerprint"].startswith("sha256:")
    assert report["usage"]["total_tokens"] == 150
    assert report["usage"]["finish_reason"] == "stop"
    assert len(report["timing"]["calls"]) == 1
    assert report["timing"]["total_seconds"] >= 0
    assert report["error"] is None
    assert "不是发布门槛" in report["caveat"]
    assert report["correspondence"] == {"matched": [], "missed": [], "unmatched_model_issues": []}


def test_check_ui_issues_match_planted_defects(tmp_path):
    shot = _make_png(tmp_path / "defect.png", overlap=True)
    spec = _spec(planted=[
        {"id": "p1", "kind": "overlap", "region": "顶部标题区域"},
        {"id": "p2", "kind": "crop", "region": "底部"},
    ])
    report = check_ui(str(shot), spec, call_fn=_call_returning(_body_from_review(DEFECT_REVIEW)))
    assert report["status"] == "complete"
    assert report["verdict"] == "issues_found"
    assert len(report["issues"]) == 2
    corr = report["correspondence"]
    assert corr["matched"] == ["p1", "p2"]
    assert corr["missed"] == []
    assert corr["unmatched_model_issues"] == []
    assert report["issues"][0]["matched_planted"] == "p1"
    assert report["issues"][1]["matched_planted"] == "p2"


def test_check_ui_unmatched_model_issue_recorded(tmp_path):
    shot = _make_png(tmp_path / "defect.png", overlap=True)
    spec = _spec(planted=[{"id": "p1", "kind": "overlap", "region": "顶部标题区域"}])
    # defect review has two issues, only the first matches p1
    report = check_ui(str(shot), spec, call_fn=_call_returning(_body_from_review(DEFECT_REVIEW)))
    corr = report["correspondence"]
    assert corr["matched"] == ["p1"]
    assert corr["missed"] == []
    assert corr["unmatched_model_issues"] == [1]


# ---------------------------------------------------------------------------
# error semantics: never "pass" when incomplete
# ---------------------------------------------------------------------------


def test_invalid_output_is_incomplete_and_retries_bounded(tmp_path):
    shot = _make_png(tmp_path / "x.png")
    calls = []

    def call(payload, *, provider, session, timeout, api_key):
        calls.append(1)
        return {"choices": [{"message": {"content": "随便说两句，不是 JSON"},
                             "finish_reason": "stop"}], "usage": {}}

    report = check_ui(str(shot), _spec(), budget=Budget(max_calls=3), call_fn=call)
    assert report["status"] == "incomplete"
    assert report["verdict"] is None
    assert report["error"]["type"] == "invalid_output"
    assert len(calls) == 3                       # 受 max_calls 约束


def test_timeout_is_incomplete_and_not_retried(tmp_path):
    shot = _make_png(tmp_path / "x.png")
    calls = []

    def call(payload, *, provider, session, timeout, api_key):
        calls.append(1)
        raise GatewayTimeout("gateway timeout after 45s")

    report = check_ui(str(shot), _spec(), budget=Budget(max_calls=3), call_fn=call)
    assert report["status"] == "incomplete"
    assert report["error"]["type"] == "timeout"
    assert len(calls) == 1                       # 超时不重试


def test_auth_failure_is_incomplete(tmp_path):
    shot = _make_png(tmp_path / "x.png")

    def call(payload, *, provider, session, timeout, api_key):
        raise GatewayError("gateway HTTP 401: unauthorized")

    report = check_ui(str(shot), _spec(), call_fn=call)
    assert report["status"] == "incomplete"
    assert report["error"]["type"] == "auth"


def test_gateway_error_is_incomplete(tmp_path):
    shot = _make_png(tmp_path / "x.png")

    def call(payload, *, provider, session, timeout, api_key):
        raise GatewayError("gateway connection error")

    report = check_ui(str(shot), _spec(), call_fn=call)
    assert report["status"] == "incomplete"
    assert report["error"]["type"] == "gateway_error"


def test_total_timeout_bound_enforced(tmp_path):
    shot = _make_png(tmp_path / "x.png")
    now = [0.0]

    def clock():
        return now[0]

    def call(payload, *, provider, session, timeout, api_key):
        now[0] += 70.0                          # 每次调用耗时 70s
        return {"choices": [{"message": {"content": "not json", "finish_reason": "stop"}}],
                            "usage": {}}

    report = check_ui(str(shot), _spec(),
                      budget=Budget(max_calls=5, total_timeout_seconds=120.0),
                      call_fn=call, clock=clock)
    assert report["status"] == "incomplete"
    assert report["error"]["type"] == "total_timeout"


def test_incomplete_never_reports_pass(tmp_path):
    shot = _make_png(tmp_path / "x.png")

    def call(payload, *, provider, session, timeout, api_key):
        raise GatewayError("gateway HTTP 401")

    report = check_ui(str(shot), _spec(), call_fn=call)
    assert "pass" not in report["status"]
    assert report["verdict"] is None
    assert report["status"] == "incomplete"


# ---------------------------------------------------------------------------
# replay (offline, zero network)
# ---------------------------------------------------------------------------


def test_save_raw_and_replay_without_network(tmp_path):
    shot = _make_png(tmp_path / "normal.png")
    spec = _spec()
    rec_path = tmp_path / "record.json"

    def call(payload, *, provider, session, timeout, api_key):
        return _body_from_review(NORMAL_REVIEW)

    report = check_ui(str(shot), spec, call_fn=call, save_raw_path=rec_path)
    assert report["status"] == "complete"
    assert rec_path.exists()

    def boom(payload, *, provider, session, timeout, api_key):
        raise AssertionError("replay must not hit the network")

    record = json.loads(rec_path.read_text(encoding="utf-8"))
    replayed = render_report_from_record(record)
    assert replayed["status"] == "complete"
    assert replayed["verdict"] == "no_issues_found"
    assert replayed["issues"] == report["issues"]
    assert replayed["replay"]["from_record"] is True
    assert replayed["input"]["screenshot_fingerprint"] == report["input"]["screenshot_fingerprint"]


def test_replay_invalid_record_reports_incomplete():
    bad = {"raw_body": {"choices": [{"message": {"content": "not json"}, "finish_reason": "stop"}],
                        "usage": {}},
           "spec": _spec().to_dict(), "provider": "kimi", "model": "kimi-k2.6",
           "budget": Budget().to_dict()}
    report = render_report_from_record(bad)
    assert report["status"] == "incomplete"
    assert report["error"]["type"] == "invalid_output"


# ---------------------------------------------------------------------------
# capture backend (offline)
# ---------------------------------------------------------------------------


def test_capture_backend_is_injectable(tmp_path):
    out = tmp_path / "shot.png"
    captured = {}

    def fake_run(cmd, capture_output, timeout, check):
        captured["cmd"] = cmd
        out.write_bytes(b"\x89PNG\r\n\x1a\n")
        return type("Proc", (), {"returncode": 0})()

    meta = capture_screenshot("http://127.0.0.1:8000/", out, viewport="1440x1000",
                              backend="headless-chrome", chrome_bin="/fake/chrome",
                              run=fake_run)
    assert meta["backend"] == "headless-chrome"
    assert meta["viewport"] == {"width": 1440, "height": 1000}
    assert out.exists()
    assert "--window-size=1440,1000" in captured["cmd"]


def test_capture_unknown_backend_raises(tmp_path):
    with pytest.raises(VisualQAError):
        capture_screenshot("http://x", tmp_path / "s.png", backend="nope")


def test_invalid_viewport_raises():
    with pytest.raises(VisualQAError):
        visualqa._parse_viewport("1440abc")
