"""Offline tests for P3 cross-document PDF Q&A (scope = many PDFs / all).

The retrieval index is the existing keyword index; the text model is always a
scripted stub injected through ``create_app``, so no test touches the network.
PDFs are synthetic (PyMuPDF) and skip cleanly without it.
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

from graph2note import pdfqa  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = json.loads(
    (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8"))


def _make_page(seed=1, w=300, h=420):
    rng = np.random.default_rng(seed)
    arr = np.full((h, w, 3), 250, np.uint8)
    for i in range(4):
        y = 60 + i * 90
        x = int(rng.integers(30, 120))
        arr[y:y + 4, x:x + int(rng.integers(50, 200)), :] = 30
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


class ScriptedAnswerer:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[str] = []

    def __call__(self, prompt, model):
        self.calls.append(prompt)
        index = len(self.calls) - 1
        reply = self.replies[index] if index < len(self.replies) else self.replies[-1]
        if isinstance(reply, Exception):
            raise reply
        return {"text": reply,
                "usage": {"prompt_tokens": 11, "completion_tokens": 7,
                          "total_tokens": 18}}


def _app(store, factory, answerer=None, **kw):
    return webapp.create_app(
        model="glm-5.3-flash", document_store=store, router_factory=factory,
        max_retries=0, pdf_answerer=answerer, pdf_qa_model="stub-model",
        pdf_qa_provider="stub", **kw)


def _upload_and_wait(client, data, filename):
    pid = client.post("/api/pdf",
                      files={"file": (filename, data, "application/pdf")}
                      ).json()["pdf_id"]
    for _ in range(600):
        body = client.get(f"/api/pdf/{pid}").json()
        if body["status"] in ("done", "failed", "interrupted"):
            return pid, body
        time.sleep(0.05)
    raise AssertionError("pdf job did not finish")


def _ask(client, question, **extra):
    return client.post("/api/pdf/ask", json={"question": question, **extra})


A_CONTENT = {"p001": "alpha 独有词 alphaonly", "p002": "beta 共享词 betashared"}
B_CONTENT = {"p001": "beta 共享词 betashared", "p002": "gamma 独有词 gammaonly"}


def _two_pdf_library(store):
    """PDF A (alpha/beta) + PDF B (beta/gamma), both offline."""
    c1 = TestClient(_app(store, _router_factory(A_CONTENT)))
    pid_a, _ = _upload_and_wait(
        c1, _pdf_bytes([_make_page(11), _make_page(12)]), "a.pdf")
    c2 = TestClient(_app(store, _router_factory(B_CONTENT)))
    pid_b, _ = _upload_and_wait(
        c2, _pdf_bytes([_make_page(21), _make_page(22)]), "b.pdf")
    return pid_a, pid_b


# ---------------------------------------------------------------------------
# AC1: multi-PDF scope merges ranked hits; citations carry PDF name + page
# ---------------------------------------------------------------------------


def test_multi_pdf_scope_merges_and_cites_name_and_page(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    pid_a, pid_b = _two_pdf_library(store)
    stub = ScriptedAnswerer(["beta 出现在两份 PDF 中 [1][2]"])
    client = TestClient(_app(store, _router_factory(A_CONTENT), stub))

    r = _ask(client, "betashared", pdf_ids=[pid_a, pid_b]).json()
    assert r["status"] == "answered"
    assert r["retrieved"] == 2

    # retrieval is one merged ranking across the selected PDFs (dedup by page)
    assert r["retrieval"]["scope"] == [pid_a, pid_b]
    assert set(r["retrieval"]["matched_pdfs"]) == {pid_a, pid_b}
    by_pdf = r["retrieval"]["by_pdf"]
    assert by_pdf[pid_a]["hits"] == 1 and by_pdf[pid_a]["pages"] == [2]
    assert by_pdf[pid_b]["hits"] == 1 and by_pdf[pid_b]["pages"] == [1]

    # citations carry the human PDF name + page (page_number provenance when
    # present, otherwise the 1-based original page order)
    assert [c["pdf_name"] for c in r["citations"]] == ["a.pdf", "b.pdf"]
    pages = [c["page_number"] if c["page_number"] is not None
             else c["page_index"] + 1 for c in r["citations"]]
    assert pages == [2, 1]
    assert [c["page_index"] for c in r["citations"]] == [1, 0]
    assert [c["pdf_page_url"] for c in r["citations"]] == [
        f"/api/pdf/{pid_a}/page/1", f"/api/pdf/{pid_b}/page/0"]

    # the prompt labels each source with its PDF name and page
    prompt = stub.calls[0]
    assert '<source id="1" pdf="a.pdf" page="2">' in prompt
    assert '<source id="2" pdf="b.pdf" page="1">' in prompt


def test_scoped_pdf_without_hits_stays_out_of_context(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    pid_a, pid_b = _two_pdf_library(store)
    stub = ScriptedAnswerer(["只有 A 命中 [1]"])
    client = TestClient(_app(store, _router_factory(A_CONTENT), stub))

    r = _ask(client, "alphaonly", pdf_ids=[pid_a, pid_b]).json()
    assert r["status"] == "answered"
    assert r["retrieved"] == 1
    assert r["retrieval"]["matched_pdfs"] == [pid_a]
    assert r["retrieval"]["by_pdf"][pid_b]["hits"] == 0
    assert [c["pdf_name"] for c in r["citations"]] == ["a.pdf"]

    # the no-hit PDF never enters the prompt (only one numbered source)
    prompt = stub.calls[0]
    assert prompt.count("<source id=") == 1
    assert "b.pdf" not in prompt


def test_scope_all_covers_every_pdf(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    pid_a, pid_b = _two_pdf_library(store)
    stub = ScriptedAnswerer(["全部范围 [1][2]"])
    client = TestClient(_app(store, _router_factory(A_CONTENT), stub))

    r = _ask(client, "betashared", pdf_ids=[]).json()      # [] == all PDFs
    assert r["status"] == "answered"
    assert r["retrieval"]["scope"] == []
    assert set(r["retrieval"]["matched_pdfs"]) == {pid_a, pid_b}
    assert {c["pdf_name"] for c in r["citations"]} == {"a.pdf", "b.pdf"}


def test_scope_with_no_hits_is_insufficient_evidence(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    pid_a, pid_b = _two_pdf_library(store)
    stub = ScriptedAnswerer(["不应被调用"])
    client = TestClient(_app(store, _router_factory(A_CONTENT), stub))

    # gamma lives only in PDF B, so scoping to A yields no evidence
    r = _ask(client, "gammaonly", pdf_ids=[pid_a]).json()
    assert r["status"] == "insufficient_evidence"
    assert r["retrieved"] == 0 and r["citations"] == []
    assert r["retrieval"]["matched_pdfs"] == []
    assert stub.calls == []            # no model call without evidence

    # unknown term across all PDFs is the same explicit failure state
    r2 = _ask(client, "nonexistentterm", pdf_ids=[]).json()
    assert r2["status"] == "insufficient_evidence"
    assert r2["retrieved"] == 0


# ---------------------------------------------------------------------------
# AC1: citation discipline (P1 rules) still holds for cross-document scope
# ---------------------------------------------------------------------------


def test_citation_discipline_is_unchanged_for_multi_pdf(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    pid_a, pid_b = _two_pdf_library(store)
    stub = ScriptedAnswerer(["越界引用 [9] 和 [1]"])
    client = TestClient(_app(store, _router_factory(A_CONTENT), stub))

    r = _ask(client, "betashared", pdf_ids=[pid_a, pid_b]).json()
    assert r["status"] == "answered"
    assert r["untrusted_citations"] == ["[9]"]
    assert [c["label"] for c in r["citations"]] == ["[1]"]
    assert r["grounded"] is True
    assert any("无效引用" in w for w in r["warnings"])


def test_multi_pdf_scope_binds_to_session(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    pid_a, pid_b = _two_pdf_library(store)
    stub = ScriptedAnswerer(["答一 [1]", "答二 [1]"])
    client = TestClient(_app(store, _router_factory(A_CONTENT), stub))

    sid = "p3-multi"
    r1 = _ask(client, "betashared", session_id=sid, pdf_ids=[pid_a, pid_b]).json()
    assert r1["session"]["scope"] == {"kind": "multi", "pdf_ids": [pid_a, pid_b]}
    r2 = _ask(client, "alphaonly", session_id=sid, pdf_ids=[pid_a, pid_b]).json()
    assert r2["turn_index"] == 2
    assert r2["retrieval"]["scope"] == [pid_a, pid_b]
