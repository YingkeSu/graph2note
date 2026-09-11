"""Offline fault-injection tests for durable/resumable PDF batch jobs (issue 09).

Covers interruption/restart recovery, retry-only-incomplete, idempotency,
bounded attempts/timeout/concurrency, and commit-before-status-persist
recovery.  Every parse path injects a router that returns recorded golden
content (or a deterministic failure), so the suite never touches the network.
PDFs are built synthetically with PyMuPDF; tests SKIP cleanly without it.
"""

import io
import json
import re
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import pdflib  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# synthetic PDF builders + offline router stub (deterministic, no network)
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


def _pdf_bytes(images) -> bytes:
    doc = pymupdf.open()
    for img in images:
        page = doc.new_page(width=img.width, height=img.height)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "PNG")
        page.insert_image(page.rect, stream=buf.getvalue())
    out = io.BytesIO()
    doc.save(out)
    doc.close()
    return out.getvalue()


def _router_factory(*, calls=None, fail_first=(), fail_always=(),
                    delay=0.0, delay_pages=(), gate=None):
    """Offline router factory with injectable faults.

    - ``calls`` records the split-page stem (e.g. ``p002``) per model call.
    - ``fail_first`` pages fail their *first* attempt then succeed (transient).
    - ``fail_always`` pages always fail (bounded-retry exhaustion).
    - ``delay``/``delay_pages`` simulate a slow page (per-page timeout).
    - ``gate`` blocks every call until released (single-flight test).
    """
    calls = calls if calls is not None else []
    fail_first = set(fail_first)
    fail_always = set(fail_always)
    delay_pages = set(delay_pages)
    failed_once: set[str] = set()
    lock = threading.Lock()

    def caller(image_path, model, recover=False):
        m = re.search(r"p(\d{3})", str(image_path))
        key = f"p{m.group(1)}" if m else Path(image_path).stem
        with lock:
            calls.append(key)
            if key in fail_first and key not in failed_once:
                failed_once.add(key)
                raise RuntimeError("injected transient per-page failure")
        if gate is not None:
            gate.wait(timeout=10)
        if delay and (not delay_pages or key in delay_pages):
            time.sleep(delay)
        if key in fail_always:
            raise RuntimeError("injected per-page failure")
        return GOLDEN, {}

    def factory(image_path, model):
        return RouteARouter(model, caller=caller, max_retries=0)

    return factory


def _app(store=None, storage_dir=None, factory=None, **kw):
    import tempfile

    if store is None:
        storage_dir = storage_dir or tempfile.mkdtemp(prefix="g2n-pdf09-")
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=storage_dir,
        document_store=store,
        router_factory=factory or _router_factory(),
        max_retries=0,
        **kw,
    )


def _upload(client, data, filename="scan.pdf"):
    return client.post("/api/pdf",
                       files={"file": (filename, data, "application/pdf")})


def _wait(client, pdf_id, terminal=("done", "failed", "interrupted"), timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/pdf/{pdf_id}").json()
        if body["status"] in terminal:
            return body
        time.sleep(0.05)
    raise AssertionError(f"pdf job did not reach {terminal}: {body['status']}")


def _wait_until(predicate, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


# ---------------------------------------------------------------------------
# AC1: durable per-page checkpoints + restart/interruption recovery
# ---------------------------------------------------------------------------


def test_page_checkpoints_persist_and_survive_restart(tmp_path):
    storage = tmp_path / "store"
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(fail_always={"p002"}),
    ))
    pdf_id = _upload(client, data).json()["pdf_id"]
    body = _wait(client, pdf_id)
    assert body["counts"]["success"] == 1 and body["counts"]["failed"] == 1

    # job.json carries the per-page status + attempt count (durable checkpoint)
    saved = json.loads((storage / "pdfs" / pdf_id / "job.json").read_text())
    pages = {p["page_index"]: p for p in saved["pages"]}
    assert pages[0]["status"] == "success" and pages[0]["attempts"] == 1
    assert pages[1]["status"] == "failed" and pages[1]["attempts"] == 1
    assert saved["max_page_attempts"] >= 1 and saved["page_timeout"] >= 1

    # a brand-new app instance (process restart) still reports the exact state
    client2 = TestClient(_app(store=FileDocumentStore(str(storage))))
    body2 = client2.get(f"/api/pdf/{pdf_id}").json()
    assert [p["page_index"] for p in body2["pages"]] == [0, 1]
    assert body2["status"] == "done"
    assert body2["pages"][1]["status"] == "failed"
    assert body2["pages"][1]["attempts"] == 1
    assert body2["pages"][1]["retryable"] is True


