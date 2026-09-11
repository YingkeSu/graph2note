"""PDF upload -> split -> per-page parse -> document library (issue 08).

Reuses the issue-09 ingest surface (``split_pdf`` for page rendering with
traceable provenance, ``cluster_pages`` for within-PDF near-duplicate merging)
and the issue-03 parse pipeline (``pipeline.parse_document``) to turn a
user-uploaded PDF into *real* library documents — one per unique page — while
recording an explainable per-page status (success / failed / blank / duplicate)
and a durable source mapping (``pdf_id`` + ``page_index``) so a page document
can always be traced back to its page in the original PDF.

Every model call goes through the same injectable ``router_factory`` seam used
by the single-image web path, so tests run fully offline and CI never touches
the network.  No secrets live here.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .ingest import split_pdf, cluster_pages, pdf_available
from .ingest.model import Page
from .ir import dumps_ir
from . import pipeline

# Limits (AC4: explicit file type / size / page-count limits).  PDFs are a
# NEW input type (FR-015's 10MB cap is JPG/JPEG/PNG-specific): a multi-page
# scan easily exceeds 10MB (the reference 21-page scan is ~10.9MB), so PDFs
# get their own, larger ceiling.
ALLOWED_PDF_EXT = {".pdf"}
MAX_PDF_SIZE = 50 * 1024 * 1024       # 50 MB
MAX_PDF_PAGES = 200                    # page-count ceiling
DEFAULT_DPI = 150


class PdfError(RuntimeError):
    """Classified PDF upload error (actionable message for the Web UI)."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # wrong_type|too_large|too_many_pages|encrypted|corrupt|unreadable


def stable_pdf_id(data: bytes) -> str:
    """Stable identity of an uploaded PDF (content hash, AC2)."""
    return "pdf-" + hashlib.sha256(data).hexdigest()[:16]


def validate_pdf(
    data: bytes,
    filename: str,
    *,
    max_size: int | None = None,
    max_pages: int | None = None,
) -> int:
    """Validate an uploaded PDF; return its page count.

    Raises :class:`PdfError` with a machine-readable ``kind`` and a
    human-actionable message for every rejectable condition.
    """
    if max_size is None:
        max_size = MAX_PDF_SIZE
    if max_pages is None:
        max_pages = MAX_PDF_PAGES
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_PDF_EXT:
        raise PdfError(
            "wrong_type",
            f"不支持的格式：仅支持 PDF（收到 {ext or '未知'}）。",
        )
    if not data:
        raise PdfError("corrupt", "空文件，无法解析。")
    if len(data) > max_size:
        raise PdfError(
            "too_large",
            f"文件超过 {max_size // 1048576}MB 上限（收到 {len(data) / 1048576:.1f}MB）。",
        )
    if not pdf_available():
        raise PdfError(
            "unreadable", "未安装 PDF 处理依赖（PyMuPDF），无法处理 PDF。"
        )

    import pymupdf

    doc = None
    try:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as exc:  # FileDataError / RuntimeError / …
            raise PdfError("corrupt", f"PDF 无法打开（可能已损坏）：{exc}") from exc
        try:
            if doc.needs_pass or doc.is_encrypted:
                raise PdfError("encrypted", "PDF 已加密，请先解密后再上传。")
            count = int(doc.page_count)
        except PdfError:
            raise
        except Exception as exc:
            raise PdfError("corrupt", f"PDF 无法读取页数（可能已损坏）：{exc}") from exc
        if count == 0:
            raise PdfError("corrupt", "PDF 不含任何页面。")
        if count > max_pages:
            raise PdfError(
                "too_many_pages",
                f"PDF 页数 {count} 超过上限 {max_pages}，请先拆分后再上传。",
            )
        return count
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Per-page + job state
# ---------------------------------------------------------------------------


@dataclass
class PageStatus:
    """Explainable status of one input page (AC3)."""

    page_index: int                # 0-based source order
    status: str = "pending"        # pending|processing|blank|duplicate|success|failed
    blank: bool = False
    low_information: bool = False
    document_id: str | None = None
    merged_into: int | None = None  # page_index of the representative (duplicate)
    title: str | None = None
    error: str | None = None
    markdown_len: int = 0

    def as_dict(self) -> dict:
        return {
            "page_index": self.page_index,
            "status": self.status,
            "blank": self.blank,
            "low_information": self.low_information,
            "document_id": self.document_id,
            "merged_into": self.merged_into,
            "title": self.title,
            "error": self.error,
            "markdown_len": self.markdown_len,
        }


