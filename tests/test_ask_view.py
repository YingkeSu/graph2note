"""P2 first-class Q&A conversation view — offline contract tests.

Three complementary checks (no network, no real LLM):

1. DOM assertions over ``index.html``: the sidebar gains a first-class ``问答``
   entry, the ``#ask`` view owns scope + conversation + new-session controls, the
   Library no longer hosts the Q&A form, and the keyword-search toolbar is kept
   as an auxiliary tool inside the ask view.
2. Frontend source assertions plus ``node tests/ask_view.mjs``: request assembly
   carries ``session_id`` across turns, citation chips target the source page,
   waiting/error/retry states are rendered, and ``prefillAsk`` is exported for
   P3's unified search hand-off.
3. A stubbed-answerer API mock drives three turns and asserts the P1 session /
   per-turn citation contract the UI renders.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.static_assets import WEBSTATIC, static_js  # noqa: F401
from tests.test_webapp_layout import _DomParser

TESTS_DIR = Path(__file__).parent


@pytest.fixture(scope="module")
def dom():
    parser = _DomParser()
    parser.feed((WEBSTATIC / "index.html").read_text(encoding="utf-8"))
    return parser.root


# ---------------------------------------------------------------------------
# 1) DOM: one-level view + scope + conversation + new session
# ---------------------------------------------------------------------------


def test_ask_is_first_class_sidebar_view(dom):
    sidebar = dom.find(id="app-sidebar")
    ask_nav = sidebar.find(id="nav-ask")
    assert ask_nav is not None, "问答 must be a sidebar first-class entry"
    assert ask_nav.attrs.get("data-route") == "#ask"
    assert ask_nav.attrs.get("data-view") == "ask"
    assert sidebar.find(id="nav-pdf-search") is None, "old temporary entry is gone"
    # the Q&A nav is view navigation, not a secondary entry
    nav = sidebar.find(id="sidebar-nav")
    assert nav.find(id="nav-ask") is not None


def test_ask_zone_owns_scope_conversation_and_new_session(dom):
    content = dom.find(id="content")
    ask = content.find(id="ask-zone")
    assert ask is not None, "ask view lives in the content area"

    scope = ask.find(id="pdf-qa-scope")
    assert scope is not None and scope.tag == "select"
    options = [n for n in scope.iter_elements() if n.tag == "option"]
    assert options and options[0].attrs.get("value") == "", "default scope = all PDFs"

    assert ask.find(id="pdf-qa-new") is not None, "explicit new-session button"
    assert ask.find(id="pdf-qa-form") is not None
    assert ask.find(id="pdf-qa-input") is not None
    assert ask.find(id="pdf-qa-history") is not None, "conversation area"
    assert ask.find(id="ask-empty") is not None, "empty state"
    assert ask.find(id="pdf-qa-status") is not None, "per-turn status line"
    assert ask.find(id="ask-sessions") is not None, "history session list"


def test_keyword_search_toolbar_is_kept_in_ask_view(dom):
    ask = dom.find(id="ask-zone")
    toolbar = ask.find(id="ask-search-toolbar")
    assert toolbar is not None
    assert toolbar.find(id="pdf-search") is not None
    assert toolbar.find(id="pdf-search-form") is not None
    assert toolbar.find(id="pdf-search-results") is not None


def test_library_and_old_zone_do_not_host_qa(dom):
    library = dom.find(id="library-zone")
    assert library is not None
    assert not library.contains_id("pdf-qa-form"), "Library must not host the QA form"
    assert not library.contains_id("ask-zone")
    assert dom.find(id="pdf-search-zone") is None, "temporary U1 zone is replaced"


# ---------------------------------------------------------------------------
# 2) frontend source contract + Node pure-function test
# ---------------------------------------------------------------------------


def test_ask_frontend_wires_session_persistence_and_citations():
    js = static_js()
    # routed view + legacy alias for P3 / bookmarks
    assert 'registerView("ask"' in js
    assert 'registerView("pdf-search"' in js
    # session id is threaded on every request and persisted for reload
    assert "state.pdfQaSessionId" in js
    assert "buildAskPayload" in js
    assert "graph2note.askSessionId" in js
    assert "sessionToTurns" in js
    # citation chips jump to the source page; retry targets one turn only
    assert "ask-citation" in js
    assert "source_page_url" in js
    assert "data-ask-retry" in js
    # waiting / error / empty states
    assert "正在检索并生成" in js
    assert "ask-pending" in js
    assert "ask-turn-error" in js
    assert "ask-empty" in js
    # cross-view entry contract for P3
    assert "prefillAsk" in js
    assert "graph2note:ask" in js
    assert "graph2note.pendingAsk" in js


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_ask_core_node_contract():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "ask_view.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "all assertions passed" in proc.stdout


# ---------------------------------------------------------------------------
# 3) API mock: three turns, one session, per-turn citations
# ---------------------------------------------------------------------------


def test_api_mock_three_turn_session_and_source_page(tmp_path):
    pytest.importorskip("pymupdf")
    from graph2note.store import FileDocumentStore
    from tests.test_pdf_qa_multiturn import ScriptedAnswerer, _three_page_library

    store = FileDocumentStore(str(tmp_path / "store"))
    stub = ScriptedAnswerer(["答案一 [1]", "答案二 [1]", "答案三 [1]"])
    client, _pdf_id = _three_page_library(store, stub)

    sid = "qa-p2-3turn"
    responses = []
    for question in ("alpha 的含义？", "beta 的含义？", "gamma 的含义？"):
        r = client.post("/api/pdf/ask", json={"question": question, "session_id": sid})
        assert r.status_code == 200, r.text
        responses.append(r.json())

    # the same session id is carried through all three requests (P1 contract)
    assert {r["session_id"] for r in responses} == {sid}
    assert [r["turn_index"] for r in responses] == [1, 2, 3]
    # each turn's citation comes from its own retrieval page (independence)
    assert [r["citations"][0]["page_index"] for r in responses] == [0, 1, 2]
    for r in responses:
        cite = r["citations"][0]
        assert cite["source_page_url"] == f"/api/documents/{cite['document_id']}/source-page"

    # the persisted session exposes all three turns: reload restores the chat
    session = client.get(f"/api/pdf/ask/sessions/{sid}").json()
    assert len(session["turns"]) == 3
    assert [t["citations"][0]["page_index"] for t in session["turns"]] == [0, 1, 2]
    assert session["scope"] == {"kind": "all", "pdf_ids": []}

    # an explicit new session does not delete the old one (history list stays)
    assert client.post("/api/pdf/ask", json={"question": "alpha", "session_id": "qa-p2-new"}
                       ).status_code == 200
    listed = {s["session_id"] for s in client.get("/api/pdf/ask/sessions").json()["sessions"]}
    assert {sid, "qa-p2-new"} <= listed
