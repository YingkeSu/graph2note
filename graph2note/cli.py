"""Minimal demo entry point: IR JSON file in, Markdown (.md) file out.

Usage:
    python -m graph2note.cli examples/note.ir.json -o out.md
    python -m graph2note.cli examples/note.ir.json --stdout
    python -m graph2note.cli examples/note.ir.json -o out.md --assets-dir assets
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .attachments import FileAssetWriter
from .ir import IRValidationError, loads_ir
from .render import render_markdown


def build_parser() -> argparse.ArgumentParser:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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


if __name__ == "__main__":
    raise SystemExit(main())
