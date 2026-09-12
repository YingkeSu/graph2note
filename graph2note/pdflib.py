"""PDF upload -> split -> per-page parse -> document library (issues 08/09).

Reuses the issue-09 ingest surface (``split_pdf`` for page rendering with
traceable provenance, ``cluster_pages`` for within-PDF near-duplicate merging)
and the issue-03 parse pipeline (``pipeline.parse_document``) to turn a
user-uploaded PDF into *real* library documents — one per unique page — while
recording an explainable per-page status (success / failed / blank / duplicate)
and a durable source mapping (``pdf_id`` + ``page_index``) so a page document
can always be traced back to its page in the original PDF.

Issue 09 adds **durable, resumable batch processing**:

- every page attempt is written back to ``job.json`` as soon as it changes, so
  a page refresh or a process restart still shows accurate per-page status;
- a job whose persisted status is ``processing``/``queued`` but has no live
  worker is reconciled to ``interrupted`` and its in-flight pages become
  retryable;
- retry only re-parses pages that are not yet successful, and commits are
  idempotent (a page already committed for ``pdf_id``/``page_index`` is
  recognised from the document library, never re-parsed or versioned again);
- each page has explicit bounds — ``MAX_PAGE_ATTEMPTS`` attempts, a
  ``PAGE_TIMEOUT`` per attempt, and ``PDF_WORKERS`` concurrent pages.

Every model call goes through the same injectable ``router_factory`` seam used
by the single-image web path, so tests run fully offline and CI never touches
the network.  No secrets live here.
"""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .ingest import split_pdf, cluster_pages, pdf_available
from .ingest.model import Page
from .ir import dumps_ir
from . import autotag
from . import pipeline

# Limits (AC4: explicit file type / size / page-count limits).  PDFs are a
# NEW input type (FR-015's 10MB cap is JPG/JPEG/PNG-specific): a multi-page
# scan easily exceeds 10MB (the reference 21-page scan is ~10.9MB), so PDFs
# get their own, larger ceiling.
ALLOWED_PDF_EXT = {".pdf"}
MAX_PDF_SIZE = 50 * 1024 * 1024       # 50 MB
MAX_PDF_PAGES = 200                    # page-count ceiling
DEFAULT_DPI = 150

# issue 09: bounded, resumable batch processing.  A page is attempted at most
# ``MAX_PAGE_ATTEMPTS`` times; each attempt gets ``PAGE_TIMEOUT`` seconds; at
# most ``PDF_WORKERS`` pages are parsed concurrently.  The bounds are stored in
# ``job.json`` so a resumed job keeps the same limits (AC4).
PAGE_TIMEOUT = int(os.environ.get("GRAPH2NOTE_PDF_PAGE_TIMEOUT", "300"))
MAX_PAGE_ATTEMPTS = int(os.environ.get("GRAPH2NOTE_PDF_MAX_PAGE_ATTEMPTS", "2"))
PDF_WORKERS = int(os.environ.get("GRAPH2NOTE_PDF_WORKERS", "2"))

# Page states that are final: a page in one of these states never gets parsed
# again (success carries a committed document; blank/duplicate are non-docs).
TERMINAL_PAGE_STATUSES = ("success", "blank", "duplicate")
RETRYABLE_PAGE_STATUSES = ("pending", "failed")


