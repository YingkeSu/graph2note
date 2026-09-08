"""CLI for the scan-ingest pipeline (issue 09).

Run with the package entry::

    python -m graph2note.ingest.cli pdf <file.pdf>...   -o outdir --threshold 6
    python -m graph2note.ingest.cli recluster report.json --threshold 2   # reversible split
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine import ingest_pdfs, load_page_numbers_from_arg
from .report import load_report, save_report, summarize
from . import cluster as cluster_mod


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="graph2note.ingest", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    pdf = sub.add_parser("pdf", help="split + hash + dedup + missing alerts for PDFs")
    pdf.add_argument("pdfs", nargs="+", type=str, metavar="FILE")
    pdf.add_argument("-o", "--outdir", type=Path, default=Path("out/ingest"))
    pdf.add_argument("--dpi", type=int, default=150, help="render DPI (150-200)")
    pdf.add_argument("--jpeg-quality", type=int, default=85)
    pdf.add_argument("--hash", choices=["phash", "dhash"], default="phash")
    pdf.add_argument("--threshold", type=int, default=6,
                     help="max Hamming distance for near-dup (higher merges more)")
    pdf.add_argument("--merge-low-info", action="store_true",
                     help="fold blank/near-blank pages into clustering (default keeps them isolated)")
    pdf.add_argument("--keep", choices=["latest", "first"], default="latest")
    pdf.add_argument("--page-numbers", type=str, default="",
                     help="flat-index:page-number pairs, e.g. '0:1,2:4'")
    pdf.add_argument("--no-blank-flag", action="store_true",
                     help="keep blank pages unflagged (default flags them)")
    pdf.add_argument("--json", type=Path, default=None, help="write report JSON here")

    rec = sub.add_parser("recluster",
                         help="re-group pages of a saved report at a new threshold "
                              "(reversible split/merge without re-rendering)")
    rec.add_argument("report_json", type=Path)
    rec.add_argument("--threshold", type=int, default=6)
    rec.add_argument("--keep", choices=["latest", "first"], default="latest")
    rec.add_argument("--out", type=Path, default=None, help="write new report JSON")
    return p


def _cmd_pdf(
    pdfs, outdir, dpi, jpeg_quality, hash_method, threshold, keep,
    page_numbers, flag_blank, json_path, merge_low_info,
) -> int:
    report = ingest_pdfs(
        pdfs,
        work_dir=outdir,
        dpi=dpi,
        jpeg_quality=jpeg_quality,
        flag_blank=flag_blank,
        hash_method=hash_method,
        threshold=threshold,
        keep=keep,
        page_numbers=load_page_numbers_from_arg(page_numbers),
        merge_low_info=merge_low_info,
    )
    print(summarize(report))
    print("rendered pages in:", outdir)
    if json_path:
        save_report(report, json_path)
        print("report written to:", json_path)
    return 0


def _cmd_recluster(report_json, threshold, keep, out) -> int:
    report = load_report(report_json)
    report.clusters = cluster_mod.cluster_pages(
        report.pages,
        threshold=threshold,
        hash_method=report.hash_method,
        keep=keep,
    )
    report.threshold = threshold
    print(summarize(report))
    print(f"(re-clustered {len(report.pages)} candidate pages)")
    if out:
        save_report(report, out)
        print("new report written to:", out)
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "pdf":
        return _cmd_pdf(
            args.pdfs, args.outdir, args.dpi, args.jpeg_quality, args.hash,
            args.threshold, args.keep, args.page_numbers,
            not args.no_blank_flag, args.json,
            args.merge_low_info,
        )
    if args.command == "recluster":
        return _cmd_recluster(args.report_json, args.threshold, args.keep, args.out)
    print(f"unknown command: {args.command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())