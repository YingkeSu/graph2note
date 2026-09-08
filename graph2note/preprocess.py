"""Document image preprocessing — an independent fixed stage before parsing.

Pipeline (SPEC FR-002/003):
  1. EXIF orientation first; when it conflicts with perceived content, content
     wins (SPEC Edge Case).
  2. Content-based rotation detection (0/90/180/270) using text-line structure.
  3. Deskew (small-angle) via projection-profile scoring on downscaled gray.
  4. Perspective correction (best-effort automatic page-corner detection, or an
     explicit ``quad`` supplied by the caller).
  5. Edge/background crop to the non-background content box.
  6. Contrast enhancement (percentile stretch + slight sharp boost).

Every stage can be written to disk for inspection (``save_stages=True``) and
the final preprocessed image path is what the parsing layer consumes.

Preprocessing invokes no OCR, no LLM, and no network.  Functions are
deterministic given the same input bytes.
"""

from __future__ import annotations

import os
from typing import Iterator

# Pillow/numpy are imported lazily so this module can be imported in minimal
# CI environments without imaging deps; the operators raise a clear error only
# when actually used.
_PIL = None
_NP = None


def _pil():
    global _PIL
    if _PIL is None:
        import PIL  # noqa: PLC0415
        from PIL import Image, ImageChops, ImageOps  # noqa: PLC0415

        _PIL = (Image, ImageChops, ImageOps)
    return _PIL


def _np():
    global _NP
    if _NP is None:
        import numpy as _m  # noqa: PLC0415

        _NP = _m
    return _NP


class PreprocessError(ValueError):
    """Raised when a source image cannot be preprocessed."""


def _require_pixels(img, font) -> None:  # pragma: no cover - trivial
    pass


def open_image(path: str) -> "object":
    Image, _, _ = _pil()
    if not os.path.exists(path):
        raise FileNotFoundError(f"source image not found: {path}")
    try:
        return Image.open(path).convert("RGB")
    except Exception as exc:
        raise PreprocessError(f"cannot open image {path!r}: {exc}") from exc


def apply_exif_orientation(img) -> "object":
    """Apply EXIF orientation tag; returns a new image (never mutates input)."""
    Image, _, ImageOps = _pil()
    try:
        return ImageOps.exif_transpose(img.copy())
    except Exception:
        return img.copy()


def _content_orientation_score(np, gray, angle_deg: int) -> float:
    """Score how ``angle`` degrees of CCW rotation makes text lines horizontal."""
    # Rotate by -angle so content lines align to the raster rows.
    import PIL.Image  # noqa: PLC0415

    if angle_deg != 0:
        rotated = PIL.Image.fromarray(gray).rotate(angle_deg, expand=False, fillcolor=255)
        arr = np.asarray(rotated)
    else:
        arr = gray
    text = arr < 128  # dark ink on light paper
    row_proj = text.sum(axis=1).astype(float)
    col_proj = text.sum(axis=0).astype(float)
    rv = row_proj.std()
    cv = col_proj.std()
    if cv < 1e-6:
        return 0.0
    return float(rv / cv)


def content_rotation_degrees(nnp: "object", gray, candidates=(0, 90, 180, 270)) -> int:
    """Pick the rotation (CCW degrees) that best yields horizontal text lines."""
    best_deg = 0
    best_score = -1.0
    for deg in candidates:
        score = _content_orientation_score(nnp, gray, deg)
        if score > best_score:
            best_score, best_deg = score, deg
    return best_deg


def _deskew_score(np, gray, angle_deg: float) -> float:
    import PIL.Image  # noqa: PLC0415

    im = PIL.Image.fromarray(gray).rotate(angle_deg, resample=2, expand=False, fillcolor=255)
    arr = np.asarray(im)
    text = arr < 128
    row_proj = text.sum(axis=1).astype(float)
    col_proj = text.sum(axis=0).astype(float)
    rv = row_proj.std()
    cv = col_proj.std()
    if cv < 1e-6:
        return 0.0
    # Robust: combine row-variance dominance with total ink edge sharpness.
    return rv / (cv + 1e-6)


def deskew_angle(nnp: "object", gray, lo: float = -6.0, hi: float = 6.0, step: float = 0.5) -> float:
    """Return the rotation angle (degrees, positive = counter-clockwise fix)."""
    best_a, best_s = 0.0, -1.0
    a = lo
    while a <= hi + 1e-9:
        s = _deskew_score(nnp, gray, a)
        if s > best_s:
            best_s, best_a = s, a
        a += step
    return best_a


def _gray_scaled(img, target_width: int = 700) -> tuple["object", int, int]:
    Image, _, _ = _pil()
    np = _np()
    w, h = img.size
    w = min(w, target_width)
    # keep aspect
    scale = w / img.size[0] if img.size[0] else 1.0
    nw, nh = max(1, round(img.size[0] * scale)), max(1, round(img.size[1] * scale))
    small = img.resize((nw, nh), Image.LANCZOS)
    gray = np.asarray(small.convert("L"))
    return gray, nw, nh


