"""W1 offline contracts: the four-section digest skeleton + section provenance.

Covers the issue acceptance criteria that are *structural*:

- the generated Markdown always carries the four deterministic sections in the
  fixed order (SPEC §3), whatever the model returns;
- 本周概览 numbers come from the pure :func:`graph2note.digest.compute_stats`
  (the model is never asked for them);
- every section carries ``source_document_ids`` that match what it actually
  cites (model-supplied ids are validated against the material, never invented);
- meta.json records ``sections`` and survives a reload, while a legacy meta
  without ``sections`` still loads (backward compatibility for W2);
- the section-level cache reuses an unchanged narrative section even when the
  whole-report fingerprint changed (bonus over the A2 whole-report cache).

The model is always an injected offline planner, so these tests never touch the
network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note import digest

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "weekly-digest.sections.json").read_text(encoding="utf-8")
)
GOLDEN_TEXT = json.dumps(GOLDEN, ensure_ascii=False)

CUSTOM = {"kind": "custom", "from": "2026-09-01", "to": "2026-09-07",
          "label": "自定义（2026-09-01 ~ 2026-09-07）"}

SECTION_KEYS = [key for key, _ in digest.SECTION_DEFS]
SECTION_TITLES = [title for _, title in digest.SECTION_DEFS]


def _slot(value=None, source="none"):
    return {"value": value, "source": source, "confidence": None, "evidence": None}


def _record(
    document_id: str,
    title: str,
    *,
    date: str = "2026-09-02",
    content: str = "内容",
    tags=None,
    topics=None,
    version_id="v1",
    created_at=None,
):
    record = {
        "document_id": document_id,
        "title": title,
        "metadata": {
            "document_time": _slot(date, "manual"),
            "capture_time": _slot(None, "exif"),
            "import_time": _slot(None, "system"),
        },
        "current_markdown": content,
        "tags": list(tags or []),
        "topics": list(topics or []),
        "latest_version_id": version_id,
    }
    if created_at:
        record["created_at"] = created_at
    return record


class SectionPlanner:
    """Offline recording planner that answers with the sectioned JSON golden."""

    def __init__(self, reply: str = GOLDEN_TEXT, *, model="stub-text", provider="stub"):
        self.reply = reply
        self.model = model
        self.provider = provider
        self.calls: list[tuple[str, str]] = []

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        return {
            "text": self.reply,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "model": self.model,
            "provider": self.provider,
        }


def _library():
    """One organized document (主题材料) + one Inbox document (待整理材料)."""
    return [
        _record("doc-a", "信道编码推导", date="2026-09-02",
                content="# 信道编码\n香农编码步骤。", topics=["编码"], tags=["重点"]),
        _record("doc-b", "实验备忘", date="2026-09-05", content="# 备忘\n本周实验记录。"),
        _record("doc-out", "上月材料", date="2026-08-02", content="# 旧\n不在范围内。"),
    ]


# ---------------------------------------------------------------------------
# skeleton
# ---------------------------------------------------------------------------


def test_section_definitions_are_fixed_titles_in_fixed_order():
    assert digest.SECTION_DEFS == (
        ("overview", "本周概览"),
        ("topics", "主题脉络"),
        ("highlights", "重点文档摘录"),
        ("pending", "待整理与连续体进展"),
    )
    assert digest.NARRATIVE_SECTIONS == ("topics", "pending")
    assert digest.SECTION_TITLES["overview"] == "本周概览"


def test_generated_markdown_carries_the_four_sections_in_order(tmp_path):
    planner = SectionPlanner()
    result = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)

    assert result["status"] == "ok" and result["llm_calls"] == 1
    markdown = result["markdown"]
    assert markdown.startswith("# 本周小结")
    positions = [markdown.index(f"## {title}") for title in SECTION_TITLES]
    assert positions == sorted(positions)
    assert markdown.index("## 来源") > positions[-1]
    # 主题脉络 sees the model prose; 待整理 keeps the deterministic statistics
    assert "概率降序排列" in markdown
    assert "Inbox 积压" in markdown
    assert [section["key"] for section in result["sections"]] == SECTION_KEYS


def test_overview_numbers_are_deterministic_and_never_asked_of_the_model(tmp_path):
    records = _library()
    planner = SectionPlanner()
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)

    in_range_stats = digest.compute_stats(_library(), CUSTOM)
    assert in_range_stats["document_count"] == 2
    assert in_range_stats["parsed_count"] == 2
    assert in_range_stats["parse_success_rate"] == 100.0
    overview = digest.render_overview_body(in_range_stats)
    assert overview in result["markdown"]
    assert "- 材料文档：2 篇" in result["markdown"]

    # the model is only asked for the narrative sections
    prompt, _model = planner.calls[0]
    assert '"topics"' in prompt and '"pending"' in prompt
    assert '"overview"' not in prompt and '"highlights"' not in prompt
    # ...and the deterministic numbers are computed, not requested
    assert "材料文档：2 篇" not in prompt


def test_highlights_are_deterministic_bounded_excerpts():
    material = digest.assemble_material(_library(), CUSTOM)
    highlight_ids = [d["document_id"] for d in material["highlights"]]
    assert highlight_ids == ["doc-a", "doc-b"]      # 重点 tag first, then the Inbox doc
    body, ids = digest.render_highlights_body(material["highlights"])
    assert ids == highlight_ids
    assert "### 1. 信道编码推导" in body
    assert "[信道编码推导](#doc/doc-a)" in body
    for doc in material["highlights"]:
        assert len(digest.document_excerpt(doc["content"])) <= digest.HIGHLIGHT_CHARS


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------


def test_section_source_ids_match_what_each_section_cites(tmp_path):
    planner = SectionPlanner()
    result = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    by_key = {section["key"]: section for section in result["sections"]}

    # 概览 counts the whole in-range material set
    assert by_key["overview"]["source_document_ids"] == ["doc-a", "doc-b"]
    # model ids are validated: "doc-not-in-material" is dropped, not invented
    assert by_key["topics"]["source_document_ids"] == ["doc-a"]
    # deterministic excerpt list
    assert by_key["highlights"]["source_document_ids"] == ["doc-a", "doc-b"]
    assert by_key["pending"]["source_document_ids"] == ["doc-b"]

    for section in result["sections"]:
        assert set(section) == {"key", "title", "source_document_ids"}
        for document_id in section["source_document_ids"]:
            assert document_id in result["digest"]["document_ids"]

    details = result["digest"]["section_details"]
    assert details["overview"]["generated_by"] == "deterministic"
    assert details["highlights"]["generated_by"] == "deterministic"
    assert details["topics"]["generated_by"] == "model"
    assert details["pending"]["generated_by"] == "model"


def test_parse_section_reply_validates_schema_and_drops_unknown_ids():
    allowed = {"doc-a", "doc-b"}
    fenced = "```json\n" + json.dumps({
        "sections": {
            "topics": {"markdown": "要点", "source_document_ids": ["doc-b", "doc-x", "doc-b"]},
            "pending": "纯字符串分节",
        }
    }, ensure_ascii=False) + "\n```"
    bodies, mode = digest.parse_section_reply(
        fenced, allowed_ids=allowed, sections=("topics", "pending"))
    assert mode == "json"
    assert bodies["topics"] == {"markdown": "要点", "source_document_ids": ["doc-b"]}
    assert bodies["pending"] == {"markdown": "纯字符串分节", "source_document_ids": []}

    # a non-JSON / wrong-shape reply is reported as unstructured
    assert digest.parse_section_reply("## 本周写了什么\n正文", allowed_ids=allowed,
                                      sections=("topics",)) == ({}, "text")
    assert digest.parse_section_reply("[1, 2]", allowed_ids=allowed,
                                      sections=("topics",)) == ({}, "text")


def test_unstructured_reply_keeps_the_skeleton_and_reports_fallback(tmp_path):
    planner = SectionPlanner("## 写了什么\n\n本周整理了信道编码。")
    result = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)

    assert result["status"] == "ok" and result["llm_calls"] == 1
    assert result["digest"]["llm_mode"] == "text-fallback"
    for title in SECTION_TITLES:
        assert f"## {title}" in result["markdown"]
    # free prose lands in the first requested section, headings demoted one level
    assert "### 写了什么" in result["markdown"]
    topics = next(s for s in result["sections"] if s["key"] == "topics")
    assert result["digest"]["section_details"]["topics"]["generated_by"] == "text-fallback"
    assert topics["source_document_ids"] == ["doc-a", "doc-b"]
    # 待整理 still carries its deterministic statistics
    assert "Inbox 积压" in result["markdown"]


def test_material_partition_keeps_a_topiced_document_in_the_topic_scope(tmp_path):
    """Only label-less / flagged docs are 待整理 material; the Inbox stats keep
    the UI projection (a topiced-but-untagged doc still counts as Inbox)."""
    records = [
        _record("only-topic", "Only topic", date="2026-09-01", topics=["数学"]),
        _record("only-tag", "Only tag", date="2026-09-02", tags=["记录"]),
        _record("bare", "Bare", date="2026-09-03"),
    ]
    material = digest.assemble_material(records, CUSTOM)
    assert [d["document_id"] for d in material["organized_documents"]] == [
        "only-topic", "only-tag"]
    assert [d["document_id"] for d in material["pending_documents"]] == ["bare"]
    assert material["stats"]["inbox_in_range"] == 3
    assert material["stats"]["inbox_reason_counts"] == {
        "no_tag": 2, "no_topic": 2}
    assert material["section_fingerprints"]["topics"]
    assert material["section_fingerprints"]["pending"]

    planner = SectionPlanner()
    digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    prompt, _model = planner.calls[0]
    assert '<document id="only-topic"' in prompt[: prompt.index("待整理材料：")]
    assert '<document id="bare"' in prompt[prompt.index("待整理材料："):]


def test_explicit_flag_moves_a_labeled_document_into_pending():
    flagged = _record("flagged", "Flagged", date="2026-09-02", topics=["数学"], tags=["重点"])
    flagged["metadata"]["needs_organization"] = True
    material = digest.assemble_material([flagged], CUSTOM)
    assert material["pending_documents"] and material["organized_documents"] == []
    assert material["documents"][0]["inbox_reasons"] == ["explicit"]


def test_llm_prompt_scopes_material_per_section(tmp_path):
    planner = SectionPlanner()
    digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    prompt, _model = planner.calls[0]
    assert "主题材料：" in prompt and "待整理材料：" in prompt and "待整理统计：" in prompt
    organized_at = prompt.index("主题材料：")
    pending_at = prompt.index("待整理材料：")
    assert organized_at < prompt.index('<document id="doc-a"') < pending_at
    assert pending_at < prompt.index('<document id="doc-b"')
    assert '<document id="doc-b"' not in prompt[:pending_at]
    assert '<document id="doc-out"' not in prompt


# ---------------------------------------------------------------------------
# meta.json contract + backward compatibility
# ---------------------------------------------------------------------------


def test_meta_records_sections_and_reloads_them(tmp_path):
    planner = SectionPlanner()
    result = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    digest_id = result["digest"]["digest_id"]

    meta = result["digest"]
    assert meta["schema_version"] == digest.SCHEMA_VERSION == 2
    assert meta["generator"] == digest.GENERATOR_VERSION
    assert [section["key"] for section in meta["sections"]] == SECTION_KEYS
    assert [section["title"] for section in meta["sections"]] == SECTION_TITLES
    assert all(set(section) == {"key", "title", "source_document_ids"}
               for section in meta["sections"])
    assert meta["stats"]["document_count"] == 2
    assert meta["section_details"]["overview"]["generated_by"] == "deterministic"
    assert meta["section_details"]["topics"]["generated_by"] == "model"
    assert meta["llm_mode"] == "json"

    stored = digest.load_digest(tmp_path, digest_id)          # emulated restart
    assert stored["sections"] == meta["sections"]
    assert digest.meta_sections(stored["meta"]) == meta["sections"]


def test_legacy_meta_without_sections_loads_and_lists(tmp_path):
    """A pre-W1 meta.json has no ``sections``/``stats`` keys and must not blow up."""
    directory = tmp_path / "digests"
    directory.mkdir(parents=True)
    legacy = {
        "schema_version": 1,
        "generator": "digest-1",
        "digest_id": "dg-legacy-1",
        "created_at": "2026-09-08T10:00:00",
        "range": CUSTOM,
        "fingerprint": "deadbeef",
        "document_ids": ["doc-a"],
        "document_count": 1,
        "usage": {"total_tokens": 12},
        "llm_calls": 1,
    }
    (directory / "dg-legacy-1.meta.json").write_text(
        json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    (directory / "dg-legacy-1.md").write_text("# 本周小结\n\n旧格式全文。", encoding="utf-8")

    assert [meta["digest_id"] for meta in digest.list_digests(tmp_path)] == ["dg-legacy-1"]
    stored = digest.load_digest(tmp_path, "dg-legacy-1")
    assert stored["meta"]["generator"] == "digest-1"
    assert stored["sections"] == []
    assert stored["markdown"].startswith("# 本周小结")
    # legacy fingerprints never collide with the new generator
    assert digest.find_cached(tmp_path, "deadbeef")["digest_id"] == "dg-legacy-1"
    assert digest.meta_sections(legacy) == []
    assert digest.meta_sections({"sections": [{"title": "no key"}, 7]}) == []


def test_meta_sections_normalizes_partial_entries():
    meta = {"sections": [
        {"key": "topics", "title": "", "source_document_ids": ["a", 1]},
        {"key": "pending"},
    ]}
    assert digest.meta_sections(meta) == [
        {"key": "topics", "title": "主题脉络", "source_document_ids": ["a", "1"]},
        {"key": "pending", "title": "待整理与连续体进展", "source_document_ids": []},
    ]


# ---------------------------------------------------------------------------
# section-level cache (W1 bonus)
# ---------------------------------------------------------------------------


def test_section_cache_reuses_the_unchanged_section(tmp_path):
    planner = SectionPlanner()
    first = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert first["llm_calls"] == 1
    pending_before = digest.load_section_bodies(
        tmp_path, first["digest"]["digest_id"])["sections"]["pending"]["markdown"]

    # only the organized document's text changes -> 主题脉络 material changed,
    # 待整理 material (Inbox docs + Inbox/continuity statistics) did not
    changed = _library()
    changed[0]["current_markdown"] = "# 信道编码\n香农编码步骤（改）。"
    second = digest.generate_digest(changed, CUSTOM, storage_dir=tmp_path, planner=planner)

    assert second["fingerprint"] != first["fingerprint"]        # whole report regenerated
    assert second["llm_calls"] == 1                              # one call, not two
    by_key = {section["key"]: section for section in second["sections"]}
    details = second["digest"]["section_details"]
    assert details["topics"]["generated_by"] == "model"
    assert details["pending"]["generated_by"] == "section-cache"
    assert by_key["pending"]["source_document_ids"] == ["doc-b"]
    reused = digest.load_section_bodies(
        tmp_path, second["digest"]["digest_id"])["sections"]["pending"]["markdown"]
    assert reused == pending_before
    prompt, _model = planner.calls[1]
    assert '"topics"' in prompt and '"pending"' not in prompt


def test_section_cache_can_skip_the_model_entirely(tmp_path):
    """A version bump with identical text invalidates the report, not the sections."""
    planner = SectionPlanner()
    first = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert first["llm_calls"] == 1

    bumped = _library()
    for record in bumped:
        record["latest_version_id"] = "v2"
    second = digest.generate_digest(bumped, CUSTOM, storage_dir=tmp_path, planner=planner)

    assert second["fingerprint"] != first["fingerprint"]
    assert second["generated"] is True and second["cached"] is False
    assert second["llm_calls"] == 0
    assert len(planner.calls) == 1
    assert second["message"] == "分节材料未变，未重新调用模型。"
    assert all(
        detail["generated_by"] == "section-cache"
        for key, detail in second["digest"]["section_details"].items()
        if key in digest.NARRATIVE_SECTIONS
    )
    assert second["digest"]["llm_mode"] == "section-cache"
    # the deterministic sections are still recomputed for the new report
    assert "Inbox 积压" in second["markdown"]


def test_force_bypasses_both_caches(tmp_path):
    planner = SectionPlanner()
    digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    forced = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path,
                                    planner=planner, force=True)
    assert forced["llm_calls"] == 1
    assert len(planner.calls) == 2
    assert all(
        detail["generated_by"] == "model"
        for key, detail in forced["digest"]["section_details"].items()
        if key in digest.NARRATIVE_SECTIONS
    )
    assert forced["digest"]["llm_mode"] == "json"


def test_section_cache_never_hits_without_material(tmp_path):
    """An empty section material has no fingerprint, so it is recomputed silently."""
    records = [_record("doc-b", "实验备忘", date="2026-09-05", content="x")]
    planner = SectionPlanner()
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    material = digest.assemble_material(records, CUSTOM)
    assert material["section_fingerprints"]["topics"] == ""
    assert material["section_fingerprints"]["pending"] != ""
    assert digest.find_cached_section(tmp_path, "topics", "") is None
    # the stored sidecar only carries the sections that have material
    payload = digest.load_section_bodies(tmp_path, result["digest"]["digest_id"])
    assert set(payload["sections"]) == {"pending"}


def test_section_bodies_sidecar_only_carries_cacheable_sections(tmp_path):
    # topics ∪ tags both filled -> organized (主题材料); nothing pending
    records = [_record("doc-a", "A", date="2026-09-02", content="x", topics=["t"], tags=["g"])]
    planner = SectionPlanner()
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    payload = digest.load_section_bodies(tmp_path, result["digest"]["digest_id"])
    assert set(payload["sections"]) == {"topics"}
    entry = payload["sections"]["topics"]
    # only the narrative body is cached; the deterministic statistics are not
    assert entry["markdown"] == GOLDEN["sections"]["topics"]["markdown"]
    assert "Inbox 积压" not in entry["markdown"]
    assert entry["fingerprint"]
    assert entry["source_document_ids"] == ["doc-a"]


def test_planner_error_path_has_no_sections_and_no_digest(tmp_path):
    def boom(prompt, model):
        raise RuntimeError("gateway down")

    result = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=boom)
    assert result["status"] == "error" and "gateway down" in result["message"]
    assert result["sections"] == [] and result["digest"] is None
    assert digest.list_digests(tmp_path) == []


def test_empty_reply_is_an_error_not_an_empty_section(tmp_path):
    planner = SectionPlanner("   ")
    result = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert result["status"] == "error" and result["message"] == "模型返回了空小结。"
    assert result["llm_calls"] == 1


@pytest.mark.parametrize("limit", [0, 1, 5, 6, 240])
def test_excerpt_budget_is_exact(limit):
    assert len(digest.document_excerpt("字" * 100, limit=limit)) <= limit
    assert len(digest.document_excerpt("123456789", limit=limit)) <= limit
    if limit:
        assert digest.document_excerpt("短", limit=limit) == "短"


def test_excerpt_truncates_with_an_ellipsis_at_the_limit():
    assert digest.document_excerpt("123456789", limit=5) == "1234…"
    assert len(digest.document_excerpt("123456789", limit=1)) == 1


# ---------------------------------------------------------------------------
# Y6 leftovers R3/R4/R5/R7/R8
# ---------------------------------------------------------------------------


def _long_library(count: int, *, distinct_labels: bool = False) -> list[dict]:
    """A material set at/over ``MAX_DOCS`` with long (truncated) content."""
    records = []
    for index in range(count):
        label = f"{index:03d}"
        records.append(_record(
            f"long-{label}",
            f"长材料 {label}",
            date="2026-09-02",
            content="# 长材料\n" + "正文内容。" * 500,          # > MAX_DOC_CHARS
            topics=[f"主题{label if distinct_labels else index % 4}"],
            tags=[f"标签{label if distinct_labels else index % 3}"],
        ))
    return records


# --- R4: long-material JSON stability / fallback ---------------------------


def test_long_material_json_reply_keeps_the_four_sections(tmp_path):
    planner = SectionPlanner()
    result = digest.generate_digest(
        _long_library(digest.MAX_DOCS), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert result["status"] == "ok" and result["llm_calls"] == 1
    assert result["digest"]["llm_mode"] == "json"
    assert [section["key"] for section in result["sections"]] == SECTION_KEYS
    material_ids = set(result["digest"]["document_ids"])
    assert len(material_ids) == digest.MAX_DOCS
    for section in result["sections"]:
        assert set(section["source_document_ids"]) <= material_ids
    prompt, _model = planner.calls[0]
    assert prompt.count("<document id=") == digest.MAX_DOCS
    assert "已截断" in prompt          # per-document content budget still applied


@pytest.mark.parametrize("reply", [
    '{"sections": {"topics": {"markdown": "要点", "source_document_ids": ["long-000"]',
    "```json\n{\"sections\": {\"topics\": \"半截\"\n```",
    "本周全部是散文，没有任何 JSON 结构，也没有一个花括号。",
    "[1, 2, 3]",
    '{"sections": {"topics": {"markdown": ["not", "a", "string"]}}}',
    '{"sections": {"topics": {"markdown": "", "source_document_ids": []}}}',
])
def test_long_material_malformed_replies_still_yield_four_sections(tmp_path, reply):
    planner = SectionPlanner(reply)
    result = digest.generate_digest(
        _long_library(digest.MAX_DOCS), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert result["status"] == "ok" and result["llm_calls"] == 1
    for _key, title in digest.SECTION_DEFS:
        assert f"## {title}" in result["markdown"]
    assert "## 来源" in result["markdown"]


# --- R3: meta size budget + verbose-list policy ----------------------------


def test_meta_size_is_bounded_and_verbose_lists_are_capped(tmp_path):
    records = _long_library(digest.MAX_DOCS, distinct_labels=True)
    planner = SectionPlanner()
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    meta = result["digest"]
    payload = json.dumps(meta, ensure_ascii=False).encode("utf-8")
    assert len(payload) <= digest.MAX_META_BYTES
    # the true totals survive; only the verbose (W2-unused) label lists are capped
    assert meta["stats"]["topic_count"] == digest.MAX_DOCS
    assert len(meta["stats"]["topics"]) == digest.META_STATS_LIST_LIMIT
    assert meta["stats"]["topics_truncated"] is True
    assert meta["stats"]["tags_truncated"] is True
    assert len(meta["budget"]["topics"]) == digest.META_STATS_LIST_LIMIT
    assert meta["budget"]["topics_truncated"] is True
    assert len(meta["budget"]["per_topic_kept"]) == digest.META_STATS_LIST_LIMIT
    assert meta["budget"]["per_topic_kept_truncated"] is True
    # the in-memory material keeps the full lists for rendering
    material = digest.assemble_material(records, CUSTOM)
    assert len(material["stats"]["topics"]) == digest.MAX_DOCS


# --- R5: elapsed semantics under llm_calls=0 -------------------------------


def test_elapsed_scope_separates_model_time_from_cache_only(tmp_path):
    planner = SectionPlanner()
    first = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert first["digest"]["llm_calls"] == 1
    assert first["digest"]["elapsed_scope"] == "model"

    bumped = _library()
    for record in bumped:
        record["latest_version_id"] = "v2"
    second = digest.generate_digest(bumped, CUSTOM, storage_dir=tmp_path, planner=planner)
    assert second["llm_calls"] == 0
    assert second["digest"]["elapsed"] == 0.0
    assert second["digest"]["elapsed_scope"] == "none"


# --- R7: GENERATOR_VERSION must stay inside the whole-report fingerprint ----


def test_generator_version_is_part_of_the_report_fingerprint(monkeypatch):
    documents = digest.assemble_material(_library(), CUSTOM)["documents"]
    baseline = digest.compute_fingerprint(CUSTOM, documents)
    monkeypatch.setattr(digest, "GENERATOR_VERSION", digest.GENERATOR_VERSION + "-next")
    assert digest.compute_fingerprint(CUSTOM, documents) != baseline


def test_generator_version_bump_invalidates_the_whole_report_cache(tmp_path, monkeypatch):
    planner = SectionPlanner()
    first = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    monkeypatch.setattr(digest, "GENERATOR_VERSION", digest.GENERATOR_VERSION + "-next")
    second = digest.generate_digest(_library(), CUSTOM, storage_dir=tmp_path, planner=planner)
    assert second["fingerprint"] != first["fingerprint"]
    assert second["cached"] is False and second["generated"] is True
    # the old digest is still reachable by its own (old-generator) fingerprint
    assert digest.find_cached(tmp_path, first["fingerprint"])["digest_id"] == \
        first["digest"]["digest_id"]


# --- R8: range-scoped vs material-scoped counts stay distinct ---------------


def test_range_total_and_material_count_are_distinct_and_labelled(tmp_path):
    records = _long_library(digest.MAX_DOCS + 5)
    material = digest.assemble_material(records, CUSTOM)
    stats = material["stats"]
    assert stats["document_count"] == digest.MAX_DOCS + 5          # in-range total
    assert stats["material_document_count"] == digest.MAX_DOCS     # selected by budget
    assert stats["omitted_count"] == 5
    assert stats["organized_material_count"] + stats["pending_material_count"] == \
        stats["material_document_count"]

    planner = SectionPlanner()
    result = digest.generate_digest(records, CUSTOM, storage_dir=tmp_path, planner=planner)
    meta = result["digest"]
    assert meta["document_count"] == digest.MAX_DOCS
    assert len(meta["document_ids"]) == digest.MAX_DOCS
    assert meta["stats"]["document_count"] == digest.MAX_DOCS + 5
    assert meta["stats"]["material_document_count"] == digest.MAX_DOCS
    overview = next(s for s in meta["sections"] if s["key"] == "overview")
    # 概览 is range-scoped by design: its provenance includes the trimmed docs
    assert len(overview["source_document_ids"]) == digest.MAX_DOCS + 5
    assert set(meta["document_ids"]) <= set(overview["source_document_ids"])
