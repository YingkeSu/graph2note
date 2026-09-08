"""Offline FastAPI TestClient tests for the Web app (issue 06).

Every parse path injects a router that returns *recorded* content (golden),
so the suite is deterministic and never touches the network.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402

HERE = Path(__file__).parent


def _golden(name):
    return (HERE / "golden" / name).read_text(encoding="utf-8")


VALID = _golden("valid-ir.golden.json")
ILLEGAL = _golden("illegal-ir.golden.json")


def _make_png(w=600, h=420, text="WebApp 测试标题"):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    d.text((30, 40), text, fill=(20, 20, 20), font=font)
    d.text((30, 90), "第二行内容用于预处理校验", fill=(30, 30, 30), font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _router_factory(content):
    """Return a router factory that always answers with ``content`` (offline)."""
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
    import time

    for _ in range(int(timeout / 0.1)):
        r = client.get(f"/api/jobs/{job_id}")
        assert r.status_code == 200, r.text
        doc = r.json()
        if doc["status"] not in ("queued", "processing"):
            return doc
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def test_upload_valid_png_runs_chain(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    doc = _wait_done(client, job_id)
    assert doc["status"] == "done"
    assert "状态空间模型" in doc["markdown"]
    # preprocessed + assets served
    assert client.get(f"/api/jobs/{job_id}/preprocessed").status_code == 200
    # original preserved
    assert client.get(f"/api/jobs/{job_id}/original").status_code == 200
    # every image reference in the .md resolves via the job asset endpoint
    # (webapp job workspace keeps .md refs and assets/ under one root — issue 15b)
    import re
    refs = re.findall(r"\[([^\]]*)\]\(([^)\s]+)\)", doc["markdown"])
    img_refs = [r[1] for r in refs if r[1].startswith("assets/")]
    assert img_refs, "expected at least one asset reference in job markdown"
    for name in img_refs:
        assert client.get(
            f"/api/jobs/{job_id}/assets/{name[len('assets/'):]}"
        ).status_code == 200


def test_upload_rejects_non_image_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("note.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    assert "JPG/JPEG/PNG" in r.json()["detail"]


def test_upload_rejects_invalid_png_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("fake.png", b"not-an-image", "image/png")})
    assert r.status_code == 415
    assert "无效" in r.json()["detail"] or "不是" in r.json()["detail"]


def test_upload_rejects_too_large(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    big = b"0" * (11 * 1024 * 1024)
    r = client.post("/api/parse",
                    files={"file": ("big.png", big, "image/png")})
    assert r.status_code == 413
    assert "10MB" in r.json()["detail"]


def test_upload_rejects_empty_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("empty.png", b"", "image/png")})
    assert r.status_code == 400


def test_invalid_ir_leads_to_clean_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app(content=ILLEGAL))
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    job_id = r.json()["job_id"]
    doc = _wait_done(client, job_id)
    assert doc["status"] == "failed"
    assert "解析失败" in (doc["error"] or "")


def test_empty_reply_degrades_to_empty_doc_not_error(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app(content=""))
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    job_id = r.json()["job_id"]
    doc = _wait_done(client, job_id)
    assert doc["status"] == "done"
    assert doc["empty"] is True
    assert doc["markdown"] == ""


def test_reparse_reuses_original_and_overwrites(tmp_path, monkeypatch):
    """Reparse uses stored original (no re-upload); returns to processing."""
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    job_id = r.json()["job_id"]
    _wait_done(client, job_id)
    # change model content on the router is not possible after mount, but
    # reparse must at least restart cleanly and finish again.
    re = client.post(f"/api/jobs/{job_id}/reparse")
    assert re.status_code == 200
    assert re.json()["status"] == "queued"
    doc = _wait_done(client, job_id)
    assert doc["status"] == "done"
    # original still present (reused, not lost)
    assert client.get(f"/api/jobs/{job_id}/original").status_code == 200


def test_export_zip_contains_edited_md_and_assets(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    job_id = r.json()["job_id"]
    _wait_done(client, job_id)

    edited = "# 编辑后\n\n用户修改的正文\n"
    rr = client.post(
        f"/api/jobs/{job_id}/export",
        json={"markdown": edited},
    )
    assert rr.status_code == 200
    assert rr.headers["content-type"].startswith("application/zip")
    z = zipfile.ZipFile(io.BytesIO(rr.content))
    names = z.namelist()
    md_name = next(n for n in names if n.endswith(".md"))
    assert z.read(md_name).decode("utf-8") == edited
    # any diagram asset referenced is included under assets/
    assert any(n.startswith("assets/") for n in names), names
    assert "export-notes.json" in names


def test_export_before_done_is_409(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    job_id = r.json()["job_id"]
    # hit export while queued/processing
    import time

    for _ in range(20):
        s = client.get(f"/api/jobs/{job_id}").json()["status"]
        if s in ("queued", "processing"):
            break
        time.sleep(0.05)
    rr = client.post(f"/api/jobs/{job_id}/export", json={"markdown": "x"})
    assert rr.status_code == 409


def test_unknown_job_404(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    assert client.get("/api/jobs/doesnotexist").status_code == 404


def test_timeout_yields_clear_timeout_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    monkeypatch.setattr(webapp, "JOB_TIMEOUT", 0.3)
    client = TestClient(_app())

    def slow_factory(image_path, model):
        def caller(p, m, recover=False):
            import time

            time.sleep(3)
            return VALID, {}
        return RouteARouter(model, caller=caller)

    # build an app with a slow router by re-mounting the variable
    import graph2note.webapp as w

    app = w.create_app(model="glm-5.3-flash", storage_dir=str(tmp_path / "s2"),
                       router_factory=slow_factory)
    client = TestClient(app)
    r = client.post("/api/parse",
                    files={"file": ("note.png", _make_png(), "image/png")})
    job_id = r.json()["job_id"]
    import time

    doc = None
    for _ in range(40):
        doc = client.get(f"/api/jobs/{job_id}").json()
        if doc["status"] in ("timeout", "failed"):
            break
        time.sleep(0.1)
    assert doc is not None and doc["status"] == "timeout"
    assert "超时" in (doc["error"] or "")


def test_index_served(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    client = TestClient(_app())
    r = client.get("/")
    assert r.status_code == 200
    assert "graph2note" in r.text
    # static assets present
    assert client.get("/static/app.js").status_code == 200


# --- issue 13: duplicate upload merges + candidate-version viewing ----------

def test_duplicate_upload_merges_and_versions_viewable(tmp_path, monkeypatch):
    """AC5 (minimal, offline): uploading the same page twice folds the second
    scan into the first DocumentRecord as a new candidate version (no new
    record), the job exposes a "已并入文档 X"-style notice, and the record lists
    both candidate versions for the UI."""
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    img_bytes = _make_png()
    client = TestClient(_app())

    # first upload -> own record
    r1 = client.post("/api/parse",
                     files={"file": ("note.png", img_bytes, "image/png")})
    d1 = _wait_done(client, r1.json()["job_id"])
    assert d1["status"] == "done"
    assert d1["document_id"]
    assert d1["merged_into"] is None
    store = client.app.state.store
    first_id = d1["document_id"]

    # second upload, identical page -> merges into first record, notice set
    r2 = client.post("/api/parse",
                     files={"file": ("note.png", img_bytes, "image/png")})
    d2 = _wait_done(client, r2.json()["job_id"])
    assert d2["status"] == "done"
    assert d2["merged_into"] == first_id
    assert d2["document_id"] == first_id

    docs = store.list_documents()
    assert len(docs) == 1                 # still ONE record, never duplicated
    rec = store.get_document(first_id)
    assert rec is not None
    assert len(rec["versions"]) == 2      # both scans retained as versions
    # candidate version list is queryable and latest (second scan) is effective
    vids = [v["version_id"] for v in rec["versions"]]
    assert d2["document_id"] == first_id
    assert rec["latest_version_id"] == vids[-1]
    # document detail endpoint surfaces version data (UI version viewing)
    detail = client.get(f"/api/documents/{first_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body.get("document_id") == first_id
    assert len(body.get("versions", [])) >= 2
    assert client.get("/static/style.css").status_code == 200