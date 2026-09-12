"""Offline tests for the S3 version-comparison payload (pure + store fixture).

The backend adds **no new diff logic**: ``build_compare`` calls S1's
:func:`graph2note.semantic.diff_ir` and reuses S2's version chain.  These tests
pin the two red lines of the issue:

* the templated summary is string assembly over the S1 numbers — **zero model
  calls** (the module is monkeypatched so any gateway/VLM call would explode);
* the statistics in the summary are the *same* DiffReport numbers the UI shows
  (same fixture, direct engine comparison).
"""

from __future__ import annotations

import json

import pytest

from graph2note import evolution
from graph2note import versiondiff
from graph2note.semantic import diff_ir
from graph2note.semantic.cli import load_version_ir
from graph2note.store import FileDocumentStore, SessionDocumentStore
from graph2note import vlm


def _dump(blocks: list[dict]) -> str:
    return json.dumps({"document_type": "note", "blocks": blocks}, ensure_ascii=False)


def _seed(store, document_id: str, blocks: list[dict], markdown: str, *, provenance=None):
    extra = {}
    if provenance is not None:
        extra["provenance"] = provenance
    store.save_document(
        document_id=document_id,
        title="手稿",
        source_job_id=f"job-{document_id}",
        model="fixture-model",
        markdown=markdown,
        ir_json=_dump(blocks),
        original_path="",
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
        pg_hash="0" * 16,
        **extra,
    )


V1_BLOCKS = [
    {"type": "heading", "level": 1, "text": "绪论"},
    {"type": "paragraph", "text": "第一版原文"},
    {"type": "formula", "latex": "E = m c^2", "inline": False},
]
V2_BLOCKS = [
    {"type": "heading", "level": 1, "text": "绪论"},
    {"type": "paragraph", "text": "第二版改写"},
    {"type": "formula", "latex": "E = m c^2", "inline": False},
    {"type": "paragraph", "text": "新增段落"},
]


