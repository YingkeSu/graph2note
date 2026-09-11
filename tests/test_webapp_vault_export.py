"""Offline tests for the Web full-library Obsidian vault export (baseline issue 06).

Every test is network-free: parse uses an injected golden router, and the vault
export runs the deterministic rule classifier + incremental exporter against a
temp target directory.  Covers the acceptance criteria:

- Web trigger -> backend execution -> result display (done/failed/empty states)
- exported vault contains notes (frontmatter + source image), attachments, MOCs,
  collections and manifest; all references resolve (no dead links)
- empty library / unwritable target / in-progress duplicate / failure all have
  clear, non-success states
- the incremental exporter + user-edit protection is reused unchanged
"""

from __future__ import annotations

import io
import json
import time
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402

HERE = Path(__file__).parent
VALID = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")


def _make_png(w=600, h=420, text="Vault 导出测试标题", block=None):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    if block is not None:
        # a large dark block makes two pages perceptually distinct (pHash)
        d.rectangle(block, fill=(15, 15, 15))
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    d.text((30, 40), text, fill=(20, 20, 20), font=font)
    d.text((30, 90), "状态空间模型核心方程与推导", fill=(30, 30, 30), font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _router_factory(content):
    def factory(image_path, model):
        return RouteARouter(model, caller=lambda p, m, recover=False: (content, {}))
    return factory


def _app(content=VALID, **kw):
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=kw.pop("storage_dir", None),
        router_factory=_router_factory(content),
        max_retries=2,
        **kw,
    )


def _wait_done(client, job_id, timeout=20):
    for _ in range(int(timeout / 0.1)):
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, r.text
        doc = r.json()
        if doc["status"] not in ("queued", "processing"):
            return doc
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def _wait_vault(client, timeout=30):
    """Poll the vault-export status until it leaves the ``running`` state."""
    for _ in range(int(timeout / 0.1)):
        r = client.get("/api/vault/export")
        assert r.status_code == 200, r.text
        st = r.json()
        if st["status"] != "running":
            return st
        time.sleep(0.1)
    raise AssertionError("vault export did not finish in time")


def _seed_one_document(client, text="Vault 导出测试标题", filename="note.png", block=None):
    """Upload + parse one document so the library is non-empty; return job doc.

    ``text``/``filename``/``block`` vary the page bytes + title so two calls
    yield two distinct documents (no near-duplicate merge)."""
    r = client.post("/api/parse",
                    files={"file": (filename, _make_png(text=text, block=block), "image/png")})
    assert r.status_code == 200, r.text
    doc = _wait_done(client, r.json()["job_id"])
    assert doc["status"] == "done"
    return doc


def test_vault_export_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)

    target = tmp_path / "vault"
    r = client.post("/api/vault/export", json={"target_dir": str(target)})
    assert r.status_code == 200, r.text
    st = _wait_vault(client)
    assert st["status"] == "done"
    assert st["exported_documents"] >= 1
    assert st["vault_root"] == str(target)
    # first export -> everything added (incremental report present)
    assert st["report"]["added"], "first export should list added files"
    assert st["error"] is None

    # vault structure: manifest + notes + mocs
    assert (target / "export-manifest.json").is_file()
    notes = list((target / "notes").glob("*/note.md"))
    assert notes, "expected at least one note.md"
    note = notes[0].read_text(encoding="utf-8")
    for key in ("document_id:", "title:", "source_image:", "parsed_at:",
                "exported_at:", "topics:", "tags:", "collections:",
                "import_time:"):
        assert key in note, f"frontmatter missing {key!r}"
    assert "数学" in note, "rule classification should tag the sample as 数学"
    # original manuscript image copied beside the note
    source = list((target / "notes").glob("*/source.*"))
    assert source and source[0].is_file()
    # diagram attachment copied (VALID IR renders a diagram asset)
    assets = list((target / "notes").glob("*/assets/*"))
    assert assets, "expected at least one copied attachment"
    # MOCs generated (rule classifier assigns every doc >=1 topic)
    mocs = list((target / "mocs").glob("*.md"))
    assert mocs, "expected at least one MOC index note"


