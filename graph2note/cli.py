"""graph2note CLI.

Two entry points:

* ``parse <image> -o out.md`` — full automated pipeline: image → preprocess →
  Recognition Router (Route A VLM) → validated IR → Markdown → assets, plus a
  staged timing JSON for the issue-11 baseline.
* legacy default — compile an existing IR JSON file to Markdown (issue-02 demo),
  preserved for backward compatibility.

No keys are accepted/printed; the gateway reads ``OPENCODE_API_KEY`` from env
or the repo-root ``.env`` (gitignored).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .attachments import FileAssetWriter
from .ir import IRValidationError, loads_ir
from .render import render_markdown

DEFAULT_MODEL = "glm-5.3-flash"


# ---------------------------------------------------------------------------
# parse <image> — full pipeline
# ---------------------------------------------------------------------------


def build_parse_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note parse",
        description="Parse a manuscript image into deterministic Markdown (full pipeline).",
    )
    p.add_argument("image", type=Path, help="path to a manuscript image (JPG/JPEG/PNG)")
    p.add_argument("-o", "--output", type=Path, default=None,
                   help="output .md file (default <out-dir>/<image-stem>.md)")
    p.add_argument("--out-dir", type=Path, default=None,
                   help="directory for .md, assets/, preprocessed/, timing.json")
    p.add_argument("--model", default=os.environ.get("GRAPH2NOTE_MODEL", DEFAULT_MODEL),
                   help="vision model id (default %(default)s)")
    p.add_argument("--cache-dir", type=Path, default=None,
                   help="optional VLM reply cache dir (recorded replies reused)")
    p.add_argument("--no-preprocess", action="store_true",
                   help="skip the preprocessing stage (send raw image to model)")
    p.add_argument("--no-stage-save", action="store_true",
                   help="do not save intermediate preprocessing stages")
    p.add_argument("--max-retries", type=int, default=2,
                   help="IR-validation retry count (default %(default)s)")
    p.add_argument("--timing", type=Path, default=None,
                   help="path for timing JSON (default <out-dir>/timing.json)")
    return p


def _cmd_parse(args) -> int:
    from . import pipeline
    from .router import RecognitionError
    from .timing import StageTimer

    image = args.image
    if not image.exists():
        print(f"error: image not found: {image}", file=sys.stderr)
        return 2

    out_dir = args.out_dir or image.parent
    out_dir = Path(out_dir)
    cache = pipeline_assets_cache(args.cache_dir)
    timer = StageTimer()
    from .pipeline import make_router

    router = make_router(args.model, cache=cache, max_retries=args.max_retries)

    try:
        result = pipeline.parse_document(
            str(image),
            str(out_dir),
            model=args.model,
            router=router,
            cache=cache,
            doc_id=image.stem,
            timer=timer,
            preprocess=not args.no_preprocess,
            save_preprocess_stages=not args.no_stage_save,
        )
    except RecognitionError as exc:
        print(f"parse failed (recognition): {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"parse failed: {exc}", file=sys.stderr)
        return 1

    out_md = args.output or Path(result.markdown_path)
    if args.output is not None:
        out_md.write_text(result.markdown, encoding="utf-8")
    print(f"wrote {out_md}", file=sys.stderr)
    print(
        f"strategy={result.route.strategy} retries={result.route.retries} "
        f"degraded={result.route.degraded_block_indices} "
        f"warnings={len(result.route.warnings)}",
        file=sys.stderr,
    )

    # human-readable summary goes to stdout
    print(json_omit(result.route.warnings, result.timing_json))
    return 0


def pipeline_assets_cache(cache_dir):
    if cache_dir is None:
        return None
    from . import vlm

    return vlm.VlmCache(str(cache_dir))


def json_omit(warnings, timing_json) -> str:
    import json

    return json.dumps(
        {"warnings": warnings, "timing": timing_json, "doc_ready": True},
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# legacy: IR JSON -> Markdown (issue 02)
# ---------------------------------------------------------------------------


def build_compile_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note",
        description="Compile a Document IR JSON file into deterministic Markdown.",
    )
    p.add_argument("ir_json", type=Path, help="path to a Document IR JSON file")
    p.add_argument("-o", "--output", type=Path, default=None, help="output .md file")
    p.add_argument("--stdout", action="store_true", help="write Markdown to stdout")
    p.add_argument(
        "--assets-dir",
        type=Path,
        default=None,
        help=(
            "base directory holding the generated assets/ folder (diagram/flow "
            "blocks render deterministic PNGs here; degrades to a crop of the "
            "original image when no structured semantics are present)"
        ),
    )
    return p


def _cmd_compile(args) -> int:
    try:
        raw = args.ir_json.read_bytes()
    except OSError as exc:
        print(f"error: cannot read IR file: {exc}", file=sys.stderr)
        return 2
    try:
        doc = loads_ir(raw)
    except IRValidationError as exc:
        print(f"IR validation failed:\n{exc}", file=sys.stderr)
        return 1

    writer = FileAssetWriter(args.assets_dir) if args.assets_dir else None
    md = render_markdown(doc, doc_id=args.ir_json.stem, attachment_writer=writer)

    if args.stdout or args.output is None:
        sys.stdout.write(md)
        return 0
    try:
        args.output.write_text(md, encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write output: {exc}", file=sys.stderr)
        return 2
    if args.assets_dir:
        print(f"wrote assets to {args.assets_dir}", file=sys.stderr)
    print(f"wrote {args.output}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "parse":
        args = build_parse_parser().parse_args(argv[1:])
        return _cmd_parse(args)
    if argv and argv[0] == "verify":
        from .verify import cli as _vcli
        args = _vcli.build_verify_parser().parse_args(argv[1:])
        return _vcli._cmd_verify(args)
    args = build_compile_parser().parse_args(argv)
    return _cmd_compile(args)


if __name__ == "__main__":
    raise SystemExit(main())