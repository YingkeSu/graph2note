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


# ---------------------------------------------------------------------------
# tags backfill — auto-tag the existing library under an explicit budget (A1)
# ---------------------------------------------------------------------------


def build_tags_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note tags",
        description="Tag vocabulary utilities (usable-product-iteration A1).",
    )
    sub = p.add_subparsers(dest="tags_command", required=True)

    b = sub.add_parser(
        "backfill",
        description=(
            "Infer auto tags for documents that never completed an auto-tag "
            "pass.  Default is a dry-run budget report; pass --yes to execute."
        ),
    )
    mode = b.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="report pending documents + estimated calls only (default)")
    mode.add_argument("--yes", action="store_true",
                      help="execute the inference calls (real LLM usage)")
    b.add_argument("--storage", default=None,
                   help="document library storage dir (default: GRAPH2NOTE_STORAGE)")
    b.add_argument("--limit", type=int, default=None,
                   help="cap the number of documents processed this run")
    b.add_argument("--max-chars", type=int, default=None,
                   help="markdown truncation budget per inference")
    b.add_argument("--model", default=None, help="text model override for inference")
    b.add_argument("--provider", default=None, help="provider override for inference")
    b.add_argument("--json", action="store_true", help="emit the report as JSON")

    o = sub.add_parser(
        "organize",
        description=(
            "Audit the whole tag vocabulary with the text model -> a validated "
            "governance plan (synonym merges + theme groups).  Default is a "
            "dry-run summary; pass --yes to apply it deterministically."
        ),
    )
    omode = o.add_mutually_exclusive_group()
    omode.add_argument("--dry-run", action="store_true",
                       help="infer the plan and report its size + budget (default)")
    omode.add_argument("--yes", action="store_true",
                       help="execute the merges + groups (real LLM usage)")
    o.add_argument("--storage", default=None,
                   help="document library storage dir (default: GRAPH2NOTE_STORAGE)")
    o.add_argument("--model", default=None, help="text model override for inference")
    o.add_argument("--provider", default=None, help="provider override for inference")
    o.add_argument("--json", action="store_true", help="emit the report as JSON")
    return p


def run_tags_backfill(args) -> int:
    from . import autotag, config
    from .store import FileDocumentStore

    storage = config.ensure_storage_dir(config.resolve_storage_dir(args.storage))
    store = FileDocumentStore(str(storage))
    max_chars = args.max_chars or autotag.DEFAULT_MAX_CHARS
    dry_run = not args.yes

    if dry_run:
        report = autotag.backfill(
            store, dry_run=True, limit=args.limit, max_chars=max_chars,
        )
    else:
        from .llm_settings import resolve_channel

        channel = resolve_channel("classify")
        provider = args.provider or channel["provider"]
        model = args.model or channel["model"]
        inferrer = autotag.TagInferrer(
            planner=autotag.live_planner(provider=provider, model=model),
            model=model,
            provider=provider,
            max_chars=max_chars,
        )
        report = autotag.backfill(
            store, inferrer=inferrer, dry_run=False, limit=args.limit,
            max_chars=max_chars,
        )

    report["storage"] = str(storage)
    if args.json:
        import json as _json

        print(_json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"storage={storage}")
    if dry_run:
        print(f"dry-run: 待回填文档 {report['pending']} 篇，预估推断调用 "
              f"{report['estimated_calls']} 次（每篇 1 次）")
        print("核对后请加 --yes 执行；可用 --limit 控制单次预算。")
        return 0
    print(f"backfill: 处理 {report['processed']} 篇（成功 {report['succeeded']}，"
          f"失败 {report['failed']}），token 合计 {report['total_tokens']}")
    for item in report["documents"]:
        tags = "、".join(item.get("tags") or []) or "（无）"
        warning = f" warning={item['warning']}" if item.get("warning") else ""
        print(f"- {item['document_id']} [{item['status']}] {tags}{warning}")
    return 0


