"""W1 offline contracts: deterministic statistics + explainable material budget.

Covers the issue acceptance criteria that are *numeric*:

- 「本周概览」 statistics are computed by pure functions (never by the model) and
  asserted against a hand-constructed library state;
- the material budget policy (有效时间优先 + 各主题保底配额) is a pure,
  deterministic function with the thresholds centralised in module constants;
- 重点文档摘录 selection and the excerpt budget are deterministic and bounded;
- Inbox / continuity statistics are read from the existing pure projections.

The model is never involved here — :func:`test_stats_never_touch_a_model`
monkeypatches the text gateway to explode and still passes.
"""

from __future__ import annotations

import pytest

from graph2note import digest

CUSTOM = {"kind": "custom", "from": "2026-09-01", "to": "2026-09-07",
          "label": "自定义（2026-09-01 ~ 2026-09-07）"}


def _slot(value=None, source="none"):
    return {"value": value, "source": source, "confidence": None, "evidence": None}


def _record(
    document_id: str,
    *,
    date: str = "2026-09-02",
    content: str = "内容",
    topics=None,
    tags=None,
    created_at=None,
    pdf_id=None,
    page_index=None,
):
    record = {
        "document_id": document_id,
        "title": document_id.upper(),
        "metadata": {
            "document_time": _slot(date, "manual"),
            "capture_time": _slot(None, "exif"),
            "import_time": _slot(None, "system"),
        },
        "current_markdown": content,
        "tags": list(tags or []),
        "topics": list(topics or []),
    }
    if created_at:
        record["created_at"] = created_at
    if pdf_id is not None:
        record["pdf_id"] = pdf_id
        record["page_index"] = page_index
    return record


def _entry(document_id: str, date: str, *, topics=None, tags=None):
    return {"document_id": document_id, "title": document_id, "date": date,
            "topics": list(topics or []), "tags": list(tags or [])}


# ---------------------------------------------------------------------------
# material budget (pure)
# ---------------------------------------------------------------------------


def test_budget_without_pressure_keeps_everything():
    entries = [_entry(f"d{i}", f"2026-09-0{i}") for i in range(1, 4)]
    selected, report = digest.apply_material_budget(entries, max_docs=5)
    assert selected == entries
    assert report["total"] == 3 and report["kept"] == 3 and report["omitted"] == 0
    assert report["kept_ids"] == ["d1", "d2", "d3"]
    assert report["guaranteed_ids"] == []


def test_budget_keeps_the_newest_documents_when_no_floor_is_set():
    entries = [_entry(f"d{i}", f"2026-09-0{i}") for i in range(1, 7)]
    selected, report = digest.apply_material_budget(entries, max_docs=3, topic_floor=0)
    assert [e["document_id"] for e in selected] == ["d4", "d5", "d6"]
    assert report["omitted"] == 3
    assert report["kept_ids"] == ["d4", "d5", "d6"]
    assert report["guaranteed_ids"] == []


def test_topic_floor_protects_a_topic_that_recency_would_drop():
    entries = [
        _entry("math-1", "2026-09-01", topics=["数学"]),
        _entry("math-2", "2026-09-02", topics=["数学"]),
        _entry("math-3", "2026-09-03", topics=["数学"]),
        _entry("math-4", "2026-09-04", topics=["数学"]),
        _entry("exp-5", "2026-09-05", topics=["实验"]),
        _entry("exp-6", "2026-09-06", topics=["实验"]),
    ]
    selected, report = digest.apply_material_budget(entries, max_docs=2, topic_floor=1)
    ids = [e["document_id"] for e in selected]
    # the newest 数学 document is protected even though recency alone dropped it,
    # and the overflow is paid by the oldest unprotected document (exp-5)
    assert ids == ["math-4", "exp-6"]
    assert report["guaranteed_ids"] == ["exp-6", "math-4"]
    assert report["omitted"] == 4
    assert report["per_topic_kept"] == {"数学": 1, "实验": 1}
    assert report["topics"] == ["实验", "数学"]


def test_budget_is_deterministic_under_permutation_and_does_not_mutate_input():
    entries = [
        _entry("a", "2026-09-01", topics=["t1"]),
        _entry("b", "2026-09-02", topics=["t2"]),
        _entry("c", "2026-09-03", topics=["t2"]),
        _entry("d", "2026-09-04", topics=["t3"]),
    ]
    snapshot = [dict(entry) for entry in entries]
    first, report = digest.apply_material_budget(entries, max_docs=2, topic_floor=1)
    second, _ = digest.apply_material_budget(list(reversed(entries)), max_docs=2, topic_floor=1)
    assert [e["document_id"] for e in first] == [e["document_id"] for e in second]
    assert report == digest.apply_material_budget(entries, max_docs=2, topic_floor=1)[1]
    assert entries == snapshot                      # inputs untouched


