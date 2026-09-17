"""Offline Web/API tests for the SPW I/P1 paper import endpoints.

`/api/papers/*` is an appended route segment: these tests drive the whole
upload → status → result chain through the FastAPI TestClient with injected
offline routers, so no model call and no network access happens here.

PDFs are synthetic (PyMuPDF) and the suite skips cleanly without it.
"""

import io
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import pdflib  # noqa: E402
from graph2note import papers  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402
from tests.static_assets import WEBSTATIC  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")

TEXT_PAGES = [
    [
        ("A Study of Things", 18.0),
        ("Alice, Bob", 10.0),
        ("Abstract", 13.0),
        ("We study things deeply and report a long series of measurements", 10.0),
        ("that together describe the behaviour of the system we built.", 10.0),
        ("1 Introduction", 15.0),
        ("Papers are nice to read when the text layer is available because", 10.0),
        ("the extraction stays deterministic and needs no model call at all.", 10.0),
    ],
    [
        ("2 Method", 15.0),
        ("2.1 Overview", 12.0),
        ("We do stuff carefully, measuring everything twice for stability.", 10.0),
        ("References", 15.0),
        ("[1] Foo et al. 2020. A useful reference entry for the list.", 10.0),
    ],
]


def _text_pdf(pages=None):
    pages = TEXT_PAGES if pages is None else pages
    doc = pymupdf.open()
    for entries in pages:
        page = doc.new_page()
        y = 90.0
        for text, size in entries:
            page.insert_text((72, y), text, fontsize=size)
            y += size + 10
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _scan_pdf(page_count=2, encrypt_with=None):
    np = pytest.importorskip("numpy")
    PILImage = pytest.importorskip("PIL.Image")
    doc = pymupdf.open()
    for index in range(page_count):
        rng = np.random.default_rng(200 + index)
        arr = np.full((320, 440, 3), 250, np.uint8)
        for row in range(3 + index):
            y = 40 + row * 70
            x = int(rng.integers(20, 140))
            arr[y:y + 6, x:x + int(rng.integers(80, 240)), :] = 20
        image = PILImage.fromarray(arr)
        page = doc.new_page(width=440, height=320)
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        page.insert_image(page.rect, stream=buffer.getvalue())
    out = io.BytesIO()
    if encrypt_with is not None:
        doc.save(out, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                 user_pw=encrypt_with, owner_pw=encrypt_with)
    else:
        doc.save(out)
    doc.close()
    return out.getvalue()


def _boom_factory(*_args, **_kwargs):
    raise AssertionError("the text-layer path must never construct a router")


class _FlipRouterFactory:
    """Router factory that fails until ``fail`` is flipped (retry tests)."""

    def __init__(self):
        self.fail = True
        self.calls = []

    def factory(self, image_path, model):
        def caller(path, selected_model, recover=False):
            self.calls.append(str(path))
            if self.fail:
                raise RuntimeError("injected parse failure")
            return GOLDEN, {}

        return RouteARouter(model, caller=caller, max_retries=1)


def _app(tmp_path, router_factory, store=None, **kwargs):
    store = store or FileDocumentStore(tmp_path / "store")
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=tmp_path / "store",
        document_store=store,
        router_factory=router_factory,
        max_retries=1,
        **kwargs,
    )


def _import(client, data, filename="paper.pdf"):
    return client.post("/api/papers/import",
                       files={"file": (filename, data, "application/pdf")})


