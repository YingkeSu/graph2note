"""RW01 (research-weekly-template 01): 科研周报 reading view + static wiring.

Two evidence layers, both offline:

1. ``node tests/report_view_dom.mjs`` drives the real
   ``webstatic/js/views/report.js`` module over a DOM shim plus a scripted
   ``fetch`` replay: template list, optional 专题 enable/order → API payload,
   sectioned rendering with source links, stats/budget strip, cached/failure/
   empty states, legacy template delegation and Markdown export.
2. Static assertions keep the territory honest: the report panel lives in its
   own ``#report-zone`` (the legacy digest panel is untouched), the router and
   entry module are wired, and the new CSS is appended.
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
NODE_TEST = ROOT / "tests" / "report_view_dom.mjs"

REPORT_HTML_IDS = {
    "report-zone", "report-template", "report-range", "report-from", "report-from-sep",
    "report-to", "report-reporter", "report-date", "report-force", "report-generate",
    "report-export", "report-modules", "report-module-list", "report-status",
    "report-actions", "report-history", "report-viewer", "report-viewer-meta",
    "report-viewer-stats", "report-viewer-content", "report-empty",
}

DIGEST_HTML_IDS = {
    "digest-panel", "digest-range", "digest-from", "digest-from-sep", "digest-to",
    "digest-force", "digest-generate", "digest-status", "digest-history",
    "digest-viewer", "digest-viewer-meta", "digest-viewer-content", "digest-empty",
}


def test_node_report_view_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    result = subprocess.run([node, str(NODE_TEST)], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all assertions passed" in result.stdout


def test_index_html_marks_up_the_report_zone_without_touching_digest():
    html = (WEBSTATIC / "index.html").read_text(encoding="utf-8")
    assert set(re.findall(r'id="(report-[a-z-]+)"', html)) == REPORT_HTML_IDS
    assert "科研周报" in html
    assert 'id="nav-reports"' in html and 'data-route="#reports"' in html
    # the legacy weekly-summary markup stays intact
    assert set(re.findall(r'id="(digest-[a-z-]+)"', html)) == DIGEST_HTML_IDS
    # the report zone sits after the dashboard zone (which owns the digest panel)
    assert html.index('id="dashboard-zone"') < html.index('id="report-zone"')


def test_router_state_and_entry_module_are_wired():
    router = (WEBSTATIC / "js" / "router.js").read_text(encoding="utf-8")
    assert 'parts[0] === "reports"' in router
    state = (WEBSTATIC / "js" / "state.js").read_text(encoding="utf-8")
    assert 'reportZone: $("#report-zone")' in state
    assert "el.reportZone" in state
    entry = (WEBSTATIC / "app.js").read_text(encoding="utf-8")
    assert '"./js/views/report.js"' in entry


def test_style_appends_rw01_rules():
    css = (WEBSTATIC / "style.css").read_text(encoding="utf-8")
    for selector in (
        ".report-zone", ".report-controls", ".report-modules", ".report-module-list",
        ".report-section-nav", ".report-section-sources", ".report-source-missing",
        ".report-stats", ".report-budget-note", ".report-actions", ".report-status-error",
    ):
        assert selector in css, selector
    assert (WEBSTATIC / "style.css").read_text(encoding="utf-8").rstrip().endswith("}")


def test_webapp_serves_report_assets_and_unified_boundary(tmp_path):
    client = TestClient(webapp.create_app(storage_dir=tmp_path))
    view = client.get("/static/js/views/report.js")
    assert view.status_code == 200
    assert "renderReportView" in view.text
    # F3: the research template reuses the existing digest create/list/detail boundary
    assert "/api/digests" in view.text
    assert client.get("/api/report-templates").status_code == 200
    assert client.get("/api/digests").json() == {"digests": [], "total": 0}
    assert client.get("/api/digests/nope").status_code == 404
