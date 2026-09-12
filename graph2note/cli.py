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


# ---------------------------------------------------------------------------
# repair scan / repair run — black-image detection + re-parse loop (R1)
# ---------------------------------------------------------------------------


def build_repair_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note repair",
        description=(
            "Detect legacy black-image documents (preprocessed.png mean < 10) and "
            "re-run them from preprocessed_raw.png as a new version.  scan is a "
            "read-only dry-run; run is a dry-run unless --yes is given."
        ),
    )
    p.add_argument("--storage", default=None,
                   help="document library storage dir (default: GRAPH2NOTE_STORAGE "
                        "or <support>/storage)")
    sub = p.add_subparsers(dest="action", required=True)

    scan = sub.add_parser("scan", help="list black/suspected/needs-reupload documents (dry-run)")
    scan.add_argument("--json", action="store_true", help="emit the full scan report as JSON")
    scan.add_argument("--storage", default=argparse.SUPPRESS,
                      help="document library storage dir")

    run = sub.add_parser("run", help="re-run selected documents (dry-run unless --yes)")
    run.add_argument("--doc", action="append", default=[],
                     help="document id to repair (repeatable); default = all repairable")
    run.add_argument("--yes", action="store_true",
                     help="confirm and actually call the parser (default: dry-run)")
    run.add_argument("--model", default=None, help="override the parse model")
    run.add_argument("--json", action="store_true", help="emit the run result as JSON")
    run.add_argument("--storage", default=argparse.SUPPRESS,
                     help="document library storage dir")
    return p


def _print_scan(report: dict) -> None:
    s = report["summary"]
    print(f"黑图 {s['black']} 篇 · 疑似空白 {s['suspected']} 篇 · "
          f"需重新上传 {s['needs_reupload']} 篇 · 正常 {s['healthy']} 篇")
    print(f"可修复 {s['repairable']} 篇 · 页数 {s['pages']} · "
          f"预估 VLM 调用数 {s['estimated_vlm_calls']}")
    if report["needs_reupload"]:
        print("需重新上传（缺 preprocessed_raw.png，不进入自动重跑队列）：")
        for item in report["documents"]:
            if item["status"] == "needs_reupload":
                print(f"  - {item['document_id']}  {item['title']}")
    problem = [d for d in report["documents"] if d["status"] != "healthy"]
    if problem:
        print("待修复名单：")
        for item in problem:
            mean = "—" if item["mean"] is None else f"{item['mean']:.1f}"
            ink = "—" if item["ink_ratio"] is None else f"{item['ink_ratio']:.4f}"
            print(f"  - {item['document_id']}  {item['status_label']}  "
                  f"页数 {item['pages']}  均值 {mean}  墨迹 {ink}  {item['title']}")
    if not problem:
        print("没有需要修复的文档。")


def _print_plan(plan: dict) -> None:
    print(f"dry-run（未执行；加 --yes 才会真实调用 VLM）")
    print(f"计划修复 {len(plan['document_ids'])} 篇 · 页数 {plan['pages']} · "
          f"预估 VLM 调用数 {plan['estimated_vlm_calls']}")
    for item in plan["documents"]:
        print(f"  - {item['document_id']}  {item['status_label']}  {item['title']}")
    for skip in plan["skipped"]:
        print(f"  - {skip['document_id']}  跳过（{skip['reason']}）")
    if not plan["document_ids"]:
        print("没有需要重跑的文档。")


def _cmd_repair(args) -> int:
    import json as _json

    from . import config
    from . import repair as repairlib
    from .store import FileDocumentStore

    storage = config.ensure_storage_dir(config.resolve_storage_dir(args.storage))
    store = FileDocumentStore(str(storage))

    if args.action == "scan":
        report = repairlib.scan_library(store)
        if args.json:
            print(_json.dumps(report, ensure_ascii=False, indent=2))
        else:
            _print_scan(report)
        return 0

    if not args.yes:
        plan = repairlib.plan_repair(store, args.doc or None)
        if args.json:
            print(_json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            _print_plan(plan)
        return 0

    job = repairlib.run_repair(store, args.doc or None, model=args.model)
    if args.json:
        print(_json.dumps(job.public(), ensure_ascii=False, indent=2))
    else:
        print(f"修复任务 {job.repair_id} · 状态 {job.status} · "
              f"预估 VLM 调用数 {job.estimated_vlm_calls} · 实际 {job.vlm_calls}")
        for item in job._sorted_items():
            detail = item.error or item.reason or ""
            post = "" if item.post_mean is None else (
                f" 均值 {item.post_mean:.1f} 墨迹 "
                f"{'—' if item.post_ink is None else format(item.post_ink, '.4f')}")
            print(f"  - {item.document_id}  {item.status}{post}  {detail}")
        print(f"结果已落盘：{job.work_dir}/job.json")
    return 0 if job.status == "done" else 1


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
    if argv and argv[0] == "repair":
        args = build_repair_parser().parse_args(argv[1:])
        return _cmd_repair(args)
    if argv and argv[0] == "visual-qa":
        from . import visualqa
        args = visualqa.build_visualqa_parser().parse_args(argv[1:])
        return visualqa.cmd_visualqa(args)
    args = build_compile_parser().parse_args(argv)
    return _cmd_compile(args)


if __name__ == "__main__":
    raise SystemExit(main())