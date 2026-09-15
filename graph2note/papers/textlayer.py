"""PDF text-layer extraction + deterministic VLM-fallback decision (P1).

A born-digital paper keeps its text in the PDF text layer.  Re-recognising it
through the screenshot → VLM path wastes a model call per page and destroys
structure (headings, reference lists), so P1 reads the text layer directly and
only falls back to the VLM page path when the PDF has no usable text layer.

Everything in this module is deterministic for the same PDF bytes:

- page / block / line / span order comes from PyMuPDF's reading order (the same
  file always yields the same order);
- :func:`decide_text_layer` is a pure threshold over measured character counts
  (no model call, no wall-clock, no randomness), so a decision can be replayed
  and unit-tested offline.

``pymupdf`` is an optional dependency: import failures surface as
``pdflib.PdfError(kind="unreadable")`` through :func:`read_text_layer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Fallback thresholds (issue AC3: the decision itself must be offline-deterministic)
# ---------------------------------------------------------------------------

#: A page counts as "text-bearing" when it has at least this many non-whitespace
#: characters (a scan often carries a stamp/header of a handful of characters —
#: that must not make us treat the document as born-digital).
MIN_PAGE_CHARS = 60

#: A document counts as born-digital when the whole PDF carries at least this
#: many non-whitespace characters …
MIN_TOTAL_CHARS = 200

#: … and at least this fraction of its pages are text-bearing.
MIN_TEXT_PAGE_RATIO = 0.3

#: Coordinate rounding for span sizes (font sizes are floats; rounding keeps the
#: "body size" mode stable across identical inputs).
SIZE_PRECISION = 1

_BOLD_FLAG = 1 << 4  # PyMuPDF span flag bit 4: bold


@dataclass
class TextLine:
    """One extracted text line (structure splitting's only input)."""

    page_index: int  # 0-based
    text: str
    size: float = 0.0
    bold: bool = False
    order: int = 0  # global reading order across the whole PDF


@dataclass
class PageText:
    """Text of one PDF page (text-layer path)."""

    page_index: int  # 0-based
    text: str = ""
    lines: list[TextLine] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        """Non-whitespace character count (CJK counts per character)."""
        return count_chars(self.text)


@dataclass
class TextLayer:
    """Whole-PDF text layer: pages in source order + flat line list."""

    pages: list[PageText] = field(default_factory=list)

    @property
    def lines(self) -> list[TextLine]:
        return [line for page in self.pages for line in page.lines]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def fulltext(self) -> str:
        """Plain text of every page, joined with a blank line."""
        return "\n\n".join(
            page.text.strip() for page in self.pages if page.text.strip()
        ).strip()

    @property
    def char_count(self) -> int:
        return sum(page.char_count for page in self.pages)


@dataclass
class TextLayerDecision:
    """Explainable result of the text-layer / VLM-fallback decision."""

    source: str            # "text-layer" | "vlm"
    reason: str
    total_chars: int = 0
    text_pages: int = 0
    total_pages: int = 0
    min_page_chars: int = MIN_PAGE_CHARS
    min_total_chars: int = MIN_TOTAL_CHARS
    min_text_page_ratio: float = MIN_TEXT_PAGE_RATIO

    @property
    def text_page_ratio(self) -> float:
        if not self.total_pages:
            return 0.0
        return self.text_pages / self.total_pages

    @property
    def use_text_layer(self) -> bool:
        return self.source == "text-layer"

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "reason": self.reason,
            "total_chars": self.total_chars,
            "text_pages": self.text_pages,
            "total_pages": self.total_pages,
            "text_page_ratio": round(self.text_page_ratio, 4),
            "min_page_chars": self.min_page_chars,
            "min_total_chars": self.min_total_chars,
            "min_text_page_ratio": self.min_text_page_ratio,
        }


def count_chars(text: str | None) -> int:
    """Non-whitespace character count (the one density metric used everywhere)."""
    if not text:
        return 0
    return len("".join(text.split()))


def round_size(size: float) -> float:
    return round(float(size or 0.0), SIZE_PRECISION)


def _span_is_bold(span: dict) -> bool:
    flags = span.get("flags")
    if isinstance(flags, int) and flags & _BOLD_FLAG:
        return True
    return "bold" in str(span.get("font") or "").lower()


def _dominant_size(spans: list[dict]) -> float:
    """Dominant span font size of one line.

    The span covering the most characters wins (a large leading capital on a
    body line must not promote the whole line); ties break to the larger size
    then to the smaller string, so the result is stable for identical input.
    """
    counts: dict[float, int] = {}
    for span in spans:
        size = round_size(span.get("size") or 0.0)
        counts[size] = counts.get(size, 0) + count_chars(str(span.get("text") or ""))
    return max(sorted(counts), key=lambda size: (counts[size], size))


