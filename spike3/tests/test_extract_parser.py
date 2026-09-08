"""Extraction parser + canonical IR tests (pure, offline).

Uses recorded fixture raw responses - never touches the network.  These cover
the deterministic JSON->Diagram path and the verdicts the renderer depends on
(ok / parse_fail / no_flow / malformed).
"""
import json

import pytest

import extract
from ir_model import Diagram

FIX = {
    "ok_loop": (
        '{"nodes":[{"id":"n1","label":"初始化"},{"id":"n2","label":"迭代"},'
        '{"id":"n3","label":"收敛？"}],"edges":[{"from":"n1","to":"n2","label":""},'
        '{"from":"n2","to":"n3","label":""},{"from":"n3","to":"n1","label":"否"}]}'),
    "ok_branch": (
        '{"nodes":[{"id":"n1","label":"接收请求"},{"id":"n2","label":"正常返回"},'
        '{"id":"n3","label":"错误返回"}],"edges":[{"from":"n2","to":"n1","label":"成功"},'
        '{"from":"n2","to":"n3","label":"失败"}]}'),
    "fenced": '```json\n{"nodes":[{"id":"n1","label":"A"}],"edges":[]}\n```',
    "no_flow": '{"error":"no_flow_extractable"}',
    "malformed_dangling_ref": (
        '{"nodes":[{"id":"n1","label":"A"}],"edges":[{"from":"nZ","to":"n1","label":""}]}'),
    "garbage": "这是无法解析的文本，不是 JSON",
    "empty": "",
}


def _raw_path(name):
    import os
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", name)


@pytest.mark.parametrize("name", ["ok_loop", "ok_branch", "fenced"])
def test_parse_and_validate_ok(name):
    data = extract.try_parse_json(FIX[name])
    diag, verdict = extract.validate(data)
    assert verdict == "ok"
    assert diag is not None
    assert all(n.id for n in diag.nodes)


def test_no_flow_verdict():
    data = extract.try_parse_json(FIX["no_flow"])
    diag, verdict = extract.validate(data)
    assert verdict == "no_flow"
    assert diag is None


def test_malformed_dangling_edge_ref():
    diag, verdict = extract.validate(extract.try_parse_json(FIX["malformed_dangling_ref"]))
    assert verdict == "malformed"
    assert diag is None


def test_garbage_and_empty():
    assert extract.try_parse_json(FIX["garbage"]) is None
    assert extract.try_parse_json(FIX["empty"]) is None


def test_self_loop_rejected():
    raw = '{"nodes":[{"id":"n1","label":"A"}],"edges":[{"from":"n1","to":"n1","label":""}]}'
    diag, verdict = extract.validate(extract.try_parse_json(raw))
    assert verdict == "malformed"


def test_canonical_ordering_is_stable():
    # same semantics, different insertion order -> identical serialized dict
    d1 = Diagram.from_dict({
        "nodes": [{"id": "n2", "label": "B"}, {"id": "n1", "label": "A"}],
        "edges": [{"from": "n2", "to": "n1", "label": "x"},
                  {"from": "n1", "to": "n2", "label": "z"}],
    }).canonical()
    d2 = Diagram.from_dict({
        "nodes": [{"id": "n1", "label": "A"}, {"id": "n2", "label": "B"}],
        "edges": [{"from": "n1", "to": "n2", "label": "z"},
                  {"from": "n2", "to": "n1", "label": "x"}],
    }).canonical()
    assert d1.to_dict() == d2.to_dict()


def test_cached_response_present_for_keyed_samples():
    """Every committed fixture maps cleanly to a verdict (regression guard)."""
    import os, glob
    fx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    found = glob.glob(os.path.join(fx, "*.json"))
    assert found, "fixtures dir should contain recorded responses"
    for p in found:
        rec = json.load(open(p))
        data = extract.try_parse_json(rec.get("raw", ""))
        _, verdict = extract.validate(data)
        assert verdict in {"ok", "no_flow", "malformed", "parse_fail"}