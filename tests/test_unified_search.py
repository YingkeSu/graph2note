"""Offline tests for the P3 unified document + PDF search index.

The unified index (``graph2note.unifiedsearch``) covers two sources with one
engine: document Markdown (block level) and parsed PDF pages.  Every test is
offline — PDFs are synthetic, the parse router and the repair model are
scripted stubs — and no test touches the network or a real LLM.
"""

from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pymupdf = pytest.importorskip("pymupdf")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import unifiedsearch  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore, SessionDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = json.loads(
    (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# helpers: synthetic PDFs + stubbed parse router
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
    def caller(image_path, model, recover=False):
        return _ir_with_text(text_by_page.get(_page_key(image_path), "默认")), {}

    def factory(image_path, model):
        return RouteARouter(model, caller=caller, max_retries=0)

    return factory


def _app(store=None, storage_dir=None, factory=None, **kw):
    import tempfile

    if store is None:
        storage_dir = storage_dir or tempfile.mkdtemp(prefix="g2n-unified-")
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
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/pdf/{pdf_id}").json()
        if body["status"] in ("done", "failed", "interrupted"):
            return body
        time.sleep(0.05)
    raise AssertionError("pdf job did not finish")


def _save_doc(store, doc_id, title, markdown, **extra):
    kwargs = dict(
        document_id=doc_id, title=title, source_job_id="job", model="m",
        markdown=markdown, ir_json="{}", original_path=None,
        original_ext=".jpg", preprocessed_path=None,
        preprocessed_raw_path=None, assets_dir=None, timing_json={})
    kwargs.update(extra)
    return store.save_document(**kwargs)


def _mkstore(tmp_path):
    return SessionDocumentStore(str(tmp_path / "store"))


# ---------------------------------------------------------------------------
# AC2: document Markdown enters the index (block level, aggregated per doc)
# ---------------------------------------------------------------------------


def test_document_markdown_enters_unified_index(tmp_path):
    store = _mkstore(tmp_path)
    _save_doc(store, "d1", "手稿A",
              "# 状态空间\n卡尔曼滤波 Kalman filter 介绍。\n\n"
              "注意力 attention 机制另起一段。")

    r = unifiedsearch.search(store, "卡尔曼")
    assert r["total"] == 1
    hit = r["documents"][0]
    assert hit["kind"] == "document"
    assert hit["document_id"] == "d1"
    assert "卡尔曼" in hit["snippet"]
    assert hit["review_url"] == "/api/documents/d1"
    assert r["indexed_documents"] == 1
    assert r["indexed_pdf_pages"] == 0

    # title is searchable too ("标题 + 文档内容")
    assert unifiedsearch.search(store, "手稿A")["documents"][0]["document_id"] == "d1"

    # multiple matching blocks aggregate to a single document result
    r2 = unifiedsearch.search(store, "状态空间")
    assert len(r2["documents"]) == 1
    assert r2["documents"][0]["matched_blocks"] >= 1

    # no match is an explicit empty result, never a stale hit
    miss = unifiedsearch.search(store, "不存在的词xyz")
    assert miss["total"] == 0 and "没有匹配" in miss["message"]

    # empty query is explicit
    empty = unifiedsearch.search(store, "   ")
    assert empty["total"] == 0 and "请输入关键词" in empty["message"]


def test_pdf_pages_and_documents_share_one_search(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    _save_doc(store, "plain", "手稿A", "状态空间 与观测器 observer 设计")
    _save_doc(store, "p1", "scan · 第1页", "状态空间 Kalman 滤波页",
              pdf_id="pdf-1", page_index=0, page_number=1)
    _save_doc(store, "p2", "scan · 第2页", "注意力 attention 机制页",
              pdf_id="pdf-2", page_index=0, page_number=3)

    r = unifiedsearch.search(store, "状态空间")
    assert {h["document_id"] for h in r["documents"]} == {"plain"}
    assert {h["document_id"] for h in r["pdf_pages"]} == {"p1"}
    assert r["indexed_documents"] == 1 and r["indexed_pdf_pages"] == 2

    page = r["pdf_pages"][0]
    assert page["pdf_id"] == "pdf-1"
    assert page["pdf_name"] == "scan"
    assert page["page_number"] == 1
    assert page["pdf_page_url"] == "/api/pdf/pdf-1/page/0"
    assert page["source_page_url"] == "/api/documents/p1/source-page"

    # group filter
    only_docs = unifiedsearch.search(store, "状态空间", kind="document")
    assert only_docs["pdf_pages"] == []
    only_pages = unifiedsearch.search(store, "状态空间", kind="pdf_page")
    assert only_pages["documents"] == []

    # pdf scope restricts the page group only
    scoped = unifiedsearch.search(store, "状态空间", pdf_ids=["pdf-2"])
    assert scoped["pdf_pages"] == []


# ---------------------------------------------------------------------------
# AC2: index consistency across create / edit / delete (+ R1 repair version)
# ---------------------------------------------------------------------------


def test_index_tracks_document_add_edit_delete(tmp_path):
    store = _mkstore(tmp_path)
    _save_doc(store, "d1", "T1", "alpha uniquetoken100")
    assert unifiedsearch.search(store, "uniquetoken100")["total"] == 1

    # edit replaces content -> no stale hit
    store.save_edits("d1", "beta replacementonly")
    assert unifiedsearch.search(store, "uniquetoken100")["total"] == 0
    assert unifiedsearch.search(store, "replacementonly")["total"] == 1

    # a brand-new document is indexed
    _save_doc(store, "d2", "T2", "gamma anothertoken")
    assert unifiedsearch.search(store, "anothertoken")["documents"][0]["document_id"] == "d2"

    # delete -> the deleted document can never be hit
    assert store.delete_document("d1") is True
    assert unifiedsearch.search(store, "replacementonly")["total"] == 0
    assert unifiedsearch.search(store, "anothertoken")["total"] == 1


def test_index_follows_repair_version(tmp_path):
    """R1 adds a repaired version; the unified index must serve the new text."""
    store = _mkstore(tmp_path)
    _save_doc(store, "d1", "black-scan", "图片为纯黑，无可识别的文字内容 blackonly")
    assert unifiedsearch.search(store, "blackonly")["total"] == 1
    before = store.get_document("d1")

    # R1 re-run stamps a new version with the repair provenance contract
    _save_doc(
        store, "d1", "black-scan",
        "# 修复后\n\n这一页记录了状态空间模型的核心方程 repairedonly",
        provenance="repair",
        provenance_detail={"source": "black-image-repair", "repair_id": "r1",
                           "old_version_id": before["latest_version"],
                           "repaired_at": "2026-09-12T00:00:00", "model": "m"},
    )
    rec = store.get_document("d1")
    assert len(rec["versions"]) == 2
    assert rec["versions"][-1]["provenance"] == "repair"

    # the old placeholder text is gone, the repaired content is searchable
    assert unifiedsearch.search(store, "blackonly")["total"] == 0
    hit = unifiedsearch.search(store, "repairedonly")["documents"][0]
    assert hit["document_id"] == "d1"
    assert hit["version_id"] == rec["latest_version"]


def _healthy_image(seed: int = 1, w: int = 600, h: int = 800):
    arr = np.full((h, w, 3), 250, np.uint8)
    rng = np.random.default_rng(seed)
    for i in range(9):
        y = 70 + i * 80
        arr[y:y + 6, 40:40 + int(rng.integers(300, 480))] = 10
    return Image.fromarray(arr)


def _black_image(w: int = 600, h: int = 800):
    return Image.fromarray(np.zeros((h, w, 3), np.uint8))


def _wait_repair(client, repair_id, timeout=30):
    for _ in range(int(timeout / 0.1)):
        body = client.get(f"/api/repair/{repair_id}").json()
        if body["status"] not in ("queued", "processing"):
            return body
        time.sleep(0.1)
    raise AssertionError("repair job did not finish in time")


def test_repair_run_updates_unified_index(tmp_path):
    """The real R1 repair loop adds a new version; unified search must follow."""
    root = tmp_path / "storage"
    store = FileDocumentStore(str(root))
    pp = root / "d-pp.png"
    _black_image().save(pp, "PNG")
    raw = root / "d-raw.png"
    _healthy_image(2).save(raw, "PNG")
    _save_doc(store, "d", "d", "图片为纯黑，无可识别的文字内容 blackonly",
              original_path=str(raw), preprocessed_path=str(pp),
              preprocessed_raw_path=str(raw))

    client = TestClient(_app(store=store, storage_dir=None,
                             factory=_router_factory({})))
    assert client.get("/api/search", params={"q": "blackonly"}).json()["total"] == 1

    r = client.post("/api/repair/run",
                    json={"document_ids": ["d"], "confirm": True})
    assert r.status_code == 200, r.text
    done = _wait_repair(client, r.json()["repair_id"])
    assert done["counts"]["success"] == 1

    after = store.get_document("d")
    assert len(after["versions"]) == 2
    assert after["versions"][-1]["provenance"] == "repair"
    # the stale black-placeholder text is gone from the unified index
    assert client.get("/api/search", params={"q": "blackonly"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "默认"}).json()["total"] == 1


def test_reindex_builds_and_persists_for_both_sources(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    _save_doc(store, "plain", "手稿A", "文档内容 docterm")
    _save_doc(store, "p1", "scan · 第1页", "PDF 内容 pageterm",
              pdf_id="pdf-1", page_index=0, page_number=1)

    index = unifiedsearch.build_index(store, persist=True)
    assert index["indexed_documents"] == 1
    assert index["indexed_pdf_pages"] == 1
    index_file = store.root / "search" / "unified-index.json"
    assert index_file.is_file()
    saved = json.loads(index_file.read_text(encoding="utf-8"))
    assert saved["version"] == unifiedsearch.INDEX_VERSION
    assert saved["fingerprint"]

    # a removed cache is transparently rebuilt from the library
    index_file.unlink()
    unifiedsearch._mem_cache.clear()
    assert unifiedsearch.search(store, "docterm")["total"] == 1
    assert index_file.is_file()


# ---------------------------------------------------------------------------
# API: grouped results over one HTTP surface
# ---------------------------------------------------------------------------


def test_api_search_returns_grouped_results(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client = TestClient(_app(store=store, factory=_router_factory({
        "p001": "状态空间 alpha 模型",
    })))
    _save_doc(store, "plain", "手稿A", "状态空间 手写笔记 handwritten")
    pid = _upload(client, _pdf_bytes([_make_page(11)]), "scan.pdf").json()["pdf_id"]
    _wait(client, pid)

    r = client.get("/api/search", params={"q": "状态空间"}).json()
    assert r["total"] == 2
    assert [h["kind"] for h in r["groups"]["documents"]] == ["document"]
    assert r["groups"]["documents"][0]["document_id"] == "plain"
    assert r["groups"]["pdf_pages"][0]["pdf_id"] == pid
    # uploaded PDF name reaches the API-level hit (from the job)
    assert r["groups"]["pdf_pages"][0]["pdf_name"] == "scan.pdf"
    assert r["indexed_documents"] == 1 and r["indexed_pdf_pages"] == 1

    # kind filter through the API
    docs_only = client.get("/api/search",
                           params={"q": "状态空间", "kind": "document"}).json()
    assert docs_only["pdf_pages"] == [] and docs_only["documents"]

    # reindex endpoint rebuilds both sources
    ri = client.post("/api/search/reindex").json()
    assert ri["indexed_documents"] == 1 and ri["indexed_pdf_pages"] == 1


def test_api_search_reflects_document_edit(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client = TestClient(_app(store=store))
    _save_doc(store, "plain", "手稿A", "初次内容 firstonly")

    assert client.get("/api/search", params={"q": "firstonly"}).json()["total"] == 1
    r = client.post("/api/documents/plain/markdown",
                    json={"markdown": "改后内容 secondonly"})
    assert r.status_code == 200
    assert client.get("/api/search", params={"q": "firstonly"}).json()["total"] == 0
    assert client.get("/api/search", params={"q": "secondonly"}).json()["total"] == 1
