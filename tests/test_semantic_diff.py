"""IR block-level diff engine tests (issue S1) — pure, offline, deterministic.

Covers acceptance criteria 1/2/3/5:

* AC1 purity/determinism (same input -> byte-identical snapshot, no IO);
* AC2 the required fixtures (all same / all changed / heading edit / paragraph
  move / formula edit / diagram add-remove / empty-IR edges), asserting op and
  block type per case;
* AC3 similarity-threshold boundary behaviour on both sides of the threshold;
* AC5 summary statistics + verdict rule table.
"""

from __future__ import annotations

import json

import pytest

from graph2note.ir import DocumentIR, loads_ir
from graph2note.semantic import (
    MINOR_MAX_DENSITY,
    MODIFIED_THRESHOLD,
    diff_ir,
)
from graph2note.semantic import diff as diff_mod


def _ir(blocks: list[dict]) -> DocumentIR:
    return loads_ir(json.dumps({"document_type": "note", "blocks": blocks}))


def _p(text: str) -> dict:
    return {"type": "paragraph", "text": text}


def _h(text: str, level: int = 1) -> dict:
    return {"type": "heading", "level": level, "text": text}


def _ops(report) -> list[str]:
    return [change.op for change in report.changes]


def _by_op(report) -> dict:
    return report.summary.by_op


def _change_for(report, op: str):
    matches = [c for c in report.changes if c.op == op]
    assert matches, f"no {op} change in {_ops(report)}"
    return matches[0]


# ---------------------------------------------------------------------------
# AC1 — purity / determinism
# ---------------------------------------------------------------------------


def test_same_input_same_output_and_snapshot_stable():
    a = _ir([_h("1 绪论"), _p("alpha beta gamma")])
    b = _ir([_h("1 绪论"), _p("alpha beta delta")])
    first = diff_ir(a, b, label_a="v1", label_b="v2")
    second = diff_ir(a, b, label_a="v1", label_b="v2")
    assert first.model_dump() == second.model_dump()
    # JSON round-trip is stable too (the S2/S3 wire shape).
    assert json.loads(first.model_dump_json()) == first.model_dump()


def test_engine_does_no_file_io(monkeypatch):
    import builtins

    a = _ir([_p("hello world")])
    b = _ir([_p("hello there")])

    def _boom(*args, **kwargs):
        raise AssertionError("diff_ir must not touch the filesystem")

    monkeypatch.setattr(builtins, "open", _boom)
    report = diff_ir(a, b)
    assert report.summary.blocks_a == 1


# ---------------------------------------------------------------------------
# AC2 — required fixtures
# ---------------------------------------------------------------------------


def test_all_identical_is_all_unchanged():
    blocks = [_h("标题"), _p("正文一"), _p("正文二")]
    report = diff_ir(_ir(blocks), _ir(blocks))
    assert set(_ops(report)) == {"unchanged"}
    assert _by_op(report)["unchanged"] == 3
    assert report.summary.changed_blocks == 0
    assert report.summary.verdict == "unchanged"
    assert report.summary.change_density == 0.0


def test_all_replaced_is_removed_plus_added_no_modified():
    a = _ir([_p("aaa bbb ccc"), _p("ddd eee fff")])
    b = _ir([_p("zzz yyy xxx"), _p("www vvv uuu")])
    report = diff_ir(a, b)
    assert _by_op(report)["removed"] == 2
    assert _by_op(report)["added"] == 2
    assert _by_op(report)["modified"] == 0
    assert _by_op(report)["unchanged"] == 0
    assert {c.block_type for c in report.changes} == {"paragraph"}
    assert report.summary.verdict == "major"


def test_heading_edit_is_modified_heading():
    a = _ir([_h("1 绪论", level=1), _p("stable body text")])
    b = _ir([_h("1 绪论与方法", level=1), _p("stable body text")])
    report = diff_ir(a, b)
    change = _change_for(report, "modified")
    assert change.block_type == "heading"
    assert change.similarity is not None and 0.0 < change.similarity < 1.0
    assert change.block_ref_a.index == 0 and change.block_ref_b.index == 0
    assert _by_op(report)["unchanged"] == 1


def test_paragraph_move_is_moved_not_removed_added():
    a = _ir([_h("H"), _p("P1 target"), _p("P2 body"), _p("P3 body")])
    b = _ir([_h("H"), _p("P2 body"), _p("P3 body"), _p("P1 target")])
    report = diff_ir(a, b)
    moved = [c for c in report.changes if c.op == "moved"]
    assert len(moved) == 1
    assert moved[0].block_type == "paragraph"
    assert moved[0].block_ref_a.preview == "P1 target"
    assert moved[0].block_ref_a.index == 1 and moved[0].block_ref_b.index == 3
    assert _by_op(report)["removed"] == 0 and _by_op(report)["added"] == 0
    assert _by_op(report)["unchanged"] == 3


