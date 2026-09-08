"""Pure-function block-level diff of two Document IRs (issue 10).

The diff is a *pure function*: two validated :class:`DocumentIR` objects in, one
:class:`BlockDiff` out — no network, no LLM, fully deterministic.

Algorithm (two passes):

1. **Exact-content matching** (order-tolerant).  Blocks whose *normalized* text
   is identical on both sides are first-class high-confidence matches
   (``consistent``).  Because this is content-based (not positional), a simple
   reordering of the same blocks correctly stays *consistent* and is reported
   as an ``order_changed`` doc-level note — no wall of spurious one-sided notes.

2. **Position-aware alignment** over the *remaining* blocks, via Needleman–
   Wunsch global alignment.  Aligned pairs whose content disagrees become
   ``conflict`` (both sides produced a block at the same position but with
   different text); unpaired blocks become ``one_side`` (present on only one
   side — suspected missed recognition).

Divergence classes (SPEC FR-024):

* ``consistent`` —— both sides produced equivalent content (high confidence)
* ``one_side``   —— content appears on only one side (suspected missed block)
* ``conflict``   —— both sides produced a block at the same aligned position,
  but their content disagrees (needs human review)
"""

from __future__ import annotations

from collections import Counter

from ..ir import DocumentIR
from . import text
from .model import (
    BlockDiff,
    DiffBlock,
    CONSISTENT,
    ONE_SIDE,
    CONFLICT,
)

# Above CONF we treat a pair as "the same content"; between ALIGN and CONF a
# pair is aligned-but-conflicting; below ALIGN they are distinct content.
CONFIDENCE = 0.95
ALIGN = 0.55
_GAP = -0.55


def block_similarity(a, b) -> float:
    return text.block_similarity(a, b)


def diff_documents(a: DocumentIR, b: DocumentIR) -> BlockDiff:
    a_blocks, b_blocks = a.blocks, b.blocks

    # ---- pass 1: exact-content matching (order-tolerant) --------------------
    consistent: list[DiffBlock] = []
    a_key_idx = {i: text.normalized_key(bl) for i, bl in enumerate(a_blocks)}
    b_key_idx = {i: text.normalized_key(bl) for i, bl in enumerate(b_blocks)}
    a_unused: set = set(range(len(a_blocks)))
    b_unused: set = set(range(len(b_blocks)))
    b_by_key: dict[str, list[int]] = {}
    for j, k in b_key_idx.items():
        b_by_key.setdefault(k, []).append(j)

    for i in list(a_unused):
        # gather candidate indices in b with the same key
        matches = [j for j in b_by_key.get(a_key_idx[i], []) if j in b_unused]
        if matches:
            j = matches[0]  # keep B reading order
            consistent.append(_mk(CONSISTENT, a_blocks[i], b_blocks[j], i, j,
                                  sim=1.0))
            a_unused.remove(i)
            b_unused.remove(j)

    # ---- pass 2: align what is left (position-aware) ------------------------
    a_rem = [i for i in range(len(a_blocks)) if i in a_unused]
    b_rem = [j for j in range(len(b_blocks)) if j in b_unused]
    conflict: list[DiffBlock] = []
    one_side: list[DiffBlock] = []
    for ai, bi in _align([a_blocks[i] for i in a_rem],
                         [b_blocks[j] for j in b_rem]):
        if ai is not None and bi is not None:
            ba, bb = a_blocks[a_rem[ai]], b_blocks[b_rem[bi]]
            s = block_similarity(ba, bb)
            tag = CONSISTENT if s >= CONFIDENCE else CONFLICT
            note = _mk(tag, ba, bb, a_rem[ai], b_rem[bi], sim=round(s, 4))
            (consistent if tag == CONSISTENT else conflict).append(note)
        elif ai is not None:
            ba = a_blocks[a_rem[ai]]
            one_side.append(_mk(ONE_SIDE, ba, None, a_rem[ai], None, side="a"))
        elif bi is not None:
            bb = b_blocks[b_rem[bi]]
            one_side.append(_mk(ONE_SIDE, None, bb, None, b_rem[bi], side="b"))

    # ---- order-change note (pure function of the consistent set) ------------
    order_changed = _order_flipped(consistent)
    note = "检出顺序差异：两侧内容一致但块顺序不同，已按内容对齐。" if order_changed else ""
    return BlockDiff(consistent=consistent, one_side=one_side,
                     conflict=conflict, order_changed=order_changed, note=note)


def _mk(tag, ba, bb, ia, ib, sim=None, side="both") -> DiffBlock:
    return DiffBlock(
        tag=tag,
        block_type=(ba or bb).type,
        text_a=text.block_text(ba) if ba is not None else None,
        text_b=text.block_text(bb) if bb is not None else None,
        index_a=ia, index_b=ib, similarity=sim,
        side=side, block=ba if ba is not None else bb,
    )


def _match_score(a, b) -> float:
    s = block_similarity(a, b)
    if s >= ALIGN:
        return (0.95 if s >= CONFIDENCE else 0.3)
    return -2.0  # below ALIGN => never aligned (treat as gap)


def _align(a_blocks, b_blocks):
    """Needleman–Wunsch global alignment -> list of ``(ai, bi)`` (None = gap)."""
    n, m = len(a_blocks), len(b_blocks)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = i * _GAP
    for j in range(1, m + 1):
        dp[0][j] = j * _GAP
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diag = dp[i - 1][j - 1] + _match_score(a_blocks[i - 1], b_blocks[j - 1])
            dp[i][j] = max(diag, dp[i - 1][j] + _GAP, dp[i][j - 1] + _GAP)
    i, j = n, m
    aligned: list[tuple] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(dp[i][j] -
                (dp[i - 1][j - 1] + _match_score(a_blocks[i - 1], b_blocks[j - 1]))) < 1e-9:
            aligned.append((i - 1, j - 1)); i -= 1; j -= 1
        elif i > 0 and abs(dp[i][j] - (dp[i - 1][j] + _GAP)) < 1e-9:
            aligned.append((i - 1, None)); i -= 1
        else:
            aligned.append((None, j - 1)); j -= 1
    aligned.reverse()
    return aligned


def _order_flipped(consistent) -> bool:
    pairs = [(d.index_a, d.index_b)
             for d in consistent if d.index_a is not None and d.index_b is not None]
    pairs.sort(key=lambda p: p[0])
    return any(pairs[i + 1][1] <= pairs[i][1] for i in range(len(pairs) - 1))


__all__ = ["diff_documents", "block_similarity", "CONFIDENCE", "ALIGN"]