@dataclass
class PdfJob:
    """State of one PDF upload task (durable via ``job.json``)."""

    pdf_id: str
    filename: str
    model: str = "glm-5.3-flash"
    status: str = "queued"          # queued|processing|done|failed
    error: str | None = None
    error_kind: str | None = None
    total_pages: int = 0
    pages: dict[int, PageStatus] = field(default_factory=dict)
    source_pdf_path: str | None = None
    work_dir: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    def set_page(self, ps: PageStatus) -> None:
        self.pages[ps.page_index] = ps

    def get_page(self, page_index: int) -> PageStatus | None:
        return self.pages.get(page_index)

    def counts(self) -> dict:
        c = {"success": 0, "failed": 0, "blank": 0, "duplicate": 0, "pending": 0}
        for ps in self.pages.values():
            c[ps.status] = c.get(ps.status, 0) + 1
        return c

    def public(self) -> dict:
        with self.lock:
            return {
                "pdf_id": self.pdf_id,
                "filename": self.filename,
                "model": self.model,
                "status": self.status,
                "error": self.error,
                "error_kind": self.error_kind,
                "total_pages": self.total_pages,
                # stable ordering: always by source page_index, never by the
                # (possibly out-of-order) async completion sequence (AC2).
                "pages": [self.pages[i].as_dict()
                          for i in sorted(self.pages)],
                "counts": self.counts(),
            }

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "pdf_id": self.pdf_id,
                "filename": self.filename,
                "model": self.model,
                "status": self.status,
                "error": self.error,
                "error_kind": self.error_kind,
                "total_pages": self.total_pages,
                "source_pdf_path": self.source_pdf_path,
                "work_dir": self.work_dir,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "pages": [self.pages[i].as_dict()
                          for i in sorted(self.pages)],
            }

    @classmethod
    def from_dict(cls, d: dict) -> "PdfJob":
        job = cls(pdf_id=d["pdf_id"], filename=d.get("filename", ""),
                  model=d.get("model", "glm-5.3-flash"))
        job.status = d.get("status", "queued")
        job.error = d.get("error")
        job.error_kind = d.get("error_kind")
        job.total_pages = d.get("total_pages", 0)
        job.source_pdf_path = d.get("source_pdf_path")
        job.work_dir = d.get("work_dir")
        job.started_at = d.get("started_at")
        job.finished_at = d.get("finished_at")
        for pd in d.get("pages", []):
            ps = PageStatus(
                page_index=pd["page_index"], status=pd.get("status", "pending"),
                blank=pd.get("blank", False),
                low_information=pd.get("low_information", False),
                document_id=pd.get("document_id"),
                merged_into=pd.get("merged_into"),
                title=pd.get("title"), error=pd.get("error"),
                markdown_len=pd.get("markdown_len", 0),
            )
            job.pages[ps.page_index] = ps
        return job


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def pdf_dir(store, pdf_id: str) -> Path:
    """Durable directory for one uploaded PDF (original + pages + job state)."""
    root = getattr(store, "root", None)
    if root is None:
        raise RuntimeError("document store has no filesystem root")
    return Path(root) / "pdfs" / pdf_id


def original_pdf_path(store, pdf_id: str) -> Path:
    """Path of the durable original PDF copy."""
    return pdf_dir(store, pdf_id) / "original.pdf"


def render_pdf_page(
    store, pdf_id: str, page_index: int, dpi: int = DEFAULT_DPI
) -> bytes:
    """Render one page of the durable original PDF to PNG bytes.

    Used by the Web "open the original PDF's page" view (AC2) and works from
    the durable copy alone, so it holds after a reload (AC5).
    """
    original = original_pdf_path(store, pdf_id)
    if not original.is_file():
        raise FileNotFoundError(f"original PDF missing: {original}")
    import pymupdf

    doc = pymupdf.open(str(original))
    try:
        if page_index < 0 or page_index >= doc.page_count:
            raise IndexError(f"page index out of range: {page_index}")
        return doc[page_index].get_pixmap(dpi=dpi).tobytes("png")
    finally:
        doc.close()


def save_job(job: PdfJob) -> Path:
    """Persist job state (source mapping survives a reload; AC5)."""
    d = Path(job.work_dir) if job.work_dir else Path(".")
    d.mkdir(parents=True, exist_ok=True)
    p = d / "job.json"
    p.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return p


