"""Determinism + rendering tests (offline, no network).

FR-020: the same diagram semantics must produce byte-identical output for both
the matplotlib and graphviz renderers.  matplotlib runs unconditionally;
graphviz is skipped if the `dot` binary is unavailable (it is a local layout
engine, never a network call) so CI stays green on machines without it.
"""
import hashlib
import json
import os
import shutil

import pytest

from ir_model import Diagram
import plot_matplotlib as pm

SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gt_diagram(name="S06"):
    p = os.path.join(SPIKE, "ground_truth", f"{name}.json")
    return Diagram.from_dict(json.load(open(p)))


def _sha(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def test_matplotlib_render_is_byte_deterministic(tmp_path):
    d = _gt_diagram("S06")
    a = str(tmp_path / "a.png")
    b = str(tmp_path / "b.png")
    pm.render(d, a)
    pm.render(d, b)
    assert _sha(a) == _sha(b)
    assert os.path.getsize(a) > 0


def test_matplotlib_different_semantics_differ(tmp_path):
    d = _gt_diagram("S06")
    a = str(tmp_path / "a.png")
    pm.render(d, a)
    # a different graph (S10 has more nodes) must not collide-innocently
    d2 = _gt_diagram("S10")
    b = str(tmp_path / "b.png")
    pm.render(d2, b)
    assert _sha(a) != _sha(b)


def test_layer_layout_layers_linear_chain():
    from plot_matplotlib import LayerLayout
    d = _gt_diagram("S06")  # 3-node linear chain
    lay = LayerLayout(d)
    layers = lay.layers()
    assert [len(l) for l in layers] == [1, 1, 1]


has_dot = shutil.which("dot") is not None


@pytest.mark.skipif(not has_dot, reason="graphviz dot binary not installed")
def test_graphviz_render_is_byte_deterministic(tmp_path):
    import plot_graphviz as pg
    d = _gt_diagram("S06")
    a = str(tmp_path / "a")
    b = str(tmp_path / "b")
    pa = pg.render(d, os.path.join(tmp_path, "a.png"))
    pb = pg.render(d, os.path.join(tmp_path, "b.png"))
    # graphviz writes <path>.png
    assert os.path.getsize(pa) > 0
    assert _sha(pa) == _sha(pb)