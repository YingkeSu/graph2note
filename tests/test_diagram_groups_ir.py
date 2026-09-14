"""SPW D1: hierarchical diagram contract — IR groups/note/style + VLM prompt.

Covers the D1 brief (SPEC §1): the optional IR fields (``DiagramGroup``,
``Node.note``, ``Edge.style``, ``DiagramBlock/FlowBlock.groups``), their
backward compatibility, the upgraded vision prompt / parse path, and the
deterministic text-side group inference.

Everything here is offline: the vision gateway is stubbed at
``graph2note.diagram._post`` and the image is never read (the data-URL helper
is stubbed too).  Live VLM behaviour is explicitly out of scope.
"""

from __future__ import annotations

import json

import pytest

from graph2note import diagram, ir, vlm
from graph2note.diagrams import infer


def _doc(block: dict):
    return ir.load_dict_as_ir({"document_type": "note", "blocks": [block]})


# ---------------------------------------------------------------------------
# IR: backward compatibility + new optional fields
# ---------------------------------------------------------------------------


def test_old_ir_json_loads_with_new_defaults():
    doc = _doc({
        "type": "flow",
        "nodes": [{"id": "n1", "label": "A"}],
        "edges": [{"from": "n1", "to": "n2", "label": ""}],
    })
    block = doc.blocks[0]
    assert block.groups == []
    assert block.nodes[0].note is None
    assert block.edges[0].style == "solid"


def test_new_ir_json_roundtrips_unchanged():
    doc = _doc({
        "type": "diagram",
        "nodes": [
            {"id": "n1", "label": "Macmini", "note": "调研："},
            {"id": "n2", "label": "MacBook"},
        ],
        "edges": [{"from": "n1", "to": "n2", "style": "dashed"}],
        "groups": [
            {"id": "g1", "label": "通信层", "kind": "layer", "nodes": ["n2", "n1"]},
        ],
    })
    reloaded = ir.loads_ir(ir.dumps_ir(doc))
    assert reloaded.model_dump() == doc.model_dump()
    block = reloaded.blocks[0]
    assert block.nodes[0].note == "调研："
    assert block.edges[0].style == "dashed"
    # membership is normalized to node-appearance order by the extractor, not
    # by the IR itself; the IR preserves what it was given.
    assert block.groups[0].nodes == ["n2", "n1"]


@pytest.mark.parametrize("kind", ["layer", "lane", "cluster"])
def test_all_group_kinds_accepted(kind):
    doc = _doc({
        "type": "flow",
        "nodes": [{"id": "n1"}],
        "edges": [],
        "groups": [{"id": "g1", "label": "L", "kind": kind, "nodes": ["n1"]}],
    })
    assert doc.blocks[0].groups[0].kind == kind


def test_dangling_group_member_is_rejected():
    with pytest.raises(ir.IRValidationError) as exc:
        _doc({
            "type": "flow",
            "nodes": [{"id": "n1"}],
            "edges": [],
            "groups": [{"id": "g1", "label": "L", "nodes": ["n1", "ghost"]}],
        })
    assert "unknown node id 'ghost'" in str(exc.value)


def test_duplicate_group_id_is_rejected():
    with pytest.raises(ir.IRValidationError) as exc:
        _doc({
            "type": "flow",
            "nodes": [{"id": "n1"}],
            "edges": [],
            "groups": [
                {"id": "g1", "label": "A", "nodes": []},
                {"id": "g1", "label": "B", "nodes": []},
            ],
        })
    assert "duplicate diagram group id 'g1'" in str(exc.value)


def test_bad_group_kind_is_rejected():
    with pytest.raises(ir.IRValidationError) as exc:
        _doc({
            "type": "flow",
            "nodes": [{"id": "n1"}],
            "edges": [],
            "groups": [{"id": "g1", "label": "L", "kind": "bogus", "nodes": []}],
        })
    assert "kind" in str(exc.value)


def test_group_label_is_required():
    with pytest.raises(ir.IRValidationError) as exc:
        _doc({
            "type": "flow",
            "nodes": [{"id": "n1"}],
            "edges": [],
            "groups": [{"id": "g1", "nodes": []}],
        })
    assert "label" in str(exc.value)


def test_bad_edge_style_is_rejected():
    with pytest.raises(ir.IRValidationError) as exc:
        _doc({
            "type": "flow",
            "nodes": [{"id": "n1"}],
            "edges": [{"from": "n1", "to": "n1", "style": "wavy"}],
        })
    assert "style" in str(exc.value)


def test_root_extra_key_policy_unchanged():
    with pytest.raises(ir.IRValidationError) as exc:
        ir.loads_ir(json.dumps({"blocks": [], "surprise": 1}))
    assert "Extra inputs are not permitted" in str(exc.value)


