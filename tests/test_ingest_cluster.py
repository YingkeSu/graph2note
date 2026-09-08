"""Near-duplicate clustering, adjustable threshold, reversible split (issue 09)."""

import numpy as np
import pytest
from PIL import Image

from graph2note.ingest import (
    phash, cluster_pages, split_cluster, dedupe, summarize_cluster, Page,
)


def _page(seed=1, source="a.pdf", idx=0, empty=False):
    """Deterministic synthetic page; ``empty`` makes a blank (low-info) page."""
    rng = np.random.default_rng(seed)
    arr = np.full((500, 400, 3), 250, np.uint8)
    if not empty:
        for i in range(5):
            y = 60 + i * 90
            x = int(rng.integers(40, 140))
            arr[y:y + 4, x:x + int(rng.integers(60, 240)), :] = 30
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return Page(
        source_pdf=source, page_index=idx, path=f"/tmp/{source[:2]}{idx}.png",
        width=400, height=500, dpi=150,
        pg_hash=phash(img), blank=empty, low_information=empty,
    )


def _brightness_variant(seed=1, source="b.pdf", gain=1.35, rot=0.0):
    rng = np.random.default_rng(seed)
    arr = np.full((500, 400, 3), 250, np.uint8)
    for i in range(5):
        y = 60 + i * 90
        x = int(rng.integers(40, 140))
        arr[y:y + 4, x:x + int(rng.integers(60, 240)), :] = float(30 * gain)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    if rot:
        img = img.rotate(rot, fillcolor=(250, 250, 250))
    return Page(source, 0, "/tmp/b0.png", 400, 500, 150, pg_hash=phash(img))


def test_duplicate_pair_merges_into_candidate_versions():
    a = _page(1)
    b = _brightness_variant(1)  # same page, brightness-only "rescan"
    assert len(cluster_pages([a, b], threshold=6)) == 1
    merged = cluster_pages([a, b], threshold=6)
    assert len(merged[0].pages) == 2  # both candidate versions retained


def test_distinct_pages_do_not_merge():
    a, b = _page(1), _page(999)
    assert len(cluster_pages([a, b], threshold=6)) == 2


def test_threshold_is_adjustable():
    a = _page(1)
    a_rot = _brightness_variant(1, rot=2.0)  # near-dup, small (2-bit) distance
    assert len(cluster_pages([a, a_rot], threshold=8)) == 1
    assert len(cluster_pages([a, a_rot], threshold=0)) == 2


def test_false_merge_is_reversibly_split():
    a, b = _page(1), _page(999)  # genuinely different
    merged = cluster_pages([a, b], threshold=64)   # wide -> forced together
    assert len(merged) == 1
    split = split_cluster(merged[0], threshold=6)  # stricter -> split
    assert len(split) == 2
    # nothing destroyed: candidate pages retained
    assert len(merged[0].pages) == 2


def test_summary_reports_similarity_and_versions():
    a, b = _page(1), _brightness_variant(1)
    s = summarize_cluster(cluster_pages([a, b], threshold=6)[0])
    assert s["pages"] == 2 and s["similarity"] >= 0.8
    assert {"source_pdf": "a.pdf"} == {"source_pdf": s["versions"][0]["source_pdf"]}


def test_dedupe_keeps_latest_representative():
    a = _page(1, source="scanA.pdf", idx=0)
    b = Page("scanB.pdf", 0, "/tmp/b.png", 400, 500, 150, pg_hash=a.pg_hash)
    reps = dedupe(cluster_pages([a, b], threshold=0))
    assert len(reps) == 1 and reps[0].source_pdf == "scanB.pdf"


def test_blank_pages_isolated_by_default():
    blank_a, blank_b = _page(1, empty=True), _page(2, empty=True)
    assert blank_a.pg_hash == blank_b.pg_hash          # identical hashes...
    assert len(cluster_pages([blank_a, blank_b], threshold=64)) == 2  # ...but not merged
    # opting in folds them back together
    assert len(cluster_pages([blank_a, blank_b], threshold=64,
                             merge_low_info=True)) == 1