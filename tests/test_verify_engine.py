"""Issue 10 — cross-validation orchestration: degrade path, serialization,
router-custom seam.  All offline (injected runner, no network, no LLM)."""

import pytest

from graph2note.ir import load_dict_as_ir
from graph2note.verify import cross_validate, report as _report
from graph2note.verify import model as _model
from graph2note.router import RouteARouter, RecognitionRouter


def _ir(content):
    return load_dict_as_ir({"document_type": "note", "blocks": content})


def _reply(content):
    """Stateful runner returning a valid IR-JSON reply for a given model."""
    def runner(image_path, model, recover=False):
        if model == "glm-5.3-flash":
            payload = {"document_type": "note", "blocks": [
                {"type": "heading", "level": 1, "text": "标题"},
                {"type": "paragraph", "text": "正文第一段"},
            ]}
        else:  # second model
            payload = {"document_type": "note", "blocks": [
                {"type": "heading", "level": 1, "text": "标题"},
                {"type": "paragraph", "text": "正文第一段"},
            ]}
        return ('```json\n' + __import__("json").dumps(payload, ensure_ascii=False)
                + '\n```', {"model": model})
    return runner


# -- happy path (two models agree) -----------------------------------------
def test_cross_validate_two_models_agree_and_report_serializes(tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"fake")
    rep = cross_validate(str(img), runner=_reply(None))
    assert rep.verified is True
    assert rep.diff.counts[_model.CONSISTENT] == 2
    assert rep.diff.counts[_model.CONFLICT] == 0
    # JSON round-trip
    j = _report.to_json(rep)
    parsed = __import__("json").loads(j)
    assert parsed["verified"] is True
    assert parsed["model_a"] and parsed["model_b"]
    md = _report.to_markdown(rep)
    assert "未验证" not in md
    assert "交叉验证分歧报告" in md


# -- degrade path (one model fails -> 未验证, never blocks) ------------------
def test_single_model_failure_degrades_to_unverified():
    def runner(image_path, model, recover=False):
        if model == "deepseek-v4-flash-vision-exp":
            raise RuntimeError("timeout/model out")  # second model fails
        return _reply(None)(image_path, model)
    rep = cross_validate("/x.jpg", runner=runner)
    assert rep.verified is False
    assert "未验证" in rep.note
    assert rep.model_b == "deepseek-v4-flash-vision-exp"
    # the surviving single model result is still surfaced (no crash)
    assert rep.diff.counts[_model.CONSISTENT] == 0  # no cross-diff when degraded
    md = _report.to_markdown(rep)
    assert "未验证" in md


def test_both_models_fail_degrades_cleanly():
    def runner(image_path, model, recover=False):
        raise RuntimeError("all fail")
    rep = cross_validate("/x.jpg", runner=runner)
    assert rep.verified is False
    assert "双模型均失败" in rep.note
    rep2 = cross_validate("/x.jpg", runner=runner)
    assert _report.to_json(rep2)  # serializes


# -- json/markdown round trip and div-by-zero safety -------------------------
def test_report_json_contains_three_class_counts():
    rep = cross_validate("/x.jpg", runner=_reply(None))
    d = __import__("json").loads(_report.to_json(rep))
    keys = {_model.CONSISTENT, _model.ONE_SIDE, _model.CONFLICT}
    assert keys.issubset(d["diff"]["counts"])


# -- divergence-rate AC metric -------------------------------------------------
def test_divergence_rate_metric_present():
    """AC: 报告给出分歧率（非一致块占比）供电竞对比趋势。"""
    rep = cross_validate("/x.jpg", runner=_reply(None))
    total = sum(rep.diff.counts.values())
    consistent = rep.diff.counts[_model.CONSISTENT]
    rate = (1 - consistent / total) * 100 if total else 0.0
    assert 0.0 <= rate <= 100.0
    # same documents => 0% divergence
    assert rate == 0.0


# -- router seam ---------------------------------------------------------------
def test_route_a_verify_second_model_uses_router_model():
    r = RouteARouter("glm-5.3-flash", second_model="deepseek-v4-flash-vision-exp")
    # base seam stays interface-only; concrete Route A implements it (needs image+second)
    from graph2note.router import RecognitionRouter as BR
    with pytest.raises(NotImplementedError):
        BR.verify_second_model(r, None)
    with pytest.raises(Exception):
        r.verify_second_model(None)


def test_route_a_verify_second_model_diff_with_runner():
    """End-to-end seam with an injected runner: no network, verifies a primary
    doc against a fresh second-model parse."""
    r = RouteARouter("glm-5.3-flash",
                     second_model="deepseek-v4-flash-vision-exp")
    primary = _ir([{"type": "heading", "level": 1, "text": "标题"},
                   {"type": "paragraph", "text": "正文第一段"}])

    def runner(image_path, model, recover=False):
        payload = {"document_type": "note", "blocks": [
            {"type": "heading", "level": 1, "text": "标题"},
        ]}  # second model misses the paragraph -> one_side
        return ('```json\n' + __import__("json").dumps(payload, ensure_ascii=False)
                + '\n```', {"model": model})

    rep = r.verify_second_model(primary, image_path="/x.jpg", runner=runner)
    assert rep.model_a == "glm-5.3-flash"
    assert rep.model_b == "deepseek-v4-flash-vision-exp"
    assert rep.verified is True
    # the missed paragraph shows up as one-sided (suspected missed recognition)
    assert rep.diff.counts[_model.ONE_SIDE] == 1