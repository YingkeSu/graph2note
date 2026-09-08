"""Issue 10 — dual-model cross-validation engine.

``graph2note.verify`` turns two independent vision-model parses of a document
image into an aggregated divergence report (双侧一致/单侧出现/不一致) plus
within-document near-dup detection.  The diff is a pure function
(``diffing.diff_documents``) so everything except the actual model calls is
offline-testable; model calls reuse the fixed gateway strategy and degrade to
a single-model "未验证" result on failure (never blocking export).
"""

from .diffing import diff_documents, block_similarity, CONFIDENCE
from .duplicates import detect_near_dup_blocks, DUP_THRESHOLD
from .engine import cross_validate, run_model, DEFAULT_MODEL_A, DEFAULT_MODEL_B
from .model import (
    CrossValidationReport,
    BlockDiff,
    DiffBlock,
    DuplicateGroup,
    CONSISTENT,
    ONE_SIDE,
    CONFLICT,
)

__all__ = [
    "diff_documents",
    "block_similarity",
    "CONFIDENCE",
    "detect_near_dup_blocks",
    "DUP_THRESHOLD",
    "cross_validate",
    "run_model",
    "DEFAULT_MODEL_A",
    "DEFAULT_MODEL_B",
    "CrossValidationReport",
    "BlockDiff",
    "DiffBlock",
    "DuplicateGroup",
    "CONSISTENT",
    "ONE_SIDE",
    "CONFLICT",
]