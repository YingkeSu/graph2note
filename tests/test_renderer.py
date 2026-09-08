"""Golden renderer tests (FR-006/007/008 + AC: determinism, 10 blocks, edges)."""

from graph2note.ir import DocumentIR, loads_ir, dumps_ir
from graph2note.render import render_markdown, escape_text
from graph2note.attachments import FileAssetWriter

import json


def test_empty_document_renders_empty():
    doc = DocumentIR(blocks=[])
    assert render_markdown(doc) == ""


def test_render_is_deterministic_byte_for_byte():
    doc_json = json.dumps(
        {
            "blocks": [
                {"type": "heading", "level": 1, "text": "标题"},
                {"type": "paragraph", "text": "正文"},
                {"type": "list", "items": [{"text": "a"}]},
                {"type": "formula", "latex": "x", "inline": False},
            ]
        }
    )
    doc = loads_ir(doc_json)
    first = render_markdown(doc)
    second = render_markdown(doc)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")
    # Even after a JSON round-trip the output is identical.
    reloaded = loads_ir(dumps_ir(doc))
    assert render_markdown(reloaded) == first


def test_golden_all_ten_block_types():
    doc_json = json.dumps(
        {
            "document_type": "note",
            "blocks": [
                {"type": "heading", "level": 2, "text": "目标"},
                {"type": "paragraph", "text": "发射吧"},
                {
                    "type": "list",
                    "ordered": False,
                    "items": [
                        {"text": "CNN"},
                        {"text": "Transformer"},
                        {"text": "序列建模", "items": [{"text": "RNN"}, {"text": "State Space"}]},
                    ],
                },
                {"type": "formula", "latex": "\\dot{x}=Ax+Bu", "inline": False},
                {"type": "table", "headers": ["编号", "项目"], "rows": [["1", "预研"], ["2", "实现"]]},
                {"type": "code", "language": "python", "content": "x = 1"},
                {"type": "quote", "text": "保持热爱"},
                {"type": "image", "src": "assets/photo.png", "alt": "照片"},
                {
                    "type": "flow",
                    "caption": "主流程",
                    "nodes": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
                    "edges": [{"from": "a", "to": "b"}],
                },
                {
                    "type": "diagram",
                    "caption": "备选",
                    "nodes": [{"id": "a", "label": "方案A"}],
                },
            ],
        }
    )
    expected = (
        "## 目标\n"
        "\n"
        "发射吧\n"
        "\n"
        "- CNN\n"
        "- Transformer\n"
        "- 序列建模\n"
        "\n"
        "  - RNN\n"
        "  - State Space\n"
        "\n"
        "$$\n"
        "\\dot{x}=Ax+Bu\n"
        "$$\n"
        "\n"
        "| 编号 | 项目 |\n"
        "| --- | --- |\n"
        "| 1 | 预研 |\n"
        "| 2 | 实现 |\n"
        "\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "\n"
        "> 保持热爱\n"
        "\n"
        "![照片](assets/photo.png)\n"
        "\n"
        "![主流程](assets/doc-flow-8.png)\n"
        "\n"
        "![备选](assets/doc-diagram-9.png)\n"
    )
    doc = loads_ir(doc_json)
    assert render_markdown(doc) == expected


def test_heading_levels_are_atx():
    doc = DocumentIR(
        blocks=[
            {"type": "heading", "level": 1, "text": "a"},
            {"type": "heading", "level": 6, "text": "b"},
        ]
    )
    out = render_markdown(doc)
    assert out == "# a\n\n###### b\n"


def test_ordered_list():
    doc = DocumentIR(blocks=[{"type": "list", "ordered": True, "items": [{"text": "x"}, {"text": "y"}]}])
    assert render_markdown(doc) == "1. x\n1. y\n"


def test_inline_and_display_formula():
    inline = DocumentIR(blocks=[{"type": "formula", "latex": "e^{i\\pi}+1=0", "inline": True}])
    assert render_markdown(inline) == "$e^{i\\pi}+1=0$\n"
    display = DocumentIR(blocks=[{"type": "formula", "latex": "E=mc^2", "inline": False}])
    assert render_markdown(display) == "$$\nE=mc^2\n$$\n"


def test_special_characters_are_escaped():
    import re

    text = r"a*b # _c_ `d` [x] {y} <z> \\e"
    doc = DocumentIR(blocks=[{"type": "paragraph", "text": text}])
    out = render_markdown(doc)
    # No special character may survive unescaped (structure-injection safe).
    assert not re.search(r"(?<!\\)[*#_`\[\]{}<>]", out)
    # Backslashes are themselves escaped; byte-for-byte equals escaping.
    assert out == escape_text(text) + "\n"


def test_chinese_full_width_and_punctuation_preserved():
    text = "中文：全角，标点。（）＃＊？！ＵＳＢ１２３　全宽空格。"
    doc = DocumentIR(blocks=[{"type": "paragraph", "text": text}])
    # Full-width ＃/＊ are NOT the ASCII specials, so must pass through.
    assert render_markdown(doc) == text + "\n"


def test_escape_text_leaves_full_width_alone():
    assert escape_text("（全角＊）") == "（全角＊）"


def test_nested_list_deep():
    doc = DocumentIR(
        blocks=[
            {
                "type": "list",
                "items": [
                    {
                        "text": "L1",
                        "items": [
                            {"text": "L2", "items": [{"text": "L3"}]},
                        ],
                    }
                ],
            }
        ]
    )
    assert render_markdown(doc) == "- L1\n\n  - L2\n\n    - L3\n"


def test_code_fence_longer_than_inner_backticks():
    content = "```\na\n```"
    doc = DocumentIR(blocks=[{"type": "code", "content": content, "language": ""}])
    out = render_markdown(doc)
    # Fence must be 4 backticks to safely wrap inner triple-backtick fence.
    assert out == "````\n" + content + "\n````\n"


def test_table_escapes_pipe():
    doc = DocumentIR(blocks=[{"type": "table", "headers": ["a|b"], "rows": [["x|y"]]}])
    out = render_markdown(doc)
    assert out == "| a\\|b |\n| --- |\n| x\\|y |\n"


def test_diagram_and_flow_attachment_paths():
    doc = DocumentIR(
        blocks=[
            {
                "type": "diagram",
                "caption": "流程",
                "nodes": [{"id": "a"}, {"id": "b"}],
                "edges": [{"from": "a", "to": "b", "label": "go"}],
            }
        ]
    )
    out = render_markdown(doc, doc_id="mynote")
    assert out == "![流程](assets/mynote-diagram-0.png)\n"


def test_file_asset_writer_drops_stub(tmp_path):
    doc = DocumentIR(
        blocks=[{"type": "flow", "caption": "f", "nodes": [{"id": "a"}]}]
    )
    writer = FileAssetWriter(tmp_path, doc_id="d")
    out = render_markdown(doc, doc_id="d", attachment_writer=writer)
    assert out == "![f](assets/d-flow-0.png)\n"
    assert (tmp_path / "assets" / "d-flow-0.png").exists()
    # Second render writes the same relative path (deterministic).
    assert render_markdown(doc, doc_id="d", attachment_writer=writer) == out