"""Offline contracts for issue 01 — research weekly report (科研周报).

Covers the issue's acceptance criteria without any live model:

- template registry: research template (stable id/version) + legacy four-section
  summary template;
- research sections 概览 / 进展 / 问题与求助, optional 专题 modules that can be
  enabled / disabled / reordered, evidence-free modules omitted, empty 问题与求助
  kept as title only;
- sources / statistics / material budget / model failure visible in meta + API;
- fingerprint cache: identical input reuses with zero model calls, template and
  module changes never reuse a stale result, empty material never calls the model;
- persistence + restart, and the legacy digest path left byte-compatible.

The text model is always an injected recording planner, so these tests never
touch the network.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph2note import digest, research_report
from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app

CUSTOM = {"kind": "custom", "from": "2026-09-01", "to": "2026-09-07",
          "label": "自定义（2026-09-01 ~ 2026-09-07）"}

REPLY = json.dumps({
    "sections": {
        "overview": {"markdown": "主线：信道编码推导。",
                     "source_document_ids": ["doc-a"]},
        "progress": {"markdown": "（一）信道编码\n- 已知：完成香农编码步骤",
                     "source_document_ids": ["doc-a", "doc-b"]},
        "issues": {"markdown": "", "source_document_ids": []},
        "experiments": {"markdown": "", "source_document_ids": []},
        "process": {"markdown": "记录过程与踩坑。", "source_document_ids": ["doc-b"]},
    }
}, ensure_ascii=False)


def _slot(value=None, source="none"):
    return {"value": value, "source": source, "confidence": None, "evidence": None}


def _record(document_id, title, *, document_time=None, markdown="", tags=None,
            topics=None, version_id=None, created_at=None):
    record = {
        "document_id": document_id,
        "title": title,
        "metadata": {
            "document_time": _slot(document_time, "manual" if document_time else "none"),
            "capture_time": _slot(None, "none"),
            "import_time": _slot(None, "none"),
        },
        "current_markdown": markdown,
        "tags": tags or [],
        "topics": topics or [],
    }
    if version_id:
        record["latest_version_id"] = version_id
    if created_at:
        record["created_at"] = created_at
    return record


def _records():
    return [
        _record("doc-a", "信道编码推导", document_time="2026-09-02",
                markdown="香农编码步骤", topics=["数学"], version_id="v1"),
        _record("doc-b", "实验备忘", document_time="2026-09-05",
                markdown="本周实验记录", tags=["重点"], version_id="v1"),
    ]


class RecordingPlanner:
    def __init__(self, reply=REPLY, *, usage=None, model="stub-text", provider="stub"):
        self.reply = reply
        self.usage = usage if usage is not None else {
            "prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200,
        }
        self.model = model
        self.provider = provider
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        return {"text": self.reply, "usage": self.usage, "model": self.model,
                "provider": self.provider}


def _seed(store: FileDocumentStore, document_id, title, *, markdown, metadata=None):
    store.save_document(
        document_id=document_id, title=title, source_job_id=f"job-{document_id}",
        model="fixture", markdown=markdown, ir_json=json.dumps({"blocks": []}),
        original_path="", original_ext=".jpg", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={}, metadata=metadata,
    )


def _app(tmp_path, planner):
    storage = tmp_path / "storage"
    store = FileDocumentStore(storage)
    _seed(store, "doc-a", "信道编码推导", markdown="# 信道编码\n香农编码步骤。",
          metadata={"document_time": _slot("2026-09-02", "manual")})
    _seed(store, "doc-b", "实验备忘", markdown="# 备忘\n本周实验记录。",
          metadata={"document_time": _slot("2026-09-05", "inferred")})
    _seed(store, "doc-old", "旧材料", markdown="# 旧\n不在范围内。",
          metadata={"document_time": _slot("2020-01-01", "manual")})
    return store, storage, TestClient(create_app(document_store=store,
                                                 storage_dir=storage,
                                                 digest_planner=planner))


# ---------------------------------------------------------------------------
# AC1 — template + sections + optional modules
# ---------------------------------------------------------------------------


def test_templates_payload_exposes_research_and_legacy():
    payload = research_report.templates_payload()
    by_id = {t["id"]: t for t in payload["templates"]}
    assert set(by_id) == {"research_weekly", "weekly_summary"}
    research = by_id["research_weekly"]
    assert research["version"] == research_report.TEMPLATE_VERSION
    assert research["supports_modules"] is True
    core = [s["key"] for s in research["sections"]][:3]
    assert core == ["overview", "progress", "issues"]
    legacy = by_id["weekly_summary"]
    assert legacy["legacy"] is True
    assert [s["key"] for s in legacy["sections"]] == [k for k, _ in digest.SECTION_DEFS]
    # every catalog module is advertised and disabled by default
    catalog_keys = [m["key"] for m in payload["modules"]]
    assert catalog_keys == [m["key"] for m in research_report.MODULE_CATALOG]
    assert all(m["enabled"] is False for m in research_report.DEFAULT_MODULES)


def test_normalize_modules_defaults_disabled_and_preserves_order():
    default = research_report.normalize_modules(None)
    assert [m["key"] for m in default] == [m["key"] for m in research_report.MODULE_CATALOG]
    assert not any(m["enabled"] for m in default)

    configured = research_report.normalize_modules([
        {"key": "process", "enabled": True},
        {"key": "experiments", "enabled": False},
        {"key": "cost", "title": "Coding 成本控制", "enabled": True},
    ])
    assert [m["key"] for m in configured] == ["process", "experiments", "cost"]
    assert configured[0]["title"] == "过程记录"           # catalog title
    assert configured[2]["title"] == "Coding 成本控制"     # custom title


def test_normalize_modules_rejects_malformed_and_core_keys():
    with pytest.raises(research_report.ModuleError):
        research_report.normalize_modules({"key": "experiments"})
    with pytest.raises(research_report.ModuleError):
        research_report.normalize_modules([{"title": "no key"}])
    with pytest.raises(research_report.ModuleError):
        research_report.normalize_modules([{"key": "issues"}])
    with pytest.raises(research_report.ModuleError):
        research_report.normalize_modules([{"key": "bad key!"}])


def test_prompt_asks_only_enabled_modules_and_carries_evidence_rules():
    modules = research_report.normalize_modules([
        {"key": "experiments", "enabled": True},
        {"key": "process", "enabled": False},
    ])
    material = digest.assemble_material(_records(), CUSTOM)
    prompt = research_report.build_report_prompt(
        CUSTOM, material["documents"], stats=material["stats"], modules=modules)
    assert "已知 / 推论 / 猜想 / 待验证 / 计划" in prompt
    assert "experiments" in prompt and "没有证据就留空" in prompt
    assert '"process"' not in prompt
    assert '<document id="doc-a"' in prompt
    assert "不编造" in prompt


def test_build_sections_keeps_empty_issues_and_drops_evidence_free_module():
    material = digest.assemble_material(_records(), CUSTOM)
    modules = research_report.normalize_modules([
        {"key": "experiments", "enabled": True},
        {"key": "process", "enabled": True},
        {"key": "method", "enabled": False},
    ])
    bodies = {
        "overview": {"markdown": "主线。", "source_document_ids": ["doc-a"]},
        "progress": {"markdown": "进展。", "source_document_ids": ["doc-a"]},
        "issues": {"markdown": "", "source_document_ids": []},
        "experiments": {"markdown": "", "source_document_ids": []},
        "process": {"markdown": "过程。", "source_document_ids": ["doc-b"]},
    }
    modes = {k: "model" for k in bodies}
    sections = research_report.build_report_sections(material, bodies, modes, modules)
    keys = [s["key"] for s in sections]
    # core → enabled modules with content (in order) → appendix
    assert keys == ["overview", "progress", "issues", "process", "appendix"]
    issues = next(s for s in sections if s["key"] == "issues")
    assert issues["markdown"] == ""            # 空求助仅标题
    # 无依据实验不出现: an enabled-but-empty 实验结果 module is omitted
    assert "experiments" not in keys
    appendix = sections[-1]
    assert appendix["generated_by"] == "deterministic"
    assert appendix["source_document_ids"] == ["doc-a", "doc-b"]


def test_render_markdown_lists_sections_and_reporter_without_submit_label():
    sections = [
        {"key": "overview", "title": "本周概览", "markdown": "主线。",
         "source_document_ids": []},
        {"key": "issues", "title": "问题与求助", "markdown": "",
         "source_document_ids": []},
    ]
    markdown = research_report.render_report_markdown(
        CUSTOM, sections, reporter="张三", report_date="2026-09-13")
    assert markdown.startswith("# 科研周报")
    assert "时间范围：自定义（2026-09-01 ~ 2026-09-07）" in markdown
    assert "汇报人：张三" in markdown and "2026-09-13" in markdown
    assert "提交日期" not in markdown
    assert "## 本周概览" in markdown and "## 问题与求助" in markdown


# ---------------------------------------------------------------------------
# AC2/AC3 — cache, module changes, empty material, failure
# ---------------------------------------------------------------------------


def test_same_input_reuses_cache_with_zero_calls(tmp_path):
    planner = RecordingPlanner()
    modules = [{"key": "experiments", "enabled": True}]
    first = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner, modules=modules)
    assert first["status"] == "ok" and first["generated"] is True and first["llm_calls"] == 1
    second = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner, modules=modules)
    assert second["cached"] is True and second["generated"] is False and second["llm_calls"] == 0
    assert len(planner.calls) == 1
    assert second["report"]["report_id"] == first["report"]["report_id"]


def test_reporter_and_date_changes_do_not_invalidate_cache(tmp_path):
    planner = RecordingPlanner()
    research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner,
        reporter="张三", report_date="2026-09-13")
    again = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner,
        reporter="李四", report_date="2026-09-14")
    assert again["cached"] is True and len(planner.calls) == 1


def test_module_change_never_reuses_a_stale_result(tmp_path):
    planner = RecordingPlanner()
    research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner,
        modules=[{"key": "experiments", "enabled": False}])
    changed = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner,
        modules=[{"key": "experiments", "enabled": True}])
    assert changed["cached"] is False and changed["llm_calls"] == 1
    assert len(planner.calls) == 2


def test_template_version_change_never_reuses_a_stale_result(tmp_path, monkeypatch):
    planner = RecordingPlanner()
    research_report.generate_report(_records(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert len(planner.calls) == 1
    monkeypatch.setattr(research_report, "TEMPLATE_VERSION", "2")
    bumped = research_report.generate_report(_records(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert bumped["cached"] is False and bumped["llm_calls"] == 1
    assert bumped["report"]["template_version"] == "2"
    assert len(planner.calls) == 2


def test_research_fingerprint_differs_from_legacy_digest_and_never_reuses_it(tmp_path):
    planner = RecordingPlanner()
    digest.generate_digest(_records(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert len(planner.calls) == 1
    # a research report over the same range/material must not reuse the digest
    result = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert result["cached"] is False and result["llm_calls"] == 1
    assert len(planner.calls) == 2
    material = digest.assemble_material(_records(), CUSTOM)
    assert research_report.compute_report_fingerprint(CUSTOM, material, []) != material["fingerprint"]


def test_empty_material_calls_no_model_and_persists_nothing(tmp_path):
    planner = RecordingPlanner()
    empty = [_record("x", "X", document_time="2020-01-01", markdown="z")]
    result = research_report.generate_report(empty, CUSTOM, storage_dir=tmp_path, planner=planner)
    assert result["status"] == "empty" and result["message"] == research_report.EMPTY_MESSAGE
    assert result["report"] is None and planner.calls == []
    assert research_report.list_reports(tmp_path) == []


def test_model_failure_is_a_status_and_persists_nothing(tmp_path):
    def boom(prompt, model):
        raise RuntimeError("gateway down")

    result = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=boom)
    assert result["status"] == "error" and "gateway down" in result["message"]
    assert result["report"] is None
    assert research_report.list_reports(tmp_path) == []


# ---------------------------------------------------------------------------
# AC2/AC4 — persistence, restart, source/stats/budget visibility
# ---------------------------------------------------------------------------


def test_report_persists_meta_sections_sources_stats_budget(tmp_path):
    planner = RecordingPlanner()
    modules = [{"key": "process", "enabled": True}]
    result = research_report.generate_report(
        _records(), CUSTOM, storage_dir=tmp_path, planner=planner, modules=modules,
        reporter="张三", report_date="2026-09-13")
    report_id = result["report"]["report_id"]

    metas = research_report.list_reports(tmp_path)
    assert [m["report_id"] for m in metas] == [report_id]
    stored = research_report.load_report(tmp_path, report_id)
    meta = stored["meta"]
    assert meta["template_id"] == research_report.TEMPLATE_ID
    assert meta["template_version"] == research_report.TEMPLATE_VERSION
    assert meta["schema_version"] == research_report.SCHEMA_VERSION
    assert meta["prompt_version"] == research_report.PROMPT_VERSION
    assert meta["reporter"] == "张三" and meta["report_date"] == "2026-09-13"
    assert meta["document_ids"] == ["doc-a", "doc-b"]
    assert meta["documents"][0]["document_id"] == "doc-a"          # 来源可见
    assert meta["stats"]["document_count"] == 2                    # 统计可见
    assert meta["budget"]["max_docs"] >= 2                         # 预算可见
    assert [s["key"] for s in meta["sections"]] == ["overview", "progress",
                                                    "issues", "process", "appendix"]
    assert meta["sections"][0]["source_document_ids"] == ["doc-a"]
    assert stored["markdown"].startswith("# 科研周报")
    assert "## 附录：来源材料" in stored["markdown"]
    assert research_report.load_report(tmp_path, "missing") is None


def test_list_reports_ignores_corrupt_meta(tmp_path):
    planner = RecordingPlanner()
    research_report.generate_report(_records(), CUSTOM, storage_dir=tmp_path, planner=planner)
    (tmp_path / "reports" / "broken.meta.json").write_text("{not json", encoding="utf-8")
    assert len(research_report.list_reports(tmp_path)) == 1


# ---------------------------------------------------------------------------
# AC4 — API generate → restart read
# ---------------------------------------------------------------------------


def test_api_full_chain_generate_restart_read(tmp_path):
    planner = RecordingPlanner()
    store, storage, client = _app(tmp_path, planner)

    templates = client.get("/api/report-templates")
    assert templates.status_code == 200
    assert {t["id"] for t in templates.json()["templates"]} == {
        "research_weekly", "weekly_summary"}

    created = client.post("/api/reports", json={
        "range": "custom", "from": "2026-09-01", "to": "2026-09-07",
        "modules": [{"key": "process", "enabled": True}],
        "reporter": "张三", "report_date": "2026-09-13",
    })
    assert created.status_code == 200
    payload = created.json()
    assert payload["status"] == "ok" and payload["generated"] is True
    assert [d["document_id"] for d in payload["documents"]] == ["doc-a", "doc-b"]
    assert "content" not in payload["documents"][0]
    assert [s["key"] for s in payload["sections"]] == [
        "overview", "progress", "issues", "process", "appendix"]
    report_id = payload["report"]["report_id"]
    assert len(planner.calls) == 1

    # restart: a brand new app over the same storage still lists and loads it
    restarted = TestClient(create_app(document_store=store, storage_dir=storage,
                                      digest_planner=planner))
    listing = restarted.get("/api/reports")
    assert listing.status_code == 200 and listing.json()["total"] == 1
    assert listing.json()["reports"][0]["report_id"] == report_id
    one = restarted.get(f"/api/reports/{report_id}")
    assert one.status_code == 200
    assert one.json()["markdown"] == payload["markdown"]
    assert one.json()["sections"] == payload["sections"]
    assert restarted.get("/api/reports/nope").status_code == 404

    # fingerprint cache over the API: identical POST makes no new call
    again = client.post("/api/reports", json={
        "range": "custom", "from": "2026-09-01", "to": "2026-09-07",
        "modules": [{"key": "process", "enabled": True}],
    })
    assert again.json()["cached"] is True and len(planner.calls) == 1


def test_api_rejects_bad_range_and_modules(tmp_path):
    _store, _storage, client = _app(tmp_path, RecordingPlanner())
    bad_range = client.post("/api/reports", json={
        "range": "custom", "from": "2026-09-07", "to": "2026-09-01"})
    assert bad_range.status_code == 422
    bad_module = client.post("/api/reports", json={
        "range": "custom", "from": "2026-09-01", "to": "2026-09-07",
        "modules": [{"key": "issues"}]})
    assert bad_module.status_code == 422


def test_api_reports_model_failure_as_502(tmp_path):
    def boom(prompt, model):
        raise RuntimeError("model down")

    storage = tmp_path / "storage2"
    store = FileDocumentStore(storage)
    _seed(store, "doc-a", "A", markdown="x",
          metadata={"document_time": _slot("2026-09-02", "manual")})
    client = TestClient(create_app(document_store=store, storage_dir=storage,
                                   digest_planner=boom))
    failed = client.post("/api/reports", json={
        "range": "custom", "from": "2026-09-01", "to": "2026-09-07"})
    assert failed.status_code == 502
    assert "model down" in failed.json()["detail"]
    assert client.get("/api/reports").json()["total"] == 0


def test_api_empty_range_is_explicit_and_offline(tmp_path):
    planner = RecordingPlanner()
    _store, _storage, client = _app(tmp_path, planner)
    response = client.post("/api/reports", json={
        "range": "custom", "from": "2019-01-01", "to": "2019-01-07"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "empty" and payload["report"] is None
    assert payload["message"] == research_report.EMPTY_MESSAGE
    assert planner.calls == []


def test_legacy_digest_endpoint_still_works_alongside_reports(tmp_path):
    """旧报告原样可读可导出: the legacy four-section path is untouched."""
    planner = RecordingPlanner()
    _store, _storage, client = _app(tmp_path, planner)
    created = client.post("/api/digests", json={
        "range": "custom", "from": "2026-09-01", "to": "2026-09-07"})
    assert created.status_code == 200
    payload = created.json()
    assert payload["markdown"].startswith("# 本周小结")
    digest_id = payload["digest"]["digest_id"]
    one = client.get(f"/api/digests/{digest_id}")
    assert one.status_code == 200
    assert [s["key"] for s in one.json()["meta"]["sections"]] == [
        k for k, _ in digest.SECTION_DEFS]
    # the research endpoints stay empty — the two stores never mix
    assert client.get("/api/reports").json()["total"] == 0
