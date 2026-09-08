"""IR schema validation tests (FR-005 + AC: illegal IR is explicitly rejected)."""

import json

import pytest

from graph2note.ir import (
    DocumentIR,
    IRValidationError,
    loads_ir,
)
from graph2note import render_markdown


def test_all_ten_block_types_are_valid():
    doc_json = {
        "document_type": "note",
        "blocks": [
            {"type": "heading", "level": 2, "text": "A"},
            {"type": "paragraph", "text": "B"},
            {"type": "list", "ordered": False, "items": [{"text": "i"}]},
            {"type": "formula", "latex": "x", "inline": False},
            {"type": "table", "headers": ["h"], "rows": [["1"]]},
            {"type": "code", "language": "py", "content": "print()"},
            {"type": "quote", "text": "q"},
            {"type": "image", "src": "a.png", "alt": "a"},
            {
                "type": "diagram",
                "nodes": [{"id": "a"}],
                "edges": [{"from": "a", "to": "b"}],
            },
            {
                "type": "flow",
                "nodes": [{"id": "a"}],
                "edges": [],
                "orientation": "TB",
            },
        ],
    }
    doc = loads_ir(json.dumps(doc_json))
    assert isinstance(doc, DocumentIR)
    assert len(doc.blocks) == 10


def test_edge_uses_from_alias():
    doc = loads_ir(
        json.dumps({"blocks": [{"type": "diagram", "edges": [{"from": "a", "to": "b"}]}]})
    )
    edge = doc.blocks[0].edges[0]
    assert edge.from_ == "a"
    assert edge.to == "b"


def test_renders_after_json_roundtrip():
    doc = loads_ir(
        json.dumps({"blocks": [{"type": "paragraph", "text": "hi"}]})
    )
    assert render_markdown(doc) == "hi\n"


@pytest.mark.parametrize(
    "raw,expect_substr",
    [
        ("not json {{{", "invalid JSON"),  # invalid JSON
        ("[1, 2, 3]", "IR root must be a JSON object"),  # root not an object
        ('{"blocks": [{"type": "bogus", "text": "x"}]}', "Input should be"),  # unknown type
        ('{"blocks": [{"type": "heading", "text": "no level"}]}', "level"),  # missing field
        ('{"blocks": [{"type": "heading", "level": 9, "text": "x"}]}', "level"),  # out of range
        ('{"blocks": [{"type": "heading", "level": "two", "text": "x"}]}', "level"),  # wrong type
        ('{"extra": 1, "blocks": []}', "extra"),  # forbidden extra key
        ('{"blocks": [{"type": "formula"}]}', "latex"),  # missing required field
    ],
)
def test_invalid_ir_is_rejected(raw, expect_substr):
    with pytest.raises(IRValidationError) as exc:
        loads_ir(raw)
    assert expect_substr in str(exc.value)


def test_invalid_json_reports_location():
    with pytest.raises(IRValidationError) as exc:
        loads_ir('{"blocks": [}')
    msg = str(exc.value)
    assert "invalid JSON" in msg