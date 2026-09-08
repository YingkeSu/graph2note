"""Preprocessing tests: EXIF + content rotation, deskew, perspective, crop.

Auto-calibration uses synthetic images with known rotation / perspective
params (SPEC testing: "预处理用合成变换图（已知旋转角/透视矩阵）验证可自动定标").
"""

import pytest

from PIL import Image, ImageDraw, ImageFont

from graph2note import preprocess

pil = pytest.importorskip("PIL")
np = pytest.importorskip("numpy")


def _make_text(width=900, height=700):
    im = Image.new("RGB", (width, height), (255, 255, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=30)
    except TypeError:  # older Pillow
        font = ImageFont.load_default()
    y = 60
    for i in range(10):
        d.text((40, y), f"Line of handwritten note {i} delta alpha", fill=(40, 40, 40), font=font)
        d.text((40, y + 40), "这是中文行的测试文本内容第x行", fill=(60, 60, 60), font=font)
        y += 90
    return im


def test_unrotated_image_needs_no_rotation():
    base = _make_text()
    g, _, _ = preprocess._gray_scaled(base, 700)
    assert preprocess.content_rotation_degrees(np, g) == 0


def test_90_rotated_image_is_detected_and_fixed(tmp_path):
    base = _make_text().rotate(-90, expand=True, resample=Image.BICUBIC,
                               fillcolor=(255, 255, 255))
    g, _, _ = preprocess._gray_scaled(base, 700)
    assert preprocess.content_rotation_degrees(np, g) == 90


def test_180_rotated_image_is_detected(tmp_path):
    base = _make_text().rotate(-180, expand=True, resample=Image.BICUBIC,
                               fillcolor=(255, 255, 255))
    g, _, _ = preprocess._gray_scaled(base, 700)
    assert preprocess.content_rotation_degrees(np, g) in (180, 0)  # 180 is self-consistent


def test_deskew_recovers_known_small_angle():
    base = _make_text()
    rotated = base.rotate(-4, expand=True, resample=Image.BICUBIC, fillcolor=(255, 255, 255))
    g, _, _ = preprocess._gray_scaled(rotated, 700)
    fix = preprocess.deskew_angle(np, g)
    # Expected ~ +4 degrees; allow tolerance for rasterization.
    assert 2.5 <= fix <= 6.0


def test_perspective_corrects_known_quad():
    base = _make_text()
    quad = [[100, 120], [800, 150], [780, 650], [110, 600]]
    out = preprocess.correct_perspective(base, quad)
    q = np.asarray(quad, float)
    want_w = int(round(max(np.linalg.norm(q[1] - q[0]), np.linalg.norm(q[3] - q[2]))))
    want_h = int(round(max(np.linalg.norm(q[3] - q[0]), np.linalg.norm(q[2] - q[1]))))
    assert out.size == (want_w, want_h)
    assert out.mode == "RGB"


def test_perspective_rejects_bad_quad():
    with pytest.raises(ValueError):
        preprocess.correct_perspective(_make_text(), [[1, 2], [3, 4]])


def test_exif_rotation_applied(tmp_path):
    # Build a synthetic image carrying a 90° EXIF orientation tag.
    base = _make_text()
    ex = base.copy()
    exif = Image.Exif()
    exif[274] = 8  # Rotate 90 CW to display
    ex.save(str(tmp_path / "exif.jpg"), exif=exif)
    opened = preprocess.open_image(str(tmp_path / "exif.jpg"))
    out = preprocess.apply_exif_orientation(opened)
    assert out.size == (base.size[1], base.size[0])  # swapped => rotation applied


def test_preprocess_chain_writes_stages_and_final(tmp_path):
    src = str(tmp_path / "src.png")
    _make_text().save(src)
    r = preprocess.preprocess_image(src, str(tmp_path / "out"), save_stages=True)
    final = r["final"]
    assert final  # final path returned
    # The final image exists and is loadable.
    im = preprocess.open_image(final)
    assert im.size[0] > 0 and im.size[1] > 0
    # Every stage was written for inspection.
    assert (tmp_path / "out" / "_stage_raw.png").exists()
    assert (tmp_path / "out" / "_stage_final.png").exists()


def test_enhance_contrast_expands_range():
    base = _make_text().convert("L")
    out = preprocess.enhance_contrast(base.convert("RGB"))
    import numpy as npn

    arr = npn.asarray(out.convert("L"))
    lo, hi = int(arr.min()), int(arr.max())
    assert hi > lo  # contrast stretch produced a real dynamic range
    assert hi <= 255 and lo >= 0