def test_pure_insertion_does_not_mark_followers_moved():
    # inserting a new block at the front must not flag every later block.
    a = _ir([_h("H"), _p("P2 body"), _p("P3 body")])
    b = _ir([_h("H"), _p("brand new intro"), _p("P2 body"), _p("P3 body")])
    report = diff_ir(a, b)
    assert _by_op(report)["moved"] == 0
    assert _by_op(report)["added"] == 1
    assert _by_op(report)["unchanged"] == 3


def test_formula_edit_is_modified_formula_via_structure():
    a = _ir([{"type": "formula", "latex": "E = m c^2", "inline": False}])
    b = _ir([{"type": "formula", "latex": "E = m c^2 / 2", "inline": False}])
    report = diff_ir(a, b)
    change = _change_for(report, "modified")
    assert change.block_type == "formula"
    assert change.block_ref_a.preview == "E = m c^2"


def test_diagram_added_and_removed():
    diagram = {
        "type": "diagram",
        "nodes": [{"id": "n1", "label": "输入"}, {"id": "n2", "label": "输出"}],
        "edges": [{"from": "n1", "to": "n2"}],
        "caption": "系统框图",
    }
    base = _ir([_h("H"), _p("body")])
    with_diagram = _ir([_h("H"), diagram, _p("body")])
    added = diff_ir(base, with_diagram)
    change = _change_for(added, "added")
    assert change.block_type == "diagram"
    assert change.block_ref_a is None
    assert change.block_ref_b.index == 1

    removed = diff_ir(with_diagram, base)
    change = _change_for(removed, "removed")
    assert change.block_type == "diagram"
    assert change.block_ref_b is None
    assert change.block_ref_a.index == 1


