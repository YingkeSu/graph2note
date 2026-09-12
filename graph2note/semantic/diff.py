"""IR block-level diff engine (issue S1) — a pure, deterministic function.

``diff_ir(ir_a, ir_b) -> DiffReport`` takes two *already validated*
:class:`~graph2note.ir.DocumentIR` objects and returns a structured report of
what changed between the two versions.  It performs no network access, reads no
files and never calls a model, so it is fully snapshot-testable.

Algorithm
---------

1. **Group by block type.**  Blocks only ever match within their own type — a
   heading is never "the same" as a paragraph.

2. **Exact-content pass (order tolerant).**  Within a type group, blocks whose
   :func:`~graph2note.semantic.text.content_key` is identical are paired, each
   A block to the nearest unused B block.  This is what makes a pure reorder a
   ``moved`` rather than a wall of ``removed`` + ``added``.

3. **Fuzzy pass (thresholded greedy).**  The remaining A/B blocks are scored
   with :func:`~graph2note.semantic.text.block_similarity`; pairs scoring
   ``>= MODIFIED_THRESHOLD`` are matched, highest score first, ties broken by
   ``(index_a, index_b)`` so the result is deterministic.

4. **Move detection.**  Every matched pair is a content match at some position.
   The pairs are read in A order; a pair is ``moved`` when its B position falls
   outside the longest increasing subsequence of the other matched pairs — i.e.
   it actually had to be relocated.  A plain insertion/deletion elsewhere in
   the document therefore does *not* mark every following block as moved.

5. **Classification.**  Matched identical pair in order -> ``unchanged``;
   matched identical out of order -> ``moved``; matched with a content edit ->
   ``modified`` (carrying the similarity score); unmatched A -> ``removed``;
   unmatched B -> ``added``.

The ``DiffReport`` is the stable interface consumed by S2 (version-chain
summaries) and S3 (side-by-side highlight + jump-to-block).  Each change
carries :class:`BlockRef` for both sides (0-based ``index``, ``block_type``,
deterministic ``anchor`` and a short ``preview``).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..ir import Block, DocumentIR
from . import text

# A pair with similarity >= this is treated as "the same block, edited"
# (modified).  Below it, the two blocks are unrelated and are reported as
# removed + added.  Explicit and testable (see tests/test_semantic_diff.py).
MODIFIED_THRESHOLD = 0.5

# Verdict rule: unchanged if nothing changed; minor while the change density
# stays at or below this; major otherwise.  Explicit and testable.
MINOR_MAX_DENSITY = 0.25

_EPS = 1e-9

Op = Literal["added", "removed", "modified", "moved", "unchanged"]
Verdict = Literal["unchanged", "minor", "major"]

_OP_ORDER = ("added", "removed", "modified", "moved", "unchanged")


# ---------------------------------------------------------------------------
# Report model (the S2/S3 interface)
# ---------------------------------------------------------------------------


class BlockRef(BaseModel):
    """Location of a block inside one version (for UI highlight/jump)."""

    index: int = Field(ge=0)
    block_type: str
    anchor: str
    preview: str = ""


class BlockChange(BaseModel):
    """One block-level operation between the two versions."""

    op: Op
    block_type: str
    block_ref_a: Optional[BlockRef] = None
    block_ref_b: Optional[BlockRef] = None
    similarity: Optional[float] = None


class TypeCounts(BaseModel):
    added: int = 0
    removed: int = 0
    modified: int = 0
    moved: int = 0
    unchanged: int = 0


class DiffSummary(BaseModel):
    blocks_a: int
    blocks_b: int
    # All block instances across both versions: ``blocks_a + blocks_b``.
    # The change density is bounded in [0, 1] against this denominator.
    total_blocks: int
    changed_blocks: int
    change_density: float
    by_op: dict[str, int]
    by_type: dict[str, TypeCounts]
    verdict: Verdict


class DiffReport(BaseModel):
    label_a: Optional[str] = None
    label_b: Optional[str] = None
    changes: list[BlockChange]
    summary: DiffSummary


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def diff_ir(
    ir_a: DocumentIR,
    ir_b: DocumentIR,
    *,
    label_a: str | None = None,
    label_b: str | None = None,
) -> DiffReport:
    """Compare two Document IRs and return a deterministic :class:`DiffReport`.

    ``label_a`` / ``label_b`` are optional human labels (e.g. version ids) that
    are carried through to the report; they never affect the comparison.
    """
    a_blocks = list(ir_a.blocks)
    b_blocks = list(ir_b.blocks)
    changes = _compute_changes(a_blocks, b_blocks)
    summary = _summarize(changes, a_blocks, b_blocks)
    return DiffReport(
        label_a=label_a, label_b=label_b, changes=changes, summary=summary
    )


def _ref(block: Block, index: int) -> BlockRef:
    return BlockRef(
        index=index,
        block_type=block.type,
        anchor=f"block-{index}",
        preview=text.preview(block),
    )


def _change(
    op: Op,
    a_blocks: list[Block],
    b_blocks: list[Block],
    index_a: int | None,
    index_b: int | None,
    similarity: float | None,
) -> BlockChange:
    ref_a = _ref(a_blocks[index_a], index_a) if index_a is not None else None
    ref_b = _ref(b_blocks[index_b], index_b) if index_b is not None else None
    block_type = (ref_a or ref_b).block_type
    sim = round(similarity, 4) if similarity is not None else None
    return BlockChange(
        op=op,
        block_type=block_type,
        block_ref_a=ref_a,
        block_ref_b=ref_b,
        similarity=sim,
    )


def _compute_changes(
    a_blocks: list[Block], b_blocks: list[Block]
) -> list[BlockChange]:
    matched: list[tuple[int, int, bool, float]] = []  # (ia, ib, identical, sim)
    used_a: set[int] = set()
    used_b: set[int] = set()

    types = sorted({bl.type for bl in a_blocks} | {bl.type for bl in b_blocks})
    for block_type in types:
        a_indices = [i for i, bl in enumerate(a_blocks) if bl.type == block_type]
        b_indices = [j for j, bl in enumerate(b_blocks) if bl.type == block_type]

        # --- pass 1: exact content identity, order tolerant ------------------
        b_by_key: dict[str, list[int]] = {}
        for j in b_indices:
            b_by_key.setdefault(text.content_key(b_blocks[j]), []).append(j)
        for i in a_indices:
            key = text.content_key(a_blocks[i])
            candidates = [j for j in b_by_key.get(key, []) if j not in used_b]
            if not candidates:
                continue
            j = min(candidates, key=lambda cand: (abs(cand - i), cand))
            used_a.add(i)
            used_b.add(j)
            matched.append((i, j, True, 1.0))

        # --- pass 2: thresholded fuzzy matching over the leftovers -----------
        remaining_a = [i for i in a_indices if i not in used_a]
        remaining_b = [j for j in b_indices if j not in used_b]
        scored: list[tuple[float, int, int]] = []
        for i in remaining_a:
            for j in remaining_b:
                sim = text.block_similarity(a_blocks[i], b_blocks[j])
                if sim + _EPS >= MODIFIED_THRESHOLD:
                    scored.append((sim, i, j))
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        for sim, i, j in scored:
            if i in used_a or j in used_b:
                continue
            used_a.add(i)
            used_b.add(j)
            matched.append((i, j, False, sim))

    moved_pairs = _moved_pairs(matched)

    changes: list[BlockChange] = []
    for index_a, index_b, identical, sim in matched:
        if identical and (index_a, index_b) in moved_pairs:
            op: Op = "moved"
        elif identical:
            op = "unchanged"
        else:
            op = "modified"
        changes.append(
            _change(op, a_blocks, b_blocks, index_a, index_b, sim)
        )

    for index_a in sorted(set(range(len(a_blocks))) - used_a):
        changes.append(_change("removed", a_blocks, b_blocks, index_a, None, None))
    for index_b in sorted(set(range(len(b_blocks))) - used_b):
        changes.append(_change("added", a_blocks, b_blocks, None, index_b, None))

    changes.sort(key=_change_sort_key)
    return changes


def _change_sort_key(change: BlockChange) -> tuple:
    ref = change.block_ref_b or change.block_ref_a
    primary = ref.index if ref is not None else 0
    secondary = change.block_ref_a.index if change.block_ref_a is not None else -1
    return (primary, secondary, change.op)


def _moved_pairs(matched: list[tuple[int, int, bool, float]]) -> set[tuple[int, int]]:
    """Pairs that had to be relocated, via LIS over matched B positions."""
    pairs = sorted((index_a, index_b) for index_a, index_b, _, _ in matched)
    if not pairs:
        return set()
    keep = _lis_indices([index_b for _, index_b in pairs])
    return {pairs[k] for k in range(len(pairs)) if k not in keep}


def _lis_indices(seq: list[int]) -> set[int]:
    """Indices of one longest strictly increasing subsequence of ``seq``."""
    if not seq:
        return set()
    tails: list[int] = []  # tails[k] = seq index of the smallest tail of length k+1
    prev = [-1] * len(seq)
    for i, value in enumerate(seq):
        lo, hi = 0, len(tails)
        while lo < hi:
            mid = (lo + hi) // 2
            if seq[tails[mid]] < value:
                lo = mid + 1
            else:
                hi = mid
        if lo > 0:
            prev[i] = tails[lo - 1]
        if lo == len(tails):
            tails.append(i)
        else:
            tails[lo] = i
    out: set[int] = set()
    cursor = tails[-1]
    while cursor != -1:
        out.add(cursor)
        cursor = prev[cursor]
    return out


def _verdict(changed_blocks: int, change_density: float) -> Verdict:
    """Explicit verdict rule table (see tests for the table-driven cases)."""
    if changed_blocks == 0:
        return "unchanged"
    if change_density <= MINOR_MAX_DENSITY + _EPS:
        return "minor"
    return "major"


def _summarize(
    changes: list[BlockChange], a_blocks: list[Block], b_blocks: list[Block]
) -> DiffSummary:
    by_op = {op: 0 for op in _OP_ORDER}
    types = sorted({bl.type for bl in a_blocks} | {bl.type for bl in b_blocks})
    by_type = {block_type: TypeCounts() for block_type in types}
    for change in changes:
        by_op[change.op] += 1
        counts = by_type.setdefault(change.block_type, TypeCounts())
        setattr(counts, change.op, getattr(counts, change.op) + 1)

    total = len(a_blocks) + len(b_blocks)
    changed = (
        by_op["added"] + by_op["removed"] + by_op["modified"] + by_op["moved"]
    )
    density = round(changed / total, 4) if total else 0.0
    return DiffSummary(
        blocks_a=len(a_blocks),
        blocks_b=len(b_blocks),
        total_blocks=total,
        changed_blocks=changed,
        change_density=density,
        by_op=by_op,
        by_type=by_type,
        verdict=_verdict(changed, density),
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
