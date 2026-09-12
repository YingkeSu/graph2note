"""Offline API contract tests for the S3 version comparison (issue S3).

Uses a real ``FileDocumentStore`` in a temp dir + the existing TestClient.
Documents are seeded straight through the store, so no router / model / network
is involved.  Asserts the S1/S2 consumption contract and the static wiring.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from graph2note import evolution
from graph2note import versiondiff
from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app

TESTS_DIR = Path(__file__).parent


def _ir(blocks: list[dict]) -> str:
    return json.dumps({"document_type": "note", "blocks": blocks}, ensure_ascii=False)


def _png(path, color):
    from PIL import Image

    Image.new("RGB", (8, 8), color).save(path)
    return str(path)


def _seed(store, document_id, blocks, markdown, *, preprocessed=""):
    store.save_document(
        document_id=document_id,
        title="手稿 X",
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=markdown,
        ir_json=_ir(blocks),
        original_path="",
        original_ext=".jpg",
        preprocessed_path=preprocessed,
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
        pg_hash="0" * 16,
    )


V1 = [
    {"type": "heading", "level": 1, "text": "绪论"},
    {"type": "paragraph", "text": "第一版原文"},
    {"type": "formula", "latex": "E = m c^2", "inline": False},
]
V2 = [
    {"type": "heading", "level": 1, "text": "绪论"},
    {"type": "paragraph", "text": "第二版改写"},
    {"type": "formula", "latex": "E = m c^2", "inline": False},
    {"type": "paragraph", "text": "新增段落"},
]


@pytest.fixture()
def library(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    png_a = _png(tmp_path / "a.png", (255, 0, 0))
    png_b = _png(tmp_path / "b.png", (0, 255, 0))
    _seed(store, "doc-x", V1, "# 绪论\n\n第一版原文\n", preprocessed=png_a)
    _seed(store, "doc-x", V2, "# 绪论\n\n第二版改写\n\n新增段落\n", preprocessed=png_b)
    _seed(store, "doc-one", V1, "# 绪论\n\n第一版原文\n", preprocessed=png_a)
    return store


def _client(store):
    return TestClient(create_app(document_store=store, storage_dir=store.root))


# ---------------------------------------------------------------------------
# compare endpoint
# ---------------------------------------------------------------------------


def test_diff_endpoint_payload_contract(library):
    payload = _client(library).get("/api/documents/doc-x/diff").json()
    assert payload["document_id"] == "doc-x"
    assert payload["count"] == 2
    assert payload["single_version"] is False
    assert payload["empty"] is False
    assert set(payload) >= {"a", "b", "report", "summary_lines", "latest_version_id"}
    for side in ("a", "b"):
        version = payload[side]
        assert set(version) >= {"version_id", "created_at", "source", "source_label",
                                "is_history", "is_current", "blocks", "block_count"}
        for block in version["blocks"]:
            assert set(block) >= {"index", "type", "anchor", "markdown"}
            assert block["anchor"] == f"block-{block['index']}"
    assert payload["b"]["is_current"] is True
    assert payload["a"]["is_history"] is True
    # the report is a plain S1 DiffReport dump
    assert set(payload["report"]) == {"label_a", "label_b", "changes", "summary"}
    assert payload["report"]["summary"]["changed_blocks"] > 0


def test_diff_endpoint_stats_match_diff_engine(library):
    """AC3: the summary numbers are the S1 DiffReport on the same fixture."""
    client = _client(library)
    payload = client.get("/api/documents/doc-x/diff").json()

    from graph2note.semantic import diff_ir
    from graph2note.semantic.cli import load_version_ir

    record = library.get_document("doc-x")
    ids = [version["version_id"] for version in record["versions"]]
    expected = diff_ir(
        load_version_ir(library, "doc-x", ids[0]),
        load_version_ir(library, "doc-x", ids[1]),
        label_a=ids[0], label_b=ids[1])
    assert payload["report"] == expected.model_dump()
    assert payload["summary_lines"] == versiondiff.summarize_diff(expected.summary)


def test_diff_endpoint_selectors_swap_and_same_version(library):
    client = _client(library)
    record = library.get_document("doc-x")
    ids = [version["version_id"] for version in record["versions"]]

    swapped = client.get(f"/api/documents/doc-x/diff?a={ids[1]}&b={ids[0]}").json()
    assert swapped["a"]["version_id"] == ids[1]
    assert swapped["b"]["version_id"] == ids[0]

    same = client.get(f"/api/documents/doc-x/diff?a={ids[0]}&b={ids[0]}").json()
    assert same["same_version"] is True
    assert same["empty"] is True
    assert same["summary_lines"] == ["两版内容一致，无块级变更。"]
    # 0-based index selectors are accepted too
    indexed = client.get("/api/documents/doc-x/diff?a=0&b=1").json()
    assert indexed["a"]["version_id"] == ids[0]


def test_diff_endpoint_single_version_safe_state(library):
    payload = _client(library).get("/api/documents/doc-one/diff").json()
    assert payload["single_version"] is True
    assert payload["count"] == 1
    assert payload["empty"] is True
    assert payload["a"]["version_id"] == payload["b"]["version_id"]


def test_diff_endpoint_reflects_the_edit_head(library):
    client = _client(library)
    client.post("/api/documents/doc-x/markdown", json={"markdown": "# 绪论\n\n手改\n"})
    payload = client.get("/api/documents/doc-x/diff").json()
    assert payload["b"]["is_edit"] is True
    assert payload["b"]["is_current"] is True
    assert payload["empty"] is False


def test_diff_endpoint_errors(library):
    client = _client(library)
    assert client.get("/api/documents/nope/diff").status_code == 404
    assert client.get("/api/documents/doc-x/diff?a=nope").status_code == 422
    assert client.get("/api/documents/doc-x/diff?b=99").status_code == 422


def test_diff_endpoint_is_read_only(library):
    client = _client(library)
    before = client.get("/api/documents/doc-x/versions").json()
    client.get("/api/documents/doc-x/diff")
    client.get("/api/documents/doc-x/diff?a=0&b=1")
    after = client.get("/api/documents/doc-x/versions").json()
    assert before == after


# ---------------------------------------------------------------------------
# per-version original image
# ---------------------------------------------------------------------------


def test_version_preprocessed_endpoint(library):
    client = _client(library)
    record = library.get_document("doc-x")
    first = record["versions"][0]["version_id"]
    response = client.get(f"/api/documents/doc-x/versions/{first}/preprocessed")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    assert client.get("/api/documents/doc-x/versions/nope/preprocessed").status_code == 404
    assert client.get("/api/documents/nope/versions/x/preprocessed").status_code == 404


def test_edit_head_reuses_latest_preprocessed(library):
    client = _client(library)
    client.post("/api/documents/doc-x/markdown", json={"markdown": "# 绪论\n\n手改\n"})
    response = client.get("/api/documents/doc-x/versions/working-copy/preprocessed")
    assert response.status_code == 200
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------------------
# static wiring
# ---------------------------------------------------------------------------


def test_compare_view_markup_and_assets_served(library):
    client = _client(library)
    html = client.get("/").text
    for element in ("diff-view", "diff-select-a", "diff-select-b", "diff-summary",
                    "diff-rows", "diff-empty", "version-compare", "version-readonly-note"):
        assert f'id="{element}"' in html, element
    assert client.get("/static/js/views/version-diff.js").status_code == 200
    assert client.get("/static/js/version_diff_core.js").status_code == 200
    script = client.get("/static/js/views/version-diff.js").text
    assert "/versions" in script
    assert "/diff" in script
    # the backend summary is templated server-side (zero model), never in JS
    assert "summary_lines" in client.get("/static/js/version_diff_core.js").text


# ---------------------------------------------------------------------------
# DOM behaviour harness (real frontend module, scripted fetch)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_version_diff_dom_behaviour_harness():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "version_diff_dom.mjs")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert "all assertions passed" in proc.stdout
