"""W2 (SPW I-track): weekly-digest sectioned view, source links and export.

Two evidence layers, both offline:

1. ``node tests/digest_view_dom.mjs`` drives the real
   ``webstatic/js/views/dashboard.js`` module over a DOM shim plus a scripted
   ``fetch`` replay (synthetic ``meta.json`` fixtures).  It covers sectioned
   rendering, the legacy whole-Markdown fallback, per-section source links with
   dead-id handling, the Blob export, history readability and the
   empty/generating/failure states.
2. Static assertions keep the territory honest: ``index.html`` is untouched
   (the export button and the action row are created from JS), ``style.css``
   only appends new selectors, and the view keeps both rendering paths.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import graph2note
from graph2note import webapp

ROOT = Path(__file__).resolve().parents[1]
WEBSTATIC = Path(graph2note.__file__).parent / "webstatic"
NODE_TEST = ROOT / "tests" / "digest_view_dom.mjs"

# Digest markup that existed before W2; the W2 additions are JS-created.
DIGEST_HTML_IDS = {
    "digest-panel", "digest-range", "digest-from", "digest-from-sep", "digest-to",
    "digest-force", "digest-generate", "digest-status", "digest-history",
    "digest-viewer", "digest-viewer-meta", "digest-viewer-content", "digest-empty",
}


def test_node_digest_view_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    result = subprocess.run([node, str(NODE_TEST)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all assertions passed" in result.stdout


def test_index_html_is_untouched_by_w2():
    html = (WEBSTATIC / "index.html").read_text(encoding="utf-8")
    assert set(re.findall(r'id="(digest-[a-z-]+)"', html)) == DIGEST_HTML_IDS
    assert "digest-export" not in html
    assert "digest-actions" not in html
    assert "digest-section" not in html


def test_style_appends_w2_rules_without_touching_existing_ones():
    css = (WEBSTATIC / "style.css").read_text(encoding="utf-8")
    for selector in (
        ".digest-stats-block", ".digest-section-nav", ".digest-nav-link",
        ".digest-section-sources", ".digest-source-missing", ".digest-actions",
        ".digest-extra-block", ".digest-status-error", ".digest-item-time",
    ):
        assert selector in css, selector
    # pre-existing digest rules stay byte-identical
    assert ".digest-item.selected { border-color: var(--accent-dark); background: var(--panel); }" in css
    assert ".digest-content { max-height: 480px; overflow: auto; }" in css
    # the new block is appended at the end, after the D3 block
    assert css.rindex("/* ============ W2 (SPW)") > css.rindex(".preview figure.g2n-diagram")
    assert css.rstrip().endswith("}")
    # readability: no auxiliary size drops below the 12px floor in the new block
    block = css[css.rindex("/* ============ W2 (SPW)"):]
    assert "font-size: 11px" not in block
    assert "font-size: 10px" not in block


def test_dashboard_view_keeps_both_rendering_paths():
    src = (WEBSTATIC / "js" / "views" / "dashboard.js").read_text(encoding="utf-8")
    # sectioned path consumes the W1 contract
    assert "meta.sections" in src
    assert "renderDigestSectioned(" in src
    assert "export function splitDigestMarkdown" in src
    # legacy fallback renders the whole markdown exactly as before
    assert "renderMarkdownInto(el.digestViewerContent, digestView.markdown)" in src
    # source links resolve against the library and mark dead ids
    assert "digestView.known" in src
    assert "digest-source-missing" in src
    # export is a frontend Blob download with a range+date filename
    assert "export function exportCurrentDigest" in src
    assert "export function digestExportFilename" in src
    assert "weekly-digest_" in src
    # the R2 caveat is rendered as text, not only as a tooltip
    assert "DIGEST_VIEW_INBOX_CAVEAT" in src


def test_webapp_serves_the_w2_assets(tmp_path):
    client = TestClient(webapp.create_app(storage_dir=tmp_path))
    view = client.get("/static/js/views/dashboard.js")
    assert view.status_code == 200
    assert "renderDigestSectioned" in view.text
    css = client.get("/static/style.css")
    assert css.status_code == 200
    assert ".digest-section-nav" in css.text
