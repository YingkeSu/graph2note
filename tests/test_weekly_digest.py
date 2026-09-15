"""Offline contracts for the A2 weekly digest.

Covers the issue's acceptance criteria:

- pure range -> document mapping (priority chain + import fallback, empty range,
  PDF-source documents, boundaries);
- deterministic material assembly + fingerprint, and the fingerprint cache
  (a repeat request makes zero new model calls; ``force`` writes a new version);
- text-channel generation with a digests-only purpose session, token usage
  recorded in the meta *and* merged into the telemetry Dashboard;
- persisted ``<storage>/digests/<id>.md`` + ``<id>.meta.json`` readable after a
  restart;
- recorded-golden full chain offline (assemble -> plan -> persist -> API/UI);
- API contract + Web block DOM assertions, with an explicit empty state.

The text model is always an injected recording planner, so these tests never
touch the network.  The single real smoke call lives in the handoff, not here.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph2note import cli, digest
from graph2note.notes import llm as notes_llm
from graph2note.store import FileDocumentStore
from graph2note.telemetry import build_stats
from graph2note.webapp import create_app

GOLDEN = (Path(__file__).parent / "golden" / "weekly-digest.golden.md").read_text(encoding="utf-8")
# W1: the sectioned JSON reply golden (SPEC §3 four-section skeleton)
SECTIONS_GOLDEN = (Path(__file__).parent / "golden" / "weekly-digest.sections.json").read_text(
    encoding="utf-8")


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


def _slot(value=None, source="none"):
    return {"value": value, "source": source, "confidence": None, "evidence": None}


def _record(
    document_id: str,
    title: str,
    *,
    document_time=None,
    capture_time=None,
    import_time=None,
    created_at=None,
    markdown="",
    tags=None,
    topics=None,
    version_id=None,
    pdf_id=None,
    page_index=None,
    page_number=None,
):
    record = {
        "document_id": document_id,
        "title": title,
        "metadata": {
            "document_time": _slot(document_time, "manual" if document_time else "none"),
            "capture_time": _slot(capture_time, "exif"),
            "import_time": _slot(import_time, "system"),
        },
        "current_markdown": markdown,
        "tags": tags or [],
        "topics": topics or [],
    }
    if created_at:
        record["created_at"] = created_at
    if version_id:
        record["latest_version_id"] = version_id
    if pdf_id:
        record.update({"pdf_id": pdf_id, "page_index": page_index, "page_number": page_number})
    return record


class RecordingPlanner:
    """Recorded offline text model; counts calls and captures prompts."""

    def __init__(self, reply=GOLDEN, *, usage=None, model="stub-text", provider="stub"):
        self.reply = reply
        self.usage = usage if usage is not None else {
            "prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200,
        }
        self.model = model
        self.provider = provider
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        return {
            "text": self.reply,
            "usage": self.usage,
            "model": self.model,
            "provider": self.provider,
        }


def _seed(store: FileDocumentStore, document_id: str, title: str, *, markdown, metadata=None):
    store.save_document(
        document_id=document_id,
        title=title,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=markdown,
        ir_json=json.dumps({"blocks": []}),
        original_path="",
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
        metadata=metadata,
    )
    return store.get_document(document_id)


CUSTOM = {"kind": "custom", "from": "2026-09-01", "to": "2026-09-07",
          "label": "自定义（2026-09-01 ~ 2026-09-07）"}


# ---------------------------------------------------------------------------
# AC1 — pure range -> document mapping
# ---------------------------------------------------------------------------


def test_resolve_range_calendar_weeks_custom_and_errors():
    monday = date(2026, 9, 10)  # Thursday
    this_week = digest.resolve_range("this_week", today=monday)
    assert this_week == {"kind": "this_week", "from": "2026-09-07", "to": "2026-09-13",
                         "label": "本周（2026-09-07 ~ 2026-09-13）"}
    last_week = digest.resolve_range("last_week", today=monday)
    assert (last_week["from"], last_week["to"]) == ("2026-08-31", "2026-09-06")
    custom = digest.resolve_range("custom", from_="2026-09-01", to="2026-09-07")
    assert (custom["from"], custom["to"]) == ("2026-09-01", "2026-09-07")
    # aliases normalize
    assert digest.resolve_range("this-week", today=monday)["kind"] == "this_week"
    with pytest.raises(digest.RangeError):
        digest.resolve_range("fortnight")
    with pytest.raises(digest.RangeError):
        digest.resolve_range("custom", from_="2026-09-01")
    with pytest.raises(digest.RangeError):
        digest.resolve_range("custom", from_="2026-09-07", to="2026-09-01")


def test_effective_time_priority_chain_and_import_fallback():
    manual = _record("a", "A", document_time="2026-09-02", capture_time="2026-09-03",
                     import_time="2026-09-04")
    assert digest.select_effective_time(manual)["field"] == "document_time"
    assert digest.select_effective_time(manual)["source"] == "manual"

    captured = _record("b", "B", capture_time="2026-09-03", import_time="2026-09-04")
    assert digest.select_effective_time(captured)["field"] == "capture_time"

    imported = _record("c", "C", import_time="2026-09-04")
    assert digest.select_effective_time(imported)["field"] == "import_time"

    # no metadata slot at all -> fall back to the import time (created_at)
    fallback = _record("d", "D", created_at="2026-09-05T08:00:00")
    effective = digest.select_effective_time(fallback)
    assert (effective["field"], effective["source"], effective["value"]) == (
        "import_time", "import_fallback", "2026-09-05T08:00:00")
    assert digest.select_effective_time(_record("e", "E")) is None


def test_documents_in_range_filters_sorts_and_is_pure():
    records = [
        _record("later", "Later", document_time="2026-09-05", markdown="c"),
        _record("early", "Early", document_time="2026-09-02", markdown="a"),
        _record("outside", "Outside", document_time="2026-09-20", markdown="z"),
        _record("fallback", "Fallback", created_at="2026-09-03T00:00:00", markdown="b"),
    ]
    entries = digest.documents_in_range(records, CUSTOM)
    assert [e["document_id"] for e in entries] == ["early", "fallback", "later"]
    # order is independent of input order
    reversed_entries = digest.documents_in_range(list(reversed(records)), CUSTOM)
    assert reversed_entries == entries
    # undated document with no metadata slot is excluded, not crashed
    assert digest.documents_in_range([_record("ghost", "Ghost")], CUSTOM) == []


def test_documents_in_range_is_inclusive_on_both_boundaries():
    records = [
        _record("start", "Start", document_time="2026-09-01"),
        _record("end", "End", document_time="2026-09-07"),
        _record("before", "Before", document_time="2026-08-31"),
        _record("after", "After", document_time="2026-09-08"),
    ]
    entries = digest.documents_in_range(records, CUSTOM)
    assert [e["document_id"] for e in entries] == ["start", "end"]


def test_empty_range_is_empty_not_an_error():
    assert digest.documents_in_range([], CUSTOM) == []
    assert digest.documents_in_range([_record("x", "X", document_time="2020-01-01")], CUSTOM) == []


def test_pdf_source_documents_are_included():
    page = _record("doc-pdf-p2", "PDF 第 2 页", document_time="2026-09-03",
                   pdf_id="pdf-1", page_index=1, page_number=2, markdown="页面内容")
    entries = digest.documents_in_range([page], CUSTOM)
    assert [e["document_id"] for e in entries] == ["doc-pdf-p2"]
    assert entries[0]["title"] == "PDF 第 2 页"


# ---------------------------------------------------------------------------
# material assembly + fingerprint
# ---------------------------------------------------------------------------


def test_assemble_material_is_deterministic_and_fingerprints_content():
    records = [
        _record("a", "A", document_time="2026-09-02", markdown="alpha 内容",
                version_id="v1", tags=["重点"], topics=["数学"]),
        _record("b", "B", document_time="2026-09-03", markdown="beta 内容", version_id="v1"),
    ]
    first = digest.assemble_material(records, CUSTOM)
    second = digest.assemble_material(list(reversed(records)), CUSTOM)
    assert first["fingerprint"] == second["fingerprint"]
    assert [d["document_id"] for d in first["documents"]] == ["a", "b"]
    assert "<document id=\"a\" date=\"2026-09-02\">" in first["prompt"]
    assert "标签：重点" in first["prompt"]

    changed = [
        records[0],
        _record("b", "B", document_time="2026-09-03", markdown="beta 改了", version_id="v1"),
    ]
    assert digest.assemble_material(changed, CUSTOM)["fingerprint"] != first["fingerprint"]

    new_version = [
        records[0],
        _record("b", "B", document_time="2026-09-03", markdown="beta 内容", version_id="v2"),
    ]
    assert digest.assemble_material(new_version, CUSTOM)["fingerprint"] != first["fingerprint"]


def test_long_content_is_truncated_at_the_explicit_limit():
    long_text = "字" * (digest.MAX_DOC_CHARS + 500)
    material = digest.assemble_material(
        [_record("a", "A", document_time="2026-09-02", markdown=long_text)], CUSTOM)
    doc = material["documents"][0]
    assert doc["truncated"] is True
    assert len(doc["content"]) < len(long_text)
    assert "已截断" in doc["content"]


def test_render_digest_markdown_keeps_skeleton_and_appends_linked_sources():
    docs = [
        {"document_id": "doc-a", "title": "A"},
        {"document_id": "doc b", "title": "B, 标题"},
    ]
    sections = [
        {"key": key, "title": title, "markdown": f"{title} 正文"}
        for key, title in digest.SECTION_DEFS
    ]
    markdown = digest.render_digest_markdown(CUSTOM, sections, docs)
    assert markdown.startswith("# 本周小结")
    # the four-section skeleton is present in fixed order
    positions = [markdown.index(f"## {title}") for _, title in digest.SECTION_DEFS]
    assert positions == sorted(positions)
    assert "## 来源" in markdown
    assert "[A](#doc/doc-a)（`doc-a`）" in markdown
    assert "[B, 标题](#doc/doc%20b)（`doc b`）" in markdown


# ---------------------------------------------------------------------------
# AC2 — fingerprint cache + force
# ---------------------------------------------------------------------------


def test_same_fingerprint_reuses_cache_with_zero_new_calls(tmp_path):
    planner = RecordingPlanner()
    records = [
        _record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1"),
        _record("b", "B", document_time="2026-09-03", markdown="beta", version_id="v1"),
    ]
    first = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    assert first["status"] == "ok" and first["generated"] is True and first["cached"] is False
    assert first["llm_calls"] == 1 and len(planner.calls) == 1

    second = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    assert second["cached"] is True and second["generated"] is False and second["llm_calls"] == 0
    assert len(planner.calls) == 1           # budget discipline: no new call
    assert second["digest"]["digest_id"] == first["digest"]["digest_id"]
    assert second["markdown"] == first["markdown"]
    assert len(list((tmp_path / "digests").glob("*.meta.json"))) == 1


def test_force_regenerates_and_writes_a_new_version(tmp_path):
    planner = RecordingPlanner()
    records = [_record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1")]
    first = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    forced = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner, force=True)
    assert forced["generated"] is True and forced["cached"] is False
    assert len(planner.calls) == 2
    assert forced["digest"]["digest_id"] != first["digest"]["digest_id"]
    assert forced["fingerprint"] == first["fingerprint"]
    assert len(digest.list_digests(tmp_path)) == 2


def test_changed_content_misses_the_cache(tmp_path):
    planner = RecordingPlanner()
    digest.generate_digest(
        [_record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1")],
        CUSTOM, storage_dir=tmp_path, planner=planner)
    digest.generate_digest(
        [_record("a", "A", document_time="2026-09-02", markdown="alpha v2", version_id="v2")],
        CUSTOM, storage_dir=tmp_path, planner=planner)
    assert len(planner.calls) == 2


def test_empty_range_generates_nothing_and_calls_no_model(tmp_path):
    planner = RecordingPlanner()
    result = digest.generate_digest(
        [_record("x", "X", document_time="2020-01-01")],
        CUSTOM, storage_dir=tmp_path, planner=planner)
    assert result["status"] == "empty" and result["generated"] is False
    assert result["message"] == digest.EMPTY_MESSAGE == "该范围内没有材料"
    assert planner.calls == []
    assert digest.list_digests(tmp_path) == []


# ---------------------------------------------------------------------------
# AC3 — text channel, purpose session isolation, telemetry
# ---------------------------------------------------------------------------


def test_digest_purpose_session_is_isolated_and_env_overridable(monkeypatch):
    monkeypatch.delenv("GRAPH2NOTE_SESSION_DIGEST", raising=False)
    monkeypatch.delenv("GRAPH2NOTE_DIGEST_SESSION", raising=False)
    assert digest.digest_session() == "graph2note-digest-01"
    assert digest.digest_session() not in {
        notes_llm.DEFAULT_SESSION, "graph2note-parse-01", "graph2note-eval-01",
        "graph2note-verify-01", "graph2note-routeb-01", "graph2note-diagram-01",
    }
    monkeypatch.setenv("GRAPH2NOTE_SESSION_DIGEST", "graph2note-digest-env")
    assert digest.digest_session() == "graph2note-digest-env"


def test_generation_records_usage_in_meta_and_metadata(tmp_path):
    planner = RecordingPlanner(usage={
        "prompt_tokens": 321, "completion_tokens": 123, "total_tokens": 444,
    })
    records = [_record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1")]
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    meta = result["digest"]
    assert meta["usage"] == {"prompt_tokens": 321, "completion_tokens": 123, "total_tokens": 444}
    assert meta["model"] == "stub-text" and meta["provider"] == "stub"
    assert meta["session"] == "graph2note-digest-01"
    assert meta["llm_calls"] == 1
    # the planner saw the deterministic material prompt, not a re-built one
    prompt, model = planner.calls[0]
    assert "<document id=\"a\" date=\"2026-09-02\">" in prompt
    assert "alpha" in prompt


def test_stats_merge_digest_tokens_without_inflating_document_counts():
    records = [_record("doc-a", "A", document_time="2026-09-02", markdown="x")]
    records[0]["created_at"] = "2026-09-02T10:00:00"
    records[0]["versions"] = [{"version_id": "v1", "created_at": "2026-09-02T10:00:00",
                               "model": "fixture", "timing_json": {}}]
    digests = [{
        "digest_id": "dg-1", "created_at": "2026-09-02T12:00:00",
        "model": "stub-text", "provider": "stub", "elapsed": 1.5,
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }]
    plain = build_stats(records, now=datetime(2026, 9, 10, 12, 0))
    merged = build_stats(records, now=datetime(2026, 9, 10, 12, 0), digest_records=digests)

    assert plain["periods"] == merged["periods"]
    assert plain["new_documents_trend"] == merged["new_documents_trend"]
    assert plain["quality"] == merged["quality"]
    digest_models = [m for m in merged["model_usage"] if m["model"] == "stub-text"]
    assert digest_models and digest_models[0]["total_tokens"] == 150
    assert all(m["model"] != "stub-text" for m in plain["model_usage"])
    merged_tokens = sum(b["total_tokens"] for b in merged["token_usage_by_day"])
    plain_tokens = sum(b["total_tokens"] for b in plain["token_usage_by_day"])
    assert merged_tokens == plain_tokens + 150


def test_normalize_usage_derives_total_and_reads_completion_details():
    assert digest.normalize_usage({"prompt_tokens": 5, "completion_tokens": 7})["total_tokens"] == 12
    out = digest.normalize_usage({"completion_tokens_details": {"reasoning_tokens": 9}})
    assert out == {"reasoning_tokens": 9}


def test_digest_live_seam_omits_temperature_and_raises_max_tokens(tmp_path, monkeypatch):
    """The live seam must not send temperature=0 (kimi-k3 rejects it) and must
    request the digest output budget, while classify keeps the 4096 default."""
    captured: dict = {}

    def fake_gateway(prompt, model, **kwargs):
        captured["model"] = model
        captured.update(kwargs)
        return {"text": "# 小结", "usage": {"total_tokens": 12}}

    monkeypatch.setattr(notes_llm, "_gateway_text_usage", fake_gateway)
    records = [_record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1")]
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path)  # planner=None -> live seam
    assert result["status"] == "ok"
    assert captured["temperature"] is None
    assert captured["max_tokens"] == digest.MAX_SUMMARY_TOKENS
    assert captured["session"] == "graph2note-digest-01"


def test_gateway_text_usage_payload_temperature_and_max_tokens(monkeypatch):
    import eval.gateway as gateway

    captured: dict = {}

    def fake_post(payload, **kwargs):
        captured.clear()
        captured.update(payload)
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    monkeypatch.setattr(gateway, "post_gateway", fake_post)
    monkeypatch.setattr(gateway, "load_api_key", lambda provider=None: "test-key")
    monkeypatch.setattr(notes_llm, "resolve_channel",
                        lambda purpose: {"provider": "kimi", "model": "kimi-k3"})

    notes_llm._gateway_text_usage("hi", temperature=None, max_tokens=8192)
    assert "temperature" not in captured
    assert captured["max_tokens"] == 8192

    notes_llm._gateway_text_usage("hi")
    assert captured["temperature"] == 0
    assert captured["max_tokens"] == 4096


def test_planner_failure_is_an_error_status_not_a_crash(tmp_path):
    def boom(prompt, model):
        raise RuntimeError("gateway down")

    result = digest.generate_digest(
        [_record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1")],
        CUSTOM, storage_dir=tmp_path, planner=boom)
    assert result["status"] == "error" and "gateway down" in result["message"]
    assert result["digest"] is None
    assert digest.list_digests(tmp_path) == []


# ---------------------------------------------------------------------------
# AC4 — persistence + restart
# ---------------------------------------------------------------------------


def test_digest_is_persisted_with_meta_and_readable_after_restart(tmp_path):
    planner = RecordingPlanner()
    records = [
        _record("a", "A", document_time="2026-09-02", markdown="alpha", version_id="v1",
                tags=["重点"], topics=["数学"]),
        _record("b", "B", document_time="2026-09-03", markdown="beta", version_id="v2"),
    ]
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    digest_id = result["digest"]["digest_id"]

    # emulate a process restart: only the storage dir is carried over
    metas = digest.list_digests(tmp_path)
    assert [m["digest_id"] for m in metas] == [digest_id]
    stored = digest.load_digest(tmp_path, digest_id)
    meta = stored["meta"]
    assert meta["range"]["from"] == "2026-09-01" and meta["range"]["to"] == "2026-09-07"
    assert meta["fingerprint"] == result["fingerprint"]
    assert meta["document_ids"] == ["a", "b"]
    assert meta["model"] == "stub-text"
    assert meta["usage"]["total_tokens"] == 200
    assert stored["markdown"].startswith("# 本周小结")
    assert "## 来源" in stored["markdown"] and "`a`" in stored["markdown"]
    assert digest.load_digest(tmp_path, "missing") is None


def test_list_digests_ignores_corrupt_meta_files(tmp_path):
    planner = RecordingPlanner()
    digest.generate_digest(
        [_record("a", "A", document_time="2026-09-02", markdown="x", version_id="v1")],
        CUSTOM, storage_dir=tmp_path, planner=planner)
    (tmp_path / "digests" / "broken.meta.json").write_text("{not json", encoding="utf-8")
    assert len(digest.list_digests(tmp_path)) == 1


# ---------------------------------------------------------------------------
# AC5/AC6 — recorded-golden full chain + API contract + UI DOM
# ---------------------------------------------------------------------------


def _digest_app(tmp_path, planner):
    storage = tmp_path / "storage"
    store = FileDocumentStore(storage)
    _seed(store, "doc-a", "信道编码推导",
          markdown="# 信道编码\n香农编码步骤。",
          metadata={"document_time": _slot("2026-09-02", "manual")})
    _seed(store, "doc-b", "实验备忘",
          markdown="# 备忘\n本周实验记录。",
          metadata={"document_time": _slot("2026-09-05", "inferred")})
    _seed(store, "doc-old", "旧材料",
          markdown="# 旧\n不在范围内。",
          metadata={"document_time": _slot("2020-01-01", "manual")})
    app = create_app(document_store=store, storage_dir=storage, digest_planner=planner)
    return store, storage, TestClient(app)


def test_full_chain_offline_golden_plan_to_api_and_ui(tmp_path):
    planner = RecordingPlanner()
    store, storage, client = _digest_app(tmp_path, planner)

    created = client.post("/api/digests", json={"range": "custom", "from": "2026-09-01", "to": "2026-09-07"})
    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "ok" and payload["generated"] is True
    assert [d["document_id"] for d in payload["documents"]] == ["doc-a", "doc-b"]
    assert "content" not in payload["documents"][0]
    assert payload["markdown"].startswith("# 本周小结")
    for _key, title in digest.SECTION_DEFS:
        assert f"## {title}" in payload["markdown"]
    assert "## 来源" in payload["markdown"]
    assert [s["key"] for s in payload["sections"]] == [k for k, _ in digest.SECTION_DEFS]
    digest_id = payload["digest"]["digest_id"]
    assert len(planner.calls) == 1

    # API contract: list + one
    listing = client.get("/api/digests")
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["digests"][0]["document_ids"] == ["doc-a", "doc-b"]
    one = client.get(f"/api/digests/{digest_id}")
    assert one.status_code == 200
    assert one.json()["markdown"] == payload["markdown"]
    assert client.get("/api/digests/nope").status_code == 404

    # fingerprint cache over the API: second identical POST makes no new call
    again = client.post("/api/digests", json={"range": "custom", "from": "2026-09-01", "to": "2026-09-07"})
    assert again.status_code == 200 and again.json()["cached"] is True
    assert len(planner.calls) == 1

    # digest tokens reach the telemetry Dashboard
    stats = client.get("/api/stats").json()
    digests_model = [m for m in stats["model_usage"] if m["model"] == "stub-text"]
    assert digests_model and digests_model[0]["total_tokens"] == 200

    # Web block DOM contract
    html = client.get("/").text
    for node in ("digest-panel", "digest-range", "digest-from", "digest-to",
                 "digest-generate", "digest-history", "digest-viewer", "digest-viewer-content"):
        assert f'id="{node}"' in html
    assert "每周小结" in html
    # U1 split app.js into ES modules: the digest block lives in the dashboard
    # view module and reuses the document view's shared Markdown renderer.
    javascript = client.get("/static/js/views/dashboard.js").text
    assert "/api/digests" in javascript
    assert "renderDigestPanel" in javascript
    assert "renderMarkdownInto" in javascript          # reuses the Markdown renderer
    assert "该范围内没有材料" in javascript        # explicit empty state
    assert "renderMarkdownInto" in client.get("/static/js/views/document.js").text
    assert "强制重新生成" in html


def test_api_digest_meta_exposes_sections_for_w2(tmp_path):
    """W1 -> W2 contract: meta.json carries sections with per-section provenance."""
    planner = RecordingPlanner(reply=SECTIONS_GOLDEN)
    _store, _storage, client = _digest_app(tmp_path, planner)
    created = client.post("/api/digests", json={
        "range": "custom", "from": "2026-09-01", "to": "2026-09-07"})
    assert created.status_code == 200
    payload = created.json()
    meta = payload["digest"]
    expected_keys = ["overview", "topics", "highlights", "pending"]
    assert [section["key"] for section in meta["sections"]] == expected_keys
    assert [section["key"] for section in payload["sections"]] == expected_keys
    assert meta["sections"][0]["source_document_ids"] == ["doc-a", "doc-b"]
    assert meta["sections"][2]["source_document_ids"] == ["doc-a", "doc-b"]
    assert meta["llm_mode"] == "json"
    assert meta["stats"]["document_count"] == 2

    # the same structure is served after a reload (W2 consumes the meta)
    one = client.get(f"/api/digests/{meta['digest_id']}")
    assert one.status_code == 200
    assert one.json()["meta"]["sections"] == meta["sections"]
    assert one.json()["markdown"] == payload["markdown"]
    assert "## 主题脉络" in one.json()["markdown"]


def test_api_serves_legacy_digest_meta_without_sections(tmp_path):
    """A pre-W1 meta.json (no ``sections``) must still list and load."""
    planner = RecordingPlanner()
    _store, storage, client = _digest_app(tmp_path, planner)
    directory = Path(storage) / "digests"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "dg-legacy-1.meta.json").write_text(json.dumps({
        "schema_version": 1, "generator": "digest-1", "digest_id": "dg-legacy-1",
        "created_at": "2026-09-08T10:00:00", "document_count": 1,
        "document_ids": ["doc-a"], "fingerprint": "legacy", "usage": {},
    }, ensure_ascii=False), encoding="utf-8")
    (directory / "dg-legacy-1.md").write_text("# 本周小结\n\n旧格式。", encoding="utf-8")

    listing = client.get("/api/digests")
    assert listing.status_code == 200
    assert [m["digest_id"] for m in listing.json()["digests"]] == ["dg-legacy-1"]

    one = client.get("/api/digests/dg-legacy-1")
    assert one.status_code == 200
    assert "sections" not in one.json()["meta"]
    assert one.json()["markdown"].startswith("# 本周小结")
    assert digest.meta_sections(one.json()["meta"]) == []


def test_api_empty_range_returns_explicit_empty_state(tmp_path):
    planner = RecordingPlanner()
    _store, _storage, client = _digest_app(tmp_path, planner)
    response = client.post("/api/digests", json={
        "range": "custom", "from": "2019-01-01", "to": "2019-01-07"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "empty"
    assert payload["message"] == "该范围内没有材料"
    assert payload["documents"] == [] and payload["digest"] is None
    assert planner.calls == []
    assert client.get("/api/digests").json()["total"] == 0


def test_api_rejects_bad_range_and_reports_model_errors(tmp_path):
    planner = RecordingPlanner()
    _store, _storage, client = _digest_app(tmp_path, planner)
    bad = client.post("/api/digests", json={"range": "custom", "from": "2026-09-07", "to": "2026-09-01"})
    assert bad.status_code == 422

    def boom(prompt, model):
        raise RuntimeError("model down")

    storage = tmp_path / "storage2"
    store = FileDocumentStore(storage)
    _seed(store, "doc-a", "A", markdown="x",
          metadata={"document_time": _slot("2026-09-02", "manual")})
    client2 = TestClient(create_app(document_store=store, storage_dir=storage, digest_planner=boom))
    failed = client2.post("/api/digests", json={"range": "custom", "from": "2026-09-01", "to": "2026-09-07"})
    assert failed.status_code == 502
    assert "model down" in failed.json()["detail"]


def test_digest_panel_is_scoped_to_dashboard_zone(tmp_path):
    _store, _storage, client = _digest_app(tmp_path, RecordingPlanner())
    html = client.get("/").text
    dashboard_start = html.index('id="dashboard-zone"')
    digest_start = html.index('id="digest-panel"')
    upload_start = html.index('id="upload-zone"')
    assert dashboard_start < digest_start < upload_start


# ---------------------------------------------------------------------------
# CLI (optional entry point) — offline paths only
# ---------------------------------------------------------------------------


def test_cli_digest_empty_range_is_offline(tmp_path, capsys):
    code = cli.main(["digest", "--week", "this", "--storage", str(tmp_path)])
    assert code == 0
    assert "该范围内没有材料" in capsys.readouterr().out


def test_cli_digest_rejects_invalid_custom_range(tmp_path, capsys):
    code = cli.main(["digest", "--from", "2026-09-07", "--to", "2026-09-01",
                     "--storage", str(tmp_path)])
    assert code == 2
    assert "起始日期" in capsys.readouterr().err


def test_cli_digest_wires_range_and_force(monkeypatch, tmp_path, capsys):
    captured = {}

    def fake_generate(records, range_spec, **kwargs):
        captured["range"] = range_spec
        captured["force"] = kwargs.get("force")
        return {"status": "empty", "message": "该范围内没有材料", "range": range_spec,
                "documents": [], "cached": False, "generated": False,
                "fingerprint": "x", "digest": None, "markdown": "", "llm_calls": 0}

    monkeypatch.setattr(digest, "generate_digest", fake_generate)
    code = cli.main(["digest", "--week", "last", "--force", "--storage", str(tmp_path)])
    assert code == 0
    assert captured["range"]["kind"] == "last_week"
    assert captured["force"] is True
    assert "该范围内没有材料" in capsys.readouterr().out


def test_cli_digest_json_emits_result(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(digest, "resolve_range", lambda *a, **k: CUSTOM)
    monkeypatch.setattr(digest, "generate_digest", lambda *a, **k: {
        "status": "empty", "message": "该范围内没有材料", "range": CUSTOM,
        "documents": [], "cached": False, "generated": False, "fingerprint": "x",
        "digest": None, "markdown": "", "llm_calls": 0,
    })
    code = cli.main(["digest", "--from", "2026-09-01", "--to", "2026-09-07",
                     "--json", "--storage", str(tmp_path)])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "empty"


# ---------------------------------------------------------------------------
# taxonomy sanity for the date helper
# ---------------------------------------------------------------------------


def test_week_boundaries_are_monday_to_sunday():
    monday = date(2026, 9, 7)
    assert monday.weekday() == 0
    resolved = digest.resolve_range("this_week", today=monday)
    assert (resolved["from"], resolved["to"]) == ("2026-09-07", "2026-09-13")
    # a later day in the same week resolves to the same stable range
    later = digest.resolve_range("this_week", today=monday + timedelta(days=3))
    assert later == resolved