def extract_text_layer(doc) -> TextLayer:
    """Build a :class:`TextLayer` from an open PyMuPDF document.

    Split out from :func:`read_text_layer` so tests can drive it with an
    in-memory document (``pymupdf.open()``) and no file I/O.
    """
    pages: list[PageText] = []
    order = 0
    for page_index in range(int(doc.page_count)):
        page = doc[page_index]
        text = page.get_text("text") or ""
        lines: list[TextLine] = []
        try:
            raw = page.get_text("dict")
        except Exception:  # pragma: no cover - PyMuPDF defensive path
            raw = {"blocks": []}
        for block in raw.get("blocks", []):
            if block.get("type", 0) != 0:  # image block
                continue
            for line in block.get("lines", []):
                spans = [s for s in line.get("spans", []) if str(s.get("text") or "")]
                if not spans:
                    continue
                line_text = "".join(str(s.get("text") or "") for s in spans)
                if not line_text.strip():
                    continue
                lines.append(TextLine(
                    page_index=page_index,
                    text=line_text,
                    size=_dominant_size(spans),
                    bold=any(_span_is_bold(s) for s in spans),
                    order=order,
                ))
                order += 1
        pages.append(PageText(page_index=page_index, text=text, lines=lines))
    return TextLayer(pages=pages)


def read_text_layer(pdf_path: str | Path) -> TextLayer:
    """Extract the text layer of ``pdf_path`` (PyMuPDF, offline).

    Raises :class:`graph2note.pdflib.PdfError` (kind ``unreadable``/``corrupt``)
    so the Web layer can surface an actionable message.
    """
    from .. import pdflib

    if not pdflib.pdf_available():
        raise pdflib.PdfError(
            "unreadable", "未安装 PDF 处理依赖（PyMuPDF），无法读取文本层。"
        )
    import pymupdf

    doc = None
    try:
        try:
            doc = pymupdf.open(str(pdf_path))
        except Exception as exc:
            raise pdflib.PdfError("corrupt", f"PDF 无法打开（可能已损坏）：{exc}") from exc
        return extract_text_layer(doc)
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def page_is_text_bearing(page: PageText, *, min_page_chars: int = MIN_PAGE_CHARS) -> bool:
    return page.char_count >= min_page_chars


def decide_text_layer(
    layer: TextLayer,
    *,
    min_page_chars: int = MIN_PAGE_CHARS,
    min_total_chars: int = MIN_TOTAL_CHARS,
    min_text_page_ratio: float = MIN_TEXT_PAGE_RATIO,
) -> TextLayerDecision:
    """Decide text-layer vs VLM fallback from measured character counts.

    Deterministic rule (no model call):

    - every page with ≥ ``min_page_chars`` non-whitespace characters is
      "text-bearing";
    - the document uses the **text layer** when it has at least one text-bearing
      page, ≥ ``min_total_chars`` characters overall and a text-bearing page
      ratio ≥ ``min_text_page_ratio``;
    - otherwise it is a scan-like PDF and **falls back to the VLM page path**.
    """
    total_chars = layer.char_count
    total_pages = layer.page_count
    text_pages = sum(
        1 for page in layer.pages if page_is_text_bearing(page, min_page_chars=min_page_chars)
    )
    ratio = (text_pages / total_pages) if total_pages else 0.0

    if total_chars < min_total_chars:
        reason = (
            f"文本层字符数 {total_chars} < 阈值 {min_total_chars}"
            f"（{text_pages}/{total_pages} 页有文本），按扫描版处理。"
        )
        source = "vlm"
    elif not text_pages:
        reason = (
            f"没有任何页面达到每页 {min_page_chars} 字符的文本层阈值"
            f"（共 {total_chars} 字符），按扫描版处理。"
        )
        source = "vlm"
    elif ratio < min_text_page_ratio:
        reason = (
            f"有文本的页占比 {ratio:.2f} < 阈值 {min_text_page_ratio:.2f}"
            f"（{text_pages}/{total_pages} 页），按扫描版处理。"
        )
        source = "vlm"
    else:
        reason = (
            f"文本层直提：{total_chars} 字符 / {text_pages} 页有文本"
            f"（占比 {ratio:.2f} ≥ {min_text_page_ratio:.2f}）。"
        )
        source = "text-layer"

    return TextLayerDecision(
        source=source,
        reason=reason,
        total_chars=total_chars,
        text_pages=text_pages,
        total_pages=total_pages,
        min_page_chars=min_page_chars,
        min_total_chars=min_total_chars,
        min_text_page_ratio=min_text_page_ratio,
    )


def line_sizes(lines: Iterable[TextLine]) -> list[float]:
    return [round_size(line.size) for line in lines]


__all__ = [
    "MIN_PAGE_CHARS",
    "MIN_TOTAL_CHARS",
    "MIN_TEXT_PAGE_RATIO",
    "SIZE_PRECISION",
    "PageText",
    "TextLayer",
    "TextLayerDecision",
    "TextLine",
    "count_chars",
    "decide_text_layer",
    "extract_text_layer",
    "line_sizes",
    "page_is_text_bearing",
    "read_text_layer",
    "round_size",
]
