"""Within-document near-duplicate block detection (issue 10, FR-024)."""

from __future__ import annotations

from ..ir import DocumentIR
from . import text
from .model import DuplicateGroup

# Two same-type blocks are "near-duplicates" when their normalized text is
# identical or nearly so.  1.0 catches exact repeats (copy-pasted lines); the
# slight relaxation below 1.0 catches re-worded repeats.
DUP_THRESHOLD = 0.85


def detect_near_dup_blocks(doc: DocumentIR) -> list[DuplicateGroup]:
    """Find groups of near-duplicate blocks *within* one document IR.

    Blocks are connected when their similarity reaches the threshold, and each
    connected component with >= 2 members is reported as a duplicate group.
    Deterministic, pure, offline.  A block is never compared with itself.
    """
    blocks = doc.blocks
    n = len(blocks)
    if n < 2:
        return []

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    sims = {}
    for i in range(n):
        for j in range(i + 1, n):
            s = text.block_similarity(blocks[i], blocks[j])
            if s >= DUP_THRESHOLD:
                union(i, j)
                sims[(i, j)] = s

    members: dict[int, list[int]] = {}
    for i in range(n):
        members.setdefault(find(i), []).append(i)

    result: list[DuplicateGroup] = []
    gid = 0
    for idxs in sorted(members.values(), key=lambda l: min(l)):
        idxs = sorted(idxs)
        if len(idxs) < 2:
            continue
        min_sim = min(sims[(i, j)] for i in idxs for j in idxs
                      if i < j and (i, j) in sims)
        result.append(DuplicateGroup(
            group_id=gid, indexes=idxs, block_type=blocks[idxs[0]].type,
            similarity=round(min_sim, 4),
            representative_text=text.block_text(blocks[idxs[0]]),
        ))
        gid += 1
    return result


__all__ = ["detect_near_dup_blocks", "DUP_THRESHOLD"]