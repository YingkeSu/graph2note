"""Offline TestClient tests for the durable local document library (issue 07).

Uses a file-system-backed `FileDocumentStore` in a temp dir so "reload
persistence" can be simulated by building a *fresh* app over the same storage
root.  Parse answers come from an injected golden router — zero network.
"""

import io
import json
import time
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

import graph2note.webapp as webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402

HERE = Path(__file__).parent
VALID = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")
ILLEGAL = (HERE / "golden" / "illegal-ir.golden.json").read_text(encoding="utf-8")


def _make_png(w=640, h=460, text="文档库测试"):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=24)
    except TypeError:
        font = ImageFont.load_default()
    d.rectangle([20, 30, w - 20, h - 20], outline=(30, 30, 30), width=3)
    d.text((40, 80), text, fill=(20, 20, 20), font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _router_factory(content):
    def factory(image_path, model):
        return RouteARouter(model, caller=lambda p, m, recover=False: (content, {}))
    return factory


def _parse_ok(store_dir, name="sheet.png", content=VALID):
    app = webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=str(store_dir),
        document_store=FileDocumentStore(store_dir),
        router_factory=_router_factory(content),
    )
    client = TestClient(app)
    r = client.post("/api/parse", files={"file": (name, _make_png(), "image/png")})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    return app, client, job_id


def _wait_done(client, job_id, timeout=20):
    for _ in range(int(timeout / 0.1)):
        doc = client.get(f"/api/jobs/{job_id}").json()
        if doc["status"] not in ("queued", "processing"):
            return doc
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_parse_auto_creates_document_record(tmp_path):
    app, client, job_id = _parse_ok(tmp_path)
    doc = _wait_done(client, job_id)
    assert doc["status"] == "done"
    assert doc["document_id"]
    docs = client.get("/api/documents").json()
    assert len(docs) == 1
    assert docs[0]["document_id"] == doc["document_id"]

    rec = client.get(f"/api/documents/{doc['document_id']}").json()
    assert rec["current_markdown"]
    assert "状态空间模型" in rec["current_markdown"]
    assert rec["latest"]["preprocessed_path"]
    # durable files exist on disk
    assert len(list((tmp_path / "documents").iterdir())) == 1


def test_edit_persists_and_reload_restores(tmp_path):
    """FR-014: edit + reload (fresh app over same storage) restores latest MD."""
    _, client, job_id = _parse_ok(tmp_path)
    doc = _wait_done(client, job_id)
    did = doc["document_id"]

    edited = "# 我改过了\n\n刷新后应保留这行编辑。\n"
    r = client.post(f"/api/documents/{did}/markdown", json={"markdown": edited})
    assert r.status_code == 200
    assert client.get(f"/api/documents/{did}").json()["current_markdown"] == edited

    # simulate page reload: brand-new app + store over the SAME storage dir
    client2 = TestClient(webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=str(tmp_path),
        document_store=FileDocumentStore(tmp_path),
        router_factory=_router_factory(VALID),
    ))
    docs = client2.get("/api/documents").json()
    assert len(docs) == 1 and docs[0]["document_id"] == did
    rec2 = client2.get(f"/api/documents/{did}").json()
    assert rec2["current_markdown"] == edited
    assert client2.get(f"/api/documents/{did}/preprocessed").status_code == 200
    assert client2.get(f"/api/documents/{did}/original").status_code == 200


def test_list_shows_multiple_documents_ordered(tmp_path):
    _, c1, j1 = _parse_ok(tmp_path, name="a.png")
    _wait_done(c1, j1)
    _, c2, j2 = _parse_ok(tmp_path, name="b.png")
    _wait_done(c2, j2)
    docs = c2.get("/api/documents").json()
    names = [d["title"] for d in docs]
    assert set(names) == {"a", "b"}
    # most recently updated first
    assert docs[0]["updated_at"] >= docs[-1]["updated_at"]


def test_delete_removes_everything(tmp_path):
    _, client, job_id = _parse_ok(tmp_path)
    doc = _wait_done(client, job_id)
    did = doc["document_id"]
    docdir = tmp_path / "documents" / did
    assert docdir.exists()

    r = client.delete(f"/api/documents/{did}")
    assert r.status_code == 200
    assert client.get(f"/api/documents/{did}").status_code == 404
    assert client.get("/api/documents").json() == []
    assert not docdir.exists()  # original, IR, MD, assets, versions all gone
    # originating job workspace removed too (no orphans)
    assert not (docdir.parent.parent / "jobs" / job_id).exists()


def test_failed_parse_leaves_no_half_document(tmp_path):
    """Failed parse must NOT create a library record."""
    _, client, job_id = _parse_ok(tmp_path, content=ILLEGAL)
    doc = _wait_done(client, job_id)
    assert doc["status"] == "failed"
    assert client.get("/api/documents").json() == []


def test_empty_reply_document_ok_not_error(tmp_path):
    _, client, job_id = _parse_ok(tmp_path, content="")
    doc = _wait_done(client, job_id)
    assert doc["status"] == "done"
    assert client.get("/api/documents").json()[0]  # record created, empty doc


def test_reparse_updates_same_record_no_duplicate(tmp_path):
    """Re-parse reuses original and adds a version, never a duplicate record."""
    _, client, job_id = _parse_ok(tmp_path, name="sheet.png")
    doc = _wait_done(client, job_id)
    did = doc["document_id"]
    assert len(client.get(f"/api/documents/{did}").json()["versions"]) == 1

    r = client.post(f"/api/documents/{did}/reparse")
    assert r.status_code == 200
    rj = r.json()["job_id"]
    _wait_done(client, rj)

    docs = client.get("/api/documents").json()
    assert len(docs) == 1 and docs[0]["document_id"] == did
    rec = client.get(f"/api/documents/{did}").json()
    assert len(rec["versions"]) == 2
    assert rec["current_markdown"]  # latest parse won


def test_document_export_zip_contains_edited_md_and_assets(tmp_path):
    _, client, job_id = _parse_ok(tmp_path)
    _wait_done(client, job_id)
    did = _did_from_job(client, job_id)
    edited = "# 编辑后\n\n导出应包含此行。\n"
    r = client.post(f"/api/documents/{did}/export", json={"markdown": edited})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    md = next(n for n in names if n.endswith(".md"))
    assert z.read(md).decode("utf-8") == edited
    assert any(n.startswith("assets/") for n in names), names
    assert "export-notes.json" in names


def _did_from_job(client, job_id):
    return client.get(f"/api/jobs/{job_id}").json()["document_id"]


def test_delete_unknown_document_404(tmp_path):
    _, client, _ = _parse_ok(tmp_path)
    assert client.delete("/api/documents/nope").status_code == 404


def test_get_unknown_document_404(tmp_path):
    _, client, _ = _parse_ok(tmp_path)
    assert client.get("/api/documents/nope").status_code == 404


def test_session_store_seam_works_in_memory(tmp_path):
    """SessionDocumentStore implements the same seam (non-durable)."""
    from graph2note.store import SessionDocumentStore

    app = webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=str(tmp_path),
        document_store=SessionDocumentStore(tmp_path),
        router_factory=_router_factory(VALID),
    )
    client = TestClient(app)
    r = client.post("/api/parse", files={"file": ("sess.png", _make_png(), "image/png")})
    job = _wait_done(client, r.json()["job_id"])
    assert job["document_id"]
    docs = client.get("/api/documents").json()
    assert len(docs) == 1
    # delete from session store also cleans the job workspace
    assert client.delete(f"/api/documents/{job['document_id']}").status_code == 200
    assert client.get("/api/documents").json() == []