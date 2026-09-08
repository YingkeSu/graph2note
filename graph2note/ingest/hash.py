"""Perceptual image hashing (pure numpy, no extra deps).

Two methods used by the scan-ingest pipeline:

- ``dhash``: differential hash — resize to ``hash_size+1`` square, compare
  horizontal neighbours, encode each comparison as a bit. Fast, robust to
  global brightness shifts.
- ``phash``: DCT-based hash — coarse Discrete Cosine Transform of a resized
  block, keep low-frequency coefficients, encode sign bits. More robust to
  slight rotation / scale and mild jpeg artefacts than dhash.

Both return a hex string whose bit-population encodes the "distance" between
two pictures; similarity is measured as a Hamming distance over the bits
(allowed to be a fraction when hashes hold non-integer-bit representation).

These functions are pure and deterministic: same input array -> same hash.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image as PILImage


# --- helpers -------------------------------------------------------------


def _as_gray_uint8(image):
    """Return a ``(H, W)`` uint8 grayscale numpy array from a PIL/image/array."""
    if isinstance(image, np.ndarray):
        arr = np.asarray(image)
        if arr.ndim == 3:
            # take luma regardless of channel order
            arr = np.mean(arr.astype(np.float32), axis=2).astype(np.uint8)
        return arr
    # PIL Image
    if image.mode != "L":
        image = image.convert("L")
    return np.asarray(image, dtype=np.uint8)


def _norm_contrast(arr: np.ndarray, lo: int = 0, hi: int = 255) -> np.ndarray:
    """Tone-map grayscale to the full range so lighting shifts are de-emphasised."""
    mn, mx = int(arr.min()), int(arr.max())
    if mx - mn < 8:
        return arr.astype(np.uint8)
    out = (arr.astype(np.float32) - mn) * (hi - lo) / (mx - mn) + lo
    return out.astype(np.uint8)


def _hex(bits: Sequence[int]) -> str:
    """Pack a bit vector into a compact hex string (left to right, MSB first)."""
    n = len(bits)
    nbytes = -(-n // 8)
    out = bytearray(nbytes)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (7 - (i % 8))
    return out.hex()


# --- hashing -------------------------------------------------------------


def dhash(image, hash_size: int = 8, normalize: bool = True) -> str:
    """64-bit (8x8) differential hash as a 16-char hex string."""
    arr = _as_gray_uint8(image)
    pil = PILImage.fromarray(arr)
    small = pil.resize((hash_size + 1, hash_size), PILImage.BILINEAR)
    sm = np.asarray(small, dtype=np.float32)
    if normalize:
        sm = _norm_contrast(sm)
    bits = []
    for row in sm:
        for i in range(hash_size):
            bits.append(1 if row[i] < row[i + 1] else 0)
    return _hex(bits)


def _dct2(block: np.ndarray) -> np.ndarray:
    """Separable orthonormal DCT-II (numpy only, surest for square blocks)."""
    N = block.shape[0]
    M = np.zeros((N, N), dtype=np.float32)
    n = np.arange(N)
    for k in range(N):
        M[k] = np.cos(np.pi * (2 * n + 1) * k / (2 * N))
    M[0] *= np.sqrt(1.0 / N)
    M[1:] *= np.sqrt(2.0 / N)
    return M @ block.astype(np.float32) @ M.T


def phash(image, hash_size: int = 8, highfreq_factor: int = 4,
          normalize: bool = True) -> str:
    """64-bit DCT-based perceptual hash as a 16-char hex string.

    Mirrors the classic approach: resize to a ``hash_size*highfreq_factor``
    square, DCT, keep the top-left ``hash_size`` block (DC included), then set
    each bit from whether a coefficient exceeds the block median.  Contrast
    normalisation (optional) de-emphasises global lighting differences.
    """
    arr = _as_gray_uint8(image)
    img_size = hash_size * highfreq_factor
    pil = PILImage.fromarray(arr).resize((img_size, img_size), PILImage.BILINEAR)
    sm = np.asarray(pil, dtype=np.float32)
    if normalize:
        sm = _norm_contrast(sm)
    dct = _dct2(sm)
    low = dct[:hash_size, :hash_size]
    med = np.median(low)
    bits = [1 if v > med else 0 for v in low.ravel()]
    return _hex(bits)


# --- distance ------------------------------------------------------------


def hamming(a: str, b: str) -> int:
    """Hamming distance (number of differing bits) between two hex hashes."""
    ia = int(a, 16)
    ib = int(b, 16)
    return bin(ia ^ ib).count("1")


def hash_len(h: str) -> int:
    """Number of bits represented by a hash string."""
    return len(h) * 4


def similarity(a: str, b: str) -> float:
    """Fractional similarity in [0, 1]; 1.0 == identical."""
    total = hash_len(a)
    if total == 0:
        return 1.0
    return 1.0 - hamming(a, b) / total


ALIASES = {"dhash": dhash, "phash": phash}