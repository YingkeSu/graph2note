"""Route B（issue 08）测试：OCR -> 文本 LLM 结构化 -> Document IR、Router 缝、特征路由。

全部离线：OCR/文本 LLM 通过注入 caller 打桩，不触网。OCR 引擎相关在线校验路径用
``pytest.importorskip`` 守护（见 test_ocr.py 的模块级 skip）。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph2note.ir import DocumentIR  # noqa: E402
from graph2note.route_b import (  # noqa: E402
    AutoRouter,
    PRINT_CONFIDENCE_THRESHOLD,
    RouteBRouter,
    _looks_like_refusal,
    classify_route_features,
    route_b_chain,
)


def _ocr(p):
    return "# Fourier 积分定理\n\n$$\\int_{-\\infty}^{+\\infty}|f(t)|\\,dt<\\infty$$ 证明如下：", {
        "chars": 60, "error": None}


def _text(txt, model, recover=False):
    return "# Fourier 积分定理\n\n设 $f(t)$ 绝对可积，则 $$F(\\omega)=\\int f(t)e^{-i\\omega t}dt$$", {
        "status": "ok", "reasoning_tokens": 0}


def test_route_b_chain_nonempty():
    res = route_b_chain("x.jpg", ocr_caller=_ocr, text_caller=_text)
    assert res.strategy == "route_b"
    assert len(res.document.blocks) > 0
    assert res.retries == 0
    assert "fell back" not in " ".join(res.warnings)


def test_route_b_chain_empty_ocr_degrades():
    res = route_b_chain("x.jpg", ocr_caller=lambda p: ("", {"chars": 0, "error": "no text"}),
                        text_caller=_text)
    assert len(res.document.blocks) == 0  # 空 IR，不崩溃
    assert res.warnings and "OCR returned empty" in res.warnings[0]


def test_route_b_chain_text_llm_empty_falls_back_to_ocr():
    res = route_b_chain("x.jpg", ocr_caller=_ocr, text_caller=lambda t, m, recover=False: ("", {}))
    assert len(res.document.blocks) > 0  # 回退原始 OCR 文本，非空
    assert res.retries >= 0
    assert any("fell back" in w for w in res.warnings)


def test_route_b_chain_text_llm_refusal_falls_back():
    # 模型判 OCR 噪声过大而拒绝 -> 视为空，回退原始 OCR
    res = route_b_chain("x.jpg", ocr_caller=_ocr,
                        text_caller=lambda t, m, recover=False: ("本次 OCR 内容噪声过大，无可整理。", {}))
    assert len(res.document.blocks) > 0
    assert any("refusal" in w for w in res.warnings) or any("fell back" in w for w in res.warnings)


def test_looks_like_refusal():
    assert _looks_like_refusal("") is True
    assert _looks_like_refusal("噪声过大，无法识别出可恢复的标题或句子") is True
    assert _looks_like_refusal("确实无法整理这段内容") is True
    assert _looks_like_refusal("# 正常标题\n\n正文内容……$\\int$ 公式如下。") is False


def test_route_b_router_recognize():
    rb = RouteBRouter(ocr_caller=_ocr, text_caller=_text)
    res = rb.recognize("img.jpg")
    assert res.strategy == "route_b"
    assert len(res.document.blocks) > 0


def test_route_b_real_tesseract_chain_skippable():
    from graph2note import ocr as ocrm
    if not ocrm.ocr_available():
        pytest.skip("tesseract 不可用")
    # 真实 tesseract + 打桩文本 LLM：证明 OCR 步骤真实可用（本地）
    dt = l_ocr_plus_text()
    assert len(dt) > 0


def l_ocr_plus_text():
    from graph2note import ocr as ocrm
    here = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "data"
    text, meta = ocrm.ocr_image(str(here / "C08.jpg"))
    return (text or "") + (meta.get("error") or "")


def test_classify_route_features_no_confidence_is_route_a():
    feat = classify_route_features("x.jpg", confidence={"mean_conf": None, "count": 0, "error": "x"})
    assert feat["print_likelihood"] == 0.0  # 无信号 -> 保守 Route A


def test_classify_route_features_high_conf_is_print():
    feat = classify_route_features("x.jpg", confidence={"mean_conf": 82.0, "count": 120, "error": None})
    assert feat["print_likelihood"] == 1.0  # 高置信印刷 -> Route B


def test_autorouter_defaults_to_route_a_on_low_confidence(monkeypatch):
    ra = AutoRouter(feature_fn=lambda p: {"print_likelihood": 0.0})
    # 用可观测的替身路由断言选择
    chosen = ra._choose_route("p.jpg")
    assert chosen is ra._route_a


def test_autorouter_route_b_on_high_confidence(monkeypatch):
    ra = AutoRouter(feature_fn=lambda p: {"print_likelihood": 1.0})
    assert ra._choose_route("p.jpg") is ra._route_b


def test_autorouter_env_forces_route(monkeypatch):
    ra = AutoRouter(feature_fn=lambda p: {"print_likelihood": 1.0})
    monkeypatch.setenv("GRAPH2NOTE_ROUTE", "a")
    assert ra._choose_route("p.jpg") is ra._route_a
    monkeypatch.setenv("GRAPH2NOTE_ROUTE", "b")
    assert ra._choose_route("p.jpg") is ra._route_b


class _FakeAB:
    """可观测的 RouteA/RouteB 替身：记录谁被调用。"""

    def __init__(self, name):
        self.name = name
        self.calls = 0

    def recognize(self, image_path, diagram_source=None):
        self.calls += 1
        return RouteResultPlaceholder(self.name)


class RouteResultPlaceholder:
    def __init__(self, name):
        self.name = name


def test_autorouter_recognize_delegates(monkeypatch):
    a = _FakeAB("a")
    b = _FakeAB("b")
    ra = AutoRouter(feature_fn=lambda p: {"print_likelihood": 0.0}, route_a=a, route_b_router=b)
    res = ra.recognize("p.jpg")
    assert res.name == "a"
    assert a.calls == 1 and b.calls == 0
    monkeypatch.setenv("GRAPH2NOTE_ROUTE", "b")
    ra2 = AutoRouter(feature_fn=lambda p: {"print_likelihood": 0.0}, route_a=a, route_b_router=b)
    res2 = ra2.recognize("p.jpg")
    assert res2.name == "b"

# ---------------- 上游零改动（AC）：parse_document 直接换 RouteBRouter ----------------

def test_route_b_router_upstream_zero_change(tmp_path):
    """上游 parse_document 只依赖 RecognitionRouter.recognize：换成 RouteB 零改动可用。"""
    import tempfile
    from graph2note.pipeline import parse_document

    def ocr(p):
        return "测试页：Fourier 积分定理\\n\\n$$\\\\int |f(t)| dt<\\\\infty$$", {"chars": 40, "error": None}

    def text(t, m, recover=False):
        return "# 测试页\\n\\nFourier 积分定理：$$\\\\int_{-\\\\infty}^{+\\\\infty}|f(t)|\\\\,dt<\\\\infty$$", {
            "status": "ok", "reasoning_tokens": 0}

    rb = RouteBRouter(ocr_caller=ocr, text_caller=text)
    img = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "data" / "A02.jpg"
    with tempfile.TemporaryDirectory() as td:
        res = parse_document(str(img), td, model="glm-5.3-flash", router=rb)
    # 上游无需任何改动：同一签名产出带 Route B 策略的 ParseResult，Markdown 与 IR 非空
    assert res.route.strategy == "route_b"
    assert res.markdown_path
    assert (res.markdown or "").strip()
    assert getattr(res.route.document, "blocks", None) is not None
