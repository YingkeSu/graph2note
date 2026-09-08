"""Router tests: router entry, IR validation/retry, degrade, P1 seams."""

import json

import pytest

from graph2note import render_markdown
from graph2note.ir import IRValidationError, DocumentIR
from graph2note.router import (
    RecognitionRouter,
    RouteARouter,
    RecognitionError,
    RouteResult,
)

def _golden(name):
    import pathlib

    p = pathlib.Path(__file__).parent / "golden" / name
    return p.read_text(encoding="utf-8")


def _valid_reply() -> str:
    return _golden("valid-ir.golden.json")


def _illegal_reply() -> str:
    return _golden("illegal-ir.golden.json")


def test_route_a_parses_valid_golden_ir():
    router = RouteARouter("glm-5.3-flash", caller=lambda p, m: (_valid_reply(), {}))
    result = router.recognize("/tmp/unused.jpg")
    assert isinstance(result, RouteResult)
    assert isinstance(result.document, DocumentIR)
    assert result.retries == 0
    assert result.strategy == "route_a"
    types = [b.type for b in result.document.blocks]
    assert "heading" in types and "diagram" in types and "formula" in types


def test_route_a_renders_through_schema():
    router = RouteARouter("glm-5.3-flash", caller=lambda p, m: (_valid_reply(), {}))
    result = router.recognize("/tmp/unused.jpg")
    assert render_markdown(result.document)  # valid IR renders
    # and the IR validates again via loads (schema seam intact)
    from graph2note.ir import loads_ir

    assert loads_ir(result.document.model_dump_json())


def test_route_a_retries_on_illegal_then_succeeds():
    replies = [_illegal_reply(), _valid_reply()]
    router = RouteARouter(
        "dummy", caller=lambda p, m: (replies.pop(0), {}), max_retries=3
    )
    result = router.recognize("/tmp/x.jpg")
    assert result.retries == 1
    assert result.document is not None
    assert result.document.blocks[0].type == "heading"


def test_route_a_fails_cleanly_after_illegal_exhaustion():
    router = RouteARouter(
        "dummy", caller=lambda p, m: (_illegal_reply(), {}), max_retries=2
    )
    with pytest.raises(RecognitionError) as exc:
        router.recognize("/tmp/x.jpg")
    # initial call + 2 retries all returned invalid IR -> clean error, no hang
    assert "3 attempts" in str(exc.value)


def test_route_a_counts_attempts():
    # covered together with the exhaustion test above; kept as an alias check
    pass


def test_route_a_empty_content_funnels_to_degrade():
    router = RouteARouter("dummy", caller=lambda p, m: ("", {}))
    result = router.recognize("/tmp/x.jpg", diagram_source="/tmp/src.png")
    assert result.document is not None
    assert result.document.blocks == []
    assert "empty content" in result.warnings[0]


def test_route_a_injects_source_for_structureless_diagram():
    # A diagram with no nodes/edges should get the source path injected so the
    # renderer's crop-degrade path fires.
    reply = json.dumps({
        "blocks": [
            {"type": "paragraph", "text": "背景"},
            {"type": "diagram", "nodes": [], "edges": [], "caption": "无法提取"},
        ]
    })
    router = RouteARouter("dummy", caller=lambda p, m: (reply, {}))
    result = router.recognize("/tmp/x.jpg", diagram_source="/tmp/prep.png")
    diagram = result.document.blocks[1]
    assert diagram.source == "/tmp/prep.png"
    assert result.degraded_block_indices == [1]


def test_p1_seams_are_interface_only():
    # multi-version candidate models (issue 11): MVP returns one
    r = RouteARouter("glm-5.3-flash")
    assert r.candidate_models == ["glm-5.3-flash"]
    # base class seam stays interface-only (other routes); concrete Route A
    # now implements cross-validation (issue 10): it needs image + second model
    with pytest.raises(NotImplementedError):
        RecognitionRouter.verify_second_model(r, None)  # base contract still stub
    with pytest.raises(Exception):
        r.verify_second_model(None)  # no image_path/second_model cached
    # Route B (OCR) is declared but not implemented at any level yet
    with pytest.raises(NotImplementedError):
        r.route_b("/tmp/x.jpg")


def test_router_is_abstract_entry():
    with pytest.raises(TypeError):
        RecognitionRouter("x")  # abstract class cannot be instantiated directly


def test_illegal_json_is_rejected_by_schema_seam():
    with pytest.raises(IRValidationError):
        from graph2note.ir import loads_ir

        loads_ir(_illegal_reply())