def test_groups_are_visual_only_and_do_not_touch_topology():
    doc = _doc({
        "type": "flow",
        "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        "edges": [{"from": "n1", "to": "n2", "label": ""}],
        "groups": [{"id": "g1", "label": "L", "nodes": ["n1", "n2"]}],
    })
    block = doc.blocks[0]
    assert [(e.from_, e.to) for e in block.edges] == [("n1", "n2")]
    assert block.groups[0].nodes == ["n1", "n2"]


# ---------------------------------------------------------------------------
# diagram.py: upgraded VLM contract (prompt + validator)
# ---------------------------------------------------------------------------


def test_system_prompt_declares_hierarchy_contract():
    prompt = diagram.SYSTEM_PROMPT
    for token in ("groups", "note", "style", "dashed", "layer", "lane", "cluster"):
        assert token in prompt
    # honest empty is explicitly required, fabrication explicitly banned
    assert "严禁编造层次" in prompt
    assert "[]" in prompt


def test_validate_keeps_flat_contract_shape():
    payload, verdict = diagram.validate_diagram_json({
        "caption": "c",
        "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        "edges": [{"from": "n1", "to": "n2", "label": ""}],
    })
    assert verdict == "ok"
    assert payload["nodes"] == [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}]
    assert payload["edges"] == [{"from": "n1", "to": "n2", "label": ""}]
    assert payload["groups"] == []


def test_validate_preserves_note_and_dashed_style():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [
            {"id": "n1", "label": "A", "note": "  亮点：Critical Path 优化 ☆  "},
            {"id": "n2", "label": "B", "note": "   "},
        ],
        "edges": [{"from": "n1", "to": "n2", "style": "dashed"}],
    })
    assert verdict == "ok"
    assert payload["nodes"][0]["note"] == "亮点：Critical Path 优化 ☆"
    assert payload["nodes"][1] == {"id": "n2", "label": "B"}  # blank -> omitted
    assert payload["edges"][0]["style"] == "dashed"


def test_validate_normalizes_and_dedupes_group_members():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}],
        "edges": [],
        "groups": [{"id": "g1", "label": "L", "kind": "lane",
                    "nodes": ["n3", "n1", "n3"]}],
    })
    assert verdict == "ok"
    assert payload["groups"] == [
        {"id": "g1", "label": "L", "kind": "lane", "nodes": ["n1", "n3"]},
    ]


def test_validate_empty_groups_is_legal():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}], "edges": [], "groups": [],
    })
    assert verdict == "ok" and payload["groups"] == []


def test_validate_dangling_group_member_is_malformed():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}],
        "edges": [],
        "groups": [{"id": "g1", "label": "L", "nodes": ["ghost"]}],
    })
    assert payload is None and verdict == "malformed"


def test_validate_bad_group_kind_is_malformed():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}],
        "edges": [],
        "groups": [{"id": "g1", "label": "L", "kind": "swim", "nodes": []}],
    })
    assert payload is None and verdict == "malformed"


def test_validate_bad_edge_style_is_malformed():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}],
        "edges": [{"from": "n1", "to": "n1", "style": "dotted"}],
    })
    assert payload is None and verdict == "malformed"


def test_validate_self_loop_still_rejected():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}],
        "edges": [{"from": "n1", "to": "n1"}],
    })
    assert payload is None and verdict == "malformed"


def test_validate_duplicate_group_id_is_malformed():
    payload, verdict = diagram.validate_diagram_json({
        "nodes": [{"id": "n1"}],
        "edges": [],
        "groups": [
            {"id": "g1", "label": "A", "nodes": []},
            {"id": "g1", "label": "B", "nodes": []},
        ],
    })
    assert payload is None and verdict == "malformed"


# ---------------------------------------------------------------------------
# diagram.py: extraction path with a stubbed gateway
# ---------------------------------------------------------------------------


def _stub_gateway(monkeypatch, content: str) -> dict:
    captured: dict = {}

    def fake_post(payload, **_kw):
        captured["payload"] = payload
        return {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10},
            "cost": "0",
        }

    monkeypatch.setattr(diagram, "_post", fake_post)
    monkeypatch.setattr(vlm, "load_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(
        vlm, "image_data_url_downscaled", lambda _p: ("data:image/png;base64,AA==", 9)
    )
    return captured


