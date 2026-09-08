"""Prepare the working sample set for Spike 3.

Builds spike3/samples/ containing all images sent to the VLM:
  * S01..S10  - synthesized flowchart sketches (ground truth in
                spike3/ground_truth/)
  * R01, R02  - the two real manuscripts from test-images/, downscaled to a
                LLM-friendly width (they are large 1920x1080).

Registers each sample as real or synthetic and its ground-truth path (None for
real ones, whose semantics we judge qualitatively).
"""
from __future__ import annotations

import os

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLES = os.path.join(HERE, "samples")
GT = os.path.join(HERE, "ground_truth")
TEST_IMAGES = os.path.abspath(os.path.join(HERE, os.pardir, "test-images"))

MAX_WIDTH = 1280


def _resize(src: str, dst: str, max_w: int = MAX_WIDTH) -> str:
    im = Image.open(src).convert("RGB")
    if im.width > max_w:
        h = round(im.height * max_w / im.width)
        im = im.resize((max_w, h), Image.LANCZOS)
    out = os.path.join(SAMPLES, dst)
    im.save(out, "PNG", optimize=True)
    return out


def prepare() -> dict:
    registry = {}
    # synthesized
    for i in range(1, 11):
        name = f"S{i:02d}"
        img = os.path.join(SAMPLES, f"{name}.png")
        gt = os.path.join(GT, f"{name}.json")
        registry[name] = dict(image=img, ground_truth=gt, real=False)
    # real manuscripts
    real = [("01-requirements-arch.jpg", "R01"),
            ("02-digitize-pipeline.jpg", "R02")]
    for src, name in real:
        img = _resize(os.path.join(TEST_IMAGES, src), f"{name}.png")
        registry[name] = dict(image=img, ground_truth=None, real=True)
    return registry


def registry_path() -> str:
    return os.path.join(HERE, "sample_registry.json")


def load_registry() -> dict:
    import json
    with open(registry_path(), encoding="utf-8") as fh:
        return json.load(fh)


def main():
    import json
    reg = prepare()
    with open(registry_path(), "w", encoding="utf-8") as fh:
        json.dump(reg, fh, ensure_ascii=False, indent=2)
    for name, info in reg.items():
        sz = os.path.getsize(info["image"])
        print(f"{name}: {'real' if info['real'] else 'synth'} "
              f"{os.path.basename(info['image'])} {sz//1024}KB "
              f"gt={'yes' if info['ground_truth'] else 'no'}")


if __name__ == "__main__":
    main()