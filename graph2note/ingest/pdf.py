"""Scan-PDF page splitting (issue 09).

Renders every page of a scanned PDF to a standalone image with traceable
provenance (``source_pdf`` + ``page_index``).  Uses PyMuPDF when available;
the module import is guarded so the rest of the pipeline stays usable without
it (mirrors the established graphviz-style optional-dependency pattern).

Blank / low-information pages are *kept by default but flagged* (非文档页策略).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from .hash import dhash, phash
from .model import Page

try:  # optional dependency
    import pymupdf  # type: ignore
    _HAS_FITZ = True
except Exception:  # pragma: no cover - depends on optional install
    pymupdf = None  # type: ignore
    _HAS_FITZ = False

DEFAULT_DPI = 150
DEFAULT_JPEG_QUALITY = 85
DEFAULT_LOW_INFO_INK = 0.004  # below this content-fraction a page is low-information

# Batch/number suffix e.g. `扫描件0908152342_1_1001` -> batch `2342`, ordinal `1`.
_FILENAME_PATTERN = re.compile(r"_(?P<batch>\d+)_(?P<ordinal>\d+)_?")


def content_fraction(image, side: int = 256, ink: int = 200) -> float:
    """Fraction of non-background pixels on a downsampled grayscale.

    Downsampling averages away scanner speckle so genuinely blank pages score
    ~0 while content pages score clearly above 0 (real scans: blanks 0.0,
    content >= 0.006 at side=256).  Pure numpy/PIL, dependency-light.
    """
    import numpy as np
    from PIL import Image as PILImage

    gray = np.asarray(
        PILImage.fromarray(np.asarray(image)).convert("L").resize((side, side)),
        dtype=np.float32,
    )
    return float((gray < ink).mean())


def is_low_information(image, ink_threshold: float = DEFAULT_LOW_INFO_INK) -> bool:
    """True when a page carries too little content to trust near-dup merging."""
    return content_fraction(image) < ink_threshold


def available() -> bool:
    """True when PyMuPDF is importable (needed to split PDFs)."""
    return _HAS_FITZ


def parse_filename_hint(path) -> Optional[dict]:
    """Best-effort filename batch/series hint (scanner naming convention)."""
    m = _FILENAME_PATTERN.search(os.path.basename(str(path)))
    if not m:
        return None
    return {"batch": m.group("batch"), "ordinal": int(m.group("ordinal"))}


def _is_blank(arr):
    """Truly blank page: effectively no content at all."""
    return content_fraction(arr) < 0.0002


def split_pdf(
    pdf_path,
    out_dir,
    dpi: int = DEFAULT_DPI,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    flag_blank: bool = True,
    hash_method: str = "phash",
    hash_size: int = 8,
) -> list[Page]:
    """Split ``pdf_path`` into per-page JPEG images under ``out_dir``.

    Returns a list of :class:`Page` in page order (``page_index`` 0-based).
    Pages are rendered at ``dpi`` and stored as JPEG of ``jpeg_quality``.  When
    ``flag_blank``, blank/low-information pages are retained with ``blank`` /
    ``low_information`` flags set.
    """
    if not _HAS_FITZ:
        raise RuntimeError(
            "PyMuPDF is required to split PDFs. Install with: pip install pymupdf"
        )
    src = Path(pdf_path)
    stem = src.stem
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(str(src))
    pages: list[Page] = []
    for i in range(doc.page_count):
        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        img = pix.pil_image()
        blank = is_low_information(img, 0.0002) if flag_blank else False
        low_info = is_low_information(img) if flag_blank else False
        fname = f"{stem}_p{i + 1:03d}.jpg"
        img.convert("RGB").save(
            out_dir / fname, "JPEG", quality=jpeg_quality
        )
        pg_hash = (phash if hash_method == "phash" else dhash)(
            img, hash_size=hash_size
        )
        pages.append(
            Page(
                source_pdf=str(src),
                page_index=i,
                path=str(out_dir / fname),
                width=img.width,
                height=img.height,
                dpi=dpi,
                pg_hash=pg_hash,
                blank=blank,
                low_information=low_info,
            )
        )
    doc.close()
    return pages


__all__ = [
    "available",
    "split_pdf",
    "parse_filename_hint",
    "content_fraction",
    "is_low_information",
    "DEFAULT_DPI",
    "DEFAULT_JPEG_QUALITY",
    "DEFAULT_LOW_INFO_INK",
]