def run_tags_organize(args) -> int:
    """``tags organize``: LLM plan -> validated review -> deterministic apply."""

    import json as _json
    from datetime import datetime

    from . import config, tagorg
    from .store import FileDocumentStore

    storage = config.ensure_storage_dir(config.resolve_storage_dir(args.storage))
    store = FileDocumentStore(str(storage))
    dry_run = not args.yes
    vocabulary = store.tag_vocabulary()
    entries = store.list_tags()
    counts = {item["tag"]: item["count"] for item in entries}
    provider = args.provider
    model = args.model
    planner = tagorg.live_planner(provider=provider, model=model)
    created_at = datetime.now().isoformat(timespec="seconds")

    try:
        result = tagorg.infer_governance(vocabulary, counts, planner=planner, model=model)
    except Exception as exc:
        report = {
            "dry_run": dry_run, "storage": str(storage), "status": "error",
            "error": str(exc), "estimated_calls": 1, "calls": 0,
        }
        tagorg.record_governance_event(store, {
            "kind": "plan", "created_at": created_at, "status": "error",
            "error": str(exc)[:300], "model": model, "provider": provider,
            "usage": {}, "total_tokens": 0,
        })
        if args.json:
            print(_json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"storage={storage}")
            print(f"治理方案生成失败：{exc}")
        return 1

    summary = tagorg.plan_summary(result.plan or tagorg.TagGovernancePlan(), counts)
    budget = tagorg.estimate_budget(result.prompt)
    report = {
        "dry_run": dry_run,
        "storage": str(storage),
        "status": "ok" if result.plan is not None else "invalid",
        "warning": result.warning,
        "estimated_calls": budget["calls"],
        "calls": 0 if dry_run else 1,
        "budget": budget,
        "usage": result.usage,
        "total_tokens": int(result.usage.get("total_tokens") or 0),
        "vocabulary_size": len(counts),
        **summary,
    }
    tagorg.record_governance_event(store, {
        "kind": "plan", "created_at": created_at,
        "status": report["status"], "warning": result.warning,
        "model": model, "provider": provider,
        "usage": result.usage, "total_tokens": report["total_tokens"],
    })

    if result.plan is None:
        if args.json:
            print(_json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"storage={storage}")
            print(f"治理方案被拒：{result.warning}")
        return 1

    if dry_run:
        if args.json:
            print(_json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        print(f"storage={storage}")
        print(f"dry-run: 词表 {report['vocabulary_size']} 个标签；方案合并 "
              f"{report['merge_count']} 对、分组 {report['group_count']} 组")
        for merge in report["merges"][:20]:
            print(f"  - {merge['source']} → {merge['target']}  "
                  f"（{merge['source_count']} → {merge['target_count']} 份）"
                  f"{(' · ' + merge['reason']) if merge['reason'] else ''}")
        if report["merge_count"] > 20:
            print(f"  … 其余 {report['merge_count'] - 20} 对省略")
        for group in report["groups"]:
            names = "、".join(item["tag"] for item in group["tags"])
            print(f"  # {group['name']}（{group['size']}）: {names}")
        print(f"预估 LLM 调用 {report['estimated_calls']} 次，"
              f"prompt {budget['prompt_chars']} 字符（约 {budget['estimated_prompt_tokens']} tokens），"
              f"输出上限 {budget['max_output_tokens']} tokens")
        print("核对后请加 --yes 执行；本次未写入词表。")
        return 0

    records = store.tag_records()
    applied = tagorg.apply_governance_plan(vocabulary, records, result.plan)
    store.save_tag_vocabulary(vocabulary)
    store.save_tag_records(records)
    report["applied"] = applied
    tagorg.record_governance_event(store, {
        "kind": "apply", "created_at": created_at, "status": "ok",
        "model": model, "provider": provider,
        "usage": result.usage, "total_tokens": report["total_tokens"],
        "merged": applied.get("merged"),
        "labels_before": applied.get("labels_before"),
        "labels_after": applied.get("labels_after"),
    })
    if args.json:
        print(_json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"storage={storage}")
    print(f"organize: 合并 {applied['merged']} 对（跳过 {len(applied['skipped_merges'])} 对），"
          f"标签 {applied['labels_before']} → {applied['labels_after']}，"
          f"分组 {len(applied['groups'])} 组，token 合计 {report['total_tokens']}")
    for group in applied["groups"]:
        print(f"  # {group['name']}: {'、'.join(group['tags'])}")
    return 0


# ---------------------------------------------------------------------------
# docs merge-continuous — significant-tier continuity batch (issue 03)
# ---------------------------------------------------------------------------


def build_docs_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note docs",
        description=(
            "Document organization utilities.  `merge-continuous` batches the "
            "deterministic significant tier (same-PDF adjacent pages) and is "
            "a dry-run unless --yes is given; the suggested tier is never "
            "merged in bulk (confirm it one by one in the Inbox)."
        ),
    )
    sub = p.add_subparsers(dest="docs_command", required=True)
    m = sub.add_parser(
        "merge-continuous",
        description=(
            "Detect and merge continuous documents (deterministic, zero LLM). "
            "Default is a dry-run report; --yes executes the significant tier "
            "only."
        ),
    )
    mode = m.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="report pairs + evidence only (default)")
    mode.add_argument("--yes", action="store_true",
                      help="execute the significant-tier merges (soft-archives sources)")
    m.add_argument("--storage", default=None,
                   help="document library storage dir (default: GRAPH2NOTE_STORAGE "
                        "or <support>/storage)")
    m.add_argument("--tail-blocks", type=int, default=None,
                   help="tail/head window N for overlap detection (default 8)")
    m.add_argument("--min-overlap-ratio", type=float, default=None,
                   help="suggested-tier minimum matched ratio in 0..1 (default 0.5)")
    m.add_argument("--max-distance", type=int, default=None,
                   help="pHash Hamming distance bound for suggestions")
    m.add_argument("--json", action="store_true", help="emit the report as JSON")
    return p