def test_floor_larger_than_the_budget_falls_back_to_recency():
    entries = [
        _entry("old", "2026-09-01", topics=["数学"]),
        _entry("mid", "2026-09-02", topics=["实验"]),
        _entry("new", "2026-09-03", topics=["实验"]),
    ]
    selected, report = digest.apply_material_budget(entries, max_docs=1, topic_floor=5)
    assert [e["document_id"] for e in selected] == ["new"]
    assert report["kept"] == 1 and report["omitted"] == 2


def test_zero_budget_keeps_nothing():
    entries = [_entry("a", "2026-09-01"), _entry("b", "2026-09-02")]
    selected, report = digest.apply_material_budget(entries, max_docs=0)
    assert selected == []
    assert report["omitted"] == 2 and report["kept_ids"] == []


def test_multi_topic_document_is_kept_once_but_counted_for_each_topic():
    entries = [
        _entry("both", "2026-09-01", topics=["数学"], tags=["实验"]),
        _entry("fill-1", "2026-09-02"),
        _entry("fill-2", "2026-09-03"),
    ]
    selected, report = digest.apply_material_budget(entries, max_docs=2, topic_floor=1)
    assert [e["document_id"] for e in selected] == ["both", "fill-2"]
    assert report["per_topic_kept"] == {"实验": 1, "数学": 1}
    assert report["guaranteed_ids"] == ["both"]


def test_budget_thresholds_live_in_module_constants():
    entries = [_entry(f"d{i}", f"2026-09-0{i}") for i in range(1, 4)]
    _selected, report = digest.apply_material_budget(entries)
    assert report["max_docs"] == digest.MAX_DOCS == 60
    assert report["topic_floor"] == digest.TOPIC_FLOOR == 2
    # the defaults are the module constants, not副本
    assert digest.apply_material_budget.__kwdefaults__ == {
        "max_docs": digest.MAX_DOCS, "topic_floor": digest.TOPIC_FLOOR}
    assert digest.HIGHLIGHT_LIMIT == 5 and digest.HIGHLIGHT_CHARS == 240
    assert digest.CONTINUITY_SUGGESTED_MAX_DOCS == 200


def test_assemble_material_reports_the_budget_and_keeps_everything_without_pressure():
    records = [
        _record("math", date="2026-09-01", topics=["数学"], tags=["a"]),
        _record("exp-1", date="2026-09-02", topics=["实验"], tags=["b"]),
        _record("exp-2", date="2026-09-03", topics=["实验"], tags=["c"]),
    ]
    material = digest.assemble_material(records, CUSTOM)
    assert [d["document_id"] for d in material["documents"]] == ["math", "exp-1", "exp-2"]
    assert material["omitted"] == 0
    assert material["stats"]["omitted_count"] == 0
    assert material["stats"]["max_docs"] == digest.MAX_DOCS
    assert material["stats"]["topic_floor"] == digest.TOPIC_FLOOR
    # 主题/标签 labels both take part in the floor accounting
    assert material["budget"]["per_topic_kept"] == {
        "a": 1, "b": 1, "c": 1, "实验": 2, "数学": 1}
    assert "材料裁剪" not in digest.render_overview_body(material["stats"])


def test_overview_explains_the_trim_rule_when_documents_were_omitted():
    stats = dict(digest.compute_stats(_library(), CUSTOM))
    stats.update({"document_count": 3, "omitted_count": 1, "max_docs": 2, "topic_floor": 1})
    overview = digest.render_overview_body(stats)
    assert "材料裁剪：本期共 3 篇，按「有效时间优先 + 每主题保底 1 篇」保留 2 篇，省略 1 篇" in overview


# ---------------------------------------------------------------------------
# deterministic statistics
# ---------------------------------------------------------------------------


def _library():
    return [
        _record("a", date="2026-09-02", content="正文", topics=["数学"], tags=["重点"],
                created_at="2026-09-02T10:00:00"),
        _record("b", date="2026-09-03", content=""),                       # parse failure + Inbox
        _record("c", date="2026-09-04", content="正文", topics=["实验"], tags=["记录"],
                created_at="2026-08-15T10:00:00"),                          # imported before the range
        _record("out", date="2026-07-01", content="旧"),                    # outside the range
    ]


def test_compute_stats_counts_every_documented_field():
    stats = digest.compute_stats(_library(), CUSTOM)
    assert stats["document_count"] == 3
    assert stats["new_document_count"] == 1            # created_at inside the range
    assert stats["parsed_count"] == 2
    assert stats["failed_count"] == 1
    assert stats["parse_success_rate"] == 66.7
    assert stats["topics"] == ["实验", "数学"] and stats["topic_count"] == 2
    assert stats["tags"] == ["记录", "重点"] and stats["tag_count"] == 2
    assert stats["tagged_count"] == 2
    # Inbox statistics: library-wide backlog vs this week's still-unorganized docs
    assert stats["inbox_pending"] == 2                 # b + the out-of-range doc
    assert stats["inbox_in_range"] == 1
    assert stats["inbox_reason_counts"] == {"no_tag": 1, "no_topic": 1}
    assert stats["continuity_significant"] == 0
    assert stats["continuity_suggested"] == 0


