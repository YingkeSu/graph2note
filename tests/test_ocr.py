"""graph2note.ocr 本地 OCR 封装测试（tesseract）。

OCR 引擎是二进制的 tesseract（非 pip 依赖），用模块级 `pytest.skip` 守护（importorskip
语义：无引擎则整模块跳过，CI 无网络/无 tesseract 也不会挂）。所有测试离线、纯本地、不触网。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from graph2note import ocr as ocrm  # noqa: E402

if not ocrm.ocr_available():
    pytest.skip(
        "tesseract 未安装/缺 chi_sim 语言包（OCR 引擎依赖，importorskip 守护）",
        allow_module_level=True,
    )

FIXTURES = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "data"


def test_tesseract_available():
    assert ocrm.tesseract_available() is True
    assert ocrm.ocr_available() is True
    assert ocrm.tesseract_binary()


def test_ocr_image_returns_non_crashing_tuple():
    img = FIXTURES / "C08.jpg"
    text, meta = ocrm.ocr_image(str(img))
    assert isinstance(text, str)
    assert isinstance(meta, dict)
    assert meta["engine"] == "tesseract"
    assert meta["lang"] == "chi_sim+eng"
    assert meta["version"]  # 有版本号
    # 真实页：要么读出内容，要么有明确 error；绝不抛异常
    assert (meta["chars"] > 0) or (meta["error"] is not None)


def test_ocr_image_missing_file_no_crash():
    text, meta = ocrm.ocr_image(str(FIXTURES / "nope.jpg"))
    assert isinstance(text, str)
    assert meta["error"] is not None  # 明确错误，不崩溃


def test_ocr_mean_confidence_shape():
    img = FIXTURES / "C08.jpg"
    conf = ocrm.ocr_mean_confidence(str(img))
    assert set(("mean_conf", "count", "error")).issubset(conf)
    assert isinstance(conf["mean_conf"], (float, type(None)))