def test_vault_export_empty_library(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/vault/export", json={"target_dir": str(tmp_path / "vault")})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "empty"
    assert r.json()["exported_documents"] == 0


def test_vault_export_unwritable_target(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    # a regular FILE at the target path -> mkdir fails deterministically
    blocked = tmp_path / "blocked"
    blocked.write_text("x", encoding="utf-8")
    r = client.post("/api/vault/export", json={"target_dir": str(blocked)})
    assert r.status_code == 422, r.text
    assert "不可" in r.json()["detail"]
    # failure must not be recorded as success
    assert client.get("/api/vault/export").json()["status"] == "idle"


def test_vault_export_duplicate_in_progress(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    client.app.state.vault_export = {"status": "running", "target_dir": str(tmp_path / "vault")}
    r = client.post("/api/vault/export", json={"target_dir": str(tmp_path / "vault")})
    assert r.status_code == 409, r.text
    assert "进行中" in r.json()["detail"]


def test_vault_export_failure_not_success(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)

    import graph2note.notes.loop as loop_module

    def boom(store, out_dir, **kw):
        raise RuntimeError("dead link in generated vault")

    monkeypatch.setattr(loop_module, "run_incremental_export", boom)
    target = tmp_path / "vault"
    r = client.post("/api/vault/export", json={"target_dir": str(target)})
    assert r.status_code == 200, r.text
    st = _wait_vault(client)
    assert st["status"] == "failed"
    assert "dead link" in st["error"]
    assert st["status"] != "done"


def test_vault_export_second_run_unchanged(tmp_path, monkeypatch):
    """Reuses the incremental exporter: a no-change re-run is zero-write."""
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)

    target = tmp_path / "vault"
    client.post("/api/vault/export", json={"target_dir": str(target)})
    assert _wait_vault(client)["status"] == "done"

    manifest_before = (target / "export-manifest.json").read_text(encoding="utf-8")
    client.post("/api/vault/export", json={"target_dir": str(target)})
    st = _wait_vault(client)
    assert st["status"] == "done"
    assert st["report"]["added"] == []
    assert st["report"]["updated"] == []
    assert st["report"]["unchanged"], "no-change re-run should list unchanged files"
    assert (target / "export-manifest.json").read_text(encoding="utf-8") == manifest_before


def test_vault_export_ui_present(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    page = client.get("/").text
    assert "导出 Vault" in page or "vault-export" in page
    assert "vault-export-zone" in page
    appjs = client.get("/static/app.js").text
    assert "startVaultExport" in appjs


# ---------------------------------------------------------------------------
# baseline issue 07: incremental change + conflict report surfaced by the Web
# ---------------------------------------------------------------------------

def _export(client, target):
    client.post("/api/vault/export", json={"target_dir": str(target)})
    return _wait_vault(client)


def _note_md(target):
    notes = list((target / "notes").glob("*/note.md"))
    assert notes, "expected at least one note.md in the vault"
    return notes[0]


def test_report_first_export_task_id_and_added(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    target = tmp_path / "vault"
    st = _export(client, target)
    assert st["status"] == "done"
    assert st["task_id"] and st["report"]["task_id"] == st["task_id"]
    assert st["report"]["added"], "first export adds all files"
    assert st["report"]["conflicts"] == []
    assert st["report"]["deleted"] == []


def test_report_no_change_reprun_zero_write(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    target = tmp_path / "vault"
    assert _export(client, target)["status"] == "done"

    mtimes = {str(p.relative_to(target)): p.stat().st_mtime
              for p in target.rglob("*") if p.is_file()}
    st = _export(client, target)
    assert st["status"] == "done"
    assert st["report"]["added"] == [] and st["report"]["updated"] == []
    assert st["report"]["unchanged"]
    for p in target.rglob("*"):
        if p.is_file():
            assert mtimes[str(p.relative_to(target))] == p.stat().st_mtime, \
                f"no-change re-run must not rewrite {p}"


def test_report_content_change_marks_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    doc = _seed_one_document(client)
    target = tmp_path / "vault"
    _export(client, target)

    rec = client.app.state.store.save_edits(doc["document_id"], "# 修改后\n\n新的正文内容。")
    assert rec is not None
    st = _export(client, target)
    assert st["status"] == "done"
    assert st["report"]["updated"], "content change should mark files updated"
    assert "新的正文内容" in _note_md(target).read_text(encoding="utf-8")


def test_report_metadata_change_marks_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    doc = _seed_one_document(client)
    target = tmp_path / "vault"
    _export(client, target)

    client.app.state.store.set_tags(doc["document_id"], ["课程", "重点"])
    st = _export(client, target)
    assert st["status"] == "done"
    assert st["report"]["updated"]
    note = _note_md(target).read_text(encoding="utf-8")
    assert "课程" in note and "重点" in note


def test_report_delete_document_marks_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client, text="第一份文档", filename="first.png", block=(0, 0, 300, 420))
    doc2 = _seed_one_document(client, text="第二份文档", filename="second.png", block=(300, 0, 600, 420))
    target = tmp_path / "vault"
    _export(client, target)

    assert client.app.state.store.delete_document(doc2["document_id"])
    st = _export(client, target)
    assert st["status"] == "done"
    assert st["report"]["deleted"], "deleted document's files should be listed"
    assert any(p.endswith("note.md") for p in st["report"]["deleted"])
    assert st["exported_documents"] == 1
    assert len(list((target / "notes").glob("*/note.md"))) == 1


def test_report_user_edit_conflict_locatable(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    target = tmp_path / "vault"
    _export(client, target)

    note = _note_md(target)
    note.write_text(note.read_text(encoding="utf-8") + "\n\n用户手工追加的内容\n", encoding="utf-8")
    st = _export(client, target)
    assert st["status"] == "done"
    conflicts = st["report"]["conflicts"]
    assert conflicts, "user-edited note should be reported as a conflict"
    c = conflicts[0]
    assert c["managed"].endswith("note.md")
    assert "user-" in c["backup"]
    assert (target / c["managed"]).is_file()
    assert (target / c["backup"]).is_file()
    assert "用户手工追加的内容" not in (target / c["managed"]).read_text(encoding="utf-8")
    assert "用户手工追加的内容" in (target / c["backup"]).read_text(encoding="utf-8")


def test_report_user_rename_preserved_and_locatable(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    target = tmp_path / "vault"
    _export(client, target)

    note = _note_md(target)
    renamed = note.parent / "My Essay.md"
    note.rename(renamed)
    st = _export(client, target)
    assert st["status"] == "done"
    assert any(p.endswith("note.md") for p in st["report"]["added"])
    user_files = st["report"]["user_files"]
    assert any(p.endswith("My Essay.md") for p in user_files), user_files
    assert renamed.is_file()


def test_report_failure_partial_vs_clean(tmp_path, monkeypatch):
    import graph2note.notes.loop as loop_module

    # partial: fake writes a file into the vault, then raises
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    _seed_one_document(client)
    target = tmp_path / "vault"

    def boom_partial(store, out_dir, **kw):
        (Path(out_dir) / "notes").mkdir(parents=True, exist_ok=True)
        (Path(out_dir) / "notes" / "partial.txt").write_text("x", encoding="utf-8")
        raise RuntimeError("dead link")

    monkeypatch.setattr(loop_module, "run_incremental_export", boom_partial)
    st = _export(client, target)
    assert st["status"] == "failed" and st["partial"] is True

    # clean: fake raises without writing anything
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store2"))
    client2 = TestClient(_app())
    _seed_one_document(client2)
    target2 = tmp_path / "vault2"

    def boom_clean(store, out_dir, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(loop_module, "run_incremental_export", boom_clean)
    st2 = _export(client2, target2)
    assert st2["status"] == "failed" and st2["partial"] is False
