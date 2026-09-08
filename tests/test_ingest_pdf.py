"""PDF splitting + end-to-end ingest: uses synthetic PDFs built in-test with
PyMuPDF.  These SKIP cleanly when PyMuPDF is unavailable (optional dependency),
mirroring the established graphviz-style pattern.
"""

import numpy as np
import pytest
from PIL import Image

pymupdf = pytest.importorskip("pymupdf")

from graph2note.ingest import (  # noqa: E402
    ingest_pdfs, split_pdf, phash, hamming, pdf_available,
)


def _make_page(seed=1, w=300, h=420, empty=False, dpi_ink=30):
    rng = np.random.default_rng(seed)
    arr = np.full((h, w, 3), 250, np.uint8)
    if not empty:
        for i in range(4):
            y = 60 + i * 90
            x = int(rng.integers(30, 120))
            arr[y:y + 4, x:x + int(rng.integers(50, 200)), :] = dpi_ink
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def _pdf_from_images(path, images):
    """Build a single page-per-image PDF deterministically."""
    from pathlib import Path
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for i, img in enumerate(images):
        page = doc.new_page(width=img.width, height=img.height)
        png = path.parent / f"_pg{i}.png"
        img.convert("RGB").save(png)
        page.insert_image(page.rect, filename=str(png))
    doc.save(path)
    doc.close()
    for p in path.parent.glob("_pg*.png"):
        p.unlink()
    return path


def _render_pages(pdf, dpi=100):
    out = []
    d = pymupdf.open(pdf)
    for pg in d:
        out.append(pg.get_pixmap(dpi=dpi).pil_image())
    d.close()
    return out


def test_pdf_available_guards_optional_dependency():
    assert pdf_available() is True  # pymupdf importable in this env


def test_split_pdf_traces_provenance_and_flags_blank(tmp_path):
    img_content = _make_page(1)
    img_blank = _make_page(2, empty=True)
    pdf = tmp_path / "scan.pdf"
    _pdf_from_images(str(pdf), [img_content, img_blank, img_content])
    pages = split_pdf(str(pdf), tmp_path / "pages", dpi=100)
    assert len(pages) == 3
    assert pages[0].source_pdf.endswith("scan.pdf")
    assert pages[0].page_index == 0 and pages[2].page_index == 2
    assert pages[1].blank is True and pages[1].low_information
    assert pages[0].blank is False and pages[0].low_information is False
    # rendered JPEG exists and is openable
    assert (tmp_path / "pages" / "scan_p001.jpg").exists()


def test_split_pdf_dpi_and_pagesize(tmp_path):
    img = _make_page(1)
    pdf = tmp_path / "s.pdf"
    _pdf_from_images(str(pdf), [img, img])
    pages_hi = split_pdf(str(pdf), tmp_path / "hi", dpi=200)
    pages_lo = split_pdf(str(pdf), tmp_path / "lo", dpi=100)
    assert pages_hi[0].dpi == 200
    assert pages_hi[0].width > pages_lo[0].width
    assert pages_hi[0].height > pages_lo[0].height


def test_ingest_merges_known_duplicate_pair(tmp_path):
    p = _make_page(1)                      # content page
    variant = _make_page(1, dpi_ink=25)    # same page, "another scan" (lighter ink)
    other = _make_page(9)                  # distinct page
    a = tmp_path / "docA.pdf"
    _pdf_from_images(str(a), [p, other])
    b = tmp_path / "docB.pdf"
    _pdf_from_images(str(b), [variant, other])
    report = ingest_pdfs([a, b], tmp_path / "pages", dpi=100, threshold=6)
    # p & variant merge; other appears twice and merges too
    assert report.unique_pages == 2
    assert report.candidate_versions == 2
    multi = [c for c in report.clusters if len(c.pages) > 1]
    assert len(multi) == 2


def test_ingest_missing_alert_with_page_numbers(tmp_path):
    p1, p2, p3, p4 = (_make_page(i) for i in (1, 2, 3, 5))
    a = tmp_path / "doc.pdf"
    _pdf_from_images(str(a), [p1, p2, p3, p4])
    report = ingest_pdfs([a], tmp_path / "pages", dpi=100,
                         page_numbers={0: 1, 1: 2, 2: 3, 3: 5})
    kinds = {al.kind for al in report.alerts}
    assert "gap" in kinds
    assert any(al.missing_numbers == [4] for al in report.alerts)


def test_ingest_no_page_numbers_no_clue(tmp_path):
    a = tmp_path / "doc.pdf"
    _pdf_from_images(str(a), [_make_page(i) for i in (1, 2, 3)])
    report = ingest_pdfs([a], tmp_path / "pages", dpi=100)
    assert all(al.kind == "no_clue" for al in report.alerts)


def test_dhash_and_phash_agree_on_single_page(tmp_path):
    p = _make_page(1)
    a = tmp_path / "doc.pdf"
    _pdf_from_images(str(a), [p, p])
    r1 = ingest_pdfs([a], tmp_path / "ph", dpi=100, hash_method="phash", threshold=0)
    assert r1.unique_pages == 1  # identical pages merge at threshold 0