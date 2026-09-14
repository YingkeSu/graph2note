"""SPW D1 seam test: extract -> _merge_visual_graph -> IR keeps groups.

Stub-driven end-to-end proof for the authorized minimal ``vlm.py`` change
(territory deviation, see handoff): ``extract_diagram_image`` returns optional
``groups``; ``vlm._merge_visual_graph`` must forward them into the appended
``flow`` block so they survive IR validation.  Offline only — the gateway and
image helper are stubbed.
"""

from __future__ import annotations

import json

from graph2note import diagram, ir, vlm
from graph2note.diagrams import infer


def test_extract_image_hierarchy_survives_merge_into_ir(monkeypatch):
    content = json.dumps({
        "caption": "01 需求/架构",
        "groups": [
            {"id": "g1", "label": "层间通信", "kind": "layer",
             "nodes": ["n2", "n1"]},
            {"id": "g2", "label": "执行层", "kind": "layer", "nodes": ["n3"]},
        ],
        "nodes": [
            {"id": "n1", "label": "Macmini"},
            {"id": "n2", "label": "MacBook"},
            {"id": "n3", "label": "360 Linux", "note": "亮点：Critical Path 优化 ☆"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n1", "to": "n3", "label": "旁注", "style": "dashed"},
        ],
    }, ensure_ascii=False)

    def fake_post(_payload, **_kw):
        return {"choices": [{"message": {"content": content},
                             "finish_reason": "stop"}],
                "usage": {}, "cost": "0"}

    monkeypatch.setattr(diagram, "_post", fake_post)
    monkeypatch.setattr(vlm, "load_api_key", lambda *a, **k: "k")
    monkeypatch.setattr(
        vlm, "image_data_url_downscaled", lambda _p: ("data:image/png;base64,AA==", 9)
    )

    # the image extractor already normalizes member order deterministically
    result = diagram.extract_diagram_image("page.png", session="s")
    assert result["ok"] is True
    assert result["groups"][0]["nodes"] == ["n1", "n2"]

    markdown = "架构图\nMacmini → MacBook\n"
    assert infer.detect_diagram_markdown(markdown)
    text_ir = json.dumps({"document_type": "note", "blocks": []})
    merged, meta = vlm._merge_visual_graph(
        text_ir, markdown, "page.png",
        model="m", api_key="k", session="s", timeout=1,
    )
    assert meta["verdict"] == "ok"

    obj = vlm.parse_ir_json(merged)
    flow = [b for b in obj["blocks"] if b["type"] == "flow"][0]
    assert flow["groups"] == result["groups"]

    doc = ir.load_dict_as_ir(obj)
    block = [b for b in doc.blocks if b.type == "flow"][0]
    assert [g.label for g in block.groups] == ["层间通信", "执行层"]
    assert block.groups[0].kind == "layer"
    assert block.groups[0].nodes == ["n1", "n2"]
    assert block.nodes[2].note == "亮点：Critical Path 优化 ☆"
    assert block.edges[1].style == "dashed"


def test_merge_defaults_to_empty_groups_for_legacy_extractor(monkeypatch):
    """A legacy result without ``groups`` must still produce a valid IR block."""
    monkeypatch.setattr(
        diagram,
        "extract_diagram_image",
        lambda *a, **k: {
            "ok": True, "verdict": "ok", "caption": "c",
            "nodes": [{"id": "n1", "label": "A"}], "edges": [],
            "meta": {"model": "m", "attempts": []},
        },
    )
    text_ir = json.dumps({"document_type": "note", "blocks": []})
    merged, _ = vlm._merge_visual_graph(
        text_ir, "架构图", "page.png",
        model="m", api_key="k", session="s", timeout=1,
    )
    doc = ir.load_dict_as_ir(vlm.parse_ir_json(merged))
    block = [b for b in doc.blocks if b.type == "flow"][0]
    assert block.groups == []
