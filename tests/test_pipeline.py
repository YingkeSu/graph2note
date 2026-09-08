"""Full-pipeline offline tests: preprocess->router->render->assets->timing.

Uses a stub router or a seeded VlmCache so everything is deterministic and
network-free (CI-ready).  Asserts the staged timing JSON (issue-11 baseline)
and that invalid IR / empty replies degrade cleanly.
"""

import json

import pytest

from graph2note import pipeline
from graph2note.ir import DocumentIR, loads_ir
from graph2note.router import RouteARouter, RecognitionError
from graph2note.vlm import VlmCache

pytest.importorskip("PIL")


def _valid_reply():
    import pathlib

    return (pathlib.Path(__file__).parent / "golden" / "valid-ir.golden.json").read_text(
        encoding="utf-8"
    )


def _make_test_image(tmp_path, draw_text=True):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (700, 500), (255, 255, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:
        font = ImageFont.load_default()
    if draw_text:
        d.text((40, 60), "标题：状态空间模型", fill=(40, 40, 40), font=font)
        d.text((40, 160), "这是一个测试段落，用于端到端管线验证。", fill=(50, 50, 50), font=font)
    p = tmp_path / "note.png"
    im.save(p)
    return p


def _stub_router(reply_getter):
    calls = {"n": 0}

    def caller(img, model):
        calls["n"] += 1
        return reply_getter(calls["n"])  # returns (content, meta)

    return RouteARouter("dummy", caller=caller)


def test_parse_document_full_chain(tmp_path):
    img = _make_test_image(tmp_path)
    router = _stub_router(lambda n: (_valid_reply(), {}) if n == 1 else ("", {}))
    result = pipeline.parse_document(str(img), str(tmp_path / "out"), model="dummy",
                                     router=router)
    # artifacts
    assert result.markdown_path and json  # md written
    md = (tmp_path / "out" / "note.md").read_text(encoding="utf-8")
    assert "状态空间模型" in md
    assert (tmp_path / "out" / "assets").is_dir()
    assert result.markdown == md
    # timing JSON present with the three required stages
    timing_path = tmp_path / "out" / "timing.json"
    data = json.loads(timing_path.read_text(encoding="utf-8"))
    stage_names = data["stage_names"]
    assert "preprocess" in stage_names
    assert "llm" in stage_names
    assert "render" in stage_names
    assert data["total_seconds"] >= 0


def test_parse_document_is_deterministic(tmp_path):
    img = _make_test_image(tmp_path)
    r1 = pipeline.parse_document(str(img), str(tmp_path / "a"), model="dummy",
                                 router=_stub_router(lambda n: (_valid_reply(), {})))
    r2 = pipeline.parse_document(str(img), str(tmp_path / "b"), model="dummy",
                                 router=_stub_router(lambda n: (_valid_reply(), {})))
    assert r1.markdown == r2.markdown
    assert r1.markdown.encode() == r2.markdown.encode()


def test_parse_rejects_permanent_invalid_ir_cleanly(tmp_path):
    import pathlib

    illegal = (pathlib.Path(__file__).parent / "golden" / "illegal-ir.golden.json").read_text(
        encoding="utf-8"
    )
    img = _make_test_image(tmp_path)
    router = _stub_router(lambda n: (illegal, {}))
    with pytest.raises(RecognitionError):
        pipeline.parse_document(str(img), str(tmp_path / "out"), model="dummy", router=router)


def test_parse_uses_seeded_cache_offline(tmp_path):
    """End-to-end offline via a pre-seeded VlmCache (no network)."""
    img = _make_test_image(tmp_path)
    cache = VlmCache(str(tmp_path / "cache"))
    cache.put(str(img), "glm-5.3-flash", _valid_reply(), {"model": "glm-5.3-flash"})
    result = pipeline.parse_document(str(img), str(tmp_path / "out"), model="glm-5.3-flash",
                                     cache=cache, preprocess=False)
    assert result.route.raw_content  # came from cache
    assert result.route.attempts[0]["meta"].get("cached") is True
    assert "状态空间模型" in result.markdown
    md_path = tmp_path / "out" / "note.md"
    assert md_path.exists()


def test_parse_degrade_empty_diagram_sets_crop_source(tmp_path):
    reply = json.dumps({
        "blocks": [
            {"type": "diagram", "nodes": [], "edges": [], "caption": "图"},
        ]
    })
    img = _make_test_image(tmp_path)
    router = _stub_router(lambda n: (reply, {}))
    result = pipeline.parse_document(str(img), str(tmp_path / "out"), model="dummy",
                                     router=router)
    # degrade -> source injected -> an asset is produced (crop or placeholder)
    assert result.route.degraded_block_indices == [0]
    asset = result.markdown  # should embed an assets/... reference
    assert "assets/note-diagram-0.png" in asset


def test_timing_null_timer_records_nothing():
    from graph2note.timing import NullTimer

    nt = NullTimer()
    with nt.stage("x"):
        pass
    assert nt.to_dict()["stage_names"] == []