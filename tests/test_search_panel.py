"""P3 unified search panel contracts (offline DOM + static assertions).

1. DOM assertions over ``index.html`` (stdlib parser): the topbar search entry,
   the ⌘K panel with its two result groups and the "ask about these results"
   action.
2. Static/behaviour assertions over ``search-panel.js``: ⌘K / Esc wiring, the
   grouped render, editor jump for documents, original-page jump for PDF pages
   and the cross-view query hand-off.
3. ``node tests/search_panel.mjs`` exercises the pure helpers (result grouping,
   page display, pending-ask round-trip, QA route detection); skipped when node
   is unavailable.

No network and no browser: everything runs against the local TestClient.
"""

from __future__ import annotations

import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph2note import webapp

TESTS_DIR = Path(__file__).parent
VOID_TAGS = {
    "meta", "link", "img", "input", "br", "hr", "source", "area", "base",
    "col", "embed", "param", "track", "wbr",
}


# ---------------------------------------------------------------------------
# tiny DOM parser (stdlib only) — enough for structural assertions
# ---------------------------------------------------------------------------


class Element:
    def __init__(self, tag: str, attrs: dict, parent: "Element | None" = None):
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[Element] = []

    @property
    def id(self) -> str | None:
        return self.attrs.get("id")

    def iter_elements(self):
        for child in self.children:
            yield child
            yield from child.iter_elements()

    def find(self, *, id=None, tag=None) -> "Element | None":
        for node in self.iter_elements():
            if id is not None and node.id != id:
                continue
            if tag is not None and node.tag != tag:
                continue
            return node
        return None

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _DomParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Element(tag, dict(attrs), self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return


def _parse(html: str) -> Element:
    parser = _DomParser()
    parser.feed(html)
    return parser.root


def _client():
    return TestClient(webapp.create_app(model="stub-model"))


# ---------------------------------------------------------------------------
# DOM: topbar entry + ⌘K panel structure
# ---------------------------------------------------------------------------


def test_index_has_topbar_entry_and_search_panel_dom():
    html = _client().get("/").text
    root = _parse(html)

    topbar = root.find(tag="header")
    assert topbar is not None
    form = topbar.find(id="global-search-form")
    assert form is not None and form.tag == "form"
    entry = form.find(id="global-search-input")
    assert entry is not None and entry.attrs.get("type") == "search"

    panel = root.find(id="global-search-panel")
    assert panel is not None
    assert panel.attrs.get("role") == "dialog"
    assert panel.find(id="global-search-panel-input") is not None
    assert panel.find(id="global-search-close") is not None
    assert panel.find(id="global-search-status") is not None
    assert panel.find(id="global-search-results") is not None

    # results are grouped: documents first, then PDF pages
    groups = [node for node in panel.iter_elements()
              if node.attrs.get("data-search-group")]
    assert [g.attrs["data-search-group"] for g in groups] == ["documents", "pdf_pages"]
    assert panel.find(id="global-search-documents") is not None
    assert panel.find(id="global-search-pdf-pages") is not None

    # "just ask about these results" lives in the panel footer
    ask = panel.find(id="global-search-ask")
    assert ask is not None and ask.tag == "button"

    # the panel is part of the ES-module graph (single module entry, U1 shell)
    entry = _client().get("/static/app.js").text
    assert '"./search-panel.js"' in entry


# ---------------------------------------------------------------------------
# behaviour source assertions: ⌘K / Esc / grouped clicks / ask hand-off
# ---------------------------------------------------------------------------


def test_search_panel_js_wires_shortcuts_groups_and_jump_targets():
    client = _client()
    js = client.get("/static/search-panel.js")
    assert js.status_code == 200
    src = js.text

    # ⌘K opens globally, Esc closes; both are wired on the document
    assert "metaKey" in src and "ctrlKey" in src
    assert '"k"' in src and "isEditable" in src
    assert "escape" in src
    # input is debounced so typing stays responsive
    assert "DEBOUNCE_MS" in src and "setTimeout(runSearch" in src

    # one unified endpoint, grouped render
    assert "/api/search?q=" in src
    assert "documents" in src and "pdf_pages" in src

    # document result -> editor; PDF result -> original page
    assert '"#doc/" + encodeURIComponent' in src
    assert "source_page_url" in src
    assert 'target = "_blank"' in src

    # cross-view hand-off carries the query into the Q&A input
    assert "graph2note.pendingAsk" in src
    assert '"pdf-qa-input"' in src
    assert "qaRoute" in src


# ---------------------------------------------------------------------------
# node pure-function suite (skipped without node)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not available")
def test_node_search_panel_helpers():
    result = subprocess.run(
        ["node", str(TESTS_DIR / "search_panel.mjs")],
        cwd=str(TESTS_DIR.parent), capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all assertions passed" in result.stdout