@pytest.fixture()
def two_versions(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-x", V1_BLOCKS, "# 绪论\n\n第一版原文\n")
    _seed(store, "doc-x", V2_BLOCKS, "# 绪论\n\n第二版改写\n\n新增段落\n")
    return store


# ---------------------------------------------------------------------------
# templated summary (pure, zero model)
# ---------------------------------------------------------------------------


def test_summarize_diff_empty_state():
    summary = {
        "blocks_a": 2, "blocks_b": 2, "total_blocks": 4, "changed_blocks": 0,
        "change_density": 0.0, "by_op": {}, "by_type": {}, "verdict": "unchanged",
    }
    assert versiondiff.summarize_diff(summary) == ["两版内容一致，无块级变更。"]


def test_summarize_diff_numbers_come_from_the_report(two_versions):
    payload = versiondiff.build_compare(two_versions, "doc-x")
    report = payload["report"]
    lines = payload["summary_lines"]
    assert payload["empty"] is False
    # verdict sentence carries changed/total and the density straight from S1
    summary = report["summary"]
    head = lines[0]
    assert f"{summary['changed_blocks']}/{summary['total_blocks']}" in head
    assert f"{summary['change_density']:.2f}" in head
    # every per-op line only contains numbers the report itself reports
    for op in ("modified", "added", "removed", "moved"):
        if not summary["by_op"].get(op):
            continue
        prefix = versiondiff.op_label(op) + "："
        line = next(line for line in lines[1:] if line.startswith(prefix))
        for block_type, counts in summary["by_type"].items():
            count = counts.get(op, 0)
            if count:
                assert f"{count} 个{versiondiff.block_type_label(block_type)}" in line


def test_summarize_diff_is_pure_string_assembly():
    summary = {
        "blocks_a": 3, "blocks_b": 3, "total_blocks": 6, "changed_blocks": 3,
        "change_density": 0.5, "verdict": "major",
        "by_op": {"added": 1, "removed": 1, "modified": 1, "moved": 1, "unchanged": 0},
        "by_type": {
            "paragraph": {"added": 1, "removed": 1, "modified": 1, "moved": 1, "unchanged": 0},
        },
    }
    lines = versiondiff.summarize_diff(summary)
    assert lines[0].startswith("整体判定：较大改动")
    assert "修改：1 个段落" in lines
    assert "新增：1 个段落" in lines
    assert "删除：1 个段落" in lines
    assert "移动：1 个段落" in lines


# ---------------------------------------------------------------------------
# build_compare (same-fixture assertions against the raw engine)
# ---------------------------------------------------------------------------


def test_compare_payload_matches_diff_ir_exactly(two_versions):
    """AC3: the UI stats are the S1 DiffReport — asserted on the same fixture."""
    payload = versiondiff.build_compare(two_versions, "doc-x")
    record = two_versions.get_document("doc-x")
    ids = [version["version_id"] for version in record["versions"]]
    ir_a = load_version_ir(two_versions, "doc-x", ids[0])
    ir_b = load_version_ir(two_versions, "doc-x", ids[1])
    expected = diff_ir(ir_a, ir_b, label_a=ids[0], label_b=ids[1])
    assert payload["report"] == expected.model_dump()
    assert payload["summary_lines"] == versiondiff.summarize_diff(expected.summary)


def test_compare_defaults_to_latest_versus_previous(two_versions):
    payload = versiondiff.build_compare(two_versions, "doc-x")
    assert payload["a"]["version_id"] != payload["b"]["version_id"]
    assert payload["b"]["is_current"] is True
    assert payload["a"]["is_history"] is True
    assert payload["b"]["version_id"] == payload["latest_version_id"]


def test_compare_blocks_carry_s1_anchors_and_rendered_markdown(two_versions):
    payload = versiondiff.build_compare(two_versions, "doc-x")
    for side in ("a", "b"):
        blocks = payload[side]["blocks"]
        assert blocks, side
        for index, block in enumerate(blocks):
            assert block["index"] == index
            assert block["anchor"] == f"block-{index}"
            assert block["type"] == block["type"]
            assert block["markdown"] != "" or block["type"] == "image"
    assert payload["a"]["blocks"][0]["markdown"] == "# 绪论"
    assert "E = m c^2" in payload["a"]["blocks"][2]["markdown"]
    # block types line up with the DiffReport's refs
    for change in payload["report"]["changes"]:
        if change["block_ref_a"] is not None:
            block = payload["a"]["blocks"][change["block_ref_a"]["index"]]
            assert block["anchor"] == change["block_ref_a"]["anchor"]
            assert block["type"] == change["block_ref_a"]["block_type"]


def test_compare_arbitrary_pair_and_same_version(two_versions):
    record = two_versions.get_document("doc-x")
    v1, v2 = (version["version_id"] for version in record["versions"])

    reversed_pair = versiondiff.build_compare(two_versions, "doc-x", version_a=v2, version_b=v1)
    assert reversed_pair["a"]["version_id"] == v2
    assert reversed_pair["b"]["version_id"] == v1
    # stats are symmetric at the op level even though labels swap
    forward = versiondiff.build_compare(two_versions, "doc-x", version_a=v1, version_b=v2)
    assert reversed_pair["report"]["summary"]["changed_blocks"] == \
        forward["report"]["summary"]["changed_blocks"]

    same = versiondiff.build_compare(two_versions, "doc-x", version_a=v1, version_b=v1)
    assert same["same_version"] is True
    assert same["empty"] is True
    assert same["summary_lines"] == ["两版内容一致，无块级变更。"]
    assert same["a"]["version_id"] == same["b"]["version_id"]


def test_compare_single_version_is_safe(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-one", V1_BLOCKS, "# 绪论\n\n第一版原文\n")
    payload = versiondiff.build_compare(store, "doc-one")
    assert payload["single_version"] is True
    assert payload["count"] == 1
    assert payload["a"]["version_id"] == payload["b"]["version_id"]
    assert payload["empty"] is True


def test_compare_empty_chain_is_safe(tmp_path):
    store = SessionDocumentStore(tmp_path / "storage")
    _seed(store, "doc-empty", [], "")
    # save_document always creates one version; drop it for the empty-chain case
    record = store.get_document("doc-empty")
    record["versions"] = []
    payload = versiondiff.build_compare(store, "doc-empty")
    assert payload["count"] == 0
    assert payload["a"] is None and payload["b"] is None
    assert payload["summary_lines"] == ["暂无版本记录，无法对比。"]


def test_compare_unknown_document_and_version(two_versions):
    assert versiondiff.build_compare(two_versions, "nope") is None
    with pytest.raises(versiondiff.VersionDiffError):
        versiondiff.build_compare(two_versions, "doc-x", version_a="v-does-not-exist")
    with pytest.raises(versiondiff.VersionDiffError):
        versiondiff.build_compare(two_versions, "doc-x", version_b="9")


def test_compare_includes_the_uncommitted_edit_head(two_versions):
    two_versions.save_edits("doc-x", "# 绪论\n\n第三版手改内容\n")
    payload = versiondiff.build_compare(two_versions, "doc-x")
    assert payload["b"]["is_edit"] is True
    assert payload["b"]["version_id"] == versiondiff.EDIT_VERSION_ID
    assert payload["b"]["is_current"] is True
    assert payload["empty"] is False
    assert payload["b"]["blocks"][1]["preview"] == "第三版手改内容"


def test_compare_makes_no_model_calls(two_versions, monkeypatch):
    """AC3 red line: templated summary + deterministic IR projection only."""

    def _boom(*_args, **_kwargs):  # pragma: no cover - only fires on regression
        raise AssertionError("version comparison must not call a model")

    monkeypatch.setattr(vlm, "call_ir", _boom)
    # the compare pipeline must work end to end (working-copy projection included)
    two_versions.save_edits("doc-x", "# 绪论\n\n手改\n")
    payload = versiondiff.build_compare(two_versions, "doc-x")
    assert payload["report"]["summary"]["verdict"] in ("minor", "major", "unchanged")


def test_versiondiff_module_has_no_network_or_model_imports():
    """Static guarantee: the compare backend imports no LLM/network transport."""
    from pathlib import Path

    import graph2note

    source = (Path(graph2note.__file__).parent / "versiondiff.py").read_text(encoding="utf-8")
    for forbidden in ("eval.gateway", "llm_settings", "urllib", "requests", "httpx"):
        assert forbidden not in source, forbidden


def test_resolve_selector_vocabulary(two_versions):
    chain = evolution.build_version_chain(two_versions, "doc-x")
    ids = [entry["version_id"] for entry in chain["versions"]]
    assert versiondiff.resolve_selector(chain, None) == ids[-1]
    assert versiondiff.resolve_selector(chain, "latest") == ids[-1]
    assert versiondiff.resolve_selector(chain, "prev") == ids[-2]
    assert versiondiff.resolve_selector(chain, "0") == ids[0]
    assert versiondiff.resolve_selector(chain, ids[0]) == ids[0]
    assert versiondiff.resolve_selector(chain, "missing") is None
