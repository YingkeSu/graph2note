"""Best-effort missing-page detection (issue 09, FR-023).

Clues used (in priority order):

- explicit **page numbers** attached to pages (from an OCR / VLM extractor —
  see the pluggable :class:`PageNumberExtractor` below): gaps in the observed
  page-number sequence produce a ``"gap"`` alert.
- **series continuity** via filename batch hints: when several source PDFs
  belong to the same scanner batch/series, pages within each file are expected
  to be contiguous; disjoint page coverage raises a continuity notice.
- duplicate-hint: pages appearing twice across a series are reported.

When **no clue** is available we emit a ``"no_clue"`` alert that explicitly
does *not* claim completeness (缺页检测 best-effort, 无线索则不声称完整).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from .model import MissingAlert, Page
from .pdf import parse_filename_hint

# Pluggable page-number reader signature: Page -> Optional[int]
PageNumberExtractor = Callable[[Page], Optional[int]]


class SequencePageNumberExtractor:
    """Continuity-only extractor: numbers pages 1..N by position in a PDF.

    Cannot detect inter-file gaps on its own; used as the offline default when
    no OCR/VLM page-number reader is plugged in.
    """

    def __init__(self) -> None:
        self._counter = 0

    def __call__(self, page: Page) -> Optional[int]:
        self._counter += 1
        return self._counter


def detect_missing(
    pages: list[Page],
    page_numbers: Optional[dict] = None,
    extractor: Optional[PageNumberExtractor] = None,
    series_hint: bool = True,
) -> list[MissingAlert]:
    """Return best-effort missing-page alerts for a set of pages.

    ``page_numbers`` may pre-populate page numbers by ``page_index``; otherwise
    an ``extractor`` is invoked per page.  With neither, the oldest offline
    ``SequencePageNumberExtractor`` falls back to positional continuity only.
    """
    if not pages:
        return [MissingAlert("no_clue", "no pages to evaluate completeness")]

    numbers: dict[int, Optional[int]] = {}
    for idx, p in enumerate(pages):
        if page_numbers is not None and idx in page_numbers:
            numbers[idx] = page_numbers[idx]
        elif extractor is not None:
            numbers[idx] = extractor(p)
        elif p.page_number is not None:
            numbers[idx] = p.page_number

    known = {idx: n for idx, n in numbers.items() if n is not None}
    alerts: list[MissingAlert] = []

    if not known:
        alerts.append(
            MissingAlert(
                "no_clue",
                "no page-number clue available; completeness is not claimed",
            )
        )
        return alerts

    observed = sorted(known.values())
    observed_set = set(observed)
    missing = [n for n in range(observed[0], observed[-1] + 1) if n not in observed_set]
    if missing:
        alerts.append(
            MissingAlert(
                "gap",
                f"possible missing page(s): {missing} "
                f"(observed {observed[0]}..{observed[-1]})",
                missing_numbers=missing,
                observed_numbers=observed,
            )
        )

    # duplicate-presence hint from page numbers appearing more than once
    from collections import Counter

    dup = sorted(n for n, c in Counter(known.values()).items() if c > 1)
    if dup:
        alerts.append(
            MissingAlert(
                "duplicate_hint",
                f"pages scanned more than once: {dup}",
                observed_numbers=dup,
            )
        )

    # series continuity across source files sharing a file-name batch hint
    if series_hint and len({p.source_pdf for p in pages}) > 1:
        by_series: dict[str, list[int]] = {}
        for p in pages:
            hint = parse_filename_hint(p.source_pdf)
            if hint:
                by_series.setdefault(
                    f"{hint['batch']}:{hint['ordinal']}", []
                ).append(p.page_index)
        for label, idxs in by_series.items():
            if len(set(idxs)) == 1:
                alerts.append(
                    MissingAlert(
                        "duplicate_hint",
                        f"series {label} scanned pages are identical-looking "
                        f"(possible duplicate batch)",
                        observed_numbers=sorted(set(idxs)),
                    )
                )
    return alerts


__all__ = [
    "detect_missing",
    "SequencePageNumberExtractor",
    "PageNumberExtractor",
    "MissingAlert",
]