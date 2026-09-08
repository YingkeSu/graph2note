"""scripts/validate_sessions.py 的 --check 健康巡检退出码（离线，mock，不触网）。"""

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate_sessions as vs  # noqa: E402


@pytest.fixture
def all_ok_probe(monkeypatch):
    calls = {"n": 0}

    def fake_validate(purpose, model=None):
        calls["n"] += 1
        return {"purpose": purpose, "direct": True, "session": purpose,
                "reasoning_tokens": 0, "status": "ok"}

    def fake_resolve(purpose, model=None):
        return f"{purpose}-sess"

    monkeypatch.setattr(vs, "validate_session_direct", fake_validate)
    monkeypatch.setattr(vs, "resolve_session_for", fake_resolve)
    return calls


def test_check_all_ok_exit_zero(all_ok_probe, tmp_path, monkeypatch):
    monkeypatch.setattr(vs, "OUT", tmp_path)
    rc = vs.main(["--only", "parse", "eval", "verify", "--check"])
    assert rc == 0
    assert all_ok_probe["n"] == 3          # 每用途一次（预算 <=3）
    assert (tmp_path / "validate_sessions.json").exists()


def test_check_any_degraded_exit_one(tmp_path, monkeypatch):
    def fake_validate(purpose, model=None):
        return {"purpose": purpose, "direct": purpose != "eval", "session": purpose,
                "reasoning_tokens": 60, "status": "ok"}

    monkeypatch.setattr(vs, "validate_session_direct", fake_validate)
    monkeypatch.setattr(vs, "resolve_session_for", lambda p, model=None: f"{p}-sess")
    monkeypatch.setattr(vs, "OUT", tmp_path)
    rc = vs.main(["--only", "parse", "eval", "verify", "--check"])
    assert rc == 1                          # 任一 degraded → 非零门控


def test_without_check_still_exit_zero(tmp_path, monkeypatch):
    def fake_validate(purpose, model=None):
        return {"purpose": purpose, "direct": False, "session": purpose,
                "reasoning_tokens": 3500, "status": "ok"}

    monkeypatch.setattr(vs, "validate_session_direct", fake_validate)
    monkeypatch.setattr(vs, "OUT", tmp_path)
    # 普通模式不 exit code 门控；JSON 仍写出
    rc = vs.main(["--only", "parse"])
    assert rc == 0
    assert (tmp_path / "validate_sessions.json").exists()