def _binarize(np, gray, threshold: int = 180) -> "object":
    return gray < threshold


# ---- connected components & document corner detection ---------------------


def _largest_component(np, binary) -> "object":
    """Two-pass union-find labeling; return mask of the largest component."""
    h, w = binary.shape
    labels = np.zeros((h, w), dtype=np.int32)
    parent = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    next_label = 1
    for y in range(h):
        for x in range(w):
            if not binary[y, x]:
                continue
            up = labels[y - 1, x] if y > 0 else 0
            left = labels[y, x - 1] if x > 0 else 0
            if up == 0 and left == 0:
                labels[y, x] = next_label
                parent[next_label] = next_label
                next_label += 1
            elif up == 0:
                labels[y, x] = left
            elif left == 0:
                labels[y, x] = up
            else:
                labels[y, x] = up
                union(up, left)

    # second pass: canonical roots
    for y in range(h):
        for x in range(w):
            if labels[y, x]:
                labels[y, x] = find(labels[y, x])

    counts = {}
    for y in range(h):
        for x in range(w):
            if labels[y, x]:
                l = labels[y, x]
                counts[l] = counts.get(l, 0) + 1
    if not counts:
        return np.zeros_like(binary)
    biggest = max(counts, key=counts.get)
    return labels == biggest


def _dilate(np, mask, radius: int = 3) -> "object":
    h, w = mask.shape
    out = np.zeros_like(mask)
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            sy = np.clip(np.arange(h) + dy, 0, h - 1)
            sx = np.clip(np.arange(w) + dx, 0, w - 1)
            out |= mask[sy[:, None], sx[None, :]]
    return out


def _document_quad(np, gray) -> "object | None":
    """Return 4 corners (approx. page) as np array [[x,y]...] or None."""
    # Page = bright region on typically darker background.
    page_mask = gray > 205
    page_mask = _dilate(np, page_mask, radius=4)
    comp = _largest_component(np, page_mask)
    if comp.sum() < 0.05 * comp.size:  # too little bright area -> not a clean page
        return None
    ys, xs = np.nonzero(comp)
    if len(xs) < 4:
        return None
    cx, cy = xs.mean(), ys.mean()
    # 4 extreme points per diagonal direction from centroid.
    dirs = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    corners = []
    for dxn, dyn in dirs:
        # maximize dot with (dxn,dyn):  pick max of x*dxn + y*dyn
        score = xs * dxn + ys * dyn
        k = int(np.argmax(score))
        corners.append((int(xs[k]), int(ys[k])))
    # dedupe
    uniq = list(dict.fromkeys(corners))
    if len(uniq) < 4:
        return None
    return np.asarray(uniq[:4], dtype=float)


def _homography(np, src, dst):
    """Return the 3x3 homography H (row-major numpy) mapping src -> dst."""
    # Solve H*src_i = dst_i (up to scale) via the standard SVD/finite method.
    n = src.shape[0]
    A = []
    for i in range(n):
        x, y = src[i]
        u, v = dst[i]
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.asarray(A, dtype=float)
    # H is the null-space of A -> last column of V from SVD (smallest singular vec).
    _, _, Vt = np.linalg.svd(A)
    h = Vt[-1]  # 8 unknowns (scale fixed: H22 = 1)
    H = np.array(
        [[h[0], h[1], h[2]], [h[3], h[4], h[5]], [h[6], h[7], 1.0]], dtype=float
    )
    return H


def correct_perspective(img, quad) -> "object":
    """Warp the quad (list of 4 [x,y], order: TL,TR,BR,BL) to a rectangle.

    Returns a new, perspective-corrected image sized to the quad's longer
    edges.  The quad is in full-resolution image coordinates.
    """
    Image, _, _ = _pil()
    np = _np()
    quad = np.asarray(quad, dtype=float)
    if quad.shape != (4, 2):
        raise ValueError("quad must be 4 [x,y] corners")
    sw = max(float(np.linalg.norm(quad[1] - quad[0])), float(np.linalg.norm(quad[3] - quad[2])))
    sh = max(float(np.linalg.norm(quad[3] - quad[0])), float(np.linalg.norm(quad[2] - quad[1])))
    sw, sh = max(2, int(round(sw))), max(2, int(round(sh)))
    src = quad.astype(float)
    dst = np.asarray([[0, 0], [sw, 0], [sw, sh], [0, sh]], dtype=float)
    # forward H: src -> dst; but PIL PERSPECTIVE wants output->input (=H^-1).
    H = _homography(np, src, dst)
    Hi = np.linalg.inv(H)
    if abs(Hi[2, 2]) < 1e-12:
        Hi[2, 2] = 1.0
    Hi /= Hi[2, 2]
    coeffs = tuple(float(v) for v in Hi[:2, :].ravel()) + tuple(float(v) for v in Hi[2, :2])
    return img.transform((sw, sh), Image.PERSPECTIVE, coeffs, resample=Image.BICUBIC)


