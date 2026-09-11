"""Offline Web/API tests for PDF content search + original-page jump (issue 10).

Every parse path injects a router returning recorded golden IR (per page), so
the suite is deterministic and never touches the network or an LLM.  PDFs are
built synthetically with PyMuPDF; tests SKIP cleanly without it.
"""

import io
import json
import re
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import pdfsearch  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore, SessionDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = json.loads(
    (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# synthetic PDFs + per-page offline router
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


def _page_key(image_path) -> str:
    m = re.search(r"p(\d{3})", str(image_path))
    return f"p{m.group(1)}" if m else "p001"


def _ir_with_text(text: str) -> str:
    base = json.loads(json.dumps(GOLDEN))
    base["blocks"][0]["text"] = text
    base["blocks"][1]["text"] = f"{text} —— 正文内容"
    return json.dumps(base, ensure_ascii=False)


def _router_factory(text_by_page):
    """Page-keyed golden content (e.g. {'p001': '状态空间模型'})."""

    def caller(image_path, model, recover=False):
        key = _page_key(image_path)
        return _ir_with_text(text_by_page.get(key, key)), {}

    def factory(image_path, model):
        return RouteARouter(model, caller=caller, max_retries=0)

    return factory


def _app(store=None, storage_dir=None, factory=None, **kw):
    import tempfile

    if store is None:
        storage_dir = storage_dir or tempfile.mkdtemp(prefix="g2n-search-")
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=storage_dir,
        document_store=store,
        router_factory=factory or _router_factory({}),
        max_retries=0,
        **kw,
    )


def _upload(client, data, filename="scan.pdf"):
    return client.post("/api/pdf",
                       files={"file": (filename, data, "application/pdf")})


def _wait(client, pdf_id, timeout=30):
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/pdf/{pdf_id}").json()
        if body["status"] in ("done", "failed", "interrupted"):
            return body
        time.sleep(0.05)
    raise AssertionError("pdf job did not finish")


def _search(client, q, **params):
    return client.get("/api/search/pdf", params={"q": q, **params}).json()


# ---------------------------------------------------------------------------
# AC1 / AC2 / AC3: query -> snippet -> review doc + original page, scopes
# ---------------------------------------------------------------------------


def test_search_chinese_english_mixed_with_complete_links(tmp_path):
    storage = tmp_path / "store"
    factory = _router_factory({
        "p001": "状态空间模型与 Kalman filter",
        "p002": "Transformer attention 机制",
        "p003": "状态空间 观测器 observer",
    })
    client = TestClient(_app(store=FileDocumentStore(str(storage)), factory=factory))
    data = _pdf_bytes([_make_page(1), _make_page(2), _make_page(3)])
    pdf_id = _upload(client, data, "mixed.pdf").json()["pdf_id"]
    assert _wait(client, pdf_id)["counts"]["success"] == 3

    # Chinese query hits both pages that contain it
    r = _search(client, "状态空间")
    assert r["total"] == 2
    assert {h["page_index"] for h in r["hits"]} == {0, 2}
    for h in r["hits"]:
        assert h["pdf_id"] == pdf_id
        assert h["version_id"]                       # content version (AC3)
        assert "状态空间" in h["snippet"]
        assert h["source_page_url"] == f"/api/documents/{h['document_id']}/source-page"
        assert h["pdf_page_url"] == f"/api/pdf/{pdf_id}/page/{h['page_index']}"
        # complete paths: review document + original PDF page (AC1)
        doc = client.get(h["review_url"])
        assert doc.status_code == 200 and "状态空间" in doc.json()["current_markdown"]
        src = client.get(h["source_page_url"])
        assert src.status_code == 200 and src.content[:4] == b"\x89PNG"
        assert client.get(h["pdf_page_url"]).status_code == 200

    # English query
    r_en = _search(client, "Transformer attention")
    assert r_en["total"] == 1 and r_en["hits"][0]["page_index"] == 1

    # mixed Chinese + English (AND semantics)
    r_mix = _search(client, "状态空间 filter")
    assert r_mix["total"] == 1 and r_mix["hits"][0]["page_index"] == 0

    # page index comes from PDF provenance, never a date / logical number (AC3)
    for h in r["hits"]:
        rec = client.get(f"/api/documents/{h['document_id']}").json()
        assert rec["pdf_id"] == pdf_id
        assert rec["page_index"] == h["page_index"]


def test_search_scope_single_pdf_vs_all(tmp_path):
    storage = tmp_path / "store"
    # two different PDFs, distinct content per page
    f1 = _router_factory({"p001": "alpha shared 关键词"})
    app1 = _app(store=FileDocumentStore(str(storage)), factory=f1)
    c1 = TestClient(app1)
    data1 = _pdf_bytes([_make_page(11)])
    pdf1 = _upload(c1, data1, "one.pdf").json()["pdf_id"]
    _wait(c1, pdf1)

    f2 = _router_factory({"p001": "beta shared 关键词"})
    app2 = _app(store=FileDocumentStore(str(storage)), factory=f2)
    c2 = TestClient(app2)
    data2 = _pdf_bytes([_make_page(22)])
    pdf2 = _upload(c2, data2, "two.pdf").json()["pdf_id"]
    _wait(c2, pdf2)

    # all imported PDFs
    all_hits = _search(c1, "shared")
    assert all_hits["total"] == 2
    assert {h["pdf_id"] for h in all_hits["hits"]} == {pdf1, pdf2}

    # scoped to one PDF
    scoped = _search(c1, "shared", pdf_id=pdf2)
    assert scoped["total"] == 1
    assert scoped["hits"][0]["pdf_id"] == pdf2
    assert "beta" in scoped["hits"][0]["snippet"]


def test_search_states_no_hit_no_parsed_and_importing(tmp_path):
    storage = tmp_path / "store"
    client = TestClient(_app(store=FileDocumentStore(str(storage))))

    # nothing parsed yet
    r = _search(client, "任何词")
    assert r["total"] == 0 and r["indexed_documents"] == 0
    assert "尚无已解析" in r["message"]

    # a PDF whose only page is blank -> no searchable document
    blank_data = _pdf_bytes([_make_page(99, empty=True)])
    pdf_id = _upload(client, blank_data, "blank.pdf").json()["pdf_id"]
    body = _wait(client, pdf_id)
    assert body["counts"]["success"] == 0 and body["counts"]["blank"] == 1

    scoped = _search(client, "x", pdf_id=pdf_id)
    assert scoped["total"] == 0 and scoped["indexed_documents"] == 0
    assert "尚无已解析页" in scoped["message"]

    # a PDF with content but an unknown term -> clear "no match"
    f = _router_factory({"p001": "已知内容 known"})
    c2 = TestClient(_app(store=FileDocumentStore(str(storage)), factory=f))
    data = _pdf_bytes([_make_page(31)])
    pid2 = _upload(c2, data, "known.pdf").json()["pdf_id"]
    _wait(c2, pid2)
    miss = _search(c2, "不存在的词")
    assert miss["total"] == 0 and miss["indexed_documents"] == 1
    assert "没有匹配" in miss["message"]

    # empty query is explicit
    empty = _search(c2, "   ")
    assert empty["total"] == 0 and "请输入关键词" in empty["message"]


# ---------------------------------------------------------------------------
# AC4: index tracks add / edit / reparse / delete; rebuildable
# ---------------------------------------------------------------------------


def test_index_updates_on_edit_reparse_delete(tmp_path):
    storage = tmp_path / "store"
    factory = _router_factory({"p001": "alpha uniquetoken100"})
    client = TestClient(_app(store=FileDocumentStore(str(storage)), factory=factory))
    data = _pdf_bytes([_make_page(41)])
    pdf_id = _upload(client, data, "edit.pdf").json()["pdf_id"]
    body = _wait(client, pdf_id)
    doc_id = body["pages"][0]["document_id"]
    assert _search(client, "uniquetoken100")["total"] == 1

    # edit removes the token -> index follows (no stale hit)
    r = client.post(f"/api/documents/{doc_id}/markdown",
                    json={"markdown": "beta replacementonly"})
    assert r.status_code == 200
    assert _search(client, "uniquetoken100")["total"] == 0
    assert _search(client, "replacementonly")["total"] == 1

    # re-parse = a new version with different content -> index follows
    store = client.app.state.store
    rec = store.get_document(doc_id)
    store.save_document(
        document_id=doc_id, title=rec["title"], source_job_id="reparse",
        model="glm-5.3-flash", markdown="gamma reparsedcontent",
        ir_json="{}", original_path=None, original_ext=".jpg",
        preprocessed_path=None, preprocessed_raw_path=None, assets_dir=None,
        timing_json={}, pdf_id=pdf_id, page_index=0, page_number=None,
    )
    assert _search(client, "replacementonly")["total"] == 0
    assert _search(client, "reparsedcontent")["total"] == 1

    # delete -> deleted content can never be hit
    assert client.delete(f"/api/documents/{doc_id}").status_code in (200, 204)
    r_del = _search(client, "reparsedcontent")
    assert r_del["total"] == 0
    assert r_del["indexed_documents"] == 0


def test_reindex_rebuilds_and_persists(tmp_path):
    storage = tmp_path / "store"
    factory = _router_factory({"p001": "rebuildable content"})
    client = TestClient(_app(store=FileDocumentStore(str(storage)), factory=factory))
    data = _pdf_bytes([_make_page(51)])
    pdf_id = _upload(client, data, "reindex.pdf").json()["pdf_id"]
    _wait(client, pdf_id)

    r = client.post("/api/search/pdf/reindex")
    assert r.status_code == 200
    assert r.json()["indexed_documents"] == 1
    index_file = storage / "search" / "pdf-index.json"
    assert index_file.is_file()
    saved = json.loads(index_file.read_text(encoding="utf-8"))
    assert saved["version"] == pdfsearch.INDEX_VERSION
    assert saved["fingerprint"]

    # a corrupted/removed cache is transparently rebuilt from the library
    index_file.unlink()
    pdfsearch._mem_cache.clear()
    assert _search(client, "rebuildable")["total"] == 1
    assert index_file.is_file()


def test_search_ignores_documents_without_pdf_provenance(tmp_path):
    # a plain (non-PDF) library document must never appear in PDF search
    store = SessionDocumentStore(str(tmp_path / "session"))
    store.save_document(
        document_id="plain-doc-1", title="plain", source_job_id="job",
        model="m", markdown="orphan uniqueterm9", ir_json="{}",
        original_path=None, original_ext=".jpg", preprocessed_path=None,
        preprocessed_raw_path=None, assets_dir=None, timing_json={},
    )
    index = pdfsearch.build_index(store, persist=False)
    assert index["documents"] == {}
    r = pdfsearch.search(store, "uniqueterm9")
    assert r["total"] == 0