def test_interrupted_processing_job_is_detected_on_restart(tmp_path):
    storage = tmp_path / "store"
    store = FileDocumentStore(str(storage))
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    pdf_id = pdflib.stable_pdf_id(data)

    # craft the on-disk state of a process killed mid-job
    work_dir = pdflib.pdf_dir(store, pdf_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "original.pdf").write_bytes(data)
    job = pdflib.PdfJob(pdf_id=pdf_id, filename="crash.pdf",
                        status="processing", total_pages=2)
    job.work_dir = str(work_dir)
    job.set_page(pdflib.PageStatus(
        page_index=0, status="success", attempts=1,
        document_id=pdflib.page_document_id(pdf_id, 0)))
    job.set_page(pdflib.PageStatus(page_index=1, status="processing", attempts=1))
    pdflib.save_job(job)

    client = TestClient(_app(store=FileDocumentStore(str(storage))))
    body = client.get(f"/api/pdf/{pdf_id}").json()
    assert body["status"] == "interrupted"
    assert body["interrupted"] is True
    assert body["pages"][0]["status"] == "success"
    # the in-flight page becomes retryable, with an explainable reason
    assert body["pages"][1]["status"] == "pending"
    assert body["pages"][1]["error_kind"] == "interrupted"
    assert body["retryable"] is True

    saved = json.loads((work_dir / "job.json").read_text())
    assert saved["status"] == "interrupted"


def test_on_demand_load_from_disk_after_memory_clear(tmp_path):
    storage = tmp_path / "store"
    data = _pdf_bytes([_make_page(1)])
    client = TestClient(_app(store=FileDocumentStore(str(storage))))
    pdf_id = _upload(client, data).json()["pdf_id"]
    _wait(client, pdf_id)

    client.app.state.pdf_jobs.clear()  # simulate a cold in-memory cache
    body = client.get(f"/api/pdf/{pdf_id}").json()
    assert body["pdf_id"] == pdf_id and body["status"] == "done"
    assert body["counts"]["success"] == 1


# ---------------------------------------------------------------------------
# AC2 / AC5: retry only incomplete pages; commit-before-status-persist recovery
# ---------------------------------------------------------------------------


def test_retry_only_reprocesses_failed_pages(tmp_path):
    storage = tmp_path / "store"
    calls: list[str] = []
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(calls=calls, fail_first={"p002"}),
    ))
    pdf_id = _upload(client, data).json()["pdf_id"]
    body = _wait(client, pdf_id)
    assert body["counts"] == {"success": 1, "failed": 1, "blank": 0,
                              "duplicate": 0, "pending": 0}
    ok_doc = body["pages"][0]["document_id"]
    versions_before = len(
        client.get(f"/api/documents/{ok_doc}").json()["versions"])

    r = client.post(f"/api/pdf/{pdf_id}/retry").json()
    assert r["triggered"] is True
    assert r["retryable_pages"] == [1]          # only the failed page

    body2 = _wait(client, pdf_id)
    assert body2["counts"]["success"] == 2 and body2["counts"]["failed"] == 0
    assert body2["pages"][1]["attempts"] == 2   # one failed + one successful try

    # the already-successful page was never re-parsed or re-versioned
    assert calls.count("p001") == 1
    versions_after = client.get(f"/api/documents/{ok_doc}").json()["versions"]
    assert len(versions_after) == versions_before == 1


def test_commit_before_status_persist_recovers_without_reparse(tmp_path):
    storage = tmp_path / "store"
    calls: list[str] = []
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(calls=calls),
    ))
    pdf_id = _upload(client, data).json()["pdf_id"]
    body = _wait(client, pdf_id)
    assert body["counts"]["success"] == 2
    doc1 = body["pages"][1]["document_id"]
    versions_before = len(client.get(f"/api/documents/{doc1}").json()["versions"])
    calls_before = list(calls)

    # simulate a crash after the page document was written but before the job
    # status was persisted: page 1 looks pending again
    job_path = storage / "pdfs" / pdf_id / "job.json"
    saved = json.loads(job_path.read_text())
    saved["status"] = "processing"
    for p in saved["pages"]:
        if p["page_index"] == 1:
            p["status"] = "pending"
            p["document_id"] = None
            p["attempts"] = 1
    job_path.write_text(json.dumps(saved), encoding="utf-8")

    client2 = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(calls=calls),
    ))
    b2 = client2.get(f"/api/pdf/{pdf_id}").json()
    assert b2["status"] == "interrupted"

    r = client2.post(f"/api/pdf/{pdf_id}/retry").json()
    assert r["triggered"] is True
    b3 = _wait(client2, pdf_id)
    assert b3["pages"][1]["status"] == "success"
    # recognised from the library: no new model call, no new version
    assert calls == calls_before
    assert len(client2.get(f"/api/documents/{doc1}").json()["versions"]) == \
        versions_before


