"""Offline Web/API tests for PDF upload -> split -> parse -> library (issue 08).

Every parse path injects a router that returns *recorded* golden content, so
the suite is deterministic and never touches the network (AC5: parse stub is
isolated from real model calls).  PDFs are built synthetically with PyMuPDF
and the tests SKIP cleanly when PyMuPDF is unavailable (optional dependency).
"""

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import webapp  # noqa: E402
from graph2note import pdflib  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore, SessionDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# synthetic PDF builders (deterministic, no network)
# ---------------------------------------------------------------------------


def _make_page(seed=1, w=300, h=420, empty=False, ink=30):
    rng = np.random.default_rng(seed)
    arr = np.full((h, w, 3), 250, np.uint8)
    if not empty:
        for i in range(4):
            y = 60 + i * 90
            x = int(rng.integers(30, 120))
            arr[y:y + 4, x:x + int(rng.integers(50, 200)), :] = ink
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _pdf_bytes(images, encrypt_with=None) -> bytes:
    doc = pymupdf.open()
    for img in images:
        page = doc.new_page(width=img.width, height=img.height)
        # render to a tiny PNG then embed (page rect sized to the image)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        page.insert_image(page.rect, stream=buf.getvalue())
    out = io.BytesIO()
    if encrypt_with is not None:
        doc.save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 user_pw="secret", owner_pw="secret")
    else:
        doc.save(out)
    doc.close()
    return out.getvalue()


def _router_factory(content=GOLDEN, fail_on=None):
    """Router factory whose caller returns ``content`` (offline golden stub).

    ``fail_on`` is a substring of the split page image path; pages whose image
    path contains it raise (simulating a per-page model failure, AC4).
    """

    def caller(image_path, model, recover=False):
        if fail_on and fail_on in str(image_path):
            raise RuntimeError("injected per-page parse failure")
        return content, {}

    def factory(image_path, model):
        return RouteARouter(model, caller=caller, max_retries=1)

    return factory


def _app(content=GOLDEN, fail_on=None, storage_dir=None, store=None, **kw):
    import tempfile

    # reject-path tests never set a storage dir; use an isolated temp dir so the
    # repo root never accumulates a `.g2n-storage` runtime dir.
    if storage_dir is None and store is None:
        storage_dir = tempfile.mkdtemp(prefix="g2n-pdf-test-")
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=storage_dir,
        document_store=store,
        router_factory=_router_factory(content, fail_on),
        max_retries=1,
        **kw,
    )


def _upload_pdf(client, data, filename="scan.pdf"):
    return client.post("/api/pdf",
                       files={"file": (filename, data, "application/pdf")})


def _wait_pdf_done(client, pdf_id, timeout=30):
    import time

    for _ in range(int(timeout / 0.1)):
        r = client.get(f"/api/pdf/{pdf_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] not in ("queued", "processing"):
            return body
        time.sleep(0.1)
    raise AssertionError("pdf job did not finish in time")


# ---------------------------------------------------------------------------
# AC4: limits and actionable errors
# ---------------------------------------------------------------------------


def test_pdf_rejects_wrong_type():
    client = TestClient(_app())
    r = client.post("/api/pdf",
                    files={"file": ("note.txt", b"x", "text/plain")})
    assert r.status_code == 415
    assert "PDF" in r.json()["detail"]


def test_pdf_rejects_empty_file():
    client = TestClient(_app())
    r = client.post("/api/pdf",
                    files={"file": ("empty.pdf", b"", "application/pdf")})
    assert r.status_code == 400
    assert "空文件" in r.json()["detail"]


def test_pdf_rejects_too_large():
    client = TestClient(_app())
    import graph2note.pdflib as pl

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pl, "MAX_PDF_SIZE", 1000)
    try:
        r = client.post("/api/pdf",
                        files={"file": ("big.pdf", b"0" * 2000, "application/pdf")})
        assert r.status_code == 413
        assert "上限" in r.json()["detail"]
    finally:
        monkeypatch.undo()


def test_pdf_rejects_corrupt_bytes():
    client = TestClient(_app())
    r = client.post("/api/pdf",
                    files={"file": ("bad.pdf", b"not-a-pdf", "application/pdf")})
    assert r.status_code == 400
    assert "损坏" in r.json()["detail"] or "无法打开" in r.json()["detail"]