def test_stats_are_deterministic_and_do_not_mutate_records():
    records = _library()
    snapshot = [dict(record) for record in records]
    assert digest.compute_stats(records, CUSTOM) == digest.compute_stats(records, CUSTOM)
    assert records == snapshot


def test_parse_success_rate_is_none_without_material():
    stats = digest.compute_stats(_library(), {"kind": "custom", "from": "2020-01-01",
                                              "to": "2020-01-02"})
    assert stats["document_count"] == 0
    assert stats["parse_success_rate"] is None
    assert "无材料" in digest.render_overview_body(stats)


def test_stats_never_touch_a_model(monkeypatch):
    from graph2note.notes import llm as notes_llm

    def boom(*args, **kwargs):
        raise AssertionError("statistics must never call the text channel")

    monkeypatch.setattr(notes_llm, "_gateway_text_usage", boom)
    monkeypatch.setattr(notes_llm, "_gateway_text", boom)
    stats = digest.compute_stats(_library(), CUSTOM)
    assert stats["document_count"] == 3
    assert "Inbox 积压" in digest.render_pending_stats_body(stats)


def test_pending_stats_body_labels_reasons_and_continuity():
    stats = digest.compute_stats(_library(), CUSTOM)
    body = digest.render_pending_stats_body(stats)
    assert "- Inbox 积压：库内 2 篇待整理（本期 1 篇）" in body
    assert "原因：无标签 1、无主题 1" in body
    assert "- 连续体：可直接合并 0 对，待确认 0 对" in body


def test_continuity_pairs_are_counted_from_adjacent_pdf_pages():
    records = [
        _record("p1", date="2026-09-02", content="甲", pdf_id="pdf-1", page_index=0),
        _record("p2", date="2026-09-02", content="乙", pdf_id="pdf-1", page_index=1),
        _record("p4", date="2026-09-02", content="丙", pdf_id="pdf-1", page_index=3),
    ]
    stats = digest.compute_stats(records, CUSTOM)
    assert stats["continuity_significant"] == 1        # p1–p2 only (p4 is not adjacent)
    assert stats["continuity_suggested"] == 0
    assert stats["continuity_suggested_counted"] is True


def test_continuity_suggested_tier_is_skipped_above_the_size_cap(monkeypatch):
    monkeypatch.setattr(digest, "CONTINUITY_SUGGESTED_MAX_DOCS", 0)
    stats = digest.compute_stats(_library(), CUSTOM)
    assert stats["continuity_suggested_counted"] is False
    assert "库规模超阈值" in digest.render_pending_stats_body(stats)


# ---------------------------------------------------------------------------
# highlights (deterministic 重点文档摘录)
# ---------------------------------------------------------------------------


def test_select_highlights_prefers_marked_then_longer_then_newer():
    documents = [
        {"document_id": "plain-long", "date": "2026-09-05", "tags": [],
         "topics": [], "content": "x" * 50},
        {"document_id": "key-short", "date": "2026-09-06", "tags": ["重点"],
         "topics": [], "content": "y"},
        {"document_id": "key-long", "date": "2026-09-04", "tags": [],
         "topics": ["important"], "content": "z" * 50},
        {"document_id": "plain-short", "date": "2026-09-07", "tags": [],
         "topics": [], "content": "w"},
    ]
    assert [d["document_id"] for d in digest.select_highlights(documents, limit=2)] == [
        "key-long", "key-short"]
    assert [d["document_id"] for d in digest.select_highlights(documents)] == [
        "key-long", "key-short", "plain-long", "plain-short"]
    assert digest.select_highlights(documents, limit=0) == []


def test_render_highlights_body_is_bounded_and_links_every_source():
    documents = [{
        "document_id": "doc-a", "title": "标题", "date": "2026-09-02",
        "tags": ["重点"], "topics": [],
        "content": "很长的正文" * 100,
    }]
    body, ids = digest.render_highlights_body(documents)
    assert ids == ["doc-a"]
    assert "### 1. 标题" in body
    assert "日期：2026-09-02" and "标签：重点" in body
    assert "[标题](#doc/doc-a)（`doc-a`）" in body
    quote_lines = [line for line in body.splitlines() if line.startswith("> ")]
    assert quote_lines and all(len(line) <= digest.HIGHLIGHT_CHARS + 2 for line in quote_lines)
    assert body.count("…") == 1


def test_render_highlights_body_without_documents():
    assert digest.render_highlights_body([]) == ("（本期没有可摘录的文档）", [])
