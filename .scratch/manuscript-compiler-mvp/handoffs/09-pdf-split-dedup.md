# Handoff 09 — 扫描 PDF 拆页 + 页级去重 + 缺页预警

Branch: `dev/09-pdf-split-dedup`  ·  Issue: `issues/09-pdf-split-dedup-missing-alert.md`  ·  Status → in-review

## What shipped

New pure-function ingest pipeline under **`graph2note/ingest/`** (no changes to
the parse-pipeline files, per the early-start boundary). Core is dependency-light
(numpy + PIL); PDF splitting additionally needs **PyMuPDF** (guarded — the pure
hash/cluster/missing functions work without it, and tests SKIP cleanly via
`pytest.importorskip("pymupdf")`).

| module | role |
|---|---|
| `hash.py` | **fixed** dHash + pHash. Rewrote pHash to classic DCT-II (top-left block incl. DC, bit = coeff > block median) because the naive version collapsed white/checkerboard/half pages to the same `55aa55aa...`. Now light-robust (Hamming 0 at 1.35× brightness) and discriminative between distinct pages (Hamming ≥ 20). |
| `model.py` | dataclasses `Page`, `PageCluster` (reversible: `pages` list + `representative`), `MissingAlert`, `IngestReport` (`unique_pages`/`candidate_versions`). |
| `pdf.py` | `split_pdf()` (PyMuPDF guarded; 150–200 DPI, JPEG q85, provenance `source_pdf`+`page_index`), filename batch/ordinal parse, `content_fraction()` + `is_low_information()` for robust blank detection (downsampled 256×256 grayscale, non-bg fraction). |
| `cluster.py` | union-find clustering by Hamming threshold; `dedupe` (keep latest/first), `split_cluster()` reversible split, `summarize_cluster()`. |
| `missing.py` | best-effort `detect_missing()`: `gap` alerts from page-number continuity, `duplicate_hint`, and `no_clue` when no numbering (never claims completeness); pluggable `PageNumberExtractor` + offline `SequencePageNumberExtractor`. |
| `engine.py` | `ingest_pdfs()` orchestration, `DEFAULT_DEDUP_THRESHOLD=6`, `--page-numbers` parse. |
| `adapter.py` | **thin 03 seam**: `ParseInput` + `report_to_parse_inputs()` → 03 consumes this; parse-pipeline files untouched. |
| `report.py` / `cli.py` | JSON round-trip; `pdf` + `recluster` (threshold re-cluster **without** re-rendering = the reversible-split/merge path). |

## Key decisions & the discovered defect (important for reviewers)

**Near-blank pages must not be dedup-merged as content duplicates.** On the 4
real scans, the *only* naive "duplicates" were near-blank scanner-noise pages
(ink fraction ~4–5% vs 0.01% truly-blank, ~12% content) that hash identically —
e.g. `3009_2` pages {2,11,25,...} collapsed to one cluster. Per the SPEC
non-document-page policy, `Page.low_information` (downsampled content fraction
< 0.004, tuned on real scans: blanks 0.0000 vs content ≥ 0.006) is set at split
and **isolates** those pages from clustering by default; `--merge-low-info`
opts them back in. Result: the real PDFs contain **no genuine duplicate content
pages** — the only false merges were blanks, now prevented.

Content-level dedup is demonstrated via `scripts/ingest_manual.py`: a real
content page + a brightness/rotation "rescan" → pHash distance 2 → merges into
1 cluster (2 candidate versions) at threshold 6, splits at threshold 1
(**reversible split**).

## Verification

- `pytest tests/ spike3/tests/` → **93 passed** (all offline; 6 integrate
  PyMuPDF synthetic-PDF tests, skipped when pymupdf absent). Synthetic coverage:
  hash determinism/lighting/rotation robustness and distinct-page separation;
  duplicate-pair merge into candidate versions; adjustable threshold; reversible
  split of a forced false merge; blank-page isolation; gap vs `no_clue` alerting;
  PDF provenance/blank-flag; end-to-end dedup of a known duplicate pair; real
  `recluster` on the saved report (threshold 6 → 154 unique, threshold 64 →
  42 clusters / 112 candidate versions, no re-render).
- Real scans (`scripts/ingest_manual.py`, **local-only, not committed**): 4 PDFs
  at 150 DPI → **154 pages, 41 low-info / 37 blank flagged, 154 unique** (no
  content dupes), `no_clue` alert. Record kept at `out/09/report.json` +
  `out/09/summary.md` (report committed; `out/*/pages/` gitignored — 37 MB).

## Known limits / follow-ups

- VLM hole-filling for page-number/date extraction beyond the offline sequence
  extractor is **not** implemented (issue allows ≤8 cached calls or no
  completeness claim). Gap detection is exact only when `page_numbers` are
  supplied; otherwise `no_clue` is the honest answer.
- Threshold (default 6) is a Hamming gate; real-world tuning and a
  multi-doc duplicate-report view are good 06/continue candidates.
- **pymupdf install note**: `pip install pymupdf` into `.venv-spike3` (dev-ish;
  registered as optional `pdf` extra in `pyproject.toml`). It is not a hard dep.

## For the next handoff

When issue 06 (Web App three-column preview) resumes, it can consume
`report_to_parse_inputs()` from `graph2note.ingest.adapter` directly; the
dedup-marker + missing-alert UI placeholders already planned in 06 map to
`PageCluster.pages`-versus-`representative` and `MissingAlert` respectively.