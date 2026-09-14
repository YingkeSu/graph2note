"""D3: structure-diagram presentation in the document reading pane.

The backend renders a grouped/layered structure diagram to a PNG; the reading
pane must present it as a labelled figure block and offer a zoom/pan
affordance (T-audit phase-1 showed a very wide drawing is unreadable when
scaled to the pane width).  Covers:

* the pure helpers run under Node (``node tests/diagram_presentation.cjs``);
* ``views/document.js`` wires the figure branch + click/keyboard zoom without
  disturbing the plain-image path;
* the appended ``style.css`` rules exist (append-only: no existing selector
  is modified).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

import graph2note

ROOT = Path(__file__).resolve().parents[1]
WEBSTATIC = Path(graph2note.__file__).parent / "webstatic"
NODE_TEST = ROOT / "tests" / "diagram_presentation.cjs"


def test_node_presentation_contract():
    node = shutil.which("node")
    if not node:
        pytest.skip("node unavailable")
    result = subprocess.run([node, str(NODE_TEST)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_document_view_wires_the_diagram_figure():
    src = (WEBSTATIC / "js" / "views" / "document.js").read_text(encoding="utf-8")
    assert "isDiagramAssetRef" in src
    assert "buildDiagramFigure" in src
    # plain images keep the <img> branch
    assert 'return `<img ${attrs}>`;' in src
    # diagram images open the shared zoom/pan viewer by click and keyboard
    assert 'target.closest("figure.g2n-diagram img")' in src
    assert "openImageViewer(img.src)" in src


def test_assets_helper_is_the_single_diagram_switch():
    src = (WEBSTATIC / "assets.js").read_text(encoding="utf-8")
    assert "isDiagramAssetRef" in src
    assert "buildDiagramFigure" in src
    assert "DIAGRAM_ASSET_RE" in src


def test_style_appends_diagram_figure_rules_without_touching_preview_img():
    css = (WEBSTATIC / "style.css").read_text(encoding="utf-8")
    assert ".preview figure.g2n-diagram" in css
    assert ".g2n-diagram-caption" in css
    # the pre-existing preview rules are still present untouched
    assert ".preview img { max-width: 100%; }" in css
    # new block sits at the end of the file (append-only)
    assert css.rstrip().endswith("}")
    assert css.rindex(".preview figure.g2n-diagram") > css.rindex(".doc-collection-chip:hover")
