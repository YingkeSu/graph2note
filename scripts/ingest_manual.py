#!/usr/bin/env python
"""Manual verification for issue 09 on the 4 real (local-only) scan PDFs.

These PDFs live under ``test-images/`` and are NOT committed (gitignored,
~80 MB).  This script renders a record at ``out/09/`` and prints a summary.

    .venv-spike3/bin/python scripts/ingest_manual.py

Requires: PyMuPDF.  No network / no LLM.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from graph2note.ingest import ingest_pdfs, phash, hamming, cluster_pages, Page  # noqa: E402
from graph2note.ingest.report import save_report, summarize  # noqa: E402


def _demo_merge_dedup(out: Path) -> str:
    """Demonstrate content-level dedup: a real page + a perturbed 'rescan'.

    Renders one content page from the real scans, then synthesizes a second
    scan of the same page (brightness + slight rotation), and shows they:
    - hash close (near-dup) and are merged as candidate versions, or
    - are kept separate at a stricter threshold (reversible split).
    """
    import pymupdf
    import numpy as np
    from PIL import Image, ImageEnhance, ImageFilter

    src = glob.glob(str(ROOT / "test-images" / "*3009_2*.pdf"))[0]
    d = pymupdf.open(src)
    page = d[5]  # a content page
    pix = page.get_pixmap(dpi=100)
    base = pix.pil_image().convert("RGB")
    rescan = ImageEnhance.Brightness(base).enhance(1.35).rotate(1.2, fillcolor=(255, 255, 255))
    d.close()

    p1 = Page("scanA.pdf", 0, "", base.width, base.height, 100,
              pg_hash=phash(base))
    p2 = Page("scanA_rescan.pdf", 0, "", rescan.width, rescan.height, 100,
              pg_hash=phash(rescan))
    dist = hamming(p1.pg_hash, p2.pg_hash)
    merged = cluster_pages([p1, p2], threshold=6)
    split = cluster_pages([p1, p2], threshold=1)
    lines = [
        "## Content-level repeat-scan merge demo (real page + perturbed rescan)",
        "",
        f"- phash distance between the two scans: **{dist}** "
        f"(<= 6 => near-dup merge)",
        f"- at threshold 6: **{len(merged)}** cluster(s) "
        f"({len(merged[0].pages)} candidate version(s) kept)",
        f"- at threshold 1 (reversible split): **{len(split)}** cluster(s)",
        "",
        "> Merging is reversible: candidate pages are retained and re-clustering",
        "> at a stricter threshold splits any false merge (拆分误合并).",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    pdfs = sorted(glob.glob(str(ROOT / "test-images" / "*.pdf")))
    if not pdfs:
        print("no test-images/*.pdf found (local-only samples not present)")
        return 2

    out = ROOT / "out" / "09"
    pages_dir = out / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    print(f"ingesting {len(pdfs)} scanned PDFs at 150 DPI ...")
    report = ingest_pdfs(pdfs, work_dir=pages_dir, dpi=150, jpeg_quality=85,
                         hash_method="phash", threshold=6, keep="latest")
    txt = summarize(report)
    print()
    print("=" * 60)
    print(txt)

    demo = _demo_merge_dedup(out)
    print()
    print(demo)

    save_report(report, out / "report.json")
    with open(out / "summary.md", "w", encoding="utf-8") as fh:
        fh.write(f"# Issue 09 manual verification ({len(pdfs)} real scan PDFs)\n\n"
                 f"```text\n{txt}\n```\n\n{demo}")
    print()
    print("report.json + summary.md written under", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())