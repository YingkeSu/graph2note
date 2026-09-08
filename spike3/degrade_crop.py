"""Degradation path: crop the original manuscript image (Spike 3).

When the VLM cannot extract structured nodes/edges from a flowchart, PRD FR-009
says the renderer MUST degrade to embedding a *cropped original image* rather
than producing garbage text.  This module implements and demonstrates that path:
fit a bounding box around the flowchart's non-background content, crop it with
a small margin, and save a clean PNG ready to embed.  No OCR, no text pipeline -
so it can never produce mojibake.
"""
from __future__ import annotations

import os

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))


def crop_diagram(src: str, out_path: str, margin_frac: float = 0.04,
                 padding_px: int = 12, max_width: int = 900) -> str:
    """Crop the non-background bounding box of an image for embedding."""
    im = Image.open(src).convert("RGB")
    arr = np.array(im.convert("L"))
    # background = near-white/near-light manuscript paper
    content = arr < 235
    if not content.any():
        raise ValueError("image appears blank; nothing to crop")
    ys, xs = np.nonzero(content)
    y0, y1 = int(ys.min()), int(ys.max())
    x0, x1 = int(xs.min()), int(xs.max())
    # margins in px, scaled to content size
    mw = int((x1 - x0) * margin_frac) + padding_px
    mh = int((y1 - y0) * margin_frac) + padding_px
    box = (max(0, x0 - mw), max(0, y0 - mh),
           min(arr.shape[1], x1 + mw), min(arr.shape[0], y1 + mh))
    c = im.crop(box)
    if c.width > max_width:  # keep embedded asset small in the repo
        h = max(1, round(c.height * max_width / c.width))
        c = c.resize((max_width, h), Image.LANCZOS)
    c.save(out_path, "PNG", optimize=True)
    return out_path


def crop_all() -> list[dict]:
    """Crop every sample image into plots/degrade/, for demonstration + a
    degraded-pipeline fixture (no extraction needed)."""
    import prepare_samples
    reg = prepare_samples.load_registry()
    outdir = os.path.join(HERE, "plots", "degrade")
    os.makedirs(outdir, exist_ok=True)
    results = []
    for name, info in reg.items():
        out = os.path.join(outdir, f"{name}_crop.png")
        try:
            crop_diagram(info["image"], out)
            results.append({"sample": name, "crop": out,
                            "size": os.path.getsize(out)})
        except ValueError as exc:
            results.append({"sample": name, "error": str(exc)})
    return results


if __name__ == "__main__":
    import json
    json.dump(crop_all(), open(os.path.join(HERE, "outputs", "degrade.json"),
                               "w"), ensure_ascii=False, indent=2)
    for r in crop_all():
        print(r)