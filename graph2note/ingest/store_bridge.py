"""Ingest <-> DocumentStore bridge (issue 13).

Wires issue 09's page-level perceptual hashing into issue 07's durable
document library: a fresh page whose pHash is *near-duplicate* of an existing
library page merges into that document as a new candidate version (default =
latest effective), instead of creating a new record.  Different pages never
merge; a wrong merge can be split back apart (reversible, reusing the ingest
re-cluster mechanism).

Everything here is offline: hashing is pure PIL/numpy, matching is pure, and
the store is the local seam.  No network.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Callable, Optional

from PIL import Image as PILImage

from .cluster import cluster_pages
from .engine import DEFAULT_DEDUP_THRESHOLD
from .hash import phash, hamming, dhash
from .model import Page
from .pdf import is_low_information


def _algo(hash_method: str):
    return phash if hash_method == "phash" else dhash


def hash_page_image(
    image_path: str | Path,
    hash_method: str = "phash",
) -> tuple[str, bool]:
    """Compute the perceptual hash of a page image file.

    Returns ``(pg_hash, low_information)``.  Low-information (blank / near
    blank) pages get an honest flag so the caller can decide whether they
    should participate in near-dup merging at all.
    """
    img = PILImage.open(str(image_path))
    img.load()
    low_info = False
    try:
        low_info = is_low_information(img)
    except Exception:
        low_info = False
    return _algo(hash_method)(img), low_info


def near_duplicate(
    store,
    pg_hash: str,
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
) -> Optional[str]:
    """Document id whose stored page hash is closest *within* ``threshold``.

    Returns ``None`` when no existing library page is near-duplicate (so the
    caller creates a new record).  Empty/missing hashes never match.
    """
    if not pg_hash:
        return None
    best: Optional[str] = None
    best_d = threshold  # only strictly-better-than-threshold wins
    for doc_id, h in store.document_hashes().items():
        if not h:
            continue
        d = hamming(pg_hash, h)
        if d < best_d:
            best_d = d
            best = doc_id
        elif d == best_d and best is None:
            best = doc_id
    return best


def resolve_merge(
    store,
    pg_hash: str,
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
    proposed_document_id: Optional[str] = None,
) -> dict:
    """Decide the commit target for a page with hash ``pg_hash``.

    Returns ``{"document_id": ..., "merged_into": document_id|None}``.  When a
    near-duplicate library page exists we merge into it; otherwise we keep the
    caller's ``proposed_document_id`` (fresh upload -> new record).  A page
    that is low-information still merges only if a real near-duplicate exists.
    """
    target = near_duplicate(store, pg_hash, threshold)
    if target is not None:
        return {"document_id": target, "merged_into": target}
    return {"document_id": proposed_document_id, "merged_into": None}


def ingest_single_page(
    store,
    image_path: str | Path,
    *,
    title: Optional[str] = None,
    model: str = "glm-5.3-flash",
    pg_hash: Optional[str] = None,
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
    hash_method: str = "phash",
    proposed_document_id: Optional[str] = None,
    source_job_id: Optional[str] = None,
    markdown: Optional[str] = None,
    ir_json: Optional[str] = None,
    preprocessed_path: Optional[str] = None,
    preprocessed_raw_path: Optional[str] = None,
    assets_dir: Optional[str] = None,
    timing_json: Optional[dict] = None,
) -> dict:
    """Commit one page into the library, merging near-duplicates.

    Returns ``{"document_id", "merged_into", "version_id", "title",
    "candidate_versions"}``.  ``merged_into`` is set when the page was absorbed
    as a candidate version of an existing document (the UI "已并入文档 X" hint);
    else ``None`` and a new record is created.
    """
    if pg_hash is None:
        pg_hash, _ = hash_page_image(image_path, hash_method)
    ext = Path(image_path).suffix or ".jpg"
    decision = resolve_merge(
        store, pg_hash, threshold=threshold,
        proposed_document_id=proposed_document_id or _new_doc_id(),
    )
    document_id = decision["document_id"]
    rec = store.save_document(
        document_id=document_id,
        title=title or Path(image_path).name or document_id,
        source_job_id=source_job_id or f"ingest-{document_id}",
        model=model,
        markdown=markdown or f"# {title or Path(image_path).name}\n\n（待解析）",
        ir_json=ir_json or _empty_ir(),
        original_path=str(image_path),
        original_ext=ext,
        preprocessed_path=preprocessed_path,
        preprocessed_raw_path=preprocessed_raw_path,
        assets_dir=assets_dir,
        timing_json=timing_json or {},
        pg_hash=pg_hash,
    )
    return {
        "document_id": document_id,
        "merged_into": decision["merged_into"],
        "version_id": rec.get("latest_version"),
        "title": rec.get("title"),
        "candidate_versions": len(rec.get("versions") or []),
    }


def ingest_report_to_store(
    report,
    store,
    *,
    model: str = "glm-5.3-flash",
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
    hash_method: str = "phash",
    recognizer: Optional[Callable] = None,
) -> list[dict]:
    """Commit a PDF ingest report into the library, one document per unique page.

    ``report`` is an :class:`IngestReport` (issue 09).  For each cluster's
    representative page we commit a document; pages that are within threshold
    of an already-committed page (cross-PDF duplicate or against an existing
    library record) merge into that document as candidate versions instead of a
    new record.  ``recognizer(page) -> dict`` optionally supplies
    ``markdown``/``ir_json``/``title`` for each unique page; when omitted a
    placeholder record is written (parse is a later 03 step).
    """
    results = []
    pages: list[Page] = []
    for p in report.pages:
        if p.low_information:
            continue  # blank/near-blank isolation per issue 09 policy
        pages.append(p)
    clusters = cluster_pages(pages, threshold=threshold, hash_method=hash_method)
    for cluster in clusters:
        rep = cluster.representative
        doc_id = _new_doc_id()
        parsed = {}
        if recognizer is not None:
            try:
                parsed = recognizer(rep) or {}
            except Exception:
                parsed = {}
        page_path = rep.path
        pg = rep.pg_hash or phash(PILImage.open(page_path))
        out = ingest_single_page(
            store, page_path, title=parsed.get("title") or Path(page_path).name,
            model=model, pg_hash=pg, threshold=threshold, hash_method=hash_method,
            proposed_document_id=doc_id,
            markdown=parsed.get("markdown"),
            ir_json=parsed.get("ir_json"),
            source_job_id=f"pdf-{Path(rep.source_pdf).name}-p{rep.page_index + 1}",
        )
        results.append(out)
    return results


def split_document_versions(
    store,
    document_id: str,
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
    hash_method: str = "phash",
    model: str = "glm-5.3-flash",
) -> list[str]:
    """Reverse a (possibly false) merge: split candidate versions of a document
    into separate documents when their page hashes disagree beyond ``threshold``.

    Reuses the ingest re-cluster (``cluster_pages``) on the *source-page hashes*
    of the document's candidate versions — the record-level equivalent of the
    issue-09 ``recluster`` split.  The representative version stays in the
    original document; each other cluster becomes a new document.  Returns the
    ids of newly-created documents (empty when nothing splits).
    """
    versions = store.version_hashes(document_id)
    if len(versions) < 2:
        return []
    pages = [
        Page(source_pdf="", page_index=i, path=v.get("original_path") or "",
             width=0, height=0, dpi=0, pg_hash=v["pg_hash"])
        for i, v in enumerate(versions)
    ]
    clusters = [c for c in cluster_pages(
        pages, threshold=threshold, hash_method=hash_method) if len(c.pages) >= 1]
    if len(clusters) <= 1:
        return []

    rec = store.get_document(document_id)
    by_vid = {v["version_id"]: v for v in versions}

    # representative cluster keeps `document_id`: the one containing the doc's
    # FIRST (original) version — a false merge gets the later additions peeled
    # away, so the original content stays where the document was born.
    first_vid = versions[0]["version_id"]
    rep_cluster = None
    for c in clusters:
        vids = [versions[c.pages[k].page_index]["version_id"]
                for k in range(len(c.pages))]
        if first_vid in vids:
            rep_cluster = c
            break
    if rep_cluster is None:
        rep_cluster = clusters[0]
        first_vid = by_vid[versions[rep_cluster.pages[0].page_index]]["version_id"]

    moved: list[str] = []
    new_ids: list[str] = []
    for c in clusters:
        if c is rep_cluster:
            continue
        # pick this cluster's effective version (its latest) to found the new doc
        c_pages = sorted(c.pages, key=lambda p: p.page_index)
        src_v = by_vid[versions[c_pages[-1].page_index]["version_id"]]
        new_id = _new_doc_id()
        store.save_document(
            document_id=new_id,
            title=f"{rec.get('title','doc')} (拆分)",
            source_job_id=f"split-{document_id}",
            model=src_v.get("model") or model,
            markdown=src_v.get("markdown") or "",
            ir_json=src_v.get("ir_json") or _empty_ir(),
            original_path=src_v.get("original_path") or "",
            original_ext=src_v.get("original_ext") or ".jpg",
            preprocessed_path=None, preprocessed_raw_path=None, assets_dir=None,
            timing_json={}, pg_hash=src_v.get("pg_hash") or "",
        )
        moved.append(src_v["version_id"])
        new_ids.append(new_id)
    # drop the moved versions from the original document
    if moved:
        store.remove_versions(document_id, moved)
    return new_ids


def _new_doc_id() -> str:
    return "doc-" + uuid.uuid4().hex[:10]


def _empty_ir() -> str:
    return json.dumps({"document_type": "note", "blocks": []}, ensure_ascii=False)


__all__ = [
    "hash_page_image",
    "near_duplicate",
    "resolve_merge",
    "ingest_single_page",
    "ingest_report_to_store",
    "split_document_versions",
    "DEFAULT_DEDUP_THRESHOLD",
]