def _wait(client, paper_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/papers/{paper_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] not in ("queued", "processing"):
            return body
        time.sleep(0.1)
    raise AssertionError("paper job did not finish in time")


# ---------------------------------------------------------------------------
# AC5/AC6: upload -> status -> result -> original page
# ---------------------------------------------------------------------------


def test_paper_import_text_layer_chain(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    data = _text_pdf()

    response = _import(client, data, "study.pdf")
    assert response.status_code == 200, response.text
    uploaded = response.json()
    assert uploaded["paper_id"] == papers.stable_paper_id(data)
    assert uploaded["pdf_id"] == uploaded["paper_id"]
    assert uploaded["total_pages"] == 2

    status = _wait(client, uploaded["paper_id"])
    assert status["status"] == "done"
    assert status["source"] == "text-layer"   # zero LLM calls (raising factory)
    assert status["sections"] >= 5
    assert status["document_id"] == f"{uploaded['paper_id']}-paper"

    result = client.get(f"/api/papers/{uploaded['paper_id']}/result")
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["doc_kind"] == "paper"
    assert body["source"] == "text-layer"
    titles = [section["title"] for section in body["sections"]]
    assert titles == ["A Study of Things", "Abstract", "Introduction",
                      "Method", "Overview", "References"]
    assert body["sections"][-1]["page_start"] == 1
    # import now runs the deterministic P2 pass: the result reflects the meta
    # that the reading view will show (no more filename-only titles).
    assert body["meta"]["title"] == "A Study of Things"
    assert body["meta"]["authors"] == ["Alice", "Bob"]
    assert body["meta"]["abstract"].startswith("We study things deeply")
    assert body["meta_status"] == "ok" and body["meta_error"] is None
    assert body["references"][0]["raw"].startswith("[1] Foo")
    assert body["references"][0]["resolved_document_id"] is None
    assert body["pages"][0]["page_number"] == 1

    # the paper is a normal library document with doc_kind provenance
    document = client.get(f"/api/documents/{body['document_id']}").json()
    assert document["doc_kind"] == "paper"
    assert document["pdf_id"] == uploaded["paper_id"]
    library = client.get("/api/documents").json()
    assert [item["doc_kind"] for item in library] == ["paper"]

    # original page viewing reuses the /source-page mechanism + paper pages
    assert client.get(f"/api/documents/{body['document_id']}/source-page").status_code == 200
    assert client.get(f"/api/papers/{uploaded['paper_id']}/page/0").status_code == 200
    assert client.get(f"/api/papers/{uploaded['paper_id']}/page/99").status_code == 404
    assert client.get(f"/api/papers/{uploaded['paper_id']}/original").status_code == 200

    listing = client.get("/api/papers").json()
    assert [item["paper_id"] for item in listing] == [uploaded["paper_id"]]


def test_paper_import_is_idempotent_for_same_bytes(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    data = _text_pdf()
    first = _import(client, data).json()
    status = _wait(client, first["paper_id"])
    second = _import(client, data).json()
    assert second["status"] == "done"
    assert second["triggered"] is False
    assert second["document_id"] == status["document_id"]
    # a second import never creates a second version
    record = client.get(f"/api/documents/{status['document_id']}").json()
    assert len(record["versions"]) == 1


def test_paper_import_falls_back_to_vlm_for_scan(tmp_path):
    flip = _FlipRouterFactory()
    flip.fail = False
    client = TestClient(_app(tmp_path, flip.factory))
    response = _import(client, _scan_pdf(2), "scan.pdf")
    assert response.status_code == 200, response.text
    paper_id = response.json()["paper_id"]

    status = _wait(client, paper_id)
    assert status["status"] == "done"
    assert status["source"] == "vlm"          # SPEC §2 fallback provenance
    assert flip.calls, "the scan must go through the injected router factory"

    result = client.get(f"/api/papers/{paper_id}/result").json()
    assert result["source"] == "vlm"
    assert result["provenance"]["source"] == "vlm"
    assert result["provenance"]["page_document_ids"] == status["page_documents"]
    # per-page documents remain reachable through the issue-08 PDF surface
    for document_id in status["page_documents"]:
        assert client.get(f"/api/documents/{document_id}").status_code == 200
        assert client.get(f"/api/documents/{document_id}/source-page").status_code == 200


# ---------------------------------------------------------------------------
# AC5: actionable errors (reuses pdflib limits)
# ---------------------------------------------------------------------------


def test_paper_import_rejects_wrong_type(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    response = client.post("/api/papers/import",
                           files={"file": ("notes.txt", b"x", "text/plain")})
    assert response.status_code == 415
    assert "PDF" in response.json()["detail"]


def test_paper_import_rejects_corrupt_and_empty(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    assert _import(client, b"not-a-pdf", "bad.pdf").status_code == 400
    assert _import(client, b"", "empty.pdf").status_code == 400


def test_paper_import_rejects_encrypted(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    response = _import(client, _scan_pdf(1, encrypt_with="secret"), "locked.pdf")
    assert response.status_code == 422
    assert "加密" in response.json()["detail"]


def test_paper_import_rejects_oversized(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, _boom_factory))
    data = _text_pdf()
    monkeypatch.setattr(pdflib, "MAX_PDF_SIZE", 100)
    response = _import(client, data)
    assert response.status_code == 413
    assert "上限" in response.json()["detail"]


def test_paper_import_rejects_too_many_pages(tmp_path, monkeypatch):
    client = TestClient(_app(tmp_path, _boom_factory))
    data = _text_pdf()
    monkeypatch.setattr(pdflib, "MAX_PDF_PAGES", 1)
    response = _import(client, data)
    assert response.status_code == 422
    assert "页数" in response.json()["detail"]


# ---------------------------------------------------------------------------
# status/result contracts, recovery and retry
# ---------------------------------------------------------------------------


def test_paper_status_and_result_unknown_ids(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    assert client.get("/api/papers/does-not-exist").status_code == 404
    assert client.get("/api/papers/does-not-exist/result").status_code == 404
    assert client.get("/api/papers/does-not-exist/original").status_code == 404
    assert client.post("/api/papers/does-not-exist/retry").status_code == 404


def test_paper_result_before_completion_is_actionable(tmp_path):
    """A failed scan has no paper document -> result is 409 with a message."""
    client = TestClient(_app(tmp_path, _FlipRouterFactory().factory))
    paper_id = _import(client, _scan_pdf(1), "scan.pdf").json()["paper_id"]
    status = _wait(client, paper_id)
    assert status["status"] == "failed"
    assert status["error_kind"] == "vlm_empty"
    assert status["document_id"] is None
    response = client.get(f"/api/papers/{paper_id}/result")
    assert response.status_code == 409
    assert "尚未导入完成" in response.json()["detail"]


def test_paper_retry_resumes_a_failed_job(tmp_path):
    flip = _FlipRouterFactory()
    client = TestClient(_app(tmp_path, flip.factory))
    paper_id = _import(client, _scan_pdf(2), "scan.pdf").json()["paper_id"]
    failed = _wait(client, paper_id)
    assert failed["status"] == "failed"

    flip.fail = False
    retried = client.post(f"/api/papers/{paper_id}/retry")
    assert retried.status_code == 200
    assert retried.json()["triggered"] is True
    recovered = _wait(client, paper_id)
    assert recovered["status"] == "done"
    assert recovered["source"] == "vlm"
    assert recovered["document_id"]

    # an already-finished job is never re-imported by a retry
    again = client.post(f"/api/papers/{paper_id}/retry").json()
    assert again["triggered"] is False
    assert "已完成" in again["message"]


def test_paper_done_retry_is_a_noop(tmp_path):
    client = TestClient(_app(tmp_path, _boom_factory))
    paper_id = _import(client, _text_pdf()).json()["paper_id"]
    done = _wait(client, paper_id)
    assert done["status"] == "done"
    response = client.post(f"/api/papers/{paper_id}/retry").json()
    assert response["triggered"] is False
    assert response["document_id"] == done["document_id"]


def test_paper_job_interrupted_is_reconciled_on_reload(tmp_path):
    """A durable job left in 'processing' is reported as interrupted (issue 09)."""
    store = FileDocumentStore(tmp_path / "store")
    client = TestClient(_app(tmp_path, _boom_factory, store=store))
    paper_id = "pdf-0123456789abcdef"
    directory = papers.paper_dir(store, paper_id)
    directory.mkdir(parents=True, exist_ok=True)
    job = papers.PaperJob(paper_id=paper_id, filename="p.pdf", work_dir=str(directory))
    with job.lock:
        job.status = "processing"
    papers.save_job(job)

    status = client.get(f"/api/papers/{paper_id}").json()
    assert status["status"] == "interrupted"
    assert status["error_kind"] == "interrupted"
    # the reconciled state is durable, not only in memory
    assert papers.load_job(directory).status == "interrupted"


def test_paper_error_does_not_touch_other_routes(tmp_path):
    """Appending /api/papers/* leaves the existing document routes intact."""
    client = TestClient(_app(tmp_path, _boom_factory))
    assert client.get("/api/documents").status_code == 200
    assert client.get("/api/papers").status_code == 200
    assert client.get("/api/pdf").status_code == 200


# ---------------------------------------------------------------------------
# AC5: frontend entry (append-only upload.js; P3 land untouched)
# ---------------------------------------------------------------------------


def test_upload_entry_routes_pdf_to_the_paper_pipeline():
    upload = (WEBSTATIC / "js" / "views" / "upload.js").read_text(encoding="utf-8")
    assert "/api/papers/import" in upload
    assert "/api/papers/" in upload              # status polling
    assert "isPdfFile" in upload
    assert "interceptPaperFile" in upload        # PDFs are intercepted …
    assert "stopPropagation" in upload           # … before the image handlers
    assert 'document.addEventListener("change", interceptPaperFile, true)' in upload
    assert 'document.addEventListener("drop", interceptPaperFile, true)' in upload


def test_p1_frontend_change_stays_out_of_p3_files():
    """P1 only appends to upload.js; router/api/state stay P3 territory."""
    for name in ("router.js", "api.js", "state.js"):
        source = (WEBSTATIC / "js" / name).read_text(encoding="utf-8")
        assert "papers" not in source, f"P1 must not touch {name}"


def test_upload_module_is_valid_es_module(tmp_path):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    target = tmp_path / "upload-check.mjs"
    shutil.copy(WEBSTATIC / "js" / "views" / "upload.js", target)
    completed = subprocess.run([node, "--check", str(target)],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