def run_docs_merge_continuous(args) -> int:
    import json as _json

    from . import config
    from . import continuity
    from . import evolution
    from .store import FileDocumentStore

    storage = config.ensure_storage_dir(config.resolve_storage_dir(args.storage))
    store = FileDocumentStore(str(storage))
    report = continuity.merge_continuous(
        store,
        dry_run=not args.yes,
        phash_max_distance=(args.max_distance
                            if args.max_distance is not None
                            else evolution.PHASH_SUGGEST_MAX_DISTANCE),
        tail_blocks=args.tail_blocks or continuity.DEFAULT_TAIL_BLOCKS,
        min_overlap_ratio=(args.min_overlap_ratio
                           if args.min_overlap_ratio is not None
                           else continuity.DEFAULT_MIN_OVERLAP_RATIO),
    )
    report["storage"] = str(storage)
    if args.json:
        print(_json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    print(f"storage={storage}")
    if report["dry_run"]:
        print(f"dry-run: 显著连续对 {report['counts']['significant']} 对，"
              f"疑似（仅入确认队列）{report['counts']['suggested']} 对，"
              f"预估 LLM 调用 {report['llm_calls']}")
        for pair in report["significant"]:
            print(f"  - [显著] {pair['document_id']} → {pair['target_id']}  "
                  f"{pair['evidence_label']}  「{pair['titles'][0]}」/「{pair['titles'][1]}」")
        for pair in report["suggested"]:
            print(f"  - [疑似·需逐条确认] {pair['document_id']} → {pair['target_id']}  "
                  f"{pair['evidence_label']}  pHash 距离 {pair['phash_distance']}")
        if not report["counts"]["total"]:
            print("没有可合并的连续笔记。")
        else:
            print("核对后请加 --yes 执行显著档（疑似档请在 Inbox 逐条确认）。")
        return 0
    print(f"已合并 {report['merged_count']} 对（仅显著档），LLM 调用 {report['llm_calls']}")
    for item in report["executed"]:
        print(f"  - {item['order'][0]} + {item['order'][1]} → {item['merged_document_id']}  "
              f"重叠 {item['overlap_blocks']} 块，合并后 {item['block_counts']['merged']} 块")
    for skip in report["skipped"]:
        print(f"  - 跳过 {skip['key']}（{skip['reason']}）")
    return 0
    return 0


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
    if argv and argv[0] == "repair":
        args = build_repair_parser().parse_args(argv[1:])
        return _cmd_repair(args)
    if argv and argv[0] == "docs":
        args = build_docs_parser().parse_args(argv[1:])
        if args.docs_command == "merge-continuous":
            return run_docs_merge_continuous(args)
        return 2
    if argv and argv[0] == "tags":
        args = build_tags_parser().parse_args(argv[1:])
        if getattr(args, "tags_command", None) == "organize":
            return run_tags_organize(args)
        return run_tags_backfill(args)
    if argv and argv[0] == "visual-qa":
        from . import visualqa
        args = visualqa.build_visualqa_parser().parse_args(argv[1:])
        return visualqa.cmd_visualqa(args)
    args = build_compile_parser().parse_args(argv)
    return _cmd_compile(args)


if __name__ == "__main__":
    raise SystemExit(main())