"""Degradation path tests (FR-009 fallback): crop original image, no garbage.

The crop path never runs OCR/text, so it cannot emit mojibake - it just embeds
the relevant region of the original manuscript.  These tests are fully offline.
"""
import os

import pytest
from PIL import Image

import degrade_crop

SPIKE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _make_fake_manuscript(path, w=400, h=300):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h), (250, 249, 244))
    d = ImageDraw.Draw(im)
    d.rectangle([60, 80, 200, 150], outline=(20, 25, 40), width=4)
    d.rectangle([240, 160, 360, 230], outline=(20, 25, 40), width=4)
    d.line([200, 115, 240, 195], fill=(20, 25, 40), width=3)
    im.save(path, "PNG")
    return path


def test_crop_produces_clean_nonblank_image(tmp_path):
    src = str(tmp_path / "src.png")
    out = str(tmp_path / "crop.png")
    _make_fake_manuscript(src)
    degrade_crop.crop_diagram(src, out)
    assert os.path.exists(out)
    im = Image.open(out)
    assert im.width > 0 and im.height > 0
    # crop should be materially smaller than the full page (content bbox)
    assert im.width < 400 and im.height < 300
    # must actually contain the dark flowchart content
    import numpy as np
    arr = np.array(im.convert("L"))
    assert (arr < 128).mean() > 0.0


def test_crop_blank_raises(tmp_path):
    src = str(tmp_path / "blank.png")
    Image.new("RGB", (100, 100), (255, 255, 255)).save(src, "PNG")
    with pytest.raises(ValueError):
        degrade_crop.crop_diagram(src, str(tmp_path / "o.png"))