def test_diagram_modification_is_structural():
    a = _ir([
        {
            "type": "diagram",
            "nodes": [{"id": "n1", "label": "输入"}, {"id": "n2", "label": "输出"}],
            "edges": [{"from": "n1", "to": "n2"}],
        }
    ])
    b = _ir([
        {
            "type": "diagram",
            "nodes": [
                {"id": "n1", "label": "输入"},
                {"id": "n2", "label": "输出"},
                {"id": "n3", "label": "反馈"},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"}],
        }
    ])
    change = _change_for(diff_ir(a, b), "modified")
    assert change.block_type == "diagram"


def test_empty_ir_edges():
    empty = _ir([])
    one = _ir([_p("只有一段")])

    both_empty = diff_ir(empty, empty)
    assert both_empty.changes == []
    assert both_empty.summary.verdict == "unchanged"
    assert both_empty.summary.total_blocks == 0
    assert both_empty.summary.change_density == 0.0

    to_non_empty = diff_ir(empty, one)
    assert _by_op(to_non_empty)["added"] == 1
    assert to_non_empty.summary.blocks_a == 0
    assert to_non_empty.summary.change_density == 1.0
    assert to_non_empty.summary.verdict == "major"

    to_empty = diff_ir(one, empty)
    assert _by_op(to_empty)["removed"] == 1
    assert to_empty.summary.change_density == 1.0


# ---------------------------------------------------------------------------
# AC3 — similarity threshold boundaries
# ---------------------------------------------------------------------------


def _similarity(a_text: str, b_text: str) -> float:
    from graph2note.semantic.text import block_similarity

    return block_similarity(_ir([_p(a_text)]).blocks[0], _ir([_p(b_text)]).blocks[0])


def test_threshold_constant_is_explicit():
    assert 0.0 < MODIFIED_THRESHOLD < 1.0
    assert 0.0 < MINOR_MAX_DENSITY < 1.0


def test_similarity_at_threshold_is_modified_below_is_removed_added():
    # "a b c d" vs "a b x y" -> Dice overlap exactly 0.5 == MODIFIED_THRESHOLD.
    assert _similarity("a b c d", "a b x y") == pytest.approx(MODIFIED_THRESHOLD)

    at = _ir([_p("a b c d")])
    at_other = _ir([_p("a b x y")])
    report = diff_ir(at, at_other)
    assert _by_op(report)["modified"] == 1
    assert _change_for(report, "modified").similarity == pytest.approx(0.5)

    # "a b c d" vs "a x y z" -> Dice overlap exactly 0.25, below the threshold.
    assert _similarity("a b c d", "a x y z") == pytest.approx(0.25)
    below = _ir([_p("a x y z")])
    report = diff_ir(at, below)
    assert _by_op(report)["modified"] == 0
    assert _by_op(report)["removed"] == 1
    assert _by_op(report)["added"] == 1


def test_threshold_is_the_only_boundary(monkeypatch):
    # Raising the threshold flips the exactly-at-boundary pair to removed+added,
    # proving classification is driven by the constant (not a hidden epsilon).
    a = _ir([_p("a b c d")])
    b = _ir([_p("a b x y")])
    assert _by_op(diff_ir(a, b))["modified"] == 1
    monkeypatch.setattr(diff_mod, "MODIFIED_THRESHOLD", 0.5 + 0.01)
    report = diff_ir(a, b)
    assert _by_op(report)["modified"] == 0
    assert _by_op(report)["removed"] == 1 and _by_op(report)["added"] == 1


# ---------------------------------------------------------------------------
# AC5 — summary statistics + verdict rule table
# ---------------------------------------------------------------------------


def _replace_n_of(n_total: int, n_replace: int) -> tuple[DocumentIR, DocumentIR]:
    a_blocks = [_p(f"original block number {i}") for i in range(n_total)]
    b_blocks = list(a_blocks)
    for i in range(n_replace):
        b_blocks[i] = _p(f"totally unrelated content {'z' * (i + 1)}")
    return _ir(a_blocks), _ir(b_blocks)


def _modify_one_of(n_total: int) -> tuple[DocumentIR, DocumentIR]:
    a_blocks = [_p(f"common token alpha beta gamma {i}") for i in range(n_total)]
    b_blocks = list(a_blocks)
    b_blocks[-1] = _p(f"common token alpha beta delta {n_total - 1}")
    return _ir(a_blocks), _ir(b_blocks)


@pytest.mark.parametrize(
    "name,a,b,changed,density,verdict",
    [
        ("identical", _ir([_h("H"), _p("one")]), _ir([_h("H"), _p("one")]),
         0, 0.0, "unchanged"),
        ("both-empty", _ir([]), _ir([]), 0, 0.0, "unchanged"),
        ("one-replaced-of-five",
         *_replace_n_of(5, 1), 2, 0.2, "minor"),
        ("one-modified-of-two",
         *_modify_one_of(2), 1, 0.25, "minor"),
        ("one-modified-of-three",
         *_modify_one_of(3), 1, 1 / 6, "minor"),
        ("full-replace-two",
         _ir([_p("aaa bbb"), _p("ccc ddd")]),
         _ir([_p("xxx yyy"), _p("zzz www")]), 4, 1.0, "major"),
        ("empty-to-two", _ir([]), _ir([_p("one"), _p("two")]),
         2, 1.0, "major"),
    ],
)
def test_verdict_rule_table(name, a, b, changed, density, verdict):
    report = diff_ir(a, b)
    summary = report.summary
    assert summary.changed_blocks == changed, name
    assert summary.change_density == pytest.approx(round(density, 4)), name
    assert summary.verdict == verdict, name


def test_verdict_boundary_at_minor_max_density():
    # exactly MINOR_MAX_DENSITY => minor; just above => major.
    a, b = _modify_one_of(2)  # changed 1, total 4 => density 0.25
    report = diff_ir(a, b)
    assert report.summary.change_density == pytest.approx(MINOR_MAX_DENSITY)
    assert report.summary.verdict == "minor"

    a, b = _modify_one_of(3)
    a = _ir([_p("common token alpha beta gamma 0"),
             _p("common token alpha beta gamma 1"),
             _p("common token alpha beta gamma 2")])
    b = _ir([_p("common token alpha beta delta 0"),
             _p("common token alpha beta delta 1"),
             _p("common token alpha beta gamma 2")])
    report = diff_ir(a, b)
    assert report.summary.change_density == pytest.approx(round(2 / 6, 4))
    assert report.summary.change_density > MINOR_MAX_DENSITY
    assert report.summary.verdict == "major"


def test_summary_by_op_and_by_type_counts_are_consistent():
    a = _ir([_h("H"), _p("alpha beta gamma"), _p("first body")])
    b = _ir([_h("H changed"), _p("first body"), _p("alpha beta gamma"),
             {"type": "formula", "latex": "x = 1"}])
    report = diff_ir(a, b)
    assert report.summary.by_op == {
        "added": 1, "removed": 0, "modified": 1, "moved": 1, "unchanged": 1,
    }
    assert report.summary.by_type["heading"].modified == 1
    assert report.summary.by_type["paragraph"].moved == 1
    assert report.summary.by_type["paragraph"].unchanged == 1
    assert report.summary.by_type["formula"].added == 1
    # by_type totals equal the number of changes touching that type.
    for block_type, counts in report.summary.by_type.items():
        total = counts.added + counts.removed + counts.modified + counts.moved
        total += counts.unchanged
        assert total == sum(
            1 for c in report.changes if c.block_type == block_type
        )
    assert report.summary.total_blocks == report.summary.blocks_a + report.summary.blocks_b


def test_block_refs_are_traceable_and_anchored():
    a = _ir([_h("H"), _p("target paragraph"), _p("other")])
    b = _ir([_h("H"), _p("other"), _p("target paragraph edited")])
    report = diff_ir(a, b, label_a="ver-a", label_b="ver-b")
    assert report.label_a == "ver-a" and report.label_b == "ver-b"
    for change in report.changes:
        for ref in (change.block_ref_a, change.block_ref_b):
            if ref is not None:
                assert ref.anchor == f"block-{ref.index}"
                assert ref.block_type == change.block_type
        if change.op in ("modified", "moved", "unchanged"):
            assert change.block_ref_a is not None and change.block_ref_b is not None
        if change.op == "added":
            assert change.block_ref_a is None and change.block_ref_b is not None
        if change.op == "removed":
            assert change.block_ref_a is not None and change.block_ref_b is None