def test_extract_sends_hierarchy_prompt_and_parses_groups(monkeypatch):
    content = json.dumps({
        "caption": "架构",
        "groups": [{"id": "g1", "label": "通信层", "kind": "layer",
                    "nodes": ["n1", "n2"]}],
        "nodes": [
            {"id": "n1", "label": "Macmini"},
            {"id": "n2", "label": "MacBook", "note": "调研："},
            {"id": "n3", "label": "方案讨论"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n3", "to": "n1", "label": "参考", "style": "dashed"},
        ],
    }, ensure_ascii=False)
    captured = _stub_gateway(monkeypatch, content)

    result = diagram.extract_diagram_image("page.png", session="s")

    assert result["ok"] is True and result["verdict"] == "ok"
    assert result["groups"] == [
        {"id": "g1", "label": "通信层", "kind": "layer", "nodes": ["n1", "n2"]},
    ]
    assert result["nodes"][1]["note"] == "调研："
    assert result["edges"][1]["style"] == "dashed"
    system = captured["payload"]["messages"][0]["content"]
    assert "groups" in system and "严禁编造层次" in system


def test_extract_no_hierarchy_yields_legal_empty_groups(monkeypatch):
    content = json.dumps({
        "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        "edges": [{"from": "n1", "to": "n2", "label": ""}],
    })
    _stub_gateway(monkeypatch, content)
    result = diagram.extract_diagram_image("page.png", session="s")
    assert result["ok"] is True
    assert result["groups"] == []


def test_extract_dangling_group_degrades_to_malformed(monkeypatch):
    content = json.dumps({
        "nodes": [{"id": "n1", "label": "A"}],
        "edges": [],
        "groups": [{"id": "g1", "label": "L", "nodes": ["ghost"]}],
    })
    _stub_gateway(monkeypatch, content)
    result = diagram.extract_diagram_image("page.png", session="s")
    assert result["ok"] is False
    assert result["verdict"] == "malformed"
    assert result["groups"] == []


# ---------------------------------------------------------------------------
# diagrams/infer.py: deterministic text-side groups
# ---------------------------------------------------------------------------


def test_parse_group_decl_variants():
    decl = infer.parse_group_decl("[layer] 通信层: Macmini、MacBook")
    assert decl == {"kind": "layer", "label": "通信层",
                    "members": ["Macmini", "MacBook"]}
    assert infer.parse_group_decl("- [lane] 执行层：A, B, C")["kind"] == "lane"
    assert infer.parse_group_decl("[cluster] 局部：A|B")["members"] == ["A", "B"]
    assert infer.parse_group_decl("普通段落") is None


def test_infer_graph_from_lines_resolves_groups():
    lines = [
        "[layer] 通信层: Macmini、MacBook",
        "Macmini → MacBook",
        "MacBook → 执行层",
    ]
    nodes, edges, groups = infer.infer_graph_from_lines(lines)
    assert [n["label"] for n in nodes] == ["Macmini", "MacBook", "执行层"]
    assert groups == [{"id": "g1", "label": "通信层", "kind": "layer",
                       "nodes": ["n1", "n2"]}]
    assert len(edges) == 2


def test_infer_graph_never_fabricates_groups():
    nodes, edges, groups = infer.infer_graph_from_lines(["A → B", "B → C"])
    assert groups == []
    assert len(nodes) == 3 and len(edges) == 2


def test_infer_graph_drops_unresolvable_members():
    _, _, groups = infer.infer_graph_from_lines(
        ["[cluster] 局部: A, 不存在", "A → B"]
    )
    assert groups[0]["nodes"] == ["n1"]


def test_infer_graph_group_members_are_deterministic():
    a = infer.infer_graph_from_lines(["[layer] L: B, A", "A → B"])
    b = infer.infer_graph_from_lines(["[layer] L: A, B", "A → B"])
    assert a[2] == b[2]


def test_arrow_flow_block_emits_groups_and_schema():
    block = infer.arrow_flow_block(
        ["[layer] L: A", "A → B"], 0
    )
    assert block["type"] == "flow"
    assert block["groups"] == [{"id": "g1", "label": "L", "kind": "layer",
                                "nodes": ["n1"]}]


def test_relation_lines_collects_group_declarations():
    lines = ["# 架构", "[layer] L: A", "A → B", "说明文字"]
    assert infer.relation_lines(lines) == ["[layer] L: A", "A → B"]


def test_detect_diagram_markdown_recognizes_group_decl():
    assert infer.detect_diagram_markdown("[layer] 通信层: Macmini, MacBook")
    assert not infer.detect_diagram_markdown("这是一段没有结构的纯文本。")


def test_infer_flow_from_lines_stays_backward_compatible():
    assert infer.infer_flow_from_lines(["A → B"]) == (
        [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        [{"from": "n1", "to": "n2", "label": ""}],
    )


# ---------------------------------------------------------------------------
# Offline fixtures for the (corrected) SPEC §1 acceptance anchors
#
# These are *expected VLM outputs*, validated through the same contract the
# live extractor uses.  They document how 01/02/02-increment must be shaped for
# D2/D3; they do not attempt a live call.
# ---------------------------------------------------------------------------


_ANCHOR_01 = {
    "caption": "01 需求/架构",
    "groups": [
        {"id": "g1", "label": "层间通信", "kind": "layer",
         "nodes": ["n1", "n2", "n3"]},
        {"id": "g2", "label": "通信层", "kind": "layer", "nodes": ["n4"]},
        {"id": "g3", "label": "执行层", "kind": "layer", "nodes": ["n5"]},
    ],
    "nodes": [
        {"id": "n1", "label": "Macmini"},
        {"id": "n2", "label": "MacBook"},
        {"id": "n3", "label": "Windows laptop"},
        {"id": "n4", "label": "Tiger VNC"},
        {"id": "n5", "label": "360 Linux"},
        # right-hand prose area: annotation only, never a peer graph node
        {"id": "n6", "label": "通信方案",
         "note": "亮点：Critical Path 优化 ☆"},
    ],
    "edges": [{"from": "n1", "to": "n4", "style": "dashed"}],
}


def test_anchor_01_yields_layered_groups_and_note_not_flat_nodes():
    payload, verdict = diagram.validate_diagram_json(_ANCHOR_01)
    assert verdict == "ok"
    groups = payload["groups"]
    assert [g["kind"] for g in groups] == ["layer", "layer", "layer"]
    assert len(groups) >= 2
    members = {m for g in groups for m in g["nodes"]}
    assert {"n1", "n2", "n3"} <= members  # macmini/macbook/windows laptop
    # the prose text lives as a note, not as a same-level node label
    assert all("Critical Path" not in n["label"] for n in payload["nodes"])
    assert payload["nodes"][-1]["note"] == "亮点：Critical Path 优化 ☆"
    # and it round-trips into a valid IR block
    doc = _doc({"type": "flow", **payload})
    assert len(doc.blocks[0].groups) == 3


_ANCHOR_02 = {
    "caption": "02 数字化管线",
    "groups": [
        {"id": "g1", "label": "阶段主线", "kind": "cluster",
         "nodes": ["n1", "n2", "n3"]},
    ],
    "nodes": [
        {"id": "n1", "label": "输入"},
        {"id": "n2", "label": "预处理"},
        {"id": "n3", "label": "矢量化", "note": "设计：标注规范"},
        {"id": "n4", "label": "调研：方案选型"},
    ],
    "edges": [
        {"from": "n1", "to": "n2", "label": ""},
        {"from": "n2", "to": "n3", "label": ""},
        {"from": "n4", "to": "n2", "label": "参考", "style": "dashed"},
    ],
}


def test_anchor_02_notes_use_note_and_dashed_weak_links():
    payload, verdict = diagram.validate_diagram_json(_ANCHOR_02)
    assert verdict == "ok"
    # main flow stays solid and directed
    main = [e for e in payload["edges"] if e.get("style") != "dashed"]
    assert [e["from"] for e in main] == ["n1", "n2"]
    # annotation is separated: note text + dashed weak link
    notes = [n["note"] for n in payload["nodes"] if n.get("note")]
    assert any("设计" in t for t in notes)
    assert any(e.get("style") == "dashed" for e in payload["edges"])
    labels = [n["label"] for n in payload["nodes"] if "调研" not in n["label"]]
    assert labels  # the annotation did not become a main-flow peer label


_ANCHOR_02_INCREMENT = {
    "caption": "02 增量：原子/增量两侧",
    "groups": [
        {"id": "g1", "label": "原子流程", "kind": "lane",
         "nodes": ["n1", "n2"]},
        {"id": "g2", "label": "增量流程", "kind": "lane",
         "nodes": ["n3", "n4"]},
    ],
    "nodes": [
        {"id": "n1", "label": "原子输入"},
        {"id": "n2", "label": "原子输出"},
        {"id": "n3", "label": "增量输入"},
        {"id": "n4", "label": "增量输出"},
    ],
    "edges": [
        {"from": "n1", "to": "n2", "label": ""},
        {"from": "n3", "to": "n4", "label": ""},
    ],
}


def test_anchor_02_increment_keeps_two_distinguishable_sides():
    payload, verdict = diagram.validate_diagram_json(_ANCHOR_02_INCREMENT)
    assert verdict == "ok"
    sides = [set(g["nodes"]) for g in payload["groups"]]
    assert len(sides) == 2
    assert sides[0].isdisjoint(sides[1])
    assert sides[0] | sides[1] == {"n1", "n2", "n3", "n4"}
