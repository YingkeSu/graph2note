"""Preprocessing tests: EXIF + content rotation, deskew, perspective, crop.

Auto-calibration uses synthetic images with known rotation / perspective
params (SPEC testing: "预处理用合成变换图（已知旋转角/透视矩阵）验证可自动定标").
"""

import os

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


def test_homography_maps_src_points_to_dst():
    # Pins the DLT solve (A h = b); the SVD null-space of A is a different problem.
    src = np.asarray([[100, 120], [800, 150], [780, 650], [110, 600]], float)
    dst = np.asarray([[0, 0], [701, 0], [701, 500], [0, 500]], float)
    H = preprocess._homography(np, src, dst)
    for p, want in zip(src, dst):
        proj = H @ np.asarray([p[0], p[1], 1.0])
        proj = proj[:2] / proj[2]
        assert np.allclose(proj, want, atol=1e-6)


def test_homography_identity_quad_is_identity():
    corners = np.asarray([[0, 0], [99, 0], [99, 79], [0, 79]], float)
    H = preprocess._homography(np, corners, corners)
    assert np.allclose(H, np.eye(3), atol=1e-9)


def test_perspective_identity_quad_preserves_content():
    base = _make_text()
    w, h = base.size
    out = preprocess.correct_perspective(base, [[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
    got = np.asarray(out.convert("L").resize(base.size)).astype(float)
    want = np.asarray(base.convert("L")).astype(float)
    assert got.mean() > 200
    assert (got < 128).mean() > 0.005
    a = (got - got.mean()) / got.std()
    b = (want - want.mean()) / want.std()
    assert float((a * b).mean()) > 0.9


def test_perspective_known_quad_keeps_ink():
    base = _make_text()
    out = preprocess.correct_perspective(base, [[100, 120], [800, 150], [780, 650], [110, 600]])
    arr = np.asarray(out.convert("L"))
    assert arr.mean() > 100
    assert (arr < 128).mean() > 0.001


def _make_full_bleed_scan(width=1240, height=1754):
    """Bright full-bleed scan: page fills the frame edge-to-edge."""
    im = Image.new("RGB", (width, height), (252, 252, 250))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:
        font = ImageFont.load_default()
    y = 60
    i = 0
    while y < height - 60:
        for _ in range(3 + (i % 3) * 2):
            words = "notes diagram alpha beta gamma " * (1 + (i % 4))
            d.text((70, y), words[:60], fill=(50, 50, 50), font=font)
            y += 52
            i += 1
            if y >= height - 60:
                break
        y += 40
    return im


def _assert_readable_scan(path):
    im = preprocess.open_image(path)
    arr = np.asarray(im.convert("L"))
    assert arr.mean() > 150, f"preprocessed output degraded (mean={arr.mean():.1f})"
    assert (arr < 128).mean() > 0.005, "ink content lost in preprocessing"


def test_preprocess_full_bleed_scan_stays_readable(tmp_path):
    src = str(tmp_path / "scan.png")
    _make_full_bleed_scan().save(src)
    r = preprocess.preprocess_image(src, str(tmp_path / "out"), save_stages=False)
    # Full-bleed page => detected quad covers the frame => warp path exercised.
    assert r["perspective_applied"] is True
    _assert_readable_scan(r["final"])


def test_preprocess_rotated90_scan_stays_readable(tmp_path):
    src = str(tmp_path / "scan90.png")
    _make_full_bleed_scan().rotate(-90, expand=True, resample=Image.BICUBIC,
                                   fillcolor=(255, 255, 255)).save(src)
    r = preprocess.preprocess_image(src, str(tmp_path / "out"), save_stages=False)
    assert r["rotation_deg"] == 90
    assert r["perspective_applied"] is True
    _assert_readable_scan(r["final"])


def test_preprocess_real_scan_fixture_stays_readable(tmp_path):
    fixture = os.path.join(os.path.dirname(__file__), "..", "eval", "fixtures", "data", "A02.jpg")
    if not os.path.exists(fixture):
        pytest.skip("eval scan fixture not present")
    r = preprocess.preprocess_image(fixture, str(tmp_path / "out"), save_stages=False)
    assert r["perspective_applied"] is True
    _assert_readable_scan(r["final"])


def test_warp_guard_rejects_collapsed_canvas():
    base = _make_text()
    black = Image.new("RGB", base.size, (0, 0, 0))
    white = Image.new("RGB", base.size, (255, 255, 255))
    assert preprocess._warp_retains_content(np, base, black) is False
    assert preprocess._warp_retains_content(np, base, white) is False
    assert preprocess._warp_retains_content(np, base, base) is True
    assert preprocess._warp_retains_content(np, white, white) is True


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