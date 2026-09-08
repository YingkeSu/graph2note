"""Issue 10 — cross-validation diff engine (offline golden fixtures).

Pure functions only (no network / no PIL / no LLM).  Covers the four AC
fixture classes: 漏块 (missed block), 多块 (extra block), 文本不一致 (content
conflict), 顺序差异 (order difference), plus identical/baseline and the AC's
three-class schema.
"""

import pytest

from graph2note.ir import load_dict_as_ir, DocumentIR
from graph2note.verify import (
    diff_documents,
    CONSISTENT,
    ONE_SIDE,
    CONFLICT,
)


def doc(blocks) -> DocumentIR:
    return load_dict_as_ir({"document_type": "note", "blocks": blocks})


def test_identical_documents_are_all_consistent():
    a = doc([
        {"type": "heading", "level": 1, "text": "标题"},
        {"type": "paragraph", "text": "第一段内容"},
        {"type": "list", "ordered": False, "items": [{"text": "项目A"}]},
    ])
    d = diff_documents(a, a)
    assert d.counts[CONSISTENT] == 3
    assert d.counts[ONE_SIDE] == 0 and d.counts[CONFLICT] == 0
    assert not d.order_changed
    assert d.consistent[0].similarity == 1.0


# -- 漏块 / 多块 -------------------------------------------------------------
def test_missing_block_on_second_document_is_one_side():
    a = doc([{"type": "heading", "level": 1, "text": "标题"},
             {"type": "paragraph", "text": "第二段"}])
    b = doc([{"type": "heading", "level": 1, "text": "标题"}])  # 漏掉第二段
    d = diff_documents(a, b)
    assert d.counts[ONE_SIDE] == 1
    side = d.one_side[0]
    assert side.side == "a" and side.block_type == "paragraph"
    assert side.index_a == 1 and side.index_b is None


def test_extra_block_is_one_side_on_other_document():
    a = doc([{"type": "heading", "level": 1, "text": "标题"}])
    b = doc([{"type": "heading", "level": 1, "text": "标题"},
             {"type": "paragraph", "text": "多出的段落"}])
    d = diff_documents(a, b)
    assert d.counts[ONE_SIDE] == 1
    assert d.one_side[0].side == "b"


# -- 文本不一致 --------------------------------------------------------------
def test_content_conflict_is_conflict_tag():
    a = doc([{"type": "heading", "level": 1, "text": "机器视觉综述"},
             {"type": "paragraph", "text": "第一段"}])
    b = doc([{"type": "heading", "level": 1, "text": "计算机视觉综述"},
             {"type": "paragraph", "text": "第一段"}])
    d = diff_documents(a, b)
    assert d.counts[CONFLICT] == 1
    c = d.conflict[0]
    assert c.block_type == "heading"
    assert c.similarity < 1.0            # 内容冲突（非一致）
    assert c.index_a == 0 and c.index_b == 0


# -- 顺序差异 -----------------------------------------------------------------
def test_reordered_blocks_stay_consistent_and_flag_order():
    p12 = doc([{"type": "paragraph", "text": "第一段"},
               {"type": "paragraph", "text": "第二段"}])
    p21 = doc([{"type": "paragraph", "text": "第二段"},
               {"type": "paragraph", "text": "第一段"}])
    d = diff_documents(p12, p21)
    assert d.counts[CONSISTENT] == 2      # 内容一致，只是顺序不同
    assert d.counts[ONE_SIDE] == 0 and d.counts[CONFLICT] == 0
    assert d.order_changed is True
    assert "顺序" in d.note


# -- within-document near-dup --------------------------------------------------
def test_near_duplicate_blocks_detected_in_doc():
    du = doc([{"type": "paragraph", "text": "同一句重复"},
              {"type": "paragraph", "text": "同一句重复"},
              {"type": "paragraph", "text": "正常段落"}])
    from graph2note.verify import detect_near_dup_blocks
    groups = detect_near_dup_blocks(du)
    assert len(groups) == 1
    assert groups[0].indexes == [0, 1]
    assert groups[0].block_type == "paragraph"


def test_no_false_near_dup_in_distinct_blocks():
    clean = doc([{"type": "paragraph", "text": "甲"}, {"type": "paragraph", "text": "乙"},
                 {"type": "heading", "level": 2, "text": "小标题"}])
    from graph2note.verify import detect_near_dup_blocks
    assert detect_near_dup_blocks(clean) == []


# -- aggregation / contract ------------------------------------------------
def test_aggregation_counts_do_not_flood():
    # many blocks differing only in one position still aggregate by class
    a = doc([{"type": "paragraph", "text": f"第{i}行"} for i in range(1, 6)])
    b = doc([{"type": "paragraph", "text": f"第{i}行"} for i in range(1, 6)]
            + [{"type": "paragraph", "text": "漏掉的一行"}])
    d = diff_documents(a, b)
    assert d.counts[CONSISTENT] == 5
    assert d.counts[ONE_SIDE] == 1  # one extra, no per-rule flooding
    assert len(d.one_side) == 1


def test_empty_documents_diff_cleanly():
    d = diff_documents(doc([]), doc([]))
    assert d.counts == {CONSISTENT: 0, ONE_SIDE: 0, CONFLICT: 0}