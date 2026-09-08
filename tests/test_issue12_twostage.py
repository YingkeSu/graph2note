"""Issue 12: Route A two-stage parse (VLM Markdown -> text LLM IR) — offline tests.

Mocks ``graph2note.vlm.post_gateway`` (and ``load_api_key``) so no network runs.
Verifies the exact root-cause fix: a dense scanned page must now yield non-empty
IR and a non-empty rendered ``.md`` (previously empty), plus clean degradation
when a stage returns nothing (no runaway retry, no router re-loop).
"""

import json
from pathlib import Path

import pytest

import graph2note.vlm as vlm
from graph2note import pipeline

pytest.importorskip("PIL")

IMG01 = Path(__file__).resolve().parents[1] / "test-images" / "01-requirements-arch.jpg"
IR_GOLDEN = {
    "document_type": "note",
    "blocks": [
        {"type": "paragraph", "text": "hello 世界"},
        {"type": "heading", "level": 1, "text": "标题"},
    ],
}


def _body(content, reasoning=0, finish="stop", comp=100, prompt=500):
    return {
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": comp,
            "total_tokens": comp + prompt,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
        "cost": "0",
    }


def _two_stage_fake(markdown, ir_json):
    """post_gateway fake dispatching by payload shape (image list vs plain text)."""

    def fake(payload, **_kw):
        last = payload["messages"][-1]["content"]
        if isinstance(last, list):          # stage-1 VLM image+text
            return _body(markdown)
        return _body(ir_json)                # stage-2 text->IR

    return fake


# ---------------- stage units ----------------

def test_transcribe_markdown_stage(monkeypatch):
    monkeypatch.setattr(vlm, "post_gateway", _two_stage_fake("# 标题\n正文内容", IR_GOLDEN))
    content, meta = vlm._transcribe_markdown(
        str(IMG01), "glm-5.3-flash", key="k", sess="s", max_tokens=3500, timeout=120,
    )
    assert content.startswith("# 标题")
    assert meta["stage"] == "markdown"
    assert meta["reasoning_tokens"] == 0


def test_ir_from_markdown_parser_default_no_network(monkeypatch):
    # default (parser) path: valid non-empty IR, no gateway/network call
    def boom(*a, **k):
        raise AssertionError("parser mode must not call the gateway")
    monkeypatch.setattr(vlm, "post_gateway", boom)
    content, meta = vlm._ir_from_markdown(
        "# 标题\n正文内容", "deepseek-v4-flash", key="k", sess="s", max_tokens=6000, timeout=120,
    )
    obj = vlm.parse_ir_json(content)
    assert obj and len(obj["blocks"]) >= 2
    assert meta["mode"] == "markdown-parser"
    assert meta["retried"] is False


def test_ir_from_markdown_llm_nonempty(monkeypatch):
    monkeypatch.setattr(vlm, "post_gateway", _two_stage_fake("x", json.dumps(IR_GOLDEN)))
    content, meta = vlm._ir_from_markdown(
        "# 标题\n正文", "deepseek-v4-flash", key="k", sess="s", max_tokens=6000, timeout=120,
        use_llm=True,
    )
    assert vlm.parse_ir_json(content) == IR_GOLDEN
    assert meta["stage"] == "ir"
    assert meta["retried"] is False
    assert len(meta["attempts"]) == 1


def test_ir_from_markdown_llm_poor_falls_back_to_parser(monkeypatch):
    # LLM returns non-JSON prose both times -> falls back to parser (never empty)
    monkeypatch.setattr(vlm, "post_gateway", lambda *a, **k: _body("这不是 JSON，是解释文字。"))
    content, meta = vlm._ir_from_markdown(
        "prose markdown", "deepseek-v4-flash", key="k", sess="s", max_tokens=6000, timeout=120,
        use_llm=True,
    )
    assert vlm.parse_ir_json(content) is not None   # fallback parser output, non-empty
    assert meta["retried"] is True
    assert meta.get("fallback") == "markdown-parser"
    assert len(meta["attempts"]) == 2


# ---------------- call_ir orchestration ----------------

def test_call_ir_two_stage_returns_nonempty_ir(monkeypatch):
    monkeypatch.setattr(vlm, "post_gateway", _two_stage_fake("# 标题\n正文：hello 世界\n", json.dumps(IR_GOLDEN)))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    content, meta = vlm.call_ir(str(IMG01), "glm-5.3-flash")
    obj = vlm.parse_ir_json(content)
    assert obj is not None and (obj.get("blocks") or [])
    assert meta["stage"] == "ir"
    assert meta["empty"] is False
    assert meta["markdown_stage"]["stage"] == "markdown"
    assert meta["ir_stage"]["stage"] == "ir"
    assert meta["markdown_len"] > 0


def test_call_ir_stage1_empty_degrades(monkeypatch):
    monkeypatch.setattr(vlm, "post_gateway", _two_stage_fake("", json.dumps(IR_GOLDEN)))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    content, meta = vlm.call_ir(str(IMG01), "glm-5.3-flash")
    assert content == ""
    assert meta["empty"] is True
    assert meta["empty_stage"] == "markdown"
    assert any("empty" in w for w in meta["warnings"])


@pytest.mark.parametrize("ir_mode", ["parser", "llm"])
def test_call_ir_stage2_never_returns_empty(monkeypatch, tmp_path, ir_mode):
    # stage-1 fine; both IR modes must yield non-empty IR (parser default / fallback)
    monkeypatch.setattr(vlm, "post_gateway", _two_stage_fake("# 标题\n正文\n", "乱七八糟不是 JSON"))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    monkeypatch.setenv("GRAPH2NOTE_IR_MODE", ir_mode)
    content, meta = vlm.call_ir(str(IMG01), "glm-5.3-flash")
    obj = vlm.parse_ir_json(content)
    assert obj is not None and len(obj["blocks"]) >= 1   # non-empty IR
    assert meta["empty"] is False


# ---------------- end-to-end pipeline offline (the AC3 regression) ----------------

def test_pipeline_renders_nonempty_md_via_two_stage(tmp_path, monkeypatch):
    """Root-cause regression: dense scanned page now renders non-empty .md."""
    monkeypatch.setattr(vlm, "post_gateway", _two_stage_fake(
        "# 需求\n- 输入：手稿、笔记\n\n节点A → 节点B\n", json.dumps(IR_GOLDEN)))
    monkeypatch.setattr(vlm, "load_api_key", lambda: "k")
    result = pipeline.parse_document(str(IMG01), str(tmp_path / "out"), model="glm-5.3-flash")
    assert result.ir.blocks                      # non-empty structured IR
    md = Path(result.markdown_path).read_text(encoding="utf-8")
    assert md.strip() != ""                      # key: no longer empty
    assert "需求" in md
    assert "输入：手稿、笔记" in md                 # reading order preserved through IR round-trip
    timing = json.loads(Path(result.timing_path).read_text(encoding="utf-8"))
    assert {"preprocess", "llm", "render"} <= set(timing["stage_names"])