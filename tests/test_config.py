"""Unified runtime config resolution (issue 02): storage/settings priority.

Web, CLI and macOS all resolve through ``graph2note.config``; these tests pin
the explicit priority so the three entry points cannot silently diverge again.
"""
from __future__ import annotations

import json
import os

import pytest

from graph2note import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("GRAPH2NOTE_STORAGE", raising=False)
    monkeypatch.delenv("GRAPH2NOTE_SETTINGS_FILE", raising=False)
    monkeypatch.delenv("GRAPH2NOTE_APP_SUPPORT", raising=False)


def test_support_dir_default_is_a_graph2note_path():
    p = config.support_dir()
    assert isinstance(p, __import__("pathlib").Path)
    assert p.name == "Graph2Note"


def test_support_dir_honors_explicit_app_support(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH2NOTE_APP_SUPPORT", str(tmp_path / "iso-support"))
    assert config.support_dir() == tmp_path / "iso-support"


def test_resolve_storage_priority(monkeypatch, tmp_path):
    explicit = tmp_path / "explicit"
    env = tmp_path / "env"
    monkeypatch.setenv("GRAPH2NOTE_APP_SUPPORT", str(tmp_path / "support"))

    # explicit arg wins over env
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(env))
    assert config.resolve_storage_dir(explicit) == explicit

    # env wins over the default
    monkeypatch.delenv("GRAPH2NOTE_STORAGE")
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(env))
    assert config.resolve_storage_dir() == env

    # default = <support>/storage
    monkeypatch.delenv("GRAPH2NOTE_STORAGE")
    assert config.resolve_storage_dir() == tmp_path / "support" / "storage"


def test_resolve_settings_file_priority(monkeypatch, tmp_path):
    storage = tmp_path / "store"
    monkeypatch.setenv("GRAPH2NOTE_SETTINGS_FILE", str(tmp_path / "explicit.json"))
    assert config.resolve_settings_file(storage) == tmp_path / "explicit.json"

    monkeypatch.delenv("GRAPH2NOTE_SETTINGS_FILE")
    assert config.resolve_settings_file(storage) == storage / "llm-settings.json"


def test_ensure_storage_dir_creates_and_is_idempotent(tmp_path):
    p = config.ensure_storage_dir(tmp_path / "a" / "b")
    assert p.is_dir()
    assert config.ensure_storage_dir(p) == p


def test_ensure_storage_dir_rejects_file_path(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(config.ConfigError, match="not a directory"):
        config.ensure_storage_dir(f)


def test_ensure_storage_dir_rejects_uncreatable_path(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    with pytest.raises(config.ConfigError, match="not writable"):
        config.ensure_storage_dir(blocker / "sub")


def test_describe_reports_effective_config(monkeypatch, tmp_path):
    monkeypatch.setenv("GRAPH2NOTE_APP_SUPPORT", str(tmp_path / "support"))
    info = config.describe()
    assert info["storage"] == str(tmp_path / "support" / "storage")
    assert info["settings"] == str(tmp_path / "support" / "storage" / "llm-settings.json")


# ---------------------------------------------------------------------------
# webapp /api/config + create_app wiring
# ---------------------------------------------------------------------------


def test_webapp_exposes_config_endpoint(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from graph2note.webapp import create_app

    monkeypatch.setenv("GRAPH2NOTE_APP_SUPPORT", str(tmp_path / "support"))
    app = create_app()
    client = TestClient(app)
    body = client.get("/api/config").json()
    assert body["storage"] == str(tmp_path / "support" / "storage")
    assert body["settings"] == str(tmp_path / "support" / "storage" / "llm-settings.json")
    assert app.state.storage_dir == body["storage"]


def test_webapp_storage_dir_env_override(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from graph2note.webapp import create_app

    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    app = create_app()
    assert app.state.storage_dir == str(tmp_path / "store")
    body = TestClient(app).get("/api/config").json()
    assert body["storage"] == str(tmp_path / "store")


# ---------------------------------------------------------------------------
# CLI config subcommand + notes-export storage resolution
# ---------------------------------------------------------------------------


def _run_cli(*args, env_extra=None):
    import subprocess
    import sys

    env = dict(os.environ)
    env.pop("GRAPH2NOTE_STORAGE", None)
    env.pop("GRAPH2NOTE_SETTINGS_FILE", None)
    env.pop("GRAPH2NOTE_APP_SUPPORT", None)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "graph2note.cli", *args],
        capture_output=True, text=True, env=env,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    )


def test_cli_config_subcommand_reports_paths(tmp_path):
    res = _run_cli("config", "--json", env_extra={"GRAPH2NOTE_APP_SUPPORT": str(tmp_path / "support")})
    assert res.returncode == 0, res.stderr
    info = json.loads(res.stdout)
    assert info["storage"] == str(tmp_path / "support" / "storage")
    assert info["settings"] == str(tmp_path / "support" / "storage" / "llm-settings.json")


def test_cli_notes_export_reports_resolved_storage(tmp_path):
    res = _run_cli(
        "notes-export", "--storage", str(tmp_path / "store"), "-o", str(tmp_path / "vault"),
    )
    assert res.returncode == 0, res.stderr
    assert f"storage={tmp_path / 'store'}" in res.stdout


# ---------------------------------------------------------------------------
# AC2: Web 入库 → CLI 导出 → 同配置重载（无需复制数据，身份一致）
# ---------------------------------------------------------------------------


def test_web_to_cli_to_reload_roundtrip(tmp_path, monkeypatch):
    from pathlib import Path as _Path

    from PIL import Image
    from graph2note.notes.loop import run_incremental_export
    from graph2note.store import FileDocumentStore
    from graph2note.webapp import create_app

    monkeypatch.setenv("GRAPH2NOTE_APP_SUPPORT", str(tmp_path / "support"))

    original = tmp_path / "page.jpg"
    Image.new("RGB", (48, 48), (255, 255, 255)).save(original)

    # web: 在统一默认库中创建文档
    app = create_app()
    storage = app.state.storage_dir
    app.state.store.save_document(
        document_id="doc-shared", title="共享库文档", source_job_id="j1", model="x",
        markdown="# 共享库\n\n正文段落。",
        ir_json='{"document_type":"note","blocks":[]}',
        original_path=str(original), original_ext=".jpg",
        preprocessed_path=None, preprocessed_raw_path=None, assets_dir=None,
        timing_json={},
    )

    # cli: 从同一 storage 导出（不复制数据）
    report, vault, entries = run_incremental_export(FileDocumentStore(storage), tmp_path / "vault")
    assert entries, "expected at least one exported document"
    assert any("doc-shared" in (getattr(e, "document_id", "") or str(e)) for e in entries)

    # reload: 同配置重载仍见同一文档（身份一致）
    app2 = create_app()
    ids = {d["document_id"] for d in app2.state.store.list_documents()}
    assert "doc-shared" in ids
    assert app2.state.storage_dir == storage
    assert _Path(storage).is_dir()