def detect_perspective_quad(img) -> "object | None":
    """Best-effort auto page-corner detection; None if not confident."""
    np = _np()
    small, nw, nh = _gray_scaled(img, target_width=400)
    quad_small = _document_quad(np, small)
    if quad_small is None:
        return None
    sx, sy = img.size[0] / nw, img.size[1] / nh
    quad = quad_small * [sx, sy]
    return quad


def _crop_content(np, gray):
    text = gray < 240
    if not text.any():
        return (0, 0, gray.shape[1], gray.shape[0])
    ys, xs = np.nonzero(text)
    pad = 12
    x0, x1 = max(0, xs.min() - pad), min(gray.shape[1], xs.max() + pad)
    y0, y1 = max(0, ys.min() - pad), min(gray.shape[0], ys.max() + pad)
    return (x0, y0, x1, y1)


def enhance_contrast(img, low: int = 2, high: int = 98) -> "object":
    """Percentile contrast stretch (brighten white, darken ink)."""
    Image, _, _ = _pil()
    np = _np()
    gray = np.asarray(img.convert("L")).astype(float)
    p_lo, p_hi = np.percentile(gray, [low, high])
    p_hi = max(p_hi, p_lo + 1)
    scaled = np.clip((gray - p_lo) * (255.0 / max(1.0, p_hi - p_lo)), 0, 255).astype("uint8")
    out = Image.fromarray(scaled)
    return out.convert("RGB") if img.mode == "RGB" else out


def save(img, path: str) -> str:
    Image, _, _ = _pil()
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    img.save(path, "PNG", optimize=True)
    return path


def preprocess_image(
    source: str,
    out_dir: str,
    *,
    save_stages: bool = True,
    content_threshold: int = 180,
) -> dict:
    """Run the full preprocessing chain on ``source``.

    Returns a dict::
        {
          "final": str,            # path to the preprocessed PNG
          "stages": {"raw": str, "exif": ..., "rotated": ..., "deskewed": ...,
                     "perspective": ..., "cropped": ..., "final": ...},
          "deskew_deg": float,
          "rotation_deg": int,
          "perspective_applied": bool,
        }

    ``save_stages`` writes every intermediate stage for inspection.
    """
    Image, _, _ = _pil()
    np = _np()
    os.makedirs(out_dir, exist_ok=True)

    def stage(img, name):
        if save_stages:
            p = os.path.join(out_dir, f"_stage_{name}.png")
            save(img, p)
        else:
            p = None
        return p

    raw = open_image(source)
    raw_path = stage(raw, "raw")

    ex = apply_exif_orientation(raw)
    exif_path = stage(ex, "exif")

    gray, _, _ = _gray_scaled(ex, target_width=700)
    rot_deg = content_rotation_degrees(np, gray)
    rotated = ex.rotate(rot_deg, expand=True, fillcolor=(255, 255, 255))
    rot_path = stage(rotated, "rotated")

    gray2, _, _ = _gray_scaled(rotated, target_width=700)
    deskew = deskew_angle(np, gray2)
    if abs(deskew) >= 0.5:
        deskewed = rotated.rotate(-deskew, expand=True, resample=Image.BICUBIC,
                                  fillcolor=(255, 255, 255))
    else:
        deskewed = rotated
    desk_path = stage(deskewed, "deskewed")

    quad = detect_perspective_quad(deskewed)
    perspective_applied = False
    persp = deskewed
    persp_path = None
    if quad is not None:
        try:
            persp = correct_perspective(deskewed, quad)
            perspective_applied = True
            persp_path = stage(persp, "perspective")
        except Exception:
            persp = deskewed

    gray3, _, _ = _gray_scaled(persp, target_width=700)
    box = _crop_content(np, gray3)
    sx, sy = persp.size[0] / gray3.shape[1], persp.size[1] / gray3.shape[0]
    box_full = (int(round(box[0] * sx)), int(round(box[1] * sy)),
                int(round(box[2] * sx)), int(round(box[3] * sy)))
    cropped = persp.crop(box_full)
    crop_path = stage(cropped, "cropped")

    final = enhance_contrast(cropped)
    # The final preprocessed image is the model input — always persist it
    # (intermediate stages are optional inspection aids).
    final_path = os.path.join(out_dir, "_stage_final.png")
    save(final, final_path)
    if not save_stages:
        final_path = final_path

    return {
        "final": final_path or "",
        "stages": {
            "raw": raw_path or source,
            "exif": exif_path,
            "rotated": rot_path,
            "deskewed": desk_path,
            "perspective": persp_path,
            "cropped": crop_path,
            "final": final_path,
        },
        "deskew_deg": round(deskew, 2),
        "rotation_deg": rot_deg,
        "perspective_applied": perspective_applied,
    }


__all__ = [
    "open_image",
    "apply_exif_orientation",
    "content_rotation_degrees",
    "deskew_angle",
    "correct_perspective",
    "detect_perspective_quad",
    "enhance_contrast",
    "preprocess_image",
    "save",
    "PreprocessError",
]