class PdfError(RuntimeError):
    """Classified PDF upload error (actionable message for the Web UI)."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind  # wrong_type|too_large|too_many_pages|encrypted|corrupt|unreadable


def stable_pdf_id(data: bytes) -> str:
    """Stable identity of an uploaded PDF (content hash, AC2)."""
    return "pdf-" + hashlib.sha256(data).hexdigest()[:16]


def page_document_id(pdf_id: str, page_index: int) -> str:
    """Deterministic page-document id (stable across retries; AC3)."""
    return f"{pdf_id}-p{page_index + 1:03d}"


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
    """Explainable, durable status of one input page (AC3 + issue 09 AC1)."""

    page_index: int                # 0-based source order
    status: str = "pending"        # pending|processing|blank|duplicate|success|failed
    blank: bool = False
    low_information: bool = False
    document_id: str | None = None
    merged_into: int | None = None  # page_index of the representative (duplicate)
    title: str | None = None
    error: str | None = None
    error_kind: str | None = None  # parse|timeout|commit|interrupted|exhausted
    attempts: int = 0
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
            "error_kind": self.error_kind,
            "attempts": self.attempts,
            "markdown_len": self.markdown_len,
        }


@dataclass
class PdfJob:
    """State of one PDF upload task (durable via ``job.json``).

    ``status`` is ``queued|processing|done|failed|interrupted``.  A job loaded
    from disk whose persisted status was ``queued``/``processing`` is marked
    ``interrupted`` because no worker is running for it (issue 09 AC1).
    """

    pdf_id: str
    filename: str
    model: str = "glm-5.3-flash"
    status: str = "queued"          # queued|processing|done|failed|interrupted
    error: str | None = None
    error_kind: str | None = None
    total_pages: int = 0
    pages: dict[int, PageStatus] = field(default_factory=dict)
    source_pdf_path: str | None = None
    work_dir: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    # issue 09 bounds (persisted so a resumed job keeps them; AC4)
    max_page_attempts: int = MAX_PAGE_ATTEMPTS
    page_timeout: int = PAGE_TIMEOUT
    workers: int = PDF_WORKERS
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    save_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancelled: bool = field(default=False, repr=False)
    _running: bool = field(default=False, repr=False)

    def set_page(self, ps: PageStatus) -> None:
        self.pages[ps.page_index] = ps

    def get_page(self, page_index: int) -> PageStatus | None:
        return self.pages.get(page_index)

    def attempts_cap(self) -> int:
        return self.max_page_attempts or MAX_PAGE_ATTEMPTS

    def counts(self) -> dict:
        c = {"success": 0, "failed": 0, "blank": 0, "duplicate": 0, "pending": 0}
        for ps in self.pages.values():
            c[ps.status] = c.get(ps.status, 0) + 1
        return c

    def retryable_page_indexes(self) -> list[int]:
        """Pages that still need parsing and are under the attempt cap (AC2)."""
        cap = self.attempts_cap()
        with self.lock:
            return [
                i for i in sorted(self.pages)
                if self.pages[i].status in RETRYABLE_PAGE_STATUSES
                and self.pages[i].attempts < cap
            ]

    def exhausted_page_indexes(self) -> list[int]:
        cap = self.attempts_cap()
        with self.lock:
            return [
                i for i in sorted(self.pages)
                if self.pages[i].status == "failed"
                and self.pages[i].attempts >= cap
            ]

    def mark_interrupted(self) -> bool:
        """Reconcile a load-from-disk job with no live worker (issue 09 AC1)."""
        changed = False
        with self.lock:
            if self.status in ("queued", "processing"):
                self.status = "interrupted"
                self.error = self.error or "任务被中断（服务重启或进程退出），可重试未完成页。"
                self.error_kind = "interrupted"
                changed = True
            for ps in self.pages.values():
                if ps.status == "processing":
                    ps.status = "pending"
                    ps.error = ps.error or "上次尝试被中断，可重试。"
                    ps.error_kind = "interrupted"
                    changed = True
        return changed

    def public(self) -> dict:
        cap = self.attempts_cap()
        with self.lock:
            pages = []
            for i in sorted(self.pages):
                d = self.pages[i].as_dict()
                d["retryable"] = (
                    d["status"] in RETRYABLE_PAGE_STATUSES and d["attempts"] < cap
                )
                pages.append(d)
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
                "pages": pages,
                "counts": self.counts(),
                "retryable": any(p["retryable"] for p in pages),
                "exhausted": any(
                    p["status"] == "failed" and not p["retryable"] for p in pages
                ),
                "running": self._running,
                "interrupted": self.status == "interrupted",
                "max_page_attempts": cap,
                "page_timeout": self.page_timeout or PAGE_TIMEOUT,
                "workers": self.workers or PDF_WORKERS,
            }

    def summary(self) -> dict:
        """Lightweight job view for list/scope pickers (no per-page payload)."""
        with self.lock:
            return {
                "pdf_id": self.pdf_id,
                "filename": self.filename,
                "status": self.status,
                "total_pages": self.total_pages,
                "counts": self.counts(),
                "running": self._running,
                "interrupted": self.status == "interrupted",
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
                "max_page_attempts": self.max_page_attempts,
                "page_timeout": self.page_timeout,
                "workers": self.workers,
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
        job.max_page_attempts = d.get("max_page_attempts", MAX_PAGE_ATTEMPTS)
        job.page_timeout = d.get("page_timeout", PAGE_TIMEOUT)
        job.workers = d.get("workers", PDF_WORKERS)
        for pd in d.get("pages", []):
            ps = PageStatus(
                page_index=pd["page_index"], status=pd.get("status", "pending"),
                blank=pd.get("blank", False),
                low_information=pd.get("low_information", False),
                document_id=pd.get("document_id"),
                merged_into=pd.get("merged_into"),
                title=pd.get("title"), error=pd.get("error"),
                error_kind=pd.get("error_kind"),
                attempts=pd.get("attempts", 0),
                markdown_len=pd.get("markdown_len", 0),
            )
            job.pages[ps.page_index] = ps
        return job


# ---------------------------------------------------------------------------
# Durable storage helpers
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
    """Persist job state (source mapping + per-page checkpoint survive reload).

    ``save_lock`` serialises writers so concurrent page workers can never
    interleave two partial ``job.json`` writes (issue 09 AC1/AC5).
    """
    with job.save_lock:
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


def load_jobs(store, *, mark_interrupted: bool = True) -> list[PdfJob]:
    """Load every durable PDF job under the store (used on app startup/reload).

    Jobs whose persisted status was ``queued``/``processing`` have no live
    worker after a restart, so they are reconciled to ``interrupted`` (AC1).
    """
    root = getattr(store, "root", None)
    if root is None:
        return []
    base = Path(root) / "pdfs"
    if not base.is_dir():
        return []
    jobs: list[PdfJob] = []
    for job_file in sorted(base.glob("*/job.json")):
        job = load_job(job_file.parent)
        if job is None:
            continue
        if mark_interrupted:
            job.mark_interrupted()
        jobs.append(job)
    return jobs


def committed_document_id(store, pdf_id: str, page_index: int) -> str | None:
    """Return the committed page-document id if this page is already in the library.

    Idempotency seam (issue 09 AC2/AC5): a page document id is deterministic
    (``{pdf_id}-pNNN``), so a commit that landed before the status update was
    persisted is recognised and never parsed or versioned a second time.
    """
    doc_id = page_document_id(pdf_id, page_index)
    try:
        rec = store.get_document(doc_id)
    except Exception:
        return None
    if not rec:
        return None
    if rec.get("pdf_id") not in (None, pdf_id):
        return None
    if rec.get("page_index") not in (None, page_index):
        return None
    return doc_id


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _seed_pages(
    job: PdfJob, pages: list[Page], rep_by_index: dict[int, int]
) -> None:
    """Seed per-page status in source order, preserving prior progress.

    Pages already recorded (success/failed/duplicate/blank) keep their status
    and attempt count so a resume never throws away finished work (AC2).
    """
    total = len(pages)
    for p in pages:
        existing = job.pages.get(p.page_index)
        if existing is not None:
            existing.blank = p.blank
            existing.low_information = p.low_information
            continue
        status = "duplicate"
        merged_into = None
        if p.blank or p.low_information:
            status = "blank"
        elif rep_by_index.get(p.page_index, p.page_index) == p.page_index:
            status = "pending"  # will be parsed
        else:
            merged_into = rep_by_index[p.page_index]
        job.set_page(PageStatus(
            page_index=p.page_index, status=status,
            blank=p.blank, low_information=p.low_information,
            merged_into=merged_into,
        ))
    # a page beyond the (stable) split is impossible; drop stale entries only if
    # the PDF somehow changed for the same content hash (defensive, no-op).
    job.total_pages = total


def _apply_outcome(job: PdfJob, page_index: int, outcome: dict) -> None:
    """Record a finished page attempt and checkpoint it to disk (AC1)."""
    with job.lock:
        ps = job.pages[page_index]
        status = outcome.get("status")
        if status == "success":
            ps.status = "success"
            ps.document_id = outcome.get("document_id")
            ps.title = outcome.get("title")
            ps.markdown_len = outcome.get("markdown_len", 0)
            ps.error = None
            ps.error_kind = None
        elif status == "timeout":
            ps.status = "failed"
            ps.error = outcome.get(
                "error",
                f"单页解析超时（超过 {job.page_timeout or PAGE_TIMEOUT} 秒），可重试。",
            )
            ps.error_kind = "timeout"
        else:
            ps.status = "failed"
            ps.error = outcome.get("error") or "解析失败。"
            ps.error_kind = outcome.get("error_kind") or "parse"
    save_job(job)


def _mark_timeout(job: PdfJob, page_index: int) -> None:
    with job.lock:
        ps = job.pages[page_index]
        if ps.status == "success":
            return
        ps.status = "failed"
        ps.error = (
            f"单页解析超时（超过 {job.page_timeout or PAGE_TIMEOUT} 秒），"
            f"已尝试 {ps.attempts}/{job.attempts_cap()} 次。"
        )
        ps.error_kind = "timeout"
    save_job(job)


def _run_attempts(
    job: PdfJob,
    pages: list[Page],
    *,
    work_dir: Path,
    store,
    router_factory,
    preprocess: bool,
    workers: int,
    page_timeout: int,
    auto_tag_inferrer=None,
) -> None:
    """Parse the retryable pages with bounded concurrency, timeout and attempts."""
    to_parse = [p for p in pages if p.page_index in set(job.retryable_page_indexes())]
    if not to_parse:
        return

    sem = threading.BoundedSemaphore(max(1, workers))
    outcomes: "queue.Queue" = queue.Queue()
    cancels = {p.page_index: threading.Event() for p in to_parse}

    def _parse_one(page: Page) -> dict:
        idx = page.page_index
        doc_id = page_document_id(job.pdf_id, idx)
        # idempotent recovery: a commit that landed before the status was
        # persisted is recognised without a second model call (AC2/AC5).
        if committed_document_id(store, job.pdf_id, idx):
            return {"status": "success", "document_id": doc_id,
                    "title": _page_title(job, idx), "markdown_len": 0,
                    "recovered": True}
        out_dir = work_dir / "out" / f"p{idx + 1:03d}"
        title = _page_title(job, idx)
        router = router_factory(str(page.path), job.model) \
            if router_factory is not None else None
        result = pipeline.parse_document(
            str(page.path), str(out_dir), model=job.model, router=router,
            doc_id=doc_id, preprocess=preprocess,
            save_preprocess_stages=True,
        )
        if cancels[idx].is_set():
            # timed out while parsing; do not write, the page stays retryable
            return {"status": "timeout"}
        store.save_document(
            document_id=doc_id,
            title=title,
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
            page_index=idx,
            page_number=page.page_number,
        )
        # A1: PDF page commit runs the same post-ingest auto-tag hook as the
        # single-image path.  Inference failure is recorded, never blocking.
        autotag.after_ingest(
            store, doc_id, result.markdown, inferrer=auto_tag_inferrer,
        )
        return {"status": "success", "document_id": doc_id, "title": title,
                "markdown_len": len(result.markdown or "")}

    def _runner(page: Page) -> None:
        idx = page.page_index
        with sem:
            if cancels[idx].is_set():
                outcomes.put((idx, "cancelled"))
                return
            outcomes.put((idx, "started", time.time()))
            try:
                outcome = _parse_one(page)
            except Exception as exc:
                outcome = {"status": "failed", "error": str(exc),
                           "error_kind": "parse"}
        outcomes.put((idx, "finished", outcome))

    threads = [threading.Thread(target=_runner, args=(p,), daemon=True)
               for p in to_parse]
    for t in threads:
        t.start()

    started: dict[int, float] = {}
    finished: set[int] = set()
    remaining = len(to_parse)
    while remaining > 0:
        now = time.time()
        for idx, start in list(started.items()):
            if idx in finished:
                continue
            if now - start > page_timeout and not cancels[idx].is_set():
                cancels[idx].set()
                _mark_timeout(job, idx)
                finished.add(idx)
                remaining -= 1
        try:
            msg = outcomes.get(timeout=0.05)
        except queue.Empty:
            continue
        kind = msg[1]
        if kind == "started":
            idx = msg[0]
            started[idx] = msg[2]
            with job.lock:
                ps = job.pages[idx]
                ps.status = "processing"
                ps.attempts += 1
                ps.error = None
                ps.error_kind = None
                ps.document_id = None
            save_job(job)
        elif kind == "finished":
            idx, outcome = msg[0], msg[2]
            if idx not in finished:
                _apply_outcome(job, idx, outcome)
                finished.add(idx)
                remaining -= 1
        else:  # cancelled (never started)
            idx = msg[0]
            if idx not in finished:
                finished.add(idx)
                remaining -= 1
    for t in threads:
        t.join(timeout=5)

    # duplicate pages resolve to their representative's document once known
    with job.lock:
        for ps in job.pages.values():
            if ps.status == "duplicate" and ps.merged_into is not None:
                rep = job.pages.get(ps.merged_into)
                if rep is not None:
                    ps.document_id = rep.document_id


def _page_title(job: PdfJob, page_index: int) -> str:
    return f"{Path(job.filename).stem} · 第{page_index + 1}页"


def process_pdf(
    job: PdfJob,
    *,
    pdf_bytes: bytes | None = None,
    store,
    router_factory=None,
    dedup_threshold: int = 6,
    dpi: int = DEFAULT_DPI,
    max_retries: int = 1,
    preprocess: bool = True,
    workers: int | None = None,
    page_timeout: int | None = None,
    max_page_attempts: int | None = None,
    auto_tag_inferrer=None,
) -> PdfJob:
    """Run/resume the chain: split -> cluster -> parse -> commit, updating ``job``.

    ``router_factory(image_path, model) -> RecognitionRouter`` is the injectable
    parse seam (offline tests pass a golden stub; production passes None and the
    real VLM gateway is used via :func:`pipeline.make_router`).

    A resumable call may pass ``pdf_bytes=None``: the durable ``original.pdf``
    is then reused and only pages that are not yet successful are attempted
    (issue 09 AC2).  Pages already committed for ``pdf_id``/``page_index`` are
    recognised as success and are neither re-parsed nor re-versioned.
    """
    work_dir = pdf_dir(store, job.pdf_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    job.work_dir = str(work_dir)
    original = work_dir / "original.pdf"
    if pdf_bytes is not None:
        original.write_bytes(pdf_bytes)
    elif not original.is_file():
        with job.lock:
            job.status = "failed"
            job.error = "原 PDF 缺失，无法恢复任务。"
            job.error_kind = "failed"
            job.finished_at = time.time()
        save_job(job)
        return job
    job.source_pdf_path = str(original)

    workers = workers or job.workers or PDF_WORKERS
    page_timeout = page_timeout or job.page_timeout or PAGE_TIMEOUT
    max_page_attempts = max_page_attempts or job.max_page_attempts or MAX_PAGE_ATTEMPTS
    job.workers = workers
    job.page_timeout = page_timeout
    job.max_page_attempts = max_page_attempts

    with job.lock:
        job.status = "processing"
        job.error = None
        job.error_kind = None
        job._cancelled = False
        if job.started_at is None:
            job.started_at = time.time()
    save_job(job)

    # 1) split + within-PDF near-duplicate clustering (blank/low-info isolated).
    #    Re-running is deterministic for the same bytes; existing page statuses
    #    are preserved so a resume does not lose finished pages (AC2).
    try:
        pages: list[Page] = split_pdf(
            str(original), work_dir / "pages", dpi=dpi
        )
    except Exception as exc:
        with job.lock:
            job.status = "failed"
            job.error = f"PDF 拆页失败：{exc}"
            job.error_kind = "failed"
            job.finished_at = time.time()
        save_job(job)
        return job

    clusters = cluster_pages(
        pages, threshold=dedup_threshold, hash_method="phash", keep="first"
    )
    rep_by_index: dict[int, int] = {}
    for c in clusters:
        rep = c.representative
        for p in c.pages:
            rep_by_index[p.page_index] = rep.page_index

    _seed_pages(job, pages, rep_by_index)

    # 2) reconcile pages that already have a committed document (a crash after
    #    the disk write but before the status update): mark success, no re-parse.
    for ps in list(job.pages.values()):
        if ps.status in TERMINAL_PAGE_STATUSES:
            continue
        doc_id = committed_document_id(store, job.pdf_id, ps.page_index)
        if doc_id:
            with job.lock:
                ps.status = "success"
                ps.document_id = doc_id
                ps.title = ps.title or _page_title(job, ps.page_index)
                ps.error = None
                ps.error_kind = None
    save_job(job)

    # 3) attempt only pages that are not yet successful and are under the cap.
    _run_attempts(
        job, pages, work_dir=work_dir, store=store,
        router_factory=router_factory, preprocess=preprocess,
        workers=workers, page_timeout=page_timeout,
        auto_tag_inferrer=auto_tag_inferrer,
    )

    # 4) finalise: 'done' even with per-page failures (issue 08 AC4); exhausted
    #    pages are reported and stop further automatic retries (issue 09 AC4).
    exhausted = job.exhausted_page_indexes()
    with job.lock:
        job.status = "done"
        job.finished_at = time.time()
        if exhausted:
            job.error = (
                f"{len(exhausted)} 页在 {job.attempts_cap()} 次尝试后仍未成功，"
                f"已停止自动重试。"
            )
            job.error_kind = "partial"
    save_job(job)
    return job


__all__ = [
    "PdfError",
    "stable_pdf_id",
    "page_document_id",
    "validate_pdf",
    "PageStatus",
    "PdfJob",
    "pdf_dir",
    "original_pdf_path",
    "render_pdf_page",
    "save_job",
    "load_job",
    "load_jobs",
    "committed_document_id",
    "process_pdf",
    "ALLOWED_PDF_EXT",
    "MAX_PDF_SIZE",
    "MAX_PDF_PAGES",
    "DEFAULT_DPI",
    "PAGE_TIMEOUT",
    "MAX_PAGE_ATTEMPTS",
    "PDF_WORKERS",
    "TERMINAL_PAGE_STATUSES",
    "RETRYABLE_PAGE_STATUSES",
]
