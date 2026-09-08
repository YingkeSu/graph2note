"""``graph2note verify`` — dual-model cross-validation CLI (issue 10).

Runs two independent model parses of an image, writes the aggregated
divergence report as JSON + readable Markdown.  The Markdown form is the human
"按块聚合" view; the JSON form is what issue 06's reserved verification display
slot and notes-organizer traceability consume.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import cross_validate, DEFAULT_MODEL_A, DEFAULT_MODEL_B
from . import report as _report


def build_verify_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note verify",
        description=(
            "Cross-validate recognition of an image with two independent "
            "vision models and emit an aggregated divergence report."
        ),
    )
    p.add_argument("image", type=Path, help="manuscript image (JPG/JPEG/PNG)")
    p.add_argument("-o", "--out-dir", type=Path, default=None,
                   help="output directory for verify.<stem>.{json,md} (default: image dir)")
    p.add_argument("--model-a", default=DEFAULT_MODEL_A, help="primary model")
    p.add_argument("--model-b", default=DEFAULT_MODEL_B, help="second model")
    p.add_argument("--cache-dir", type=Path, default=None,
                   help="optional VLM reply cache dir (recorded replies reused)")
    p.add_argument("--no-preprocess", action="store_true",
                   help="send the raw image to the models (skip preprocessing)")
    p.add_argument("--json", dest="json_path", type=Path, default=None,
                   help="explicit path for the JSON report")
    p.add_argument("--md", dest="md_path", type=Path, default=None,
                   help="explicit path for the Markdown report")
    return p


def _cmd_verify(args) -> int:
    image = args.image
    if not image.exists():
        print(f"error: image not found: {image}", file=sys.stderr)
        return 2

    cache = None
    if args.cache_dir:
        from .. import vlm
        cache = vlm.VlmCache(str(args.cache_dir))

    # preprocess before sending to BOTH models (independent fixed stage)
    pre_img = str(image)
    if not args.no_preprocess:
        out_dir = args.out_dir or image.parent
        pre_dir = Path(out_dir) / "preprocessed"
        pre_dir.mkdir(parents=True, exist_ok=True)
        from .. import preprocess as pp
        pre_img = pp.preprocess_image(str(image), str(pre_dir), save_stages=False)["final"]

    try:
        rep = cross_validate(
            pre_img,
            model_a=args.model_a,
            model_b=args.model_b,
            cache=cache,
        )
    except Exception as exc:
        print(f"verify failed: {exc}", file=sys.stderr)
        return 1

    out_dir = args.out_dir or image.parent
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = image.stem
    json_path = args.json_path or (out_dir / f"verify.{stem}.json")
    md_path = args.md_path or (out_dir / f"verify.{stem}.md")
    json_path.write_text(_report.to_json(rep), encoding="utf-8")
    md_path.write_text(_report.to_markdown(rep, include_raw=True), encoding="utf-8")

    print(f"wrote {json_path}", file=sys.stderr)
    print(f"wrote {md_path}", file=sys.stderr)
    print(json.dumps({
        "verified": rep.verified,
        "note": rep.note,
        "counts": rep.diff.counts,
        "duplicates_a": len(rep.duplicates_a),
        "duplicates_b": len(rep.duplicates_b),
        "model_a": rep.model_a,
        "model_b": rep.model_b,
    }, ensure_ascii=False, indent=2))
    return 0


__all__ = ["build_verify_parser", "_cmd_verify"]