# ---------------------------------------------------------------------------
# AC3: idempotency across re-upload and concurrent retry
# ---------------------------------------------------------------------------


def test_reupload_same_pdf_is_idempotent(tmp_path):
    storage = tmp_path / "store"
    calls: list[str] = []
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(calls=calls, fail_first={"p002"}),
    ))
    first = _upload(client, data).json()
    pdf_id = first["pdf_id"]
    body = _wait(client, pdf_id)
    assert body["counts"]["success"] == 1
    ok_doc = body["pages"][0]["document_id"]
    versions_before = len(
        client.get(f"/api/documents/{ok_doc}").json()["versions"])

    # re-upload the exact same bytes -> same stable id, resume only page 2
    second = _upload(client, data).json()
    assert second["pdf_id"] == pdf_id
    body2 = _wait(client, pdf_id)
    assert body2["counts"]["success"] == 2

    docs = client.get("/api/documents").json()
    assert len(docs) == 2                              # one doc per unique page
    assert len({d["document_id"] for d in docs}) == 2  # no duplicate documents
    assert calls.count("p001") == 1                    # success page untouched
    assert len(client.get(f"/api/documents/{ok_doc}").json()["versions"]) == \
        versions_before


def test_concurrent_retry_is_single_flight(tmp_path):
    storage = tmp_path / "store"
    gate = threading.Event()
    data = _pdf_bytes([_make_page(1)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(gate=gate),
    ))
    pdf_id = _upload(client, data).json()["pdf_id"]
    _wait_until(lambda: client.get(f"/api/pdf/{pdf_id}").json()["status"]
                == "processing")

    # a second trigger while the job runs is rejected, not duplicated (AC3)
    r = client.post(f"/api/pdf/{pdf_id}/retry").json()
    assert r["triggered"] is False
    assert "正在处理" in r["message"]

    gate.set()
    body = _wait(client, pdf_id)
    assert body["counts"]["success"] == 1


# ---------------------------------------------------------------------------
# AC4: bounded attempts / timeout / concurrency
# ---------------------------------------------------------------------------


def test_max_attempts_stops_and_reports(tmp_path):
    storage = tmp_path / "store"
    calls: list[str] = []
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(calls=calls, fail_always={"p002"}),
        pdf_max_page_attempts=2,
    ))
    pdf_id = _upload(client, data).json()["pdf_id"]
    body = _wait(client, pdf_id)
    assert body["pages"][1]["attempts"] == 1
    assert body["pages"][1]["retryable"] is True

    assert client.post(f"/api/pdf/{pdf_id}/retry").json()["triggered"] is True
    body2 = _wait(client, pdf_id)
    assert body2["pages"][1]["attempts"] == 2          # cap reached
    assert body2["pages"][1]["retryable"] is False
    assert body2["exhausted"] is True

    # further retries stop and report the limit (no infinite retry)
    r3 = client.post(f"/api/pdf/{pdf_id}/retry").json()
    assert r3["triggered"] is False
    assert r3["exhausted_pages"] == [1]
    assert "上限" in r3["message"]
    assert calls.count("p001") == 1                    # success page untouched


def test_page_timeout_marks_failed_and_job_completes(tmp_path):
    storage = tmp_path / "store"
    data = _pdf_bytes([_make_page(1), _make_page(2)])
    client = TestClient(_app(
        store=FileDocumentStore(str(storage)),
        factory=_router_factory(delay=1.5, delay_pages={"p002"}),
        pdf_page_timeout=1,
        pdf_workers=1,
    ))
    pdf_id = _upload(client, data).json()["pdf_id"]
    body = _wait(client, pdf_id, timeout=20)
    assert body["status"] == "done"
    assert body["pages"][0]["status"] == "success"
    assert body["pages"][1]["status"] == "failed"
    assert body["pages"][1]["error_kind"] == "timeout"
    assert "超时" in body["pages"][1]["error"]
    # the slow page is retryable (under the attempt cap)
    assert body["pages"][1]["retryable"] is True
