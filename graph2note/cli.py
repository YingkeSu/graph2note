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

    # 默认 out-dir：--out-dir 显式给出→用它；否则若 -o 显式给出→用 .md 父目录
    #（保证 assets/ 与 .md 同址，相对引用可解析）；都未给出→图片父目录。
    out_dir = args.out_dir
    if out_dir is None:
        out_dir = (args.output.parent if args.output is not None
                   else image.parent)
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


# ---------------------------------------------------------------------------
# notes-export [storage] -o vault — incremental export closed loop (issue 03)
# ---------------------------------------------------------------------------


def build_notes_export_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note notes-export",
        description=(
            "Incremental Obsidian vault export closed loop: load the document "
            "library, classify (rule classifier) into a scheme, persist topics,"
            " then incrementally apply only the changed files to the vault.  "
            "Re-run after parsing docs."
        ),
    )
    p.add_argument(
        "-o", "--output", type=Path, help="vault output directory"
    )
    p.add_argument(
        "--storage", default=None,
        help="document library storage dir (default: GRAPH2NOTE_STORAGE or "
             "<support>/storage)",
    )
    return p


def _cmd_notes_export(args) -> int:
    from . import config
    from .notes.loop import run_incremental_export
    from .store import FileDocumentStore

    out_dir = args.output or Path("notes-export")
    storage = config.ensure_storage_dir(config.resolve_storage_dir(args.storage))
    store = FileDocumentStore(str(storage))
    try:
        report, vault, entries = run_incremental_export(store, out_dir)
    except Exception as exc:  # includes VaultExportError (dead link)
        print(f"notes-export failed: {exc}", file=sys.stderr)
        return 1
    print(f"storage={storage}")
    print(f"{'documents='}{len(entries)}")
    for label in ("added", "updated", "deleted", "conflicts", "kept_user"):
        items = report[label]
        if items:
            print(f"{label}: {len(items)}")
    print(f"vault={vault.root}")
    return 0


# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------


def build_digest_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note digest",
        description=(
            "Generate a weekly digest (Markdown summary over a time-ranged slice "
            "of the library). Repeat requests reuse the fingerprint cache; "
            "--force regenerates."
        ),
    )
    p.add_argument("--week", choices=("this", "last"), default=None,
                   help="shortcut for 本周 (this) / 上周 (last)")
    p.add_argument("--from", dest="from_date", default=None,
                   help="custom range start date (YYYY-MM-DD)")
    p.add_argument("--to", dest="to_date", default=None,
                   help="custom range end date (YYYY-MM-DD)")
    p.add_argument("--force", action="store_true",
                   help="ignore the fingerprint cache and regenerate")
    p.add_argument("--storage", default=None,
                   help="document library storage dir (default: GRAPH2NOTE_STORAGE or "
                        "<support>/storage)")
    p.add_argument("--json", action="store_true", help="emit the full result as JSON")
    return p


def _cmd_digest(args) -> int:
    import json

    from . import config as _cfg
    from . import digest as _digest
    from .store import FileDocumentStore

    storage = _cfg.ensure_storage_dir(_cfg.resolve_storage_dir(args.storage))
    if args.week:
        kind = "this_week" if args.week == "this" else "last_week"
        from_, to = None, None
    elif args.from_date or args.to_date:
        kind, from_, to = "custom", args.from_date, args.to_date
    else:
        kind, from_, to = "this_week", None, None
    try:
        range_spec = _digest.resolve_range(kind, from_=from_, to=to)
    except _digest.RangeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    store = FileDocumentStore(str(storage))
    records = []
    for summary in store.list_documents():
        record = store.get_document(summary["document_id"])
        if record is not None:
            records.append(record)
    result = _digest.generate_digest(records, range_spec, storage_dir=storage, force=args.force)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if result["status"] == "empty":
        print(result["message"])
        return 0
    if result["status"] == "error":
        print(f"digest failed: {result['message']}", file=sys.stderr)
        return 1
    meta = result["digest"] or {}
    state = "cached" if result["cached"] else "generated"
    print(f"{state} {meta.get('digest_id')} · {result['range']['label']} · "
          f"{len(result['documents'])} 篇 · {meta.get('model')}")
    print(f"wrote {_digest.digests_dir(storage) / (str(meta.get('digest_id')) + '.md')}")
    return 0


def build_config_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note config",
        description="Show the effective runtime config (support/storage/settings paths).",
    )
    p.add_argument("--json", action="store_true", help="emit JSON")
    return p


def _cmd_config(args) -> int:
    import json as _json
    from . import config as _cfg

    info = _cfg.describe()
    if args.json:
        print(_json.dumps(info, ensure_ascii=False, indent=2))
    else:
        for key, value in info.items():
            print(f"{key}={value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "parse":
        args = build_parse_parser().parse_args(argv[1:])
        return _cmd_parse(args)
    if argv and argv[0] == "config":
        args = build_config_parser().parse_args(argv[1:])
        return _cmd_config(args)
    if argv and argv[0] == "verify":
        from .verify import cli as _vcli
        args = _vcli.build_verify_parser().parse_args(argv[1:])
        return _vcli._cmd_verify(args)
    if argv and argv[0] == "notes-export":
        args = build_notes_export_parser().parse_args(argv[1:])
        return _cmd_notes_export(args)
    if argv and argv[0] == "digest":
        args = build_digest_parser().parse_args(argv[1:])
        return _cmd_digest(args)
    if argv and argv[0] == "diff":
        from .semantic import cli as _dcli
        args = _dcli.build_diff_parser().parse_args(argv[1:])
        return _dcli.cmd_diff(args)
    if argv and argv[0] == "visual-qa":
        from . import visualqa
        args = visualqa.build_visualqa_parser().parse_args(argv[1:])
        return visualqa.cmd_visualqa(args)
    args = build_compile_parser().parse_args(argv)
    return _cmd_compile(args)


if __name__ == "__main__":
    raise SystemExit(main())