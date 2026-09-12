"""U2 document library cards + grid (offline).

Covers the AC that is server-testable plus the frontend contract:

- pure ``extract_headline`` (Markdown first non-empty heading/line -> card title,
  filename fallback stays a frontend concern);
- ``/api/documents`` additive card fields with the legacy fields untouched;
- card date sourced from the existing effective-time priority chain
  (``select_effective_time``) rather than re-derived;
- ``/api/documents/{id}/thumbnail`` server-side downscale + on-disk cache;
- density switch markup + the Node card/lazy-load/action contract
  (``tests/library_cards.mjs``).

Zero network: golden router + TestClient + PIL-generated pages.
"""

import io
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

import graph2note.webapp as webapp  # noqa: E402
from graph2note.metadata import extract_headline  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402
from tests.static_assets import WEBSTATIC, static_js  # noqa: E402

HERE = Path(__file__).parent
TESTS_DIR = HERE
VALID = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")

LEGACY_FIELDS = {
    "document_id", "title", "created_at", "updated_at",
    "metadata", "effective_time", "collections",
}


# ---------------------------------------------------------------------------
# helpers (mirror tests/test_documents.py so the fixtures stay recognisable)
# ---------------------------------------------------------------------------


def _make_png(w=640, h=460, text="文档库测试"):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (w, h), (250, 250, 250))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=24)
    except TypeError:
        font = ImageFont.load_default()
    pos = ((ord((text or "s")[0]) * 53) % 600) + 20
    d.rectangle([pos, 40, pos + 140, 180], fill=(35, 35, 35))
    d.rectangle([pos // 2, 220, pos // 2 + 180, 300], fill=(70, 70, 70))
    d.rectangle([20, 30, 620, 440], outline=(30, 30, 30), width=3)
    d.text((40, 360), text, fill=(20, 20, 20), font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _router_factory(content):
    def factory(image_path, model):
        return RouteARouter(model, caller=lambda p, m, recover=False: (content, {}))
    return factory


def _app(store_dir):
    return webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=str(store_dir),
        document_store=FileDocumentStore(store_dir),
        router_factory=_router_factory(VALID),
    )


def _parse_one(tmp_path, name="sheet.png"):
    client = TestClient(_app(tmp_path))
    response = client.post(
        "/api/parse",
        files={"file": (name, _make_png(text=Path(name).stem), "image/png")},
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] not in ("queued", "processing"):
            assert job["status"] == "done", job
            return client, job["document_id"]
        time.sleep(0.1)
    raise AssertionError("job did not finish")


# ---------------------------------------------------------------------------
# 1) pure headline extraction (card title source)
# ---------------------------------------------------------------------------


def test_extract_headline_prefers_first_non_empty_line():
    assert extract_headline("# 状态空间模型笔记\n\n正文。") == "状态空间模型笔记"
    assert extract_headline("\n\n##  推理要点  ##\n正文") == "推理要点"
    assert extract_headline("没有标题的首行\n第二行") == "没有标题的首行"
    assert extract_headline("没有标题的首行\n# 后面的标题") == "没有标题的首行"


def test_extract_headline_skips_blanks_and_code_fences():
    assert extract_headline("```\nprint('not a title')\n```\n# 真标题") == "真标题"
    assert extract_headline("~~~\nfenced\n~~~") == ""
    assert extract_headline("   \n\t\n") == ""
    assert extract_headline("") == ""
    assert extract_headline(None) == ""
    # a Markdown hashtag without the ATX space is body text, not a heading
    assert extract_headline("#话题 首行") == "#话题 首行"


def test_extract_headline_is_bounded():
    assert len(extract_headline("x" * 500)) <= 200


# ---------------------------------------------------------------------------
# 2) /api/documents additive card fields (backward compatible)
# ---------------------------------------------------------------------------


def test_documents_list_appends_card_fields_without_touching_legacy(tmp_path):
    client, document_id = _parse_one(tmp_path)
    cards = client.get("/api/documents").json()
    assert len(cards) == 1
    card = cards[0]

    # legacy contract unchanged
    assert LEGACY_FIELDS <= set(card)
    assert card["document_id"] == document_id
    assert card["title"] == "sheet"
    assert card["metadata"]["effective_time"] is not None or card["effective_time"]

    # appended U2 fields
    assert card["headline"] == "状态空间模型笔记"
    assert card["thumbnail_url"] == f"/api/documents/{document_id}/thumbnail"
    assert card["source_kind"] == "image"
    assert card["source_pdf"] is None
    assert card["tags"] == []
    assert card["version_count"] == 1


def test_headline_follows_edited_markdown_and_falls_back_to_filename(tmp_path):
    client, document_id = _parse_one(tmp_path, name="IMG_2031.png")
    client.post(f"/api/documents/{document_id}/markdown",
                json={"markdown": "随手记下的第一行\n\n更多内容\n"})
    card = client.get("/api/documents").json()[0]
    assert card["headline"] == "随手记下的第一行"
    # the raw filename is still present for the frontend fallback/secondary line
    assert card["title"] == "IMG_2031"

    client.post(f"/api/documents/{document_id}/markdown", json={"markdown": "   \n\n"})
    card = client.get("/api/documents").json()[0]
    assert card["headline"] == ""


def test_card_date_uses_effective_time_priority_chain(tmp_path):
    client, document_id = _parse_one(tmp_path)
    # a manual document date must win the existing document_time > capture >
    # import chain; the card simply consumes the API's selection.
    response = client.put(f"/api/documents/{document_id}/metadata",
                          json={"document_time": "2026-03-04"})
    assert response.status_code == 200
    card = client.get("/api/documents").json()[0]
    assert card["effective_time"]["value"].startswith("2026-03-04")
    assert card["effective_time"]["source"] == "manual"
    assert card["effective_time"]["field"] == "document_time"


def test_card_tags_come_from_the_document_tags(tmp_path):
    client, document_id = _parse_one(tmp_path)
    response = client.put(f"/api/documents/{document_id}/tags",
                          json={"tags": ["数学", "控制", "笔记", "额外"]})
    assert response.status_code == 200
    card = client.get("/api/documents").json()[0]
    assert card["tags"] == ["数学", "控制", "笔记", "额外"]


def test_pdf_page_documents_report_pdf_source(tmp_path):
    store = FileDocumentStore(tmp_path)
    store.save_document(
        document_id="doc-page",
        title="lecture-p012",
        source_job_id="job-1",
        model="glm-5.3-flash",
        markdown="# 讲稿第 12 页\n",
        ir_json="{}",
        original_path=None,
        original_ext=".png",
        preprocessed_path=None,
        preprocessed_raw_path=None,
        assets_dir=None,
        timing_json={},
        source_pdf="lecture.pdf",
        page_number=12,
    )
    client = TestClient(webapp.create_app(
        model="glm-5.3-flash",
        storage_dir=str(tmp_path),
        document_store=store,
        router_factory=_router_factory(VALID),
    ))
    card = client.get("/api/documents").json()[0]
    assert card["source_kind"] == "pdf"
    assert card["source_pdf"] == "lecture.pdf"
    assert card["page_number"] == 12
    assert card["source_label"] == "lecture.pdf · 第 12 页"


# ---------------------------------------------------------------------------
# 3) thumbnail endpoint (downscale + cache)
# ---------------------------------------------------------------------------


def test_thumbnail_endpoint_downscales_and_caches(tmp_path):
    from PIL import Image

    client, document_id = _parse_one(tmp_path)
    original = client.get(f"/api/documents/{document_id}/preprocessed")
    assert original.status_code == 200
    thumb = client.get(f"/api/documents/{document_id}/thumbnail")
    assert thumb.status_code == 200
    assert thumb.headers["content-type"].startswith("image/png")
    with Image.open(io.BytesIO(thumb.content)) as image:
        thumb_pixels = image.size[0] * image.size[1]
        assert max(image.size) <= webapp.THUMBNAIL_MAX
    with Image.open(io.BytesIO(original.content)) as source:
        source_pixels = source.size[0] * source.size[1]
    # the thumbnail is a real downscale, not just a CSS constraint
    assert thumb_pixels < source_pixels

    # cached: the second request serves the same on-disk file
    cached = list(Path(tmp_path, "documents", document_id).rglob("thumbnail.png"))
    assert len(cached) == 1
    before = cached[0].read_bytes()
    assert client.get(f"/api/documents/{document_id}/thumbnail").content == before


def test_thumbnail_unknown_document_404(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.get("/api/documents/nope/thumbnail").status_code == 404


# ---------------------------------------------------------------------------
# 4) frontend contract + Node card/lazy/action test
# ---------------------------------------------------------------------------


def test_library_density_toggle_present():
    html = (WEBSTATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="library-density"' in html
    assert 'data-density="compact"' in html and 'data-density="comfortable"' in html


def test_library_cards_module_is_wired_and_lazy():
    source = static_js()
    # the grid renders through the shared pure card module
    assert "library_cards.js" in source
    assert "cardHtml" in source
    assert "createThumbnailLoader" in source
    assert "IntersectionObserver" in source
    # thumbnails are deferred (data-src) and tagged native-lazy
    assert 'data-src="' in source
    assert 'loading="lazy"' in source


def test_delete_confirmation_is_not_bypassed():
    source = static_js()
    # both the document view and the new card quick action keep a confirm step
    assert source.count("window.confirm") >= 2
    assert "确定删除？" in source
    assert "confirmDelete" in source
    assert "wireCardActions" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_library_cards_node_contract():
    proc = subprocess.run(
        ["node", str(TESTS_DIR / "library_cards.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
