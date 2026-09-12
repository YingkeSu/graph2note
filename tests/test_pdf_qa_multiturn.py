"""Offline tests for multi-turn PDF Q&A sessions (P1).

The text model is always a scripted stub injected through ``create_app``, so no
test touches the network; PDFs are built synthetically with PyMuPDF and skip
cleanly without it.  Sessions are persisted under the (temporary) document-store
root, so a second app built over the same store simulates a process restart.
"""

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
from graph2note import pdfqa_sessions  # noqa: E402
from graph2note import pdfsearch  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore, SessionDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = json.loads(
    (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# fixtures / helpers (same shapes as tests/test_pdf_qa.py)
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


class ScriptedAnswerer:
    """Recorded offline text model; one reply per call (last one repeats)."""

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


def _app(store, factory, answerer, **kw):
    return webapp.create_app(
        model="glm-5.3-flash", document_store=store, router_factory=factory,
        max_retries=0, pdf_answerer=answerer, pdf_qa_model="stub-model",
        pdf_qa_provider="stub", **kw)


def _upload_and_wait(client, data, filename="qa.pdf"):
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
    return client.post("/api/pdf/ask",
                       json={"question": question, **extra})


def _three_page_library(store, answerer, **kw):
    """One PDF: page 1 alpha / page 2 beta / page 3 gamma (unique tokens)."""
    client = TestClient(_app(store, _router_factory({
        "p001": "状态空间 alpha 模型",
        "p002": "注意力 beta 机制",
        "p003": "观测器 gamma 设计",
    }), answerer, **kw))
    pdf_id, _ = _upload_and_wait(
        client, _pdf_bytes([_make_page(11), _make_page(12), _make_page(13)]))
    return client, pdf_id


# ---------------------------------------------------------------------------
# AC1: 3-turn follow-up, prompt carries prior turns, retrieval is per-turn
# ---------------------------------------------------------------------------


def test_three_turn_followup_prompt_contains_history(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    stub = ScriptedAnswerer(["答案一 [1]", "答案二 [1]", "答案三 [1]"])
    client, _ = _three_page_library(store, stub)

    sid = "conv-ac1"
    r1 = _ask(client, "alpha 的含义？", session_id=sid).json()
    r2 = _ask(client, "beta 的含义？", session_id=sid).json()
    r3 = _ask(client, "gamma 的含义？", session_id=sid).json()

    assert [r1["turn_index"], r2["turn_index"], r3["turn_index"]] == [1, 2, 3]
    assert {r["session_id"] for r in (r1, r2, r3)} == {sid}
    assert r1["session"]["context_turns"] == 0
    assert r2["session"]["context_turns"] == 1

    # 2nd/3rd prompts replay the previous Q&A as context, before the sources
    assert "第 1 轮 问：alpha 的含义？" in stub.calls[1]
    assert "第 1 轮 答：答案一" in stub.calls[1]
    assert "第 1 轮 问：alpha 的含义？" in stub.calls[2]
    assert "第 2 轮 问：beta 的含义？" in stub.calls[2]
    assert "第 2 轮 答：答案二" in stub.calls[2]
    for prompt in stub.calls[1:]:
        assert prompt.index("对话历史") < prompt.index("资料：")

    # retrieval tokens come only from the current question (no history weighting)
    assert r2["retrieval"]["tokens"] == pdfsearch.tokenize("beta 的含义？")
    assert "alpha" not in r2["retrieval"]["tokens"]
    assert r3["retrieval"]["tokens"] == pdfsearch.tokenize("gamma 的含义？")

    # and each turn's evidence really is the page that matches that question
    assert r1["citations"][0]["page_index"] == 0
    assert r2["citations"][0]["page_index"] == 1
    assert r3["citations"][0]["page_index"] == 2


# ---------------------------------------------------------------------------
# AC2: each turn's citations come from that turn's retrieval set only
# ---------------------------------------------------------------------------


def test_citations_come_from_current_turn_not_history(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    stub = ScriptedAnswerer(["历史答案 [1]", "本轮答案 [1]", "只有旧标签 [2]"])
    client, _ = _three_page_library(store, stub)

    sid = "conv-ac2"
    r1 = _ask(client, "alpha", session_id=sid).json()
    assert r1["citations"][0]["page_index"] == 0          # history hit page A

    r2 = _ask(client, "beta", session_id=sid).json()
    assert r2["citations"][0]["page_index"] == 1          # current hit page B
    # the earlier turn's marker was rewritten to a "前文提到" reference
    assert "历史答案 [1]" not in stub.calls[1]
    assert "（前文提到 第1页）" in stub.calls[1]

    # a marker that was valid last turn but is out of range this turn is refused
    r3 = _ask(client, "beta", session_id=sid).json()
    assert r3["citations"] == []
    assert r3["untrusted_citations"] == ["[2]"]
    assert r3["grounded"] is False


# ---------------------------------------------------------------------------
# AC3: no session_id is the single-turn baseline (backward compatible)
# ---------------------------------------------------------------------------


def test_stateless_call_is_backward_compatible(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    stub = ScriptedAnswerer(["答案 [1]"])
    client, _ = _three_page_library(store, stub)

    r1 = _ask(client, "alpha").json()
    r2 = _ask(client, "alpha").json()

    assert r1["session_id"] is None and r1["turn_index"] is None
    assert r1["session"] is None
    assert r1["status"] == "answered" and r1["grounded"] is True
    assert "对话历史（" not in stub.calls[0]     # no history block
    assert "轮 问：" not in stub.calls[0]
    assert "对话历史（" not in stub.calls[1]     # nothing accumulates
    assert "轮 问：" not in stub.calls[1]
    assert client.app.state.pdf_session_store.count() == 0


def test_stateless_response_keeps_baseline_contract(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client, _ = _three_page_library(store, ScriptedAnswerer(["答案 [1]"]))
    r = _ask(client, "alpha").json()
    # every key the issue-11 single-turn caller relies on is still present
    for key in ("status", "question", "answer", "citations", "sources",
                "untrusted_citations", "warnings", "provider", "model",
                "usage", "retrieved", "grounded", "message", "elapsed", "limits"):
        assert key in r, key


def test_explicit_provider_reaches_live_gateway(monkeypatch, tmp_path):
    """The request provider/model override must reach the gateway seam."""
    store = SessionDocumentStore(str(tmp_path / "store"))
    store.save_document(
        document_id="d1", title="p1", source_job_id="j", model="m",
        markdown="状态空间 alpha 模型", ir_json="{}", original_path="o.png",
        original_ext=".png", preprocessed_path="a.png",
        preprocessed_raw_path="b.png", assets_dir="assets", timing_json={},
        pdf_id="pdf-1", page_index=0, page_number=1)
    recorded = {}

    def fake_gateway(prompt, model, *, provider=None, session=None, timeout=None):
        recorded.update(provider=provider, model=model)
        return {"text": "答案 [1]", "usage": {"total_tokens": 5}}

    monkeypatch.setattr(pdfqa, "_gateway_answer", fake_gateway)
    answer = pdfqa.answer_question(store, "alpha", provider="deepseek",
                                   model="deepseek-flash")
    assert answer.status == "answered"
    assert recorded == {"provider": "deepseek", "model": "deepseek-flash"}


def test_invalid_session_id_is_rejected(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client, _ = _three_page_library(store, ScriptedAnswerer(["答案 [1]"]))
    r = _ask(client, "alpha", session_id="bad/id")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# AC4: >5 turns truncates the oldest from the prompt; disk resume after restart
# ---------------------------------------------------------------------------


def test_context_truncated_after_max_turns(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    stub = ScriptedAnswerer([f"答案{i} [1]" for i in range(1, 8)])
    client, _ = _three_page_library(store, stub)

    sid = "conv-truncate"
    for i in range(1, 8):
        r = _ask(client, f"alpha 第{i}问", session_id=sid).json()
        assert r["status"] == "answered"

    prompt = stub.calls[6]
    assert prompt.count("轮 问：") == pdfqa.MAX_CONTEXT_TURNS
    assert "第 1 轮 问：alpha 第1问" not in prompt
    assert "第 2 轮 问：alpha 第2问" in prompt
    assert "第 6 轮 问：alpha 第6问" in prompt
    assert r["session"]["context_turns"] == pdfqa.MAX_CONTEXT_TURNS
    assert r["session"]["turn_count"] == 7

    # the full exchange history is still retained in the session record
    body = client.get(f"/api/pdf/ask/sessions/{sid}").json()
    assert len(body["turns"]) == 7
    assert body["turns"][0]["question"] == "alpha 第1问"
    assert body["limits"]["max_context_turns"] == pdfqa.MAX_CONTEXT_TURNS


def test_session_resumes_after_restart(tmp_path):
    root = tmp_path / "store"
    store = FileDocumentStore(str(root))
    stub1 = ScriptedAnswerer(["第一答 [1]", "第二答 [1]"])
    client1, _ = _three_page_library(store, stub1)

    sid = "conv-restart"
    _ask(client1, "alpha", session_id=sid)
    _ask(client1, "beta", session_id=sid)

    # "restart": a fresh app + fresh SessionStore over the same store root
    stub2 = ScriptedAnswerer(["第三答 [1]"])
    client2 = TestClient(_app(FileDocumentStore(str(root)),
                              _router_factory({
                                  "p001": "状态空间 alpha 模型",
                                  "p002": "注意力 beta 机制",
                                  "p003": "观测器 gamma 设计",
                              }), stub2))
    r3 = _ask(client2, "gamma", session_id=sid).json()

    assert r3["turn_index"] == 3
    assert r3["session"]["context_turns"] == 2
    assert "第 1 轮 问：alpha" in stub2.calls[0]
    assert "第 1 轮 答：第一答" in stub2.calls[0]
    assert "第 2 轮 问：beta" in stub2.calls[0]


def test_session_turn_retention_is_bounded():
    session = pdfqa_sessions.QaSession(session_id="x")
    total = pdfqa_sessions.MAX_SESSION_TURNS + 5
    for i in range(total):
        session.append(pdfqa_sessions.Turn(index=i + 1, question=f"q{i + 1}"))
    assert len(session.turns) == pdfqa_sessions.MAX_SESSION_TURNS
    assert session.turns[0].index == 6
    assert session.turns[-1].index == total
    assert len(session.context_turns()) == pdfqa.MAX_CONTEXT_TURNS


def test_session_store_capacity_is_bounded(tmp_path):
    root = tmp_path / "sessions"
    store = pdfqa_sessions.SessionStore(root, max_sessions=2)
    for i, sid in enumerate(("s1", "s2", "s3"), start=1):
        session = store.get_or_create(sid, [])
        session.append(pdfqa_sessions.Turn(index=1, question=f"q{i}"))
        session.updated_at = float(i)
        store.save(session)

    assert store.count() == 2
    assert store.get("s1") is None                 # oldest evicted
    assert store.get("s3") is not None
    assert len(list(root.glob("*.json"))) == 2     # eviction reaches disk

    reloaded = pdfqa_sessions.SessionStore(root, max_sessions=2)
    assert reloaded.count() == 2
    assert reloaded.get("s3") is not None


# ---------------------------------------------------------------------------
# AC: scope is bound to the session; switching scope needs a new session
# ---------------------------------------------------------------------------


def test_scope_is_bound_to_session(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client = TestClient(_app(store, _router_factory({"p001": "alpha 主题"}), None))
    pid_a, _ = _upload_and_wait(client, _pdf_bytes([_make_page(21)]), "a.pdf")

    stub = ScriptedAnswerer(["答案 A [1]", "答案 B [1]"])
    client2 = TestClient(_app(store, _router_factory({"p001": "alpha 主题"}), stub))
    pid_b, _ = _upload_and_wait(client2, _pdf_bytes([_make_page(22)]), "b.pdf")

    sid = "conv-scope"
    ok = _ask(client2, "alpha", session_id=sid, pdf_id=pid_a)
    assert ok.status_code == 200
    assert ok.json()["session"]["scope"] == {"kind": "pdf", "pdf_ids": [pid_a]}

    conflict = _ask(client2, "alpha", session_id=sid, pdf_id=pid_b)
    assert conflict.status_code == 409
    assert "新建会话" in conflict.json()["detail"]

    # explicit new session, new scope -> fine, and the old session is untouched
    fresh = _ask(client2, "alpha", session_id="conv-scope-2", pdf_id=pid_b).json()
    assert fresh["session"]["scope"]["pdf_ids"] == [pid_b]
    assert client2.app.state.pdf_session_store.get(sid) is not None


def test_multi_pdf_scope_shape_is_accepted(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client = TestClient(_app(store, _router_factory({"p001": "alpha 主题"}),
                             ScriptedAnswerer(["答案 [1]"])))
    pid_a, _ = _upload_and_wait(client, _pdf_bytes([_make_page(31)]), "a.pdf")
    pid_b, _ = _upload_and_wait(client, _pdf_bytes([_make_page(32)]), "b.pdf")

    sid = "conv-multi"
    r = _ask(client, "alpha", session_id=sid, pdf_ids=[pid_a, pid_b]).json()
    assert r["status"] == "answered"
    assert r["session"]["scope"] == {"kind": "multi", "pdf_ids": [pid_a, pid_b]}
    body = client.get(f"/api/pdf/ask/sessions/{sid}").json()
    assert body["scope"]["kind"] == "multi"


# ---------------------------------------------------------------------------
# AC: session token usage lands in telemetry (existing channel)
# ---------------------------------------------------------------------------


def test_session_token_usage_is_recorded_in_telemetry(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    stub = ScriptedAnswerer(["答一 [1]", "答二 [1]"])
    client, _ = _three_page_library(store, stub)

    sid = "conv-telemetry"
    r1 = _ask(client, "alpha", session_id=sid).json()
    r2 = _ask(client, "beta", session_id=sid).json()

    # per-turn usage is normalised through graph2note.telemetry
    assert r1["telemetry"]["schema_version"] == 1
    assert r1["telemetry"]["total_tokens"] == 18
    assert r1["telemetry"]["model"] == "stub-model"
    assert r1["telemetry"]["provider"] == "stub"
    assert r1["telemetry"]["has_usage"] is True

    # cumulative session telemetry is exposed on the answer and by the API
    assert r1["session"]["telemetry"]["total_tokens"] == 18
    assert r2["session"]["telemetry"]["total_tokens"] == 36
    assert r2["session"]["telemetry"]["model_calls"] == 2

    body = client.get(f"/api/pdf/ask/sessions/{sid}").json()
    assert body["telemetry"]["total_tokens"] == 36
    assert body["telemetry"]["turns"] == 2

    listing = client.get("/api/pdf/ask/sessions").json()
    assert [s["session_id"] for s in listing["sessions"]] == [sid]
    assert listing["sessions"][0]["telemetry"]["total_tokens"] == 36


def test_ask_ui_exposes_multiturn_controls(tmp_path):
    """The QA block keeps its place but gains session/追问 controls (P1, in-place)."""
    store = FileDocumentStore(str(tmp_path / "store"))
    client, _ = _three_page_library(store, ScriptedAnswerer(["答案 [1]"]))
    html = client.get("/").text
    assert 'id="pdf-qa-new"' in html              # explicit new-session button
    assert 'id="pdf-qa-history"' in html          # prior-turn history area
    assert "单轮问答" not in html
    js = client.get("/static/app.js").text
    assert "pdfQaSessionId" in js and "session_id: state.pdfQaSessionId" in js
    assert "前文提到" in js                       # historical citations are labelled


def test_unknown_session_is_404(tmp_path):
    store = FileDocumentStore(str(tmp_path / "store"))
    client, _ = _three_page_library(store, ScriptedAnswerer(["答案 [1]"]))
    assert client.get("/api/pdf/ask/sessions/nope").status_code == 404
