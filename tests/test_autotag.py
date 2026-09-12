"""Offline contracts for A1: parse-result auto tagging.

Covers the acceptance criteria:
- recorded golden fixtures for the three inference classes (reuse / new
  normalized / illegal output rejected); no live model call.
- the single post-ingest hook attaches auto tags from the single-image and PDF
  page commit paths; a failing inference leaves the document committed with a
  queryable warning.
- auto/manual provenance is exposed by the API and persists across reload.
- vocabulary-first: an alias output merges into the existing canonical tag.
- ``tags backfill`` defaults to dry-run; the reported budget equals the calls a
  ``--yes`` run performs.
- token usage of every inference is recorded on the document telemetry.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import autotag  # noqa: E402
from graph2note import cli  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore, SessionDocumentStore  # noqa: E402
from graph2note.webapp import create_app  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = HERE / "golden"
VALID = (GOLDEN / "valid-ir.golden.json").read_text(encoding="utf-8")

USAGE = {
    "prompt_tokens": 120,
    "completion_tokens": 18,
    "total_tokens": 138,
    "completion_tokens_details": {"reasoning_tokens": 5},
}


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


class StubPlanner:
    """Recorded-reply planner with call/usage accounting (offline)."""

    def __init__(self, reply: str, *, usage=None, raises: Exception | None = None):
        self.reply = reply
        self.usage = dict(USAGE if usage is None else usage)
        self.raises = raises
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model):
        self.calls += 1
        self.prompts.append(prompt)
        if self.raises is not None:
            raise self.raises
        return self.reply, self.usage


def _inferrer(planner: StubPlanner, **kw) -> autotag.TagInferrer:
    return autotag.TagInferrer(
        planner=planner, model=kw.pop("model", "stub-tagger"),
        provider=kw.pop("provider", "stub"), **kw,
    )


def _seed(store, document_id: str, markdown: str = "# 标题\n\n机器学习与知识库。") -> dict:
    original = Path(store.root) / f"{document_id}.jpg"
    original.write_bytes(b"fixture-image")
    return store.save_document(
        document_id=document_id,
        title=document_id,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=markdown,
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
    )


# ---------------------------------------------------------------------------
# AC1: the inference function is offline-testable with recorded goldens
# ---------------------------------------------------------------------------


def test_infer_reuses_vocabulary_golden():
    vocabulary = {
        "version": 1,
        "tags": {"机器学习": {"aliases": []}, "知识库": {"aliases": []}},
    }
    planner = StubPlanner(_golden("autotag-reuse.json"))
    result = autotag.infer_tags("# 正文", vocabulary, planner=planner, model="stub")
    assert result.tags == ["机器学习", "知识库"]
    assert result.warning is None
    assert planner.calls == 1
    assert result.usage == {
        "prompt_tokens": 120,
        "completion_tokens": 18,
        "reasoning_tokens": 5,
        "total_tokens": 138,
    }


def test_infer_new_tags_are_normalized():
    planner = StubPlanner(_golden("autotag-new.json"))
    result = autotag.infer_tags("# 正文", {"version": 1, "tags": {}}, planner=planner)
    # separators/case/whitespace collapse; duplicates dedupe
    assert result.tags == ["vector search", "检索增强", "rag"]


def test_infer_rejects_illegal_output():
    planner = StubPlanner(_golden("autotag-invalid.json"))
    result = autotag.infer_tags("# 正文", {"version": 1, "tags": {}}, planner=planner)
    assert result.tags is None
    assert "合法" in (result.warning or "")


def test_build_prompt_lists_vocabulary_and_truncates():
    vocabulary = {
        "version": 1,
        "tags": {"机器学习": {"aliases": ["machine learning"]}},
    }
    markdown = "x" * 500
    prompt = autotag.build_prompt(markdown, vocabulary, max_chars=100)
    assert "机器学习" in prompt and "machine learning" in prompt
    assert "已截断" in prompt
    assert "x" * 100 in prompt
    assert "x" * 101 not in prompt


# ---------------------------------------------------------------------------
# AC2 / AC6: post-ingest hook + failure path + telemetry
# ---------------------------------------------------------------------------


def test_after_ingest_attaches_tags_and_records_usage(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    planner = StubPlanner(_golden("autotag-reuse.json"))
    result = autotag.after_ingest(
        store, "doc-a", "# 正文", inferrer=_inferrer(planner))
    assert result["status"] == "ok"
    record = store.get_document("doc-a")
    assert record["tags"] == ["机器学习", "知识库"]
    assert record["tag_provenance"] == {"机器学习": "auto", "知识库": "auto"}
    assert record["auto_tag"]["status"] == "ok"
    assert record["auto_tag"]["inferences"][0]["total_tokens"] == 138
    assert record["auto_tag"]["model"] == "stub-tagger"


def test_after_ingest_failure_keeps_document_and_warns(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    planner = StubPlanner("", raises=RuntimeError("gateway down"))
    result = autotag.after_ingest(
        store, "doc-a", "# 正文", inferrer=_inferrer(planner))
    assert result["status"] == "failed"
    assert "gateway down" in result["warning"]
    record = store.get_document("doc-a")
    assert record["tags"] == []                       # parse doc still committed
    assert record["auto_tag"]["status"] == "failed"
    assert "gateway down" in record["auto_tag"]["warning"]


def test_after_ingest_invalid_reply_is_a_warning(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    planner = StubPlanner(_golden("autotag-invalid.json"))
    result = autotag.after_ingest(
        store, "doc-a", "# 正文", inferrer=_inferrer(planner))
    assert result["status"] == "failed"
    assert store.get_document("doc-a")["tags"] == []


def test_after_ingest_disabled_is_a_noop(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    assert autotag.after_ingest(store, "doc-a", "# 正文", inferrer=None)["status"] == "disabled"
    assert store.get_document("doc-a")["tags"] == []


def test_repair_rerun_hook_attaches_tags_to_new_version(tmp_path):
    """R1 repair rerun uses the same hook: commit a new version, then tag it."""
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", "# 空白页")
    _seed(store, "doc-a", "# 修复后的正文：机器学习")
    planner = StubPlanner(_golden("autotag-reuse.json"))
    result = autotag.after_ingest(
        store, "doc-a", "# 修复后的正文：机器学习", inferrer=_inferrer(planner))
    assert result["status"] == "ok"
    record = store.get_document("doc-a")
    assert len(record["versions"]) == 2               # old version preserved
    assert record["tags"] == ["机器学习", "知识库"]


# ---------------------------------------------------------------------------
# AC4: vocabulary-first alias merge
# ---------------------------------------------------------------------------


def test_vocabulary_priority_merges_alias_without_new_tag(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    store.create_tag("机器学习")
    store.add_tag_alias("机器学习", "machine learning")
    planner = StubPlanner(_golden("autotag-alias.json"))
    result = autotag.after_ingest(
        store, "doc-a", "# 正文", inferrer=_inferrer(planner))
    assert result["status"] == "ok"
    assert store.get_document("doc-a")["tags"] == ["机器学习", "知识库"]
    names = {item["tag"] for item in store.list_tags()}
    assert names == {"机器学习", "知识库"}            # no synonym created


# ---------------------------------------------------------------------------
# AC3: API provenance + persistence
# ---------------------------------------------------------------------------


def _app(tmp_path, **kw):
    return create_app(
        model="glm-5.3-flash",
        storage_dir=str(tmp_path / "store"),
        router_factory=_router_factory(VALID),
        max_retries=2,
        **kw,
    )


def _router_factory(content):
    def factory(image_path, model):
        return RouteARouter(model, caller=lambda p, m, recover=False: (content, {}))
    return factory


def _make_png(w=600, h=420):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    d.text((30, 40), "自动打标签测试", fill=(20, 20, 20), font=font)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _wait_done(client, job_id, timeout=20):
    import time

    for _ in range(int(timeout / 0.1)):
        body = client.get(f"/api/jobs/{job_id}").json()
        if body["status"] not in ("queued", "processing"):
            return body
        time.sleep(0.1)
    raise AssertionError("job did not finish in time")


def test_single_image_parse_attaches_auto_tags(tmp_path):
    planner = StubPlanner(_golden("autotag-reuse.json"))
    app = _app(tmp_path, auto_tag_inferrer=_inferrer(planner))
    client = TestClient(app)
    job_id = client.post(
        "/api/parse", files={"file": ("note.png", _make_png(), "image/png")}
    ).json()["job_id"]
    assert _wait_done(client, job_id)["status"] == "done"
    documents = client.get("/api/documents").json()
    assert len(documents) == 1
    doc = client.get(f"/api/documents/{documents[0]['document_id']}").json()
    assert planner.calls == 1
    assert doc["tag_provenance"] == {"机器学习": "auto", "知识库": "auto"}
    assert {item["provenance"] for item in doc["tags_detail"]} == {"auto"}


def test_api_promote_and_remove_auto_tag_persist(tmp_path):
    import tempfile

    storage_dir = Path(tempfile.mkdtemp(prefix="g2n-a1-"))
    store = FileDocumentStore(storage_dir / "storage")
    _seed(store, "doc-a")
    store.add_auto_tags("doc-a", json.loads(_golden("autotag-reuse.json")))
    client = TestClient(create_app(document_store=store, storage_dir=storage_dir))

    doc = client.get("/api/documents/doc-a").json()
    assert doc["tag_provenance"]["机器学习"] == "auto"

    promoted = client.patch(
        "/api/documents/doc-a/tags/机器学习", json={"provenance": "manual"})
    assert promoted.status_code == 200
    assert promoted.json()["tag_provenance"]["机器学习"] == "manual"
    # persisted across a fresh store instance (same root)
    reloaded = FileDocumentStore(storage_dir / "storage")
    assert reloaded.get_document("doc-a")["tag_provenance"]["机器学习"] == "manual"

    removed = client.delete("/api/documents/doc-a/tags/知识库")
    assert removed.status_code == 200
    assert removed.json()["tags"] == ["机器学习"]
    reloaded = FileDocumentStore(storage_dir / "storage")
    assert reloaded.get_document("doc-a")["tags"] == ["机器学习"]


def test_manual_add_endpoint_marks_manual(tmp_path):
    import tempfile

    storage_dir = Path(tempfile.mkdtemp(prefix="g2n-a1-"))
    store = FileDocumentStore(storage_dir / "storage")
    _seed(store, "doc-a")
    client = TestClient(create_app(document_store=store, storage_dir=storage_dir))
    added = client.post("/api/documents/doc-a/tags/manual", json={"tag": "手写笔记"})
    assert added.status_code == 200
    assert added.json()["tag_provenance"]["手写笔记"] == "manual"


def test_promote_unknown_provenance_is_rejected(tmp_path):
    import tempfile

    storage_dir = Path(tempfile.mkdtemp(prefix="g2n-a1-"))
    store = FileDocumentStore(storage_dir / "storage")
    _seed(store, "doc-a")
    client = TestClient(create_app(document_store=store, storage_dir=storage_dir))
    assert client.patch(
        "/api/documents/doc-a/tags/机器学习", json={"provenance": "auto"}
    ).status_code == 422


# ---------------------------------------------------------------------------
# AC5: backfill dry-run budget == real calls
# ---------------------------------------------------------------------------


def test_backfill_dry_run_reports_budget_without_calls(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    _seed(store, "doc-b")
    _seed(store, "doc-c")
    _seed(store, "doc-empty", markdown="   ")
    store.set_auto_tag_meta("doc-c", {"status": "ok", "tags": []})
    planner = StubPlanner(_golden("autotag-reuse.json"))
    report = autotag.backfill(store, dry_run=True)
    assert report["pending"] == 2
    assert report["estimated_calls"] == 2
    assert planner.calls == 0


def test_backfill_yes_calls_match_report(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a")
    _seed(store, "doc-b")
    planner = StubPlanner(_golden("autotag-reuse.json"))
    dry = autotag.backfill(store, dry_run=True)
    report = autotag.backfill(
        store, inferrer=_inferrer(planner), dry_run=False)
    assert report["processed"] == dry["estimated_calls"] == 2
    assert planner.calls == dry["estimated_calls"]
    assert report["succeeded"] == 2
    assert report["total_tokens"] == 2 * 138
    assert store.get_document("doc-a")["tags"] == ["机器学习", "知识库"]
    # second dry-run: nothing left to backfill
    assert autotag.backfill(store, dry_run=True)["pending"] == 0


def test_backfill_limit_caps_budget(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    for index in range(3):
        _seed(store, f"doc-{index}")
    report = autotag.backfill(store, dry_run=True, limit=2)
    assert report["pending"] == 2
    assert report["estimated_calls"] == 2


def test_cli_backfill_defaults_to_dry_run(tmp_path, capsys):
    store_root = tmp_path / "storage"
    store = FileDocumentStore(store_root)
    _seed(store, "doc-a")
    args = cli.build_tags_parser().parse_args(
        ["backfill", "--storage", str(store_root)])
    assert args.yes is False
    rc = cli.run_tags_backfill(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run" in out and "预估推断调用 1" in out


def test_cli_backfill_yes_uses_injected_planner(tmp_path, monkeypatch, capsys):
    store_root = tmp_path / "storage"
    store = FileDocumentStore(store_root)
    _seed(store, "doc-a")
    planner = StubPlanner(_golden("autotag-reuse.json"))
    monkeypatch.setattr(autotag, "live_planner", lambda **kw: planner)
    args = cli.build_tags_parser().parse_args(
        ["backfill", "--yes", "--storage", str(store_root)])
    rc = cli.run_tags_backfill(args)
    out = capsys.readouterr().out
    assert rc == 0
    assert planner.calls == 1
    assert "成功 1" in out


# ---------------------------------------------------------------------------
# PDF page commit entry (AC2)
# ---------------------------------------------------------------------------


def test_pdf_page_commit_attaches_auto_tags(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    import numpy as np
    from PIL import Image

    from graph2note import pdflib

    def _page(seed=1, w=300, h=420):
        arr = np.full((h, w, 3), 250, np.uint8)
        rng = np.random.default_rng(seed)
        for i in range(4):
            y = 60 + i * 90
            x = int(rng.integers(30, 120))
            arr[y:y + 4, x:x + int(rng.integers(50, 200)), :] = 30
        return Image.fromarray(arr)

    doc = pymupdf.open()
    img = _page()
    page = doc.new_page(width=img.width, height=img.height)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    page.insert_image(page.rect, stream=buf.getvalue())
    out = io.BytesIO()
    doc.save(out)
    doc.close()

    store = FileDocumentStore(tmp_path / "storage")
    job = pdflib.PdfJob(pdf_id="pdf-test", filename="scan.pdf",
                        model="glm-5.3-flash")
    planner = StubPlanner(_golden("autotag-reuse.json"))

    def factory(image_path, model):
        return RouteARouter(model, caller=lambda p, m, recover=False: (VALID, {}))

    pdflib.process_pdf(
        job, pdf_bytes=out.getvalue(), store=store, router_factory=factory,
        auto_tag_inferrer=_inferrer(planner),
    )
    assert job.status == "done"
    assert planner.calls == 1
    assert job.pages[0].document_id
    record = store.get_document(job.pages[0].document_id)
    assert record["tags"] == ["机器学习", "知识库"]
    assert record["tag_provenance"]["机器学习"] == "auto"


def test_session_store_provenance_helpers(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "doc-a")
    store.add_auto_tags("doc-a", {"tags": ["自动标签"]})
    assert store.get_document("doc-a")["tag_provenance"] == {"自动标签": "auto"}
    store.add_manual_tags("doc-a", ["手工标签"])
    assert store.get_document("doc-a")["tag_provenance"] == {
        "自动标签": "auto", "手工标签": "manual",
    }
    store.promote_tag("doc-a", "自动标签")
    assert store.get_document("doc-a")["tag_provenance"]["自动标签"] == "manual"
    store.remove_tag("doc-a", "自动标签")
    assert store.get_document("doc-a")["tags"] == ["手工标签"]
