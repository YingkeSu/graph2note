"""Page-level near-duplicate clustering (issue 09, FR-022).

Groups pages that hash close together (same page scanned / photographed more
than once) into :class:`PageCluster` *candidate versions*.  The threshold is a
Hamming distance on the perceptual hash and is **user-adjustable**; raising it
merges more (accepts more false-positive merges), lowering it splits.

Merging is **reversible** — every ``PageCluster`` keeps the full list of
candidate ``pages`` and picks a ``representative``; expanding a cluster back
out (or re-clustering at a stricter threshold) reverses any wrong merge, so no
page data is ever destroyed by de-duplication.
"""

from __future__ import annotations

from typing import Callable, Optional

from .hash import hamming
from .model import Page, PageCluster


def cluster_pages(
    pages: list[Page],
    threshold: int = 0,
    hash_method: str = "phash",
    keep: str = "latest",
    distance: Optional[Callable[[Page, Page], int]] = None,
    merge_low_info: bool = False,
) -> list[PageCluster]:
    """Greedy union-find clustering of near-duplicate pages.

    ``threshold`` is the max allowed Hamming distance for two pages to be
    considered the *same page*.  ``0`` means only byte-identical hashes group.
    ``keep`` selects the representative within a cluster ("latest" by source
    order + page index; any other value keeps the first scan).

    By default ``low_information`` pages (blank / near-blank) are factored out
    and each becomes its own singleton cluster, so trivial blank pages never
    falsely merge as content duplicates; pass ``merge_low_info=True`` to fold
    them into normal clustering.
    """
    if not pages:
        return []
    if not merge_low_info:
        low = [p for p in pages if p.low_information]
        rest = [p for p in pages if not p.low_information]
        low_clusters = [
            PageCluster(i, [p], hash_method, 0, keep) for i, p in enumerate(low)
        ]
        if not rest:
            return low_clusters
        inner = cluster_pages(rest, threshold, hash_method, keep, distance,
                              merge_low_info=True)
        offset = len(low_clusters)
        for c in inner:
            c.cluster_id += offset
        return low_clusters + inner

    parent = list(range(len(pages)))
    rank = [0] * len(pages)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    dist = distance or (lambda p, q: hamming(p.pg_hash, q.pg_hash))
    n = len(pages)
    for i in range(n):
        for j in range(i + 1, n):
            if same_pages(pages[i], pages[j], threshold, hash_method, dist):
                union(i, j)

    groups: dict[int, list[Page]] = {}
    for idx, p in enumerate(pages):
        groups.setdefault(find(idx), []).append(p)

    clusters = []
    for cid, members in enumerate(sorted(groups.values(), key=lambda m: m[0].page_index)):
        max_d = max(
            (dist(a, b) for a in members for b in members if a is not b), default=0
        )
        clusters.append(
            PageCluster(
                cluster_id=cid,
                pages=sorted(members, key=lambda p: (p.source_pdf, p.page_index)),
                hash_method=hash_method,
                max_distance=max_d,
                keep=keep,
            )
        )
    return clusters


def same_pages(
    p: Page,
    q: Page,
    threshold: int,
    hash_method: str = "phash",
    distance: Optional[Callable[[Page, Page], int]] = None,
) -> bool:
    """Boolean: do two pages fall within the near-duplicate threshold."""
    if hash_method not in ("phash", "dhash"):
        raise ValueError(f"unknown hash method: {hash_method!r}")
    if not p.pg_hash or not q.pg_hash:
        return False
    dist = distance or (lambda a, b: hamming(a.pg_hash, b.pg_hash))
    return dist(p, q) <= threshold


def dedupe(clusters: list[PageCluster]) -> list[Page]:
    """Return one representative per cluster (the default latest version)."""
    return [c.representative for c in clusters]


def split_cluster(cluster: PageCluster, threshold: int) -> list[PageCluster]:
    """Reverse a (possibly false) merge into smaller clusters.

    Re-runs clustering on the candidate pages of a single cluster at a stricter
    threshold — the operation 拆分误合并.  The original candidate pages are
    never discarded.
    """
    if len(cluster.pages) <= 1:
        return [cluster]
    return cluster_pages(
        cluster.pages,
        threshold=threshold,
        hash_method=cluster.hash_method,
        keep=cluster.keep,
    )


def summarize_cluster(cluster: PageCluster) -> dict:
    """Human-readable summary of one candidate-version group (for reports)."""
    from .hash import similarity

    reps = cluster.pages
    sim = (
        similarity(reps[0].pg_hash, reps[-1].pg_hash)
        if len(reps) > 1 and reps[0].pg_hash and reps[-1].pg_hash
        else 1.0
    )
    return {
        "cluster_id": cluster.cluster_id,
        "pages": len(reps),
        "versions": [
            {"source_pdf": p.source_pdf, "page_index": p.page_index, "blank": p.blank}
            for p in reps
        ],
        "similarity": round(sim, 3),
        "keep": {"page_index": cluster.representative.page_index,
                 "source_pdf": cluster.representative.source_pdf},
    }