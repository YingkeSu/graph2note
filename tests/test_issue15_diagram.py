"""Issue 15: production-line diagram extraction & reconstruction (FR-009 E2E) —
offline tests (fake gateway / deterministic inference).  No network anywhere.

AC coverage:
  AC1  test-images/01 architecture E2E -> flow block with nodes/edges, rendered
       asset embedded in .md, three-pane UI attachables (attachment completeness).
  AC2  6 representative flowchart transcriptions >= 4 yield structured blocks.
  AC3  pure-text `A → B` (no image) -> deterministic flow block.
  AC4  extraction-empty / unparseable -> degrade, E2E never fails (no mojibake).
  AC5  all offline, no live calls; productized image extractor tested w/ fake gw.
  AC6  same semantics render byte-identical PNGs (FR-020 determinism).
"""

import json
from pathlib import Path

import pytest

pytest.importorskip("PIL")

from graph2note import diagram, ir, pipeline, render, vlm  # noqa: E402
from graph2note.diagrams import infer  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IMG01 = ROOT / "test-images" / "01-requirements-arch.jpg"

EMPTY_IR = json.dumps({"document_type": "note", "blocks": []})


def _gw_fake(stage1_markdown):
    """post_gateway fake: image+text payload -> stage-1 markdown; text -> IR."""

    def fake(payload, **_kw):
        last = payload["messages"][-1]["content"]
        if isinstance(last, list):
            content = stage1_markdown
            return {"choices": [{"message": {"content": content},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 100,
                              "total_tokens": 200},
                    "cost": "0"}
        # stage-2 text->IR uses the deterministic parser (no gateway call), but
        # a fake still answers harmlessly if invoked.
        return {"choices": [{"message": {"content": EMPTY_IR},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 1,
                          "total_tokens": 101},
                "cost": "0"}

    return fake


# ---------------- AC3: deterministic text-side inference ----------------

def test_markdown_to_ir_arrow_chain_becomes_flow():
    ir_str, _ = vlm._ir_from_markdown("A → B\nB → C\nC → D\n", "x",
                                      key="k", sess="s", max_tokens=100,
                                      timeout=30)
    obj = vlm.parse_ir_json(ir_str)
    flows = [b for b in obj["blocks"] if b["type"] in ("flow", "diagram")]
    assert len(flows) == 1
    assert len(flows[0]["nodes"]) == 4
    assert len(flows[0]["edges"]) == 3
    # edges reference node ids, valid IR; the flow block is appended at the end
    doc = ir.load_dict_as_ir(obj)
    flow = [b for b in doc.blocks if b.type == "flow"][0]
    assert flow.edges[0].from_ == "n1"


def test_markdown_to_ir_architecture_text():
    md = "# 层间通信\n第一层 → 第二层\n第二层 → 360 Linux\n"
    ir_str, _ = vlm._ir_from_markdown(md, "x", key="k", sess="s",
                                      max_tokens=100, timeout=30)
    obj = vlm.parse_ir_json(ir_str)
    blocks = obj["blocks"]
    assert blocks[0]["type"] == "heading"
    assert any(b["type"] == "flow" and b["nodes"] for b in blocks)


def test_relation_unparseable_preserves_caption():
    # relation-like line that can't be structured -> caption-only diagram block
    ir_str, _ = vlm._ir_from_markdown("→ → →\n", "x", key="k", sess="s",
                                      max_tokens=100, timeout=30)
    obj = vlm.parse_ir_json(ir_str)
    diag = [b for b in obj["blocks"] if b["type"] == "diagram"]
    assert diag
    blk = diag[0]
    assert blk["nodes"] == [] and blk["edges"] == []
    assert blk["caption"]


def test_non_relation_line_stays_paragraph():
    ir_str, _ = vlm._ir_from_markdown("普通段落文字，不含箭头。\n", "x",
                                      key="k", sess="s", max_tokens=100,
                                      timeout=30)
    obj = vlm.parse_ir_json(ir_str)
    assert obj["blocks"][0]["type"] == "paragraph"


def test_detect_diagram_markdown():
    assert infer.detect_diagram_markdown("第一层 → 第二层")
    assert infer.detect_diagram_markdown("# 架构图")
    assert infer.detect_diagram_markdown("flow: 输入 → 输出")
    assert not infer.detect_diagram_markdown("这是纯文本，没有图表。")
    assert not infer.detect_diagram_markdown("")


# ---------------- AC2: eval-style flowchart transcriptions ----------------

# 6 representative flowchart page transcriptions (style of eval A13/flowchart,
# as the stage-1 VLM produces for real flowchart scans).
_FLOWCHARTS = [
    "开始\n输入 → 预处理\n预处理 → 特征提取\n特征提取 → 分类\n分类 → 输出\n结束",       # chain (structured)
    "开始 → A\nA → B\nB → C\nC → 结束",                                              # chain (structured)
    "读取数据\n数据 → 清洗\n清洗 → 建模\n建模 → 评估\n评估 → 部署",                      # chain (structured)
    "入口 → 权限检查\n权限检查 → 业务处理\n业务处理 → 日志\n日志 → 出口",                 # chain (structured)
    "用户 → 鉴权\ngateway → 路由\n路由 → 服务",                                        # (structured, 3 lines runs)
    "一些描述性的段落，没有明确的节点箭头关系，只有文字说明。",                          # no diagram
]


def test_eval_flowchart_pages_mostly_structured():
    structured = 0
    for md in _FLOWCHARTS:
        ir_str, _ = vlm._ir_from_markdown(md, "x", key="k", sess="s",
                                          max_tokens=100, timeout=30)
        obj = vlm.parse_ir_json(ir_str)
        has_struct = any(
            b["type"] in ("flow", "diagram") and b["nodes"] for b in obj["blocks"]
        )
        if has_struct:
            structured += 1
    assert structured >= 4  # AC2: >=4 of 6 yield structured diagram blocks


# ---------------- AC1: test-images/01 E2E (offline fake gateway) ----------------

def test_img01_e2e_produces_structured_flow_asset(tmp_path, monkeypatch):
    # stage-1 markdown faithfully transcribes the 01 architecture board the way
    # the VLM would (actor boxes + arrow directions), per MARKDOWN_USER_PROMPT.
    markdown = (
        "# 架构\n"
        "# 层间通信\n"
        "- Account\n"
        "第一层 → 第二层\n"
        "- 第二层：Macmini、TeirEval 执行\n"
        "任务图 → 节点图\n"
        "- 360 Linux\n"
        "Windows → Mac：Ragget TS\n"
    )
    monkeypatch.setattr(vlm, "post_gateway", _gw_fake(markdown))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")

    result = pipeline.parse_document(
        str(IMG01), str(tmp_path / "out"), model="glm-5.3-flash"
    )
    flow_blocks = [b for b in result.ir.blocks
                   if b.type in ("diagram", "flow")]
    assert flow_blocks and all(b.nodes and b.edges for b in flow_blocks)
    md = Path(result.markdown_path).read_text(encoding="utf-8")
    assert "assets/" in md
    assert "架构" in md
    # every image reference has a written asset (three-pane UI sees real images)
    from graph2note.attachments import missing_attachments
    assert missing_attachments(md, result.assets_dir) == []


def test_img01_authentic_transcription_yields_structured_flow(tmp_path, monkeypatch):
    """AC1 (authentic): real glm-5.3-flash transcription of test-images/01
    (recorded golden, no network) -> structured diagram blocks with nodes/edges.
    """
    rec = json.loads(
        (Path(__file__).parent / "golden" / "img01-diagram-stage1.golden.json")
        .read_text(encoding="utf-8")
    )
    monkeypatch.setattr(vlm, "post_gateway", _gw_fake(rec["stage1_markdown"]))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")

    result = pipeline.parse_document(
        str(IMG01), str(tmp_path / "out"), model="glm-5.3-flash"
    )
    flow_blocks = [b for b in result.ir.blocks if b.type in ("diagram", "flow")]
    assert flow_blocks                              # this image is a diagram page
    assert any(b.nodes and b.edges for b in flow_blocks)
    md = Path(result.markdown_path).read_text(encoding="utf-8")
    assert "assets/" in md
    from graph2note.attachments import missing_attachments
    assert missing_attachments(md, result.assets_dir) == []


# ---------------- AC4: degrade path (empty / unparseable never fails) --------

def test_degrade_caption_only_block_renders_placeholder(tmp_path):
    doc = ir.load_dict_as_ir({
        "document_type": "note",
        "blocks": [{"type": "diagram", "nodes": [], "edges": [],
                    "caption": "→ → →", "source": None}],
    })
    from graph2note.attachments import FileAssetWriter, missing_attachments
    root = tmp_path / "assets"
    writer = FileAssetWriter(str(root), doc_id="d")
    md = render.render_markdown(doc, doc_id="d", attachment_writer=writer)
    assert (root / "assets" / "d-diagram-0.png").exists()  # blank placeholder written
    assert missing_attachments(md, str(root)) == []


# ---------------- AC5: productized image extractor (fake gateway) ------------

def test_extract_diagram_image_ok(monkeypatch):
    good = json.dumps({
        "caption": "抽取的网络",
        "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        "edges": [{"from": "n1", "to": "n2", "label": ""}],
    })

    def fake_gw(payload, **_kw):
        return {"choices": [{"message": {"content": good},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20,
                          "total_tokens": 120},
                "cost": "0"}

    monkeypatch.setattr("graph2note.diagram._post", lambda payload, **k: fake_gw(payload))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    res = diagram.extract_diagram_image(str(IMG01), session="s")
    assert res["ok"] is True and res["verdict"] == "ok"
    assert res["nodes"] == [{"id": "n1", "label": "A"},
                            {"id": "n2", "label": "B"}]
    assert res["edges"] == [{"from": "n1", "to": "n2", "label": ""}]


def test_extract_diagram_empty_degrades_no_retry(monkeypatch):
    calls = []

    def fake_gw(payload, **_kw):
        calls.append(payload)
        return {"choices": [{"message": {"content": ""},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 0,
                          "total_tokens": 100},
                "cost": "0"}

    monkeypatch.setattr("graph2note.diagram._post", lambda payload, **k: fake_gw(payload))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    res = diagram.extract_diagram_image(str(IMG01), session="s")
    assert res["ok"] is False and res["verdict"] == "empty"
    assert len(calls) == 1  # empty content -> NO same-parameters retry
    assert res["meta"]["retried"] is False


def test_extract_diagram_unparseable_parse_fail(monkeypatch):
    def fake_gw(payload, **_kw):
        return {"choices": [{"message": {"content": "不是JSON的文字解释", },
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 5,
                          "total_tokens": 105},
                "cost": "0"}

    monkeypatch.setattr("graph2note.diagram._post", lambda payload, **k: fake_gw(payload))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    res = diagram.extract_diagram_image(str(IMG01), session="s")
    assert res["ok"] is False and res["verdict"] == "parse_fail"


def test_extract_diagram_length_exhaustion_upgrades_once(monkeypatch):
    calls = []

    def fake_gw(payload, **_kw):
        calls.append(payload)
        mt = payload.get("max_tokens")
        if mt == diagram.DIAGRAM_MAX_TOKENS:
            return {"choices": [{"message": {"content": ""},
                                 "finish_reason": "length"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 1,
                              "total_tokens": 101}, "cost": "0"}
        return {"choices": [{"message": {
            "content": json.dumps({"nodes": [{"id": "n1", "label": "X"}],
                                   "edges": []})}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                          "total_tokens": 110}, "cost": "0"}

    monkeypatch.setattr("graph2note.diagram._post", lambda payload, **k: fake_gw(payload))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    res = diagram.extract_diagram_image(str(IMG01), session="s")
    assert res["ok"] is True
    assert res["meta"]["retried"] is True
    assert len(calls) == 2
    assert calls[1]["max_tokens"] == diagram.DIAGRAM_RETRY_TOKENS


# ---------------- AC6: FR-020 determinism -------------------------------------

def test_flow_render_byte_identical(tmp_path):
    doc = ir.load_dict_as_ir({
        "document_type": "note",
        "blocks": [{"type": "flow", "orientation": "LR",
                    "nodes": [{"id": "n1", "label": "A"},
                              {"id": "n2", "label": "B"},
                              {"id": "n3", "label": "C"}],
                    "edges": [{"from": "n1", "to": "n2", "label": ""},
                              {"from": "n2", "to": "n3", "label": ""}],
                    "caption": "", "source": None}],
    })
    from graph2note.attachments import FileAssetWriter
    w1 = FileAssetWriter(str(tmp_path / "a"), doc_id="d")
    m1 = render.render_markdown(doc, doc_id="d", attachment_writer=w1)
    w2 = FileAssetWriter(str(tmp_path / "b"), doc_id="d")
    m2 = render.render_markdown(doc, doc_id="d", attachment_writer=w2)
    b1 = (tmp_path / "a" / "assets" / "d-flow-0.png").read_bytes()
    b2 = (tmp_path / "b" / "assets" / "d-flow-0.png").read_bytes()
    assert b1 == b2              # same semantics -> byte-identical PNG
    assert m1 == m2