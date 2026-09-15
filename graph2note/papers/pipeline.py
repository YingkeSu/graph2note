"""Paper PDF import pipeline (SPW I-track / P1).

The chain is: **validate → text-layer direct extraction → deterministic section
splitting → library commit**, with an automatic fallback to the existing VLM
per-page path for scanned (no text layer) PDFs.

Design points:

- the text-layer path never touches the model: no router is constructed and no
  gateway call happens (issue AC1/AC3);
- the fallback path reuses :func:`graph2note.pdflib.process_pdf` **unchanged**
  (size/page limits, per-page attempts/timeouts, idempotent page commits and
  job recovery all come from issue 08/09 — nothing is copied here).  Its model
  seam is the injectable ``router_factory``, so CI never touches the network;
- the original PDF lives at ``pdflib``'s durable location
  (``<root>/pdfs/<pdf_id>/original.pdf``) and the paper job state at
  ``<root>/papers/<pdf_id>/job.json``, so a reload can reconcile and resume;
- the committed document carries ``doc_kind="paper"`` plus the SPEC §2 paper
  payload (sections + full text + page map + empty P2 meta/reference slots).
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from .. import pdflib
from ..ir import DocumentIR, dumps_ir
from . import model, structure, textlayer

#: Sub-directory (under the store root) holding paper job state.
PAPERS_DIRNAME = "papers"

#: Suffix of the paper-level document id (page documents use ``-pNNN``).
PAPER_DOC_SUFFIX = "-paper"

#: Model label recorded for the deterministic text-layer commit (no model ran).
TEXT_LAYER_MODEL = "text-layer"

#: Wall-clock budget for one paper job (watchdog only; the VLM fallback has its
#: own per-page bounds inside ``pdflib``).
PAPER_JOB_TIMEOUT = int(
    os.environ.get(
        "GRAPH2NOTE_PAPER_JOB_TIMEOUT",
        str(pdflib.PAGE_TIMEOUT * 20),
    )
)

#: How many times one paper job may be (re)started before it reports exhausted.
MAX_PAPER_ATTEMPTS = int(os.environ.get("GRAPH2NOTE_PAPER_MAX_ATTEMPTS", "2"))

_POOL = concurrent.futures.ThreadPoolExecutor(
    max_workers=int(os.environ.get("GRAPH2NOTE_PAPER_WORKERS", "2")),
    thread_name_prefix="paper",
)


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def paper_id_for_pdf(pdf_id: str) -> str:
    """A paper job shares the PDF's content identity (issue 08/09 mapping)."""
    return pdf_id


def paper_document_id(pdf_id: str) -> str:
    """Deterministic paper-document id (stable across retries/re-uploads)."""
    return f"{pdf_id}{PAPER_DOC_SUFFIX}"


def stable_paper_id(data: bytes) -> str:
    """Stable content identity of an uploaded paper PDF (reuses ``pdflib``)."""
    return paper_id_for_pdf(pdflib.stable_pdf_id(data))


def validate_paper(data: bytes, filename: str, **kwargs) -> int:
    """Validate an uploaded paper PDF; return its page count.

    Thin, semantics-preserving wrapper over :func:`pdflib.validate_pdf` so the
    Web layer gets the same ``PdfError`` kinds (wrong_type/too_large/
    too_many_pages/encrypted/corrupt/unreadable) for papers.
    """
    return pdflib.validate_pdf(data, filename, **kwargs)


# ---------------------------------------------------------------------------
# Job state (durable, mirrors the issue-09 PDF job semantics)
# ---------------------------------------------------------------------------


@dataclass
class PaperJob:
    """State of one paper import task (durable via ``job.json``)."""

    paper_id: str
    filename: str
    status: str = "queued"          # queued|processing|done|failed|interrupted
    source: str | None = None       # text-layer|vlm (set when the run finishes)
    document_id: str | None = None
    error: str | None = None
    error_kind: str | None = None   # parse|timeout|interrupted|vlm_empty|partial|failed
    total_pages: int = 0
    sections_count: int = 0
    page_documents: list[str] = field(default_factory=list)
    decision: dict = field(default_factory=dict)
    model: str = ""
    attempts: int = 0
    max_attempts: int = MAX_PAPER_ATTEMPTS
    started_at: float | None = None
    finished_at: float | None = None
    source_pdf_path: str | None = None
    work_dir: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    save_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancelled: bool = field(default=False, repr=False)
    _running: bool = field(default=False, repr=False)

    def attempts_cap(self) -> int:
        return self.max_attempts or MAX_PAPER_ATTEMPTS

    def mark_interrupted(self) -> bool:
        """Reconcile a load-from-disk job with no live worker (issue 09 AC1)."""
        changed = False
        with self.lock:
            if self.status in ("queued", "processing"):
                self.status = "interrupted"
                self.error = self.error or "任务被中断（服务重启或进程退出），可重试。"
                self.error_kind = "interrupted"
                changed = True
        return changed

    def public(self) -> dict:
        with self.lock:
            return {
                "paper_id": self.paper_id,
                "pdf_id": self.paper_id,
                "filename": self.filename,
                "status": self.status,
                "source": self.source,
                "document_id": self.document_id,
                "total_pages": self.total_pages,
                "sections": self.sections_count,
                "page_documents": list(self.page_documents),
                "decision": dict(self.decision),
                "error": self.error,
                "error_kind": self.error_kind,
                "running": self._running,
                "interrupted": self.status == "interrupted",
                "attempts": self.attempts,
                "max_attempts": self.attempts_cap(),
            }

    def summary(self) -> dict:
        """Lightweight job view for list pickers (no per-section payload)."""
        with self.lock:
            return {
                "paper_id": self.paper_id,
                "pdf_id": self.paper_id,
                "filename": self.filename,
                "status": self.status,
                "source": self.source,
                "document_id": self.document_id,
                "total_pages": self.total_pages,
                "sections": self.sections_count,
                "running": self._running,
                "interrupted": self.status == "interrupted",
            }

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "paper_id": self.paper_id,
                "filename": self.filename,
                "status": self.status,
                "source": self.source,
                "document_id": self.document_id,
                "error": self.error,
                "error_kind": self.error_kind,
                "total_pages": self.total_pages,
                "sections_count": self.sections_count,
                "page_documents": list(self.page_documents),
                "decision": dict(self.decision),
                "model": self.model,
                "attempts": self.attempts,
                "max_attempts": self.max_attempts,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "source_pdf_path": self.source_pdf_path,
                "work_dir": self.work_dir,
            }

    @classmethod
    def from_dict(cls, data: dict) -> "PaperJob":
        job = cls(
            paper_id=data["paper_id"],
            filename=data.get("filename", ""),
            status=data.get("status", "queued"),
        )
        job.source = data.get("source")
        job.document_id = data.get("document_id")
        job.error = data.get("error")
        job.error_kind = data.get("error_kind")
        job.total_pages = data.get("total_pages", 0)
        job.sections_count = data.get("sections_count", 0)
        job.page_documents = list(data.get("page_documents") or [])
        job.decision = dict(data.get("decision") or {})
        job.model = data.get("model", "")
        job.attempts = data.get("attempts", 0)
        job.max_attempts = data.get("max_attempts", MAX_PAPER_ATTEMPTS)
        job.started_at = data.get("started_at")
        job.finished_at = data.get("finished_at")
        job.source_pdf_path = data.get("source_pdf_path")
        job.work_dir = data.get("work_dir")
        return job


# ---------------------------------------------------------------------------
# Durable storage helpers (paper jobs live beside ``pdflib``'s pdf storage)
# ---------------------------------------------------------------------------


def paper_dir(store, paper_id: str) -> Path:
    root = getattr(store, "root", None)
    if root is None:
        raise RuntimeError("document store has no filesystem root")
    return Path(root) / PAPERS_DIRNAME / paper_id


def save_job(job: PaperJob) -> Path:
    """Persist job state (survives a reload; serialises concurrent writers)."""
    with job.save_lock:
        directory = Path(job.work_dir) if job.work_dir else Path(".")
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "job.json"
        path.write_text(
            json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


def load_job(work_dir: str | Path) -> PaperJob | None:
    path = Path(work_dir) / "job.json"
    if not path.is_file():
        return None
    try:
        return PaperJob.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def load_jobs(store, *, mark_interrupted: bool = True) -> list[PaperJob]:
    """Load every durable paper job under the store (app startup/reload)."""
    root = getattr(store, "root", None)
    if root is None:
        return []
    base = Path(root) / PAPERS_DIRNAME
    if not base.is_dir():
        return []
    jobs: list[PaperJob] = []
    for job_file in sorted(base.glob("*/job.json")):
        job = load_job(job_file.parent)
        if job is None:
            continue
        if mark_interrupted:
            job.mark_interrupted()
        jobs.append(job)
    return jobs


# ---------------------------------------------------------------------------
# Rendering / payload assembly
# ---------------------------------------------------------------------------


def render_paper_markdown(title: str, sections: list[model.PaperSection]) -> str:
    """Deterministic Markdown for the library document (doc title + sections)."""
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    for section in sections:
        if section.title:
            parts.append(f"{'#' * min(section.level + 1, 6)} {section.title}")
        if section.text:
            parts.append(section.text)
    return "\n\n".join(parts).strip() + "\n"


def build_page_map(layer: textlayer.TextLayer) -> list[model.PaperPage]:
    return [
        model.PaperPage(
            page_index=page.page_index,
            page_number=page.page_index + 1,
            char_count=page.char_count,
        )
        for page in layer.pages
    ]


def _empty_ir_json() -> str:
    """Canonical empty IR for a text-layer paper (no diagram/VLM blocks)."""
    return dumps_ir(DocumentIR(blocks=[]))


def result_payload(job: PaperJob, store) -> dict | None:
    """Read-only paper result built from the job + committed store payload."""
    if not job.document_id:
        return None
    payload = store.get_paper_payload(job.document_id)
    if payload is None:
        return None
    document_id = job.document_id
    paper_id = job.paper_id
    return {
        "paper_id": paper_id,
        "pdf_id": paper_id,
        "document_id": document_id,
        "status": job.status,
        "doc_kind": model.PAPER_DOC_KIND,
        "source": payload.get("source") or job.source,
        "sections": payload.get("sections") or [],
        "pages": payload.get("page_map") or [],
        "fulltext": payload.get("fulltext") or "",
        "meta": payload.get("meta") or {},
        "references": payload.get("references") or [],
        "provenance": payload.get("provenance") or {},
        "source_page_url": f"/api/documents/{quote(document_id, safe='')}/source-page",
        "original_url": f"/api/papers/{quote(paper_id, safe='')}/original",
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _fail(job: PaperJob, message: str, kind: str) -> PaperJob:
    with job.lock:
        job.status = "failed"
        job.error = message
        job.error_kind = kind
        job.finished_at = time.time()
    save_job(job)
    return job


def _commit_text_layer(
    job: PaperJob,
    *,
    store,
    layer: textlayer.TextLayer,
    sections: list[model.PaperSection],
    decision: textlayer.TextLayerDecision,
    title: str,
) -> PaperJob:
    document_id = job.document_id or paper_document_id(job.paper_id)
    payload = model.PaperPayload(
        source="text-layer",
        sections=sections,
        fulltext=layer.fulltext,
        page_map=build_page_map(layer),
        meta=model.PaperMeta(),
        references=[],
        provenance=model.PaperProvenance(
            source="text-layer",
            pdf_id=job.paper_id,
            source_pdf=job.source_pdf_path or "",
            page_count=layer.page_count,
            sections=len(sections),
            decision=decision.as_dict(),
        ),
    )
    store.save_paper_document(
        document_id=document_id,
        title=title,
        markdown=render_paper_markdown(title, sections),
        paper=payload.as_dict(),
        source_job_id=f"paper-{job.paper_id}",
        model=TEXT_LAYER_MODEL,
        ir_json=_empty_ir_json(),
        original_path=job.source_pdf_path,
        original_ext=".pdf",
        preprocessed_path=None,
        preprocessed_raw_path=None,
        assets_dir=None,
        timing_json={
            "stage": "paper",
            "source": "text-layer",
            "pages": layer.page_count,
            "sections": len(sections),
        },
        source_pdf=job.source_pdf_path,
        pdf_id=job.paper_id,
        page_index=0,
        page_number=1,
        provenance="paper-text-layer",
        provenance_detail={
            "source": "text-layer",
            "pdf_id": job.paper_id,
            "sections": len(sections),
            "decision": decision.as_dict(),
        },
    )
    with job.lock:
        job.status = "done"
        job.source = "text-layer"
        job.document_id = document_id
        job.total_pages = layer.page_count
        job.sections_count = len(sections)
        job.decision = decision.as_dict()
        job.error = None
        job.error_kind = None
        job.finished_at = time.time()
    save_job(job)
    return job


def _page_document_markdown(store, document_id: str | None) -> str:
    if not document_id:
        return ""
    try:
        record = store.get_document(document_id)
    except Exception:
        return ""
    if not record:
        return ""
    markdown = record.get("current_markdown")
    if markdown is None:
        markdown = record.get("markdown")
    return markdown or ""


def _commit_vlm_fallback(
    job: PaperJob,
    *,
    store,
    pdf_job: pdflib.PdfJob,
    decision: textlayer.TextLayerDecision,
    title: str,
) -> PaperJob:
    pages = [pdf_job.pages[i] for i in sorted(pdf_job.pages)]
    successful = [ps for ps in pages if ps.status == "success" and ps.document_id]

    skipped: list[dict] = []
    for ps in pages:
        if ps.status == "success" and ps.document_id:
            continue
        skipped.append({
            "page_index": ps.page_index,
            "page_number": ps.page_index + 1,
            "status": ps.status,
            "error": ps.error,
        })

    if not successful:
        return _fail(
            job,
            "扫描版论文回退 VLM 逐页解析后没有可用页面，请检查 PDF 或稍后重试。",
            "vlm_empty",
        )

    sections: list[model.PaperSection] = []
    for ps in successful:
        text = _page_document_markdown(store, ps.document_id)
        sections.append(model.PaperSection(
            level=1,
            title=ps.title or f"{Path(job.filename).stem} · 第{ps.page_index + 1}页",
            text=text,
            page_start=ps.page_index,
            page_end=ps.page_index,
        ))

    document_id = job.document_id or paper_document_id(job.paper_id)
    fulltext = "\n\n".join(section.text for section in sections).strip()
    payload = model.PaperPayload(
        source="vlm",
        sections=sections,
        fulltext=fulltext,
        page_map=[
            model.PaperPage(
                page_index=ps.page_index,
                page_number=ps.page_index + 1,
                char_count=textlayer.count_chars(section.text),
            )
            for ps, section in zip(successful, sections)
        ],
        meta=model.PaperMeta(),
        references=[],
        provenance=model.PaperProvenance(
            source="vlm",
            pdf_id=job.paper_id,
            source_pdf=job.source_pdf_path or "",
            page_count=pdf_job.total_pages,
            sections=len(sections),
            decision=decision.as_dict(),
            page_document_ids=[ps.document_id for ps in successful],
            skipped_pages=skipped,
        ),
    )
    store.save_paper_document(
        document_id=document_id,
        title=title,
        markdown=render_paper_markdown(title, sections),
        paper=payload.as_dict(),
        source_job_id=f"paper-{job.paper_id}",
        model=pdf_job.model or TEXT_LAYER_MODEL,
        ir_json=_empty_ir_json(),
        original_path=job.source_pdf_path,
        original_ext=".pdf",
        preprocessed_path=None,
        preprocessed_raw_path=None,
        assets_dir=None,
        timing_json={
            "stage": "paper",
            "source": "vlm",
            "pages": pdf_job.total_pages,
            "sections": len(sections),
        },
        source_pdf=job.source_pdf_path,
        pdf_id=job.paper_id,
        page_index=0,
        page_number=1,
        provenance="paper-vlm-fallback",
        provenance_detail={
            "source": "vlm",
            "pdf_id": job.paper_id,
            "pages": len(successful),
            "skipped_pages": len(skipped),
            "decision": decision.as_dict(),
        },
    )
    with job.lock:
        job.source = "vlm"
        job.document_id = document_id
        job.total_pages = pdf_job.total_pages
        job.sections_count = len(sections)
        job.decision = decision.as_dict()
        job.page_documents = [ps.document_id for ps in successful]
        job.status = "done"
        if skipped:
            job.error = (
                f"{len(skipped)} 页未产出文本（空白/重复/失败），已跳过并记录 provenance。"
            )
            job.error_kind = "partial"
        else:
            job.error = None
            job.error_kind = None
        job.finished_at = time.time()
    save_job(job)
    return job


def _load_or_create_pdf_job(store, job: PaperJob) -> pdflib.PdfJob:
    """Reuse the durable issue-09 PDF job for the same content hash."""
    try:
        work_dir = pdflib.pdf_dir(store, job.paper_id)
    except RuntimeError:
        work_dir = None
    existing = pdflib.load_job(work_dir) if work_dir else None
    if existing is not None:
        existing.mark_interrupted()
        if job.model:
            existing.model = job.model
        return existing
    pdf_job = pdflib.PdfJob(pdf_id=job.paper_id, filename=job.filename)
    if job.model:
        pdf_job.model = job.model
    return pdf_job


def process_paper(
    job: PaperJob,
    *,
    pdf_bytes: bytes | None = None,
    store,
    router_factory=None,
    dpi: int = pdflib.DEFAULT_DPI,
    preprocess: bool = True,
    workers: int | None = None,
    page_timeout: int | None = None,
    max_page_attempts: int | None = None,
    auto_tag_inferrer=None,
    model: str | None = None,
    title: str | None = None,
) -> PaperJob:
    """Run/resume one paper import, updating ``job`` in place.

    ``router_factory(image_path, model) -> RecognitionRouter`` is only used by
    the VLM fallback (a scanned PDF); the text-layer path never builds a router.
    A resume may pass ``pdf_bytes=None``: the durable original PDF and the
    existing page documents are reused (issue 09 semantics).
    """
    work_dir = paper_dir(store, job.paper_id)
    work_dir.mkdir(parents=True, exist_ok=True)
    job.work_dir = str(work_dir)
    job.source_pdf_path = str(pdflib.original_pdf_path(store, job.paper_id))
    original = Path(job.source_pdf_path)
    if pdf_bytes is not None:
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(pdf_bytes)
    elif not original.is_file():
        return _fail(job, "原 PDF 缺失，无法恢复任务。", "failed")

    document_title = title or Path(job.filename).stem or job.paper_id
    if model:
        job.model = model
    with job.lock:
        job.status = "processing"
        job.error = None
        job.error_kind = None
        job._cancelled = False
        job.attempts += 1
        if job.started_at is None:
            job.started_at = time.time()
    save_job(job)

    try:
        # 1) text layer first: born-digital papers never reach the VLM.
        layer = textlayer.read_text_layer(original)
        decision = textlayer.decide_text_layer(layer)
        with job.lock:
            job.total_pages = layer.page_count
            job.decision = decision.as_dict()
        save_job(job)

        if decision.use_text_layer:
            sections = structure.split_sections(layer.lines)
            return _commit_text_layer(
                job, store=store, layer=layer, sections=sections,
                decision=decision, title=document_title,
            )

        # 2) no usable text layer -> reuse the issue-08/09 VLM page path.
        pdf_job = _load_or_create_pdf_job(store, job)
        pdf_job.filename = pdf_job.filename or job.filename
        pdf_job.model = job.model or pdf_job.model
        pdflib.process_pdf(
            pdf_job,
            pdf_bytes=None,  # original.pdf is already durable
            store=store,
            router_factory=router_factory,
            dpi=dpi,
            preprocess=preprocess,
            workers=workers,
            page_timeout=page_timeout,
            max_page_attempts=max_page_attempts,
            auto_tag_inferrer=auto_tag_inferrer,
        )
        return _commit_vlm_fallback(
            job, store=store, pdf_job=pdf_job, decision=decision,
            title=document_title,
        )
    except pdflib.PdfError as exc:
        return _fail(job, str(exc), exc.kind)
    except Exception as exc:  # never present a failure as a clean run
        return _fail(job, f"论文导入失败：{exc}", "parse")


# ---------------------------------------------------------------------------
# Background runner (single-flight; mirrors the Web PDF runner semantics)
# ---------------------------------------------------------------------------


def start_job(
    job: PaperJob,
    *,
    store,
    pdf_bytes: bytes | None = None,
    router_factory=None,
    dpi: int = pdflib.DEFAULT_DPI,
    preprocess: bool = True,
    workers: int | None = None,
    page_timeout: int | None = None,
    max_page_attempts: int | None = None,
    auto_tag_inferrer=None,
    model: str | None = None,
    title: str | None = None,
    timeout: int | None = None,
) -> bool:
    """Start/resume one paper job in the background; False if already running."""
    with job.lock:
        if job._running:
            return False
        job._running = True

    def _run() -> None:
        process_paper(
            job,
            pdf_bytes=pdf_bytes,
            store=store,
            router_factory=router_factory,
            dpi=dpi,
            preprocess=preprocess,
            workers=workers,
            page_timeout=page_timeout,
            max_page_attempts=max_page_attempts,
            auto_tag_inferrer=auto_tag_inferrer,
            model=model,
            title=title,
        )

    def _wrapper() -> None:
        try:
            future = _POOL.submit(_run)
            try:
                future.result(timeout=timeout or PAPER_JOB_TIMEOUT)
            except concurrent.futures.TimeoutError:
                with job.lock:
                    if job.status == "processing" and not job._cancelled:
                        job.status = "failed"
                        job.error = (
                            f"论文导入超时（超过 {timeout or PAPER_JOB_TIMEOUT} 秒）。"
                        )
                        job.error_kind = "timeout"
                        job._cancelled = True
            except Exception as exc:
                with job.lock:
                    if not job._cancelled and job.status == "processing":
                        job.status = "failed"
                        job.error = f"论文导入失败：{exc}"
                        job.error_kind = "failed"
                        job._cancelled = True
        finally:
            save_job(job)
            with job.lock:
                job._running = False

    threading.Thread(target=_wrapper, daemon=True).start()
    return True


__all__ = [
    "MAX_PAPER_ATTEMPTS",
    "PAPERS_DIRNAME",
    "PAPER_DOC_SUFFIX",
    "PAPER_JOB_TIMEOUT",
    "TEXT_LAYER_MODEL",
    "PaperJob",
    "build_page_map",
    "load_job",
    "load_jobs",
    "paper_dir",
    "paper_document_id",
    "paper_id_for_pdf",
    "process_paper",
    "render_paper_markdown",
    "result_payload",
    "save_job",
    "stable_paper_id",
    "start_job",
    "validate_paper",
]
