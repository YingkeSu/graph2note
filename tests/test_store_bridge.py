"""Issue 13 — ingest<->store integration (dedup-on-ingest, candidate versions).

Offline only: pHash/dHash are pure PIL/numpy, store is the local seam, and
clustering is pure.  No network.  Sample "pages" are synthetic scans (dark
blocks on white) with controllable lighting / angle perturbations.

AC coverage:
  AC1  same page, two uploads with different lighting/angle -> one DocumentRecord
       with two candidate versions (merged end-to-end).
  AC2  different pages do not merge (negative) + a false merge can be split back
       apart via the ingest re-cluster path (reversible).
  AC3  candidate versions retained & queryable; latest effective by default.
  AC4  PDF batch ingest: dedup-then-per-page-document, cross-PDF near-dup + merge
       against an existing library record.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from graph2note.ingest import (
    hamming,
    phash,
    store_bridge,
)
from graph2note.ingest.model import IngestReport, Page
from graph2note.store import SessionDocumentStore

# -- synthetic page renderer -------------------------------------------------

NAIVE = object()
_EMPTY_IR = '{"document_type":"note","blocks":[]}'


def _render_page(rects, size=(200, 260)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for box in rects:
        x0, y0, x1, y1, ink = box
        d.rectangle([x0, y0, x1, y1], fill=(ink, ink, ink))
    return img


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _write(tmp: Path, name: str, img: Image.Image) -> Path:
    p = tmp / name
    p.write_bytes(_png_bytes(img))
    return p


# Page A layout (~5 text-ish lines + header bar)
_RECT_A = [(20, 30, 180, 46, 40), (20, 60, 160, 74, 30), (25, 90, 150, 100, 35),
           (20, 120, 170, 134, 30), (15, 150, 165, 158, 35)]


def _page_a() -> Image.Image:
    return _render_page(_RECT_A)


def _page_a_lighting() -> Image.Image:
    # same layout, different brightness = "different lighting"
    return _page_a().point(lambda p: min(255, int(p * 1.35))).convert("RGB")


def _page_a_angle() -> Image.Image:
    # same layout, ~3deg rotation = "different angle"
    return _page_a().rotate(3, expand=False, fillcolor=(255, 255, 255)).convert("RGB")


def _page_c() -> Image.Image:
    # visually distinct layout (a different page)
    return _render_page([(10, 10, 60, 120, 20), (90, 90, 180, 200, 200),
                         (30, 200, 70, 250, 128), (120, 10, 190, 80, 60)])


def _make_store(tmp_path=None):
    base = tmp_path or Path("./.g2n-test-session")
    return SessionDocumentStore(str(base))


# -- AC1: same page, two uploads w/ different lighting/angle merge -----------

def test_same_page_different_lighting_and_angle_merge(tmp_path):
    store = _make_store(tmp_path)
    a = _write(tmp_path, "scanA.png", _page_a())
    b = _write(tmp_path, "scanB-light.png", _page_a_lighting())
    c = _write(tmp_path, "scanC-angle.png", _page_a_angle())

    r1 = store_bridge.ingest_single_page(
        store, a, title="需求规格", markdown="# 需求规格", ir_json=_EMPTY_IR)
    r2 = store_bridge.ingest_single_page(
        store, b, title="需求规格", markdown="# 需求规格 (scan2)", ir_json=_EMPTY_IR)
    r3 = store_bridge.ingest_single_page(
        store, c, title="需求规格", markdown="# 需求规格 (scan3)", ir_json=_EMPTY_IR)

    # end-to-end: all three uploads land in ONE DocumentRecord, no new record
    assert r1["merged_into"] is None          # first upload creates the record
    assert r2["merged_into"] == r1["document_id"]
    assert r3["merged_into"] == r1["document_id"]
    assert len(store.list_documents()) == 1

    rec = store.get_document(r1["document_id"])
    assert rec["document_id"] == r1["document_id"]
    assert len(rec["versions"]) == 3
    # same page under different lighting/angle => near-overlapping pHash
    hs = [v["pg_hash"] for v in store.version_hashes(r1["document_id"])]
    h = phash(_page_a())
    assert hs[0] == h and hs[1] == h          # lighting variant -> identical hash
    assert hamming(hs[0], hs[2]) <= 6         # small-angle variant -> within threshold


# -- AC3: candidate versions queryable, latest effective by default ----------

def test_candidate_versions_retained_latest_effective(tmp_path):
    store = _make_store(tmp_path)
    a = _write(tmp_path, "v1.png", _page_a())
    b = _write(tmp_path, "v2.png", _page_a_lighting())

    r1 = store_bridge.ingest_single_page(store, a, title="规格",
                                         markdown="# 规格 v1", ir_json=_EMPTY_IR)
    r2 = store_bridge.ingest_single_page(store, b, title="规格",
                                         markdown="# 规格 v2", ir_json=_EMPTY_IR)

    assert r1["document_id"] == r2["document_id"]
    assert r2["merged_into"] == r1["document_id"]

    rec = store.get_document(r1["document_id"])
    versions = rec["versions"]

    # candidate version list queryable (both retained, newest last)
    assert len(versions) == 2
    vid_order = [v["version_id"] for v in versions]
    assert vid_order == [r1["version_id"], r2["version_id"]]
    # version_hashes primitive also reflects them
    vhs = store.version_hashes(r1["document_id"])
    assert len(vhs) == 2

    # latest effective by default
    assert rec["latest_version"] == r2["version_id"]
    assert rec["current_markdown"] == "# 规格 v2"
    flags = {v["version_id"]: v["current"] for v in versions}
    assert flags[r2["version_id"]] is True
    assert flags[r1["version_id"]] is False


# -- AC2: different pages don't merge; false merge is splittable -------------

def test_different_pages_do_not_merge(tmp_path):
    store = _make_store(tmp_path)
    a = _write(tmp_path, "pageA.png", _page_a())
    c = _write(tmp_path, "pageC.png", _page_c())

    ra = store_bridge.ingest_single_page(store, a, markdown="# A", ir_json=_EMPTY_IR)
    rc = store_bridge.ingest_single_page(store, c, markdown="# C", ir_json=_EMPTY_IR)

    assert ra["document_id"] != rc["document_id"]
    assert rc["merged_into"] is None
    # distinct page never collides with the A-document (it only matches its OWN
    # freshly-created record), and vice-versa
    assert store_bridge.near_duplicate(
        store, phash(_page_c()), threshold=6) == rc["document_id"]
    assert store_bridge.near_duplicate(
        store, phash(_page_a()), threshold=6) == ra["document_id"]
    assert len(store.list_documents()) == 2


def test_false_merge_split_via_recluster(tmp_path):
    store = _make_store(tmp_path)
    a = _write(tmp_path, "a.png", _page_a())
    b = _write(tmp_path, "b.png", _page_a_lighting())
    c = _write(tmp_path, "c.png", _page_c())

    # two genuine near-duplicates
    ra = store_bridge.ingest_single_page(store, a, markdown="# A", ir_json=_EMPTY_IR)
    rbc = store_bridge.ingest_single_page(store, b, markdown="# B", ir_json=_EMPTY_IR)
    doc_a = ra["document_id"]
    assert rbc["merged_into"] == doc_a
    assert store.get_document(doc_a)["latest_version"] == rbc["version_id"]

    # simulate a WRONG merge: force the distinct page into the same record
    # (proposed_document_id = doc_a keeps it there even though not near-dup)
    r_false = store_bridge.ingest_single_page(
        store, c, pg_hash=phash(_page_c()),
        proposed_document_id=doc_a, markdown="# C", ir_json=_EMPTY_IR)
    assert r_false["document_id"] == doc_a
    assert len(store.version_hashes(doc_a)) == 3

    # reversible split: distinct page should be peeled into its own document
    new_ids = store_bridge.split_document_versions(store, doc_a, threshold=6)
    assert len(new_ids) == 1

    # the original re-integration point now holds only the near-dup pair
    versions = store.version_hashes(doc_a)
    assert len(versions) == 2
    hv = [v["pg_hash"] for v in versions]
    assert all(hamming(hv[0], h) <= 6 for h in hv)
    # the distinct page is now its own document
    new_doc = store.get_document(new_ids[0])
    assert new_doc["document_id"] == new_ids[0]
    assert new_doc["current_markdown"] == "# C"
    assert new_ids[0] != doc_a


# -- AC4: PDF batch ingest dedup-then-per-page-document ----------------------

def test_pdf_batch_dedup_per_page_document(tmp_path):
    store = _make_store(tmp_path)
    # library already holds a page identical to A (so the batch merges into it)
    pre = _write(tmp_path, "pre.png", _page_a())
    pre_r = store_bridge.ingest_single_page(store, pre, title="已入库",
                                            markdown="# 已入库", ir_json=_EMPTY_IR)
    lib_doc = pre_r["document_id"]

    # PDF "report": page A (dup of library), near-dup A-light in another PDF,
    # plus a distinct page C. Unique cluster reps: A and C.
    ha = phash(_page_a())
    hb = phash(_page_a_lighting())
    hc = phash(_page_c())
    report = IngestReport(
        source_pdfs=["in.pdf", "in2.pdf"],
        pages=[
            Page("in.pdf", 0, str(tmp_path / "a.pdf.png"), 200, 260, 96, ha),
            Page("in2.pdf", 0, str(tmp_path / "alight.pdf.png"), 200, 260, 96, hb),
            Page("in.pdf", 1, str(tmp_path / "c.pdf.png"), 200, 260, 96, hc),
        ],
        threshold=6,
    )

    results = store_bridge.ingest_report_to_store(
        report, store, model="deepseek-v4-flash-vision-exp")

    # dedup within batch: 2 unique pages -> 2 commit points
    assert len(results) == 2
    # A-representative merges into the existing library record (candidate v2)
    repA = [r for r in results if r["candidate_versions"] >= 2][0]
    assert repA["merged_into"] == lib_doc
    assert repA["document_id"] == lib_doc
    assert store.get_document(lib_doc)["versions"][-1]["pg_hash"] in (ha, hb)
    # distinct page C is its own new document, not merged into anything
    repC = [r for r in results if r["document_id"] != lib_doc][0]
    assert repC["merged_into"] is None
    assert phash(_page_c()) == store.version_hashes(repC["document_id"])[0]["pg_hash"]
    assert len(store.list_documents()) == 2


# -- durable FileDocumentStore path also supports merge + split + versions ----

def test_file_store_merge_versions_and_split(tmp_path):
    from graph2note.store import FileDocumentStore

    store = FileDocumentStore(str(tmp_path / "lib"))
    a = _write(tmp_path, "a.png", _page_a())
    b = _write(tmp_path, "b.png", _page_a_lighting())
    c = _write(tmp_path, "c.png", _page_c())

    r1 = store_bridge.ingest_single_page(store, a, title="规格",
                                         markdown="# 规格 v1", ir_json=_EMPTY_IR)
    r2 = store_bridge.ingest_single_page(store, b, title="规格",
                                         markdown="# 规格 v2", ir_json=_EMPTY_IR)
    assert r2["merged_into"] == r1["document_id"]
    assert store.get_document(r1["document_id"])["hash"]
    # per-version source pages retained on disk, candidate list queryable
    rec = store.get_document(r1["document_id"])
    assert len(rec["versions"]) == 2
    for v in rec["versions"]:
        assert Path(v["page_path"]).is_file()
    vhs = store.version_hashes(r1["document_id"])
    assert len(vhs) == 2 and all(v["pg_hash"] for v in vhs)

    # false merge + reversible split (durable)
    store_bridge.ingest_single_page(store, c, pg_hash=phash(_page_c()),
                                    proposed_document_id=r1["document_id"],
                                    markdown="# C", ir_json=_EMPTY_IR)
    assert len(store.version_hashes(r1["document_id"])) == 3
    new_ids = store_bridge.split_document_versions(store, r1["document_id"], 6)
    assert len(new_ids) == 1
    kept = store.version_hashes(r1["document_id"])
    assert len(kept) == 2 and all(v["pg_hash"] == phash(_page_a()) for v in kept)
    newrec = store.get_document(new_ids[0])
    assert newrec["current_markdown"] == "# C"
    assert len(newrec["versions"]) == 1


# -- threshold adjustability -------------------------------------------------

def test_threshold_adjustable(tmp_path):
    store = _make_store(tmp_path)
    a = _write(tmp_path, "a.png", _page_a())
    c = _write(tmp_path, "c.png", _page_c())
    ra = store_bridge.ingest_single_page(store, a, markdown="# A", ir_json=_EMPTY_IR)

    # at a sane threshold a very different page does not merge
    assert store_bridge.near_duplicate(store, phash(_page_c()), threshold=6) is None

    # at an intentionally very-lenient threshold even a very different page
    # collides (demonstrates the knob is live; >~24 forces the merge)
    rc = store_bridge.ingest_single_page(
        store, c, markdown="# C", ir_json=_EMPTY_IR, threshold=64)
    assert rc["merged_into"] == ra["document_id"]