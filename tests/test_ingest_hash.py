"""Perceptual hashing determinism + robustness (issue 09)."""

import numpy as np
import pytest
from PIL import Image

from graph2note.ingest import dhash, phash, hamming, similarity


def _page(seed=1, w=420, h=560, brightness=1.0, rotate=0.0, ink=25):
    rng = np.random.default_rng(seed)
    im = np.full((h, w, 3), 250, dtype=np.uint8)
    for i in range(6):
        y = 70 + i * 80
        x = int(rng.integers(40, 140))
        n = int(rng.integers(80, 220))
        im[y:y + 4, x:x + n, :] = min(255, int(ink * brightness))
        # second line
        im[y + 20:y + 24, int(rng.integers(60, 160)):int(rng.integers(200, 360)), :] = \
            min(255, int(ink * brightness))
    im = np.clip(im, 0, 255).astype(np.uint8)
    pil = Image.fromarray(im)
    if rotate:
        pil = pil.rotate(rotate, fillcolor=(250, 250, 250))
    return pil


def _blank():
    return Image.fromarray(np.full((300, 240, 3), 250, np.uint8))


def test_hashes_are_deterministic():
    im = _page(seed=7)
    assert phash(im) == phash(im)
    assert dhash(im) == dhash(im)
    assert len(phash(im)) == 16  # 64 bits
    assert len(dhash(im)) == 16


def test_same_page_lighting_rotation_stays_close():
    base = _page(seed=1)
    for perturb in [dict(brightness=1.35), dict(brightness=0.6),
                    dict(rotate=1.3), dict(rotate=-1.0)]:
        other = _page(seed=1, **perturb)
        assert hamming(phash(base), phash(other)) <= 6, perturb
        assert hamming(dhash(base), dhash(other)) <= 10, perturb


def test_different_pages_are_far_apart():
    a = _page(seed=1)
    b = _page(seed=123)
    assert hamming(phash(a), phash(b)) >= 20
    assert hamming(dhash(a), dhash(b)) >= 20


def test_blank_pages_hash_consistently_but_not_merged_semantics():
    b1, b2 = _blank(), _blank()
    assert hamming(phash(b1), phash(b2)) == 0
    assert similarity(phash(b1), phash(b2)) == 1.0