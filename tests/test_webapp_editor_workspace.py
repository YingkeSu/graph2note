"""U3 editor workspace contracts (offline).

Two complementary layers:

1. Structural DOM assertions over ``index.html``: the editor main axis is
   exactly a permanent toolbar plus the three panes; tags / collections / time
   metadata / needs-organization / version info live in the collapsible right
   side panel; autosave indicator + warnings sit in the toolbar (outside the
   scrolling panes); the large-image viewer markup exists for both sources.
2. A Node DOM behaviour harness (``node tests/editor_workspace_dom.mjs``) that
   drives the real ``js/views/document.js`` module against a scripted ``fetch``
   and asserts every side-panel form still reaches the same API and updates the
   same shared state.  Skipped when node is unavailable.

No network: the static-serving check uses the local FastAPI TestClient.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.html_dom import load_dom
from tests.static_assets import WEBSTATIC, static_js  # noqa: F401

TESTS_DIR = Path(__file__).parent


@pytest.fixture(scope="module")
def dom():
    return load_dom(WEBSTATIC / "index.html")


# ---------------------------------------------------------------------------
# 1) editor workspace structure
# ---------------------------------------------------------------------------


def test_editor_axis_is_toolbar_plus_three_panes(dom):
    work = dom.find(id="work-zone")
    assert work is not None
    # The viewer is a fixed overlay; the visible editor axis is toolbar + panes.
    axis = [n for n in work.children if n.id != "image-viewer"]
    assert len(axis) == 2, [n.id or n.attrs.get("class") for n in axis]
    toolbar, main = axis
    assert "doc-toolbar" in toolbar.classes
    assert "doc-main" in main.classes

    panes = main.find(cls="panes")
    assert panes is not None
    pane_classes = [p.classes for p in panes.find_all(cls="pane")]
    assert len(pane_classes) == 3, pane_classes
    for expected in ("pane-image", "pane-md", "pane-preview"):
        assert any(expected in c for c in pane_classes), expected
    # three-pane axis is a direct child of doc-main; side panel is its sibling
    assert panes.parent is main
    assert main.find(id="doc-side-panel") is not None


def test_info_panel_owns_tags_collections_metadata_versions(dom):
    work = dom.find(id="work-zone")
    main = work.find(cls="doc-main")
    panel = main.find(id="doc-side-panel")
    assert panel is not None
    for moved in ("document-tags", "document-collections", "metadata-panel",
                  "version-panel", "version-info", "version-list"):
        assert panel.find(id=moved) is not None, f"{moved} must live in the side panel"
    # form controls for the full metadata/tag/collection behaviour live inside
    for control in ("document-tag-form", "document-tag-input", "document-collection-form",
                    "document-collection-select", "metadata-document-time",
                    "metadata-needs-organization", "metadata-save"):
        assert panel.contains_id(control), control
    # none of the moved blocks remain on the three-pane axis
    for moved in ("document-tags", "document-collections", "metadata-panel",
                  "version-panel", "version-info"):
        assert not main.find(cls="panes").contains_id(moved), moved
    # default collapsed, with a toggle that reflects state
    assert "hidden" in panel.classes
    toggle = work.find(id="doc-panel-toggle")
    assert toggle is not None and toggle.attrs.get("aria-expanded") == "false"
    assert toggle.attrs.get("aria-controls") == "doc-side-panel"


def test_toolbar_keeps_autosave_and_warnings_visible(dom):
    work = dom.find(id="work-zone")
    toolbar = work.find(cls="doc-toolbar")
    assert toolbar is not None
    # AC: autosave indicator + warnings are permanent toolbar content, so they
    # can never scroll away with the editor.
    assert toolbar.contains_id("save-indicator")
    assert toolbar.contains_id("warnings")
    assert toolbar.contains_id("status-text")
    # document actions migrated here (semantics unchanged)
    for action in ("btn-reparse", "btn-copy", "btn-download", "btn-delete"):
        assert toolbar.contains_id(action), action
    # the toolbar is not inside a scrolling pane body
    for pane_body in dom.find_all(cls="pane-body"):
        assert not pane_body.contains_id("save-indicator")
        assert not pane_body.contains_id("warnings")


def test_image_viewer_markup_and_entry_points(dom):
    work = dom.find(id="work-zone")
    viewer = work.find(id="image-viewer")
    assert viewer is not None and "hidden" in viewer.classes
    for control in ("image-viewer-stage", "image-viewer-img", "viewer-zoom-in",
                    "viewer-zoom-out", "viewer-fit", "viewer-close",
                    "viewer-zoom-label"):
        assert viewer.find(id=control) is not None, control
    # entry points: a dedicated button in the image pane head + the image itself
    image_pane = work.find(cls="pane-image")
    assert image_pane.find(id="btn-zoom-image") is not None
    original = image_pane.find(id="original-img")
    assert original is not None and original.attrs.get("role") == "button"
    # re-load control kept from the pre-U3 pane
    assert image_pane.find(id="btn-repic") is not None


def test_editor_module_exposes_u3_behaviour(dom):
    javascript = static_js()
    # viewer supports image uploads and PDF source pages
    assert "/source-page" in javascript
    assert "viewerSource" in javascript
    # shortcuts: explicit ⌘S save, ⌘/ panel, Esc viewer, input guard
    assert "handleEditorShortcut" in javascript
    assert "isTextInputFocused" in javascript
    assert "explicitSave" in javascript


# ---------------------------------------------------------------------------
# 2) DOM behaviour harness (real frontend module, scripted fetch)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_editor_dom_behaviour_harness():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "editor_workspace_dom.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "all assertions passed" in proc.stdout


# ---------------------------------------------------------------------------
# 3) the reshaped workspace is still served statically (zero-build)
# ---------------------------------------------------------------------------


def test_editor_workspace_served(tmp_path):
    from fastapi.testclient import TestClient

    from graph2note import webapp

    client = TestClient(webapp.create_app(storage_dir=tmp_path))
    index = client.get("/")
    assert index.status_code == 200
    assert 'id="doc-side-panel"' in index.text
    assert 'id="image-viewer"' in index.text
    assert client.get("/static/js/views/document.js").status_code == 200
