"""CLI tests for ``graph2note visual-qa`` (offline).

``cmd_visualqa`` accepts an injected ``call_fn`` (same seam as check_ui), so the
CLI is exercised end-to-end without network or credentials; the replay path is
exercised via a saved raw record.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note import visualqa
from graph2note.visualqa import Budget, ScenarioSpec, build_visualqa_parser, cmd_visualqa

pytest.importorskip("PIL")

from eval.gateway import GatewayError, GatewayTimeout  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "visualqa"
NORMAL_REVIEW = json.loads((GOLDEN / "ui-normal.review.json").read_text(encoding="utf-8"))


def _make_png(path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (300, 200), (250, 250, 250))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=18)
    except TypeError:
        font = ImageFont.load_default()
    d.text((20, 20), "Graph2Note", fill=(20, 20, 20), font=font)
    im.save(path)
    return path


def _body():
    return {"model": "kimi-k2.6",
            "choices": [{"message": {"content": json.dumps(NORMAL_REVIEW, ensure_ascii=False)},
                         "finish_reason": "stop"}],
            "usage": {"total_tokens": 100}}


def _ui_args(tmp_path, *extra):
    shot = _make_png(tmp_path / "shot.png")
    argv = ["ui", "--screenshot", str(shot), "--scene", "library-empty",
            "--expectation", "空状态有引导", "-o", str(tmp_path / "report.json")]
    argv.extend(str(x) for x in extra)
    args = build_visualqa_parser().parse_args(argv)
    return args


def test_cli_ui_complete_writes_report(tmp_path, capsys):
    args = _ui_args(tmp_path)
    rc = cmd_visualqa(args, call_fn=lambda payload, *, provider, session, timeout, api_key: _body())
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert report["verdict"] == "no_issues_found"
    err = capsys.readouterr().err
    assert "检查未完成" not in err


def test_cli_ui_timeout_exit_nonzero_and_not_pass(tmp_path, capsys):
    args = _ui_args(tmp_path)

    def call(payload, *, provider, session, timeout, api_key):
        raise GatewayTimeout("timeout")

    rc = cmd_visualqa(args, call_fn=call)
    assert rc == 1
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "incomplete"
    assert report["error"]["type"] == "timeout"
    assert report["verdict"] is None
    err = capsys.readouterr().err
    assert "检查未完成" in err


def test_cli_ui_auth_exit_nonzero(tmp_path, capsys):
    args = _ui_args(tmp_path)

    def call(payload, *, provider, session, timeout, api_key):
        raise GatewayError("gateway HTTP 401")

    rc = cmd_visualqa(args, call_fn=call)
    assert rc == 1
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["error"]["type"] == "auth"
    assert "检查未完成" in capsys.readouterr().err


def test_cli_ui_replay_offline(tmp_path):
    # first produce a raw record via an injected call, then replay it with a
    # call_fn that would fail if it were invoked (proves replay is offline).
    shot = _make_png(tmp_path / "shot.png")
    spec = ScenarioSpec(scene="library-empty")
    rec = tmp_path / "record.json"
    check = visualqa.check_ui(str(shot), spec, call_fn=lambda *a, **k: _body(), save_raw_path=rec)
    assert check["status"] == "complete"

    argv = ["ui", "--replay", str(rec), "-o", str(tmp_path / "report.json")]
    args = build_visualqa_parser().parse_args(argv)

    def boom(*a, **k):
        raise AssertionError("replay must be offline")

    rc = cmd_visualqa(args, call_fn=boom)
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["status"] == "complete"
    assert report["replay"]["from_record"] is True


def test_cli_ui_requires_input(tmp_path, capsys):
    argv = ["ui", "--scene", "x", "-o", str(tmp_path / "r.json")]
    args = build_visualqa_parser().parse_args(argv)
    rc = cmd_visualqa(args)
    assert rc == 2
    assert "需要" in capsys.readouterr().err


def test_cli_capture_missing_chrome_reports_clear_error(tmp_path, capsys):
    argv = ["capture", "http://127.0.0.1:1/", "-o", str(tmp_path / "s.png"),
            "--chrome-bin", "/nonexistent/chrome"]
    args = build_visualqa_parser().parse_args(argv)
    rc = cmd_visualqa(args)
    assert rc == 1
    assert "capture failed" in capsys.readouterr().err


def test_cli_ui_budget_flags_plumbed(tmp_path):
    seen = {}

    def call(payload, *, provider, session, timeout, api_key):
        seen["payload"] = payload
        seen["timeout"] = timeout
        return _body()

    args = _ui_args(tmp_path, "--max-tokens", 999, "--timeout", 12.5, "--max-calls", 1)
    rc = cmd_visualqa(args, call_fn=call)
    assert rc == 0
    assert seen["payload"]["max_tokens"] == 999
    assert seen["timeout"] == 12.5


def test_cli_ui_prompt_version_override(tmp_path):
    args = _ui_args(tmp_path, "--prompt-version", "custom-v9")
    rc = cmd_visualqa(args, call_fn=lambda *a, **k: _body())
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["prompt_version"] == "custom-v9"


def _content_args(tmp_path, *extra):
    src = _make_png(tmp_path / "source.png")
    cand = tmp_path / "cand.md"
    cand.write_text("# 状态空间模形\n", encoding="utf-8")
    argv = ["content", "--source", str(src), "--candidate", str(cand),
            "-o", str(tmp_path / "report.json"), *[str(x) for x in extra]]
    return build_visualqa_parser().parse_args(argv)


def test_cli_content_complete_writes_report(tmp_path):
    args = _content_args(tmp_path)
    body = {"model": "kimi-k2.6",
            "choices": [{"message": {"content": '{"issues": [], "limitations": []}'},
                         "finish_reason": "stop"}],
            "usage": {"total_tokens": 10}}
    rc = cmd_visualqa(args, call_fn=lambda *a, **k: body)
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "content"
    assert report["status"] == "complete"
    assert report["verdict"] == "no_issues_found"


def test_cli_content_replay_offline(tmp_path):
    src = _make_png(tmp_path / "source.png")
    spec = visualqa.ContentSpec()
    rec = tmp_path / "rec.json"
    body = {"model": "kimi-k2.6",
            "choices": [{"message": {"content": '{"issues": [], "limitations": []}'},
                         "finish_reason": "stop"}],
            "usage": {"total_tokens": 10}}
    visualqa.check_content(str(src), "candidate", spec=spec, save_raw_path=rec,
                           call_fn=lambda *a, **k: body)
    argv = ["content", "--replay", str(rec), "-o", str(tmp_path / "report.json")]
    args = build_visualqa_parser().parse_args(argv)
    rc = cmd_visualqa(args, call_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("offline")))
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "content"
    assert report["replay"]["from_record"] is True


def test_cli_content_requires_source(tmp_path, capsys):
    cand = tmp_path / "cand.md"
    cand.write_text("x\n", encoding="utf-8")
    argv = ["content", "--candidate", str(cand), "-o", str(tmp_path / "r.json")]
    args = build_visualqa_parser().parse_args(argv)
    rc = cmd_visualqa(args)
    assert rc == 2
    assert "--source" in capsys.readouterr().err


def test_cli_content_prompt_version_override(tmp_path):
    args = _content_args(tmp_path, "--prompt-version", "content-v2")
    body = {"model": "kimi-k2.6",
            "choices": [{"message": {"content": '{"issues": [], "limitations": []}'},
                         "finish_reason": "stop"}],
            "usage": {"total_tokens": 10}}
    rc = cmd_visualqa(args, call_fn=lambda *a, **k: body)
    assert rc == 0
    report = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
    assert report["prompt_version"] == "content-v2"