def load_job(work_dir: str | Path) -> PdfJob | None:
    p = Path(work_dir) / "job.json"
    if not p.is_file():
        return None
    try:
        return PdfJob.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def process_pdf(
    job: PdfJob,
    *,
    pdf_bytes: bytes,
    store,
    router_factory=None,
    dedup_threshold: int = 6,
    dpi: int = DEFAULT_DPI,
    max_retries: int = 1,
    preprocess: bool = True,
    workers: int = 2,
) -> PdfJob:
    """Run the full chain: split -> cluster -> parse -> commit, updating ``job``.

    ``router_factory(image_path, model) -> RecognitionRouter`` is the injectable
    parse seam (offline tests pass a golden stub; production passes None and the
    real VLM gateway is used via :func:`pipeline.make_router`).
    """
    work_dir = pdf_dir(store, job.pdf_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    job.work_dir = str(work_dir)
    original = work_dir / "original.pdf"
    original.write_bytes(pdf_bytes)
    job.source_pdf_path = str(original)

    with job.lock:
        job.status = "processing"
        job.started_at = time.time()

    # 1) split (page images carry source_pdf + page_index + blank/low_info)
    pages: list[Page] = split_pdf(
        str(original), work_dir / "pages", dpi=dpi
    )
    job.total_pages = len(pages)

    # 2) within-PDF near-duplicate clustering (blank/low-info isolated).  The
    #    FIRST page of a duplicate group is the representative; later copies
    #    map to it (keep="first") so the earlier page stays the parse target.
    clusters = cluster_pages(
        pages, threshold=dedup_threshold, hash_method="phash", keep="first"
    )
    rep_by_index: dict[int, int] = {}
    for c in clusters:
        rep = c.representative
        for p in c.pages:
            rep_by_index[p.page_index] = rep.page_index

    # seed per-page status in source order
    for p in pages:
        status = "duplicate"
        merged_into = None
        if p.blank or p.low_information:
            status = "blank"
        elif rep_by_index.get(p.page_index, p.page_index) == p.page_index:
            status = "pending"  # will be parsed
            merged_into = None
        else:
            merged_into = rep_by_index[p.page_index]
        job.set_page(PageStatus(
            page_index=p.page_index, status=status,
            blank=p.blank, low_information=p.low_information,
            merged_into=merged_into,
        ))
    save_job(job)

    # 3) parse every unique (non-blank, representative) page.  Each page's
    #    outcome is recorded independently, so one failing page never discards
    #    the successful ones (AC4).  Ordering stays by page_index regardless of
    #    async completion order (AC2).
    to_parse = [p for p in pages if job.get_page(p.page_index).status == "pending"]

    import concurrent.futures

    def _parse_one(page: Page) -> tuple[int, dict]:
        ps = job.get_page(page.page_index)
        ps.status = "processing"
        doc_id = f"{job.pdf_id}-p{page.page_index + 1:03d}"
        out_dir = work_dir / "out" / f"p{page.page_index + 1:03d}"
        try:
            router = router_factory(str(page.path), job.model) \
                if router_factory is not None else None
            result = pipeline.parse_document(
                str(page.path), str(out_dir), model=job.model, router=router,
                doc_id=doc_id, preprocess=preprocess,
                save_preprocess_stages=True,
            )
            store.save_document(
                document_id=doc_id,
                title=f"{Path(job.filename).stem} · 第{page.page_index + 1}页",
                source_job_id=f"pdf-{job.pdf_id}",
                model=job.model,
                markdown=result.markdown,
                ir_json=dumps_ir(result.ir),
                original_path=str(page.path),
                original_ext=".jpg",
                preprocessed_path=result.preprocessed_path,
                preprocessed_raw_path=result.preprocessed_raw_path,
                assets_dir=result.assets_dir,
                timing_json=result.timing_json,
                pg_hash=page.pg_hash,
                source_pdf=page.source_pdf,
                pdf_id=job.pdf_id,
                page_index=page.page_index,
                page_number=page.page_number,
            )
            return page.page_index, {
                "status": "success", "document_id": doc_id,
                "title": f"{Path(job.filename).stem} · 第{page.page_index + 1}页",
                "markdown_len": len(result.markdown or ""),
            }
        except Exception as exc:
            return page.page_index, {"status": "failed", "error": str(exc)}

    if workers > 1 and len(to_parse) > 1:
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, workers)
        ) as ex:
            results = dict(ex.map(_parse_one, to_parse))
    else:
        results = dict(_parse_one(p) for p in to_parse)

    for idx, outcome in results.items():
        ps = job.get_page(idx)
        ps.status = outcome["status"]
        if outcome["status"] == "success":
            ps.document_id = outcome["document_id"]
            ps.title = outcome["title"]
            ps.markdown_len = outcome["markdown_len"]
        else:
            ps.error = outcome["error"]

    # duplicate pages resolve to their representative's document once known
    for ps in job.pages.values():
        if ps.status == "duplicate" and ps.merged_into is not None:
            rep = job.get_page(ps.merged_into)
            if rep is not None:
                ps.document_id = rep.document_id

    with job.lock:
        job.status = "done"
        job.finished_at = time.time()
    save_job(job)
    return job


__all__ = [
    "PdfError",
    "stable_pdf_id",
    "validate_pdf",
    "PageStatus",
    "PdfJob",
    "pdf_dir",
    "original_pdf_path",
    "render_pdf_page",
    "save_job",
    "load_job",
    "process_pdf",
    "ALLOWED_PDF_EXT",
    "MAX_PDF_SIZE",
    "MAX_PDF_PAGES",
    "DEFAULT_DPI",
]