def test_pdf_rejects_encrypted():
    data = _pdf_bytes([_make_page(1)], encrypt_with="secret")
    client = TestClient(_app())
    r = client.post("/api/pdf",
                    files={"file": ("locked.pdf", data, "application/pdf")})
    assert r.status_code == 422
    assert "加密" in r.json()["detail"]


def test_pdf_rejects_too_many_pages():
    data = _pdf_bytes([_make_page(i) for i in range(4)])
    client = TestClient(_app())
    import graph2note.pdflib as pl

    # default MAX_PDF_PAGES is 200; lower the module constant to prove the
    # page-count ceiling is explicit + actionable (validate_pdf reads it at
    # call time, so patching before the request is enough).
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(pl, "MAX_PDF_PAGES", 3)
    try:
        r = client.post("/api/pdf",
                        files={"file": ("many.pdf", data, "application/pdf")})
        assert r.status_code == 422
        assert "页数" in r.json()["detail"] and "上限" in r.json()["detail"]
    finally:
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# AC1: full chain — upload -> split -> actual parse -> library (no placeholders)
# ---------------------------------------------------------------------------


def test_pdf_upload_parses_every_page_into_real_documents(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    data = _pdf_bytes([_make_page(1), _make_page(2), _make_page(3)])
    client = TestClient(_app())
    r = _upload_pdf(client, data, "three.pdf")
    assert r.status_code == 200, r.text
    pdf_id = r.json()["pdf_id"]
    assert r.json()["total_pages"] == 3

    body = _wait_pdf_done(client, pdf_id)
    assert body["status"] == "done"
    assert body["counts"] == {"success": 3, "failed": 0, "blank": 0,
                              "duplicate": 0, "pending": 0}

    docs = client.get("/api/documents").json()
    assert len(docs) == 3
    for page in body["pages"]:
        assert page["status"] == "success"
        assert page["document_id"]
        # a *real* parse committed, never a "待解析" placeholder (AC1)
        doc = client.get(f"/api/documents/{page['document_id']}").json()
        md = doc.get("current_markdown") or ""
        assert "状态空间模型" in md
        assert "待解析" not in md


# ---------------------------------------------------------------------------
# AC2: stable pdf identity + stable page order + open original PDF page
# ---------------------------------------------------------------------------


def test_pdf_stable_identity_and_ordering(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    data = _pdf_bytes([_make_page(i) for i in (3, 1, 2)])  # distinct pages
    client = TestClient(_app())

    r1 = _upload_pdf(client, data, "order.pdf")
    r2 = _upload_pdf(client, data, "order.pdf")
    # stable content-derived identity (AC2)
    assert r1.json()["pdf_id"] == r2.json()["pdf_id"]
    assert r1.json()["pdf_id"] == pdflib.stable_pdf_id(data)

    body = _wait_pdf_done(client, r1.json()["pdf_id"])
    assert body["status"] == "done"
    # results are always in source page order, never completion order (AC2)
    idxs = [p["page_index"] for p in body["pages"]]
    assert idxs == sorted(idxs) == [0, 1, 2]
    # each page document links back to its original PDF page (AC2)
    for page in body["pages"]:
        doc = client.get(f"/api/documents/{page['document_id']}").json()
        assert doc.get("pdf_id") == r1.json()["pdf_id"]
        assert doc.get("page_index") == page["page_index"]
        # the "open original PDF page" view renders from the durable PDF
        src = client.get(f"/api/documents/{page['document_id']}/source-page")
        assert src.status_code == 200
        assert src.headers["content-type"] == "image/png"
        assert src.content[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# AC3: blank / duplicate / success / failed distinguishable; dedup keeps mapping
# ---------------------------------------------------------------------------


def test_pdf_blank_duplicate_failed_are_distinguishable(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    p0 = _make_page(7)             # content (will be parsed)
    p_dup = _make_page(7, ink=26)  # near-duplicate of p0 (different brightness)
    p_blank = _make_page(99, empty=True)
    p_fail = _make_page(11)        # content the stub is told to fail on
    data = _pdf_bytes([p0, p_blank, p_dup, p_fail])
    client = TestClient(_app(fail_on="p004"))
    r = _upload_pdf(client, data, "mix.pdf")
    body = _wait_pdf_done(client, r.json()["pdf_id"])
    assert body["status"] == "done"
    assert body["counts"] == {"success": 1, "failed": 1, "blank": 1,
                              "duplicate": 1, "pending": 0}

    by_idx = {p["page_index"]: p for p in body["pages"]}
    assert by_idx[0]["status"] == "success"
    assert by_idx[1]["status"] == "blank"
    assert by_idx[2]["status"] == "duplicate"
    assert by_idx[3]["status"] == "failed"
    # dedup kept the full source mapping: the duplicate page maps to the same
    # document as its representative, and every page has an explainable status
    assert by_idx[2]["merged_into"] == 0
    assert by_idx[2]["document_id"] == by_idx[0]["document_id"]
    assert by_idx[3]["error"] and "injected" in by_idx[3]["error"]
    # the failed page produced no document; the successful one is real
    assert by_idx[3]["document_id"] is None
    assert client.get(f"/api/documents/{by_idx[0]['document_id']}").status_code == 200


# ---------------------------------------------------------------------------
# AC4: one page failing must not discard successful pages
# ---------------------------------------------------------------------------


def test_pdf_partial_failure_keeps_success_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    data = _pdf_bytes([_make_page(1), _make_page(2)])  # p001 ok, p002 fails
    client = TestClient(_app(fail_on="p002"))
    r = _upload_pdf(client, data, "partial.pdf")
    body = _wait_pdf_done(client, r.json()["pdf_id"])
    assert body["status"] == "done"          # whole job still completes
    assert body["counts"]["success"] == 1
    assert body["counts"]["failed"] == 1
    pages = {p["page_index"]: p for p in body["pages"]}
    assert pages[0]["status"] == "success" and pages[0]["document_id"]
    assert pages[1]["status"] == "failed" and pages[1]["document_id"] is None
    # the successful page's document is real and queryable
    ok = client.get(f"/api/documents/{pages[0]['document_id']}").json()
    assert "状态空间模型" in (ok.get("current_markdown") or "")


# ---------------------------------------------------------------------------
# AC5: offline fixture through Web/API/storage/view; mapping survives reload
# ---------------------------------------------------------------------------


def test_pdf_source_mapping_survives_reload(tmp_path, monkeypatch):
    storage = tmp_path / "store"
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(storage))
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(store=FileDocumentStore(str(storage))))
    r = _upload_pdf(client, data, "reload.pdf")
    pdf_id = r.json()["pdf_id"]
    body = _wait_pdf_done(client, pdf_id)
    assert body["status"] == "done"

    # durable job state records the full source mapping on disk (AC5)
    job_json = storage / "pdfs" / pdf_id / "job.json"
    assert job_json.is_file()
    saved = json.loads(job_json.read_text(encoding="utf-8"))
    saved_pages = {p["page_index"]: p for p in saved["pages"]}
    assert saved_pages[0]["document_id"] and saved_pages[1]["document_id"]
    assert saved_pages[0]["document_id"] != saved_pages[1]["document_id"]

    # "reload": a brand-new app instance over the same durable storage
    client2 = TestClient(_app(store=FileDocumentStore(str(storage))))
    docs = client2.get("/api/documents").json()
    assert len(docs) == 2
    for d in docs:
        rec = client2.get(f"/api/documents/{d['document_id']}").json()
        assert rec.get("pdf_id") == pdf_id
        assert rec.get("page_index") is not None
        # original PDF page still viewable from the page document after reload
        src = client2.get(f"/api/documents/{d['document_id']}/source-page")
        assert src.status_code == 200
        assert src.content[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# Session store (non-durable) implements the same seam
# ---------------------------------------------------------------------------


def test_pdf_session_store_same_seam(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH2NOTE_STORAGE", str(tmp_path / "store"))
    data = _pdf_bytes([_make_page(1)])
    client = TestClient(_app(store=SessionDocumentStore(str(tmp_path / "s"))))
    r = _upload_pdf(client, data, "sess.pdf")
    body = _wait_pdf_done(client, r.json()["pdf_id"])
    assert body["status"] == "done"
    assert body["counts"]["success"] == 1
    doc = client.get(f"/api/documents/{body['pages'][0]['document_id']}").json()
    assert doc.get("pdf_id") == r.json()["pdf_id"]
    assert client.get(f"/api/documents/{doc['document_id']}/source-page").status_code == 200
