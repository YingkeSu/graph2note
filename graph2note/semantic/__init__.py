"""Semantic Diff track (S1): pure Document-IR block diff engine.

Public surface consumed by S2 (version-chain summaries) and S3 (comparison UI):

* :func:`~graph2note.semantic.diff.diff_ir` — pure ``diff_ir(ir_a, ir_b)``
* :class:`~graph2note.semantic.diff.DiffReport` and its sub-models
* :data:`~graph2note.semantic.diff.MODIFIED_THRESHOLD` (match threshold)
* :data:`~graph2note.semantic.diff.MINOR_MAX_DENSITY` (verdict rule)

The engine performs no IO.  The read-only CLI lives in
:mod:`graph2note.semantic.cli`.
"""

from __future__ import annotations

from .diff import (
    MINOR_MAX_DENSITY,
    MODIFIED_THRESHOLD,
    BlockChange,
    BlockRef,
    DiffReport,
    DiffSummary,
    TypeCounts,
    diff_ir,
)

__all__ = [
    "diff_ir",
    "DiffReport",
    "DiffSummary",
    "BlockChange",
    "BlockRef",
    "TypeCounts",
    "MODIFIED_THRESHOLD",
    "MINOR_MAX_DENSITY",
]
