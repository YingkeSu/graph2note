"""SPW Y3 — behavioural contract for upload.js PDF interception.

The P1 source-string assertion
(``tests/test_papers_ingest_api.py::test_upload_entry_routes_pdf_to_the_paper_pipeline``)
only proves the guard's *words* are present: the P1 reviewer's mutation
「反向拦截守卫（``interceptPaperFile`` 直接 ``return``，保留字符串）」 stayed
green.  This module adds the missing behaviour-level layer.

``node tests/upload_pdf_intercept.mjs`` drives the real capture-phase handler
under an offline DOM shim and pins the decision matrix:

* a PDF ``change`` on the hidden file input, or a PDF ``drop`` on the upload
  card (or a descendant) is intercepted — ``preventDefault`` +
  ``stopPropagation`` and entry into ``/api/papers/import``;
* JPG/PNG on the same zone is not intercepted, so the untouched image path
  (``/api/parse``) still runs;
* events outside the zone are inert.

The pure helpers (``isPdfFile`` / ``paperFileFromEvent`` /
``shouldInterceptPaperEvent``) are exported by ``upload.js`` for the harness.
Guards are mutation-sensitive: flipping them makes this suite red.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
NODE_TEST = TESTS_DIR / "upload_pdf_intercept.mjs"


def test_node_upload_pdf_intercept_contract():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")
    result = subprocess.run(
        [node, str(NODE_TEST)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all assertions passed" in result.stdout
