"""U4 review fix — offline DOM contract for graph interaction.

Runs the real ``views/graph.js`` under a minimal Node DOM shim
(``tests/graph_interaction.mjs``) against an exact ``build_graph`` payload, so
the two review blockers are asserted without a browser and without network:

* U4-1  drag-pan stays linear across >=5 ``pointermove`` events (the previous
  evidence dispatched one event and could not see the quadratic feedback).
* U4-2  a single click navigates topic/tag/collection nodes to their library
  route, while documents first enter the focus state.

The test skips only when ``node`` is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from graph2note.graph import build_graph

TESTS_DIR = Path(__file__).parent
HARNESS = TESTS_DIR / "graph_interaction.mjs"
DRAG_STEPS = 6


def _payload() -> dict:
    records = []
    for index in range(26):
        records.append({
            "document_id": f"d{index:02d}",
            "title": f"文档 {index}",
            "topics": [["数学", "物理", "化学"][index % 3]],
            "tags": ["重点" if index % 2 == 0 else "草稿"],
            "manual_collections": ["research"] if index < 3 else [],
            "collection_names": {"research": "研究"} if index < 3 else {},
            "manual_relations": [],
        })
    return build_graph(records)


@pytest.fixture(scope="module")
def summary() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node 未安装")
    payload = _payload()
    proc = subprocess.run(
        ["node", str(HARNESS)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return json.loads(proc.stdout)


def test_drag_pan_is_linear_over_multiple_pointermove_events(summary):
    detail = summary["details"]["drag_pan_is_linear_across_many_pointermoves"]
    assert summary["checks"]["drag_pan_is_linear_across_many_pointermoves"] is True
    assert detail["steps"] >= DRAG_STEPS >= 5
    # each event adds the same bounded delta: a quadratic feedback loop (the
    # reviewed bug) makes the increment grow with the event index.
    increments = [
        round(detail["panX"][i] - detail["panX"][i - 1], 6)
        for i in range(1, detail["steps"])
    ]
    assert increments == [-20] * (detail["steps"] - 1)
    assert detail["stepIncrement"] == {"x": -20, "y": -10}
    assert detail["total"] == {"x": -20 * detail["steps"], "y": -10 * detail["steps"]}
    # grab semantics: the content follows the pointer, so the pan runs opposite.
    assert detail["total"]["x"] < 0 and detail["total"]["y"] < 0


def test_single_click_navigation_for_document_topic_tag(summary):
    details = summary["details"]
    assert summary["checks"]["document_click_focuses_then_navigates"] is True
    assert summary["checks"]["topic_and_tag_click_navigate_directly"] is True

    document = details["document_click_focuses_then_navigates"]
    assert document["focusId"].startswith("document:")
    assert document["route"].startswith("#doc/")

    kinds = details["topic_and_tag_click_navigate_directly"]
    assert set(kinds) == {"topic", "tag", "collection"}
    for kind, info in kinds.items():
        assert info["nodeId"].startswith(f"{kind}:"), kind
        assert info["route"].startswith("#library/"), kind
        assert info["focusId"] is None, f"{kind} single click must not focus"


def test_cluster_keyboard_expand_toggle_feedback_and_tooltip(summary):
    detail = summary["details"]["cluster_keyboard_expand_and_toggle_feedback"]
    assert summary["checks"]["cluster_keyboard_expand_and_toggle_feedback"] is True
    assert detail["after"] > detail["before"]
    assert detail["collapsedLabel"] == "聚类收敛"
    assert detail["expandedLabel"] == "聚类展开"


def test_zoom_anchor_uses_rendered_cluster_layout(summary):
    detail = summary["details"]["zoom_button_anchor_uses_rendered_layout"]
    assert summary["checks"]["zoom_button_anchor_uses_rendered_layout"] is True
    # the collapsed view re-solves the aggregate positions, so its rendered
    # layout differs from the pre-cluster one; the zoom anchor must use the
    # former (U4-6).
    assert detail["collapsed"] != detail["expanded"]
