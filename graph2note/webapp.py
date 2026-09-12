"""Local single-user Web app: upload -> three-pane review/edit -> copy/export.

FastAPI backend wrapping ``pipeline.parse_document`` (issue 03) and the
attachment/assets organization (issue 05).  Personal/local-only: single user,
no auth, bind-free (serve on 127.0.0.1).

Scope guard: issue 07 (durable document library) IS built here — uploads commit
into a file-system-backed ``FileDocumentStore`` (data stays local; no database).
The ``DocumentStore`` ABC is the persistence seam: ``SessionDocumentStore``
(in-memory) and ``FileDocumentStore`` (durable, re-scanable on reload) both
implement it.

Parse runs in a background worker so the upload endpoint returns immediately;
a watchdog drives the job to a clear ``timeout`` failure instead of hanging the
client.  All parsing goes through the Recognition Router (never bypassed).  No
secrets are ever requested/accepted here — the gateway reads the key from env
or the repo-root ``.env`` (gitignored).
"""

from __future__ import annotations

import json
import concurrent.futures
import io
import os
import re
import threading
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .attachments import missing_attachments
from .ir import dumps_ir
from .metadata import extract_capture_time, infer_document_time
from .collections import CollectionError
from .graph import build_graph
from .inbox import build_inbox
from .llm_settings import (
    LLMSettingsStore,
    MODEL_PURPOSES,
    SettingsError,
    configure_settings_path,
    probe_channel,
)
from .tags import TagError
from .telemetry import build_stats, load_price_table
from .timeline import GROUPINGS, build_timeline
from . import autotag
from .store import (
    DocumentStore,
    FileDocumentStore,
    SessionDocumentStore,
)
from . import config
from . import evolution
from . import versiondiff
from . import digest
from . import pipeline
from . import pdflib
from . import pdfsearch
from . import pdfqa
from . import pdfqa_sessions
from . import repair as repairlib

DEFAULT_MODEL = os.environ.get("GRAPH2NOTE_MODEL", "glm-5.3-flash")
MAX_SIZE = 10 * 1024 * 1024  # 10 MB (FR-015)
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}
# Server-side single page budget (FR-025 target P95 <= 60s; allow slack for
# the gateway + a retry).  On expiry the job fails with a clear "timeout".
JOB_TIMEOUT = int(os.environ.get("GRAPH2NOTE_JOB_TIMEOUT", "180"))
# A PDF job parses many pages; give it a per-page budget worth of wall time.
PDF_JOB_TIMEOUT = int(
    os.environ.get("GRAPH2NOTE_PDF_JOB_TIMEOUT", str(JOB_TIMEOUT * 20))
)


def _resolve_thumbnail_url(record: dict, document_id: str) -> str | None:
    """Read-only preview URL for a timeline entry (U5).

    The store record always declares a preprocessed path even when the parse
    produced no image, so the API handler verifies existence here and falls back
    to the original page; ``None`` renders a placeholder in the timeline.
    """

    if not document_id:
        return None
    quoted = quote(document_id, safe="")
    latest = record.get("latest") if isinstance(record.get("latest"), dict) else {}
    candidates = (
        ("preprocessed", latest.get("preprocessed_path")),
        ("original", record.get("original_path")),
    )
    for suffix, path in candidates:
        if path and Path(path).is_file():
            return f"/api/documents/{quoted}/{suffix}"
    return None


def _pdf_error_status(kind: str) -> int:
    return {
        "wrong_type": 415,
        "too_large": 413,
        "too_many_pages": 422,
        "encrypted": 422,
        "corrupt": 400,
        "unreadable": 503,
    }.get(kind, 400)


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------


def _tag_payload(record: dict | None) -> dict:
    """Document tags with per-tag provenance for the API contract."""

    record = record or {}
    tags = list(record.get("tags") or [])
    provenance = record.get("tag_provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    detail = [
        {"tag": tag, "provenance": provenance.get(tag, "manual")}
        for tag in tags
    ]
    return {
        "document_id": record.get("document_id"),
        "tags": tags,
        "tag_provenance": {item["tag"]: item["provenance"] for item in detail},
        "tags_detail": detail,
    }


# Maximum edge of the Library card thumbnail (U2).  Cards display at ~250-320
# CSS px, so 480px keeps a crisp 1.5x/2x raster while cutting the 43-document
# first-paint payload far below the raw preprocessed pages.
THUMBNAIL_MAX = 480


def _write_thumbnail(source: Path, target: Path) -> None:
    """Downscale ``source`` into a cached PNG ``target`` (Pillow, offline)."""

    from PIL import Image

    resample = getattr(Image, "Resampling", Image).LANCZOS
    with Image.open(source) as image:
        thumb = image.copy()
        thumb.thumbnail((THUMBNAIL_MAX, THUMBNAIL_MAX), resample)
        if thumb.mode not in ("1", "L", "LA", "RGB", "RGBA", "P"):
            thumb = thumb.convert("RGB")
        tmp = target.with_name(target.name + ".tmp")
        thumb.save(tmp, format="PNG", optimize=True)
    tmp.replace(target)


def _library_card_fields(doc: dict) -> dict:
    """Append U2 card fields to a ``/api/documents`` summary (additive only).

    No existing key is removed or redefined; the frontend degrades to
    filename+date when any of these are absent (older API responses).
    """

    document_id = str(doc.get("document_id") or "")
    source_pdf = doc.get("source_pdf")
    page_number = doc.get("page_number")
    if source_pdf:
        label = Path(str(source_pdf)).name
        if page_number:
            label = f"{label} · 第 {page_number} 页"
        source_kind = "pdf"
    else:
        label = "图片上传"
        source_kind = "image"
    version_count = doc.get("version_count")
    if version_count is None:
        versions = doc.get("versions")
        version_count = len(versions) if isinstance(versions, list) else 0
    return {
        "headline": str(doc.get("headline") or ""),
        "tags": list(doc.get("tags") or []),
        "thumbnail_url": (
            f"/api/documents/{quote(document_id, safe='')}/thumbnail"
            if document_id else ""
        ),
        "source_kind": source_kind,
        "source_label": label,
        "source_pdf": source_pdf,
        "page_number": page_number,
        "version_count": version_count,
    }


@dataclass
class Job:
    job_id: str
    model: str
    original_ext: str
    provider: str | None = None
    status: str = "queued"          # queued|processing|done|failed|timeout
    error: str | None = None
    error_kind: str | None = None   # invalid|failed|timeout
    markdown: str | None = None
    doc_id: str | None = None
    document_id: str | None = None
    title: str | None = None
    merged_into: str | None = None  # issue 13: doc a duplicate page merged into
    warnings: list[str] = field(default_factory=list)
    degraded: list[int] = field(default_factory=list)
    timing: dict | None = None
    preprocessed_path: str | None = None
    assets_dir: str | None = None
    out_dir: str | None = None
    started_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cancelled: bool = field(default=False, repr=False)

    def public(self) -> dict:
        with self.lock:
            return {
                "job_id": self.job_id,
                "status": self.status,
                "error": self.error,
                "error_kind": self.error_kind,
                "markdown": self.markdown,
                "doc_id": self.doc_id,
                "document_id": self.document_id,
                "title": self.title,
                "merged_into": self.merged_into,
                "warnings": list(self.warnings),
                "degraded": list(self.degraded),
                "timing": self.timing,
                "model": self.model,
                "provider": self.provider,
                "empty": bool(self.markdown is not None and self.markdown.strip() == ""),
                "can_reparse": self.status in ("done", "failed", "timeout"),
            }


# ---------------------------------------------------------------------------
# Background parse runner with a timeout watchdog
# ---------------------------------------------------------------------------


class JobRunner:
    def __init__(self, app: FastAPI):
        self.app = app
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    def trigger(self, job: Job) -> None:
        threading.Thread(target=self._wrapper, args=(job,), daemon=True).start()

    def _wrapper(self, job: Job) -> None:
        fut = self._executor.submit(self._run_parse, job)
        try:
            fut.result(timeout=JOB_TIMEOUT)
        except concurrent.futures.TimeoutError:
            with job.lock:
                if job.status == "processing" and not job._cancelled:
                    job.status = "timeout"
                    job.error = f"解析超时（超过 {JOB_TIMEOUT} 秒），可点击「重新解析」重试。"
                    job.error_kind = "timeout"
                    job._cancelled = True
        except Exception as exc:  # parse raised before reaching job-state update
            with job.lock:
                if not job._cancelled and job.status == "processing":
                    job.status = "failed"
                    job.error = f"解析失败：{exc}"
                    job.error_kind = "failed"
                    job._cancelled = True

    def trigger_pdf(self, job: pdflib.PdfJob, data: bytes | None = None) -> bool:
        """Start/resume one PDF job; False if it is already running (single-flight)."""
        with job.lock:
            if job._running:
                return False
            job._running = True
        threading.Thread(target=self._wrapper_pdf, args=(job, data), daemon=True).start()
        return True

    def _wrapper_pdf(self, job: pdflib.PdfJob, data: bytes | None = None) -> None:
        try:
            fut = self._executor.submit(self._run_pdf, job, data)
            try:
                fut.result(timeout=PDF_JOB_TIMEOUT)
            except concurrent.futures.TimeoutError:
                with job.lock:
                    if job.status == "processing" and not job._cancelled:
                        job.status = "failed"
                        job.error = f"PDF 处理超时（超过 {PDF_JOB_TIMEOUT} 秒）。"
                        job.error_kind = "timeout"
                        job._cancelled = True
                pdflib.save_job(job)
            except Exception as exc:  # split/commit raised before per-page handling
                with job.lock:
                    if not job._cancelled and job.status == "processing":
                        job.status = "failed"
                        job.error = f"PDF 处理失败：{exc}"
                        job.error_kind = "failed"
                        job._cancelled = True
                pdflib.save_job(job)
        finally:
            with job.lock:
                job._running = False

    def _run_pdf(self, job: pdflib.PdfJob, data: bytes | None = None) -> None:
        app = self.app
        store = app.state.store
        try:
            pdflib.process_pdf(
                job,
                pdf_bytes=data,
                store=store,
                router_factory=app.state.router_factory,
                dedup_threshold=app.state.dedup_threshold,
                max_retries=app.state.max_retries,
                auto_tag_inferrer=getattr(app.state, "auto_tag_inferrer", None),
            )
        finally:
            pdflib.save_job(job)

    # ---- R1 black-image repair jobs -----------------------------------------

    def trigger_repair(self, job: repairlib.RepairJob) -> bool:
        """Start/resume one repair job; False if it is already running."""
        with job.lock:
            if job._running:
                return False
            job._running = True
        threading.Thread(target=self._wrapper_repair, args=(job,), daemon=True).start()
        return True

    def _wrapper_repair(self, job: repairlib.RepairJob) -> None:
        app = self.app
        try:
            channel = app.state.llm_settings.resolve("parse_visual")
            model = app.state.model_override or channel["model"]
            with job.lock:
                job.model = model
            repairlib.run_job(
                app.state.store,
                job,
                router_factory=app.state.router_factory,
                provider=channel["provider"],
            )
        except Exception as exc:  # never present a failure as a clean run
            with job.lock:
                job.status = "failed"
                job.error = f"修复任务失败：{exc}"
                job.error_kind = "failed"
            repairlib.save_job(job)
        finally:
            with job.lock:
                job._running = False

    def _run_parse(self, job: Job) -> None:
        app = self.app
        store = app.state.store
        original = store.get_original(job.job_id)
        if original is None:
            raise FileNotFoundError("原图缺失")
        with job.lock:
            job.status = "processing"
            job.started_at = time.time()
            job.doc_id = original.stem
        out_dir = store.job_out_dir(job.job_id) / "out"

        channel = app.state.llm_settings.resolve("parse_visual")
        selected_model = app.state.model_override or channel["model"]
        selected_provider = channel["provider"]
        with job.lock:
            job.model = selected_model
            job.provider = selected_provider

        if app.state.router_factory is not None:
            router = app.state.router_factory(str(original), selected_model)
        else:
            router = pipeline.make_router(
                selected_model,
                provider=selected_provider,
                max_retries=app.state.max_retries,
            )

        result = pipeline.parse_document(
            str(original),
            str(out_dir),
            model=selected_model,
            router=router,
            doc_id=job.doc_id,
            preprocess=True,
            save_preprocess_stages=True,
        )

        with job.lock:
            if job._cancelled:
                return  # timed out or superseded — ignore late completion
            job.markdown = result.markdown
            job.doc_id = result.markdown_path and Path(result.markdown_path).stem
            job.preprocessed_path = result.preprocessed_path
            job.assets_dir = result.assets_dir
            job.out_dir = str(out_dir)
            job.warnings = list(result.route.warnings)
            job.degraded = list(result.route.degraded_block_indices)
            job.timing = result.timing_json

        # Commit into the durable document library (issue 07 + issue 13).
        #  * re-parse of the SAME upload keeps its stable document_id -> the
        #    commit appends a new immutable version, never a duplicate record;
        #  * a FRESH upload's page is pHash-matched against the library: when a
        #    near-duplicate page already exists, we MERGE into that document as a
        #    new candidate version (issue 13, PRD User Story 31) and flag the
        #    "已并入文档 X" notice for the UI; otherwise a new record is created.
        # A re-parse stays on its own document_id when that page's own hash still
        # matches (never steal a page from its own record); only an actually
        # different/duplicate scan merges elsewhere.
        # Failures/timeouts never reach this point (no half-finished records).
        from .ingest import store_bridge
        from .ingest.hash import hamming

        pg_hash = ""
        merged_into = None
        try:
            pg_hash, _ = store_bridge.hash_page_image(str(original))
            threshold = app.state.dedup_threshold
            target = None
            own = store.get_document(job.document_id) if job.document_id else None
            own_hash = (own or {}).get("hash") or ""
            if own_hash and hamming(pg_hash, own_hash) <= threshold:
                target = None            # re-parse of the same page -> stay
            else:
                target = store_bridge.near_duplicate(
                    store, pg_hash, threshold=threshold)
                if target == job.document_id:
                    target = None
            merged_into = target
        except Exception:
            pg_hash = ""
            merged_into = None
        document_id = (merged_into
                       or job.document_id
                       or _safe_filename(job.doc_id or "doc"))
        metadata = {
            "capture_time": extract_capture_time(original),
        }
        document_time = infer_document_time(result.markdown)
        if document_time:
            metadata["document_time"] = document_time
        store.save_document(
            document_id=document_id,
            title=job.title or job.doc_id or document_id,
            source_job_id=job.job_id,
            model=selected_model,
            markdown=result.markdown,
            ir_json=dumps_ir(result.ir),
            original_path=str(original),
            original_ext=job.original_ext,
            preprocessed_path=result.preprocessed_path,
            preprocessed_raw_path=result.preprocessed_raw_path,
            assets_dir=result.assets_dir,
            timing_json=result.timing_json,
            pg_hash=pg_hash,
            metadata=metadata,
        )
        # A1: single post-ingest auto-tag hook.  Runs before the job is marked
        # done so a poller that sees 'done' can rely on the tags being present;
        # an inference failure is recorded as a warning and never blocks.
        autotag.after_ingest(
            store, document_id, result.markdown,
            inferrer=getattr(app.state, "auto_tag_inferrer", None),
        )
        # the record is durable NOW; only then present the job as done so a
        # poller can rely on the document existing with its final id(s)
        with job.lock:
            job.status = "done"
            job.document_id = document_id
            job.merged_into = merged_into


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    model: str | None = None,
    storage_dir: str | Path | None = None,
    document_store: DocumentStore | None = None,
    router_factory=None,
    max_retries: int = 1,
    dedup_threshold: int = 6,
    price_table: dict | None = None,
    llm_settings: LLMSettingsStore | None = None,
    llm_probe=None,
    pdf_max_page_attempts: int | None = None,
    pdf_page_timeout: int | None = None,
    pdf_workers: int | None = None,
    pdf_answerer=None,
    pdf_qa_model: str | None = None,
    pdf_qa_provider: str | None = None,
    pdf_qa_session: str | None = None,
    pdf_qa_timeout: int | None = None,
    pdf_qa_max_attempts: int | None = None,
    pdf_session_store: pdfqa_sessions.SessionStore | None = None,
    auto_tag_inferrer=None,
    auto_tag: bool = False,
    auto_tag_model: str | None = None,
    auto_tag_provider: str | None = None,
    auto_tag_max_chars: int = autotag.DEFAULT_MAX_CHARS,
    digest_planner=None,
) -> FastAPI:
    """Build the FastAPI app.

    ``router_factory(image_path, model) -> RecognitionRouter`` lets tests inject
    an offline (golden/cache) router; when None, the real pipeline router with a
    VLM gateway is used.  ``document_store`` is the issue-07 persistence seam.

    ``auto_tag_inferrer`` is the A1 post-ingest tag seam: pass a
    :class:`graph2note.autotag.TagInferrer` (or a bare planner callable) to
    enable offline auto-tagging.  ``auto_tag=True`` builds the live classify
    planner; the default (``False``) keeps ingest LLM-free so tests stay
    offline.  Production enables it from ``macos/launcher.py``.
    """
    storage_dir = config.ensure_storage_dir(config.resolve_storage_dir(storage_dir))
    store = document_store or FileDocumentStore(storage_dir)
    settings_path = config.resolve_settings_file(storage_dir)
    settings = llm_settings or LLMSettingsStore(settings_path)
    configure_settings_path(settings.path)

    app = FastAPI(title="graph2note", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.storage_dir = str(storage_dir)
    app.state.settings_path = str(settings_path)
    app.state.jobs: dict[str, Job] = {}
    app.state.jobs_lock = threading.Lock()
    app.state.model_override = model
    app.state.llm_settings = settings
    app.state.llm_probe = llm_probe
    app.state.model = model or settings.resolve("parse_visual")["model"]
    app.state.provider = settings.resolve("parse_visual")["provider"]
    app.state.max_retries = max_retries
    app.state.router_factory = router_factory
    app.state.runner = JobRunner(app)
    # issue 13: near-dup merge threshold (hamming distance on page pHash)
    app.state.dedup_threshold = dedup_threshold
    app.state.price_table = load_price_table() if price_table is None else price_table
    # baseline issue 06: single-flight Obsidian vault export state (one-way).
    app.state.vault_export = {
        "status": "idle",          # idle|running|done|failed
        "task_id": None,           # unique per run (report never mixes tasks)
        "target_dir": None,
        "started_at": None,
        "report": None,            # enriched incremental report (see _enrich_export_report)
        "vault_root": None,
        "exported_documents": 0,
        "partial": False,          # failed after writing some files
        "error": None,
    }
    app.state.vault_export_lock = threading.Lock()
    # issue 08: PDF upload jobs, keyed by stable content hash (AC2).
    # issue 09: explicit, persisted per-page bounds for PDF batch jobs (AC4).
    app.state.pdf_jobs: dict[str, pdflib.PdfJob] = {}
    app.state.pdf_jobs_lock = threading.Lock()
    app.state.pdf_max_page_attempts = pdf_max_page_attempts or pdflib.MAX_PAGE_ATTEMPTS
    app.state.pdf_page_timeout = pdf_page_timeout or pdflib.PAGE_TIMEOUT
    app.state.pdf_workers = pdf_workers or pdflib.PDF_WORKERS
    # issue 11: injectable text-model seam for grounded PDF Q&A (offline tests
    # pass a stub; production leaves None and uses the configured provider).
    app.state.pdf_answerer = pdf_answerer
    app.state.pdf_qa_model = pdf_qa_model
    app.state.pdf_qa_provider = pdf_qa_provider
    app.state.pdf_qa_session = pdf_qa_session
    app.state.pdf_qa_timeout = pdf_qa_timeout or pdfqa.ANSWER_TIMEOUT
    app.state.pdf_qa_max_attempts = pdf_qa_max_attempts or pdfqa.MAX_ATTEMPTS
    # P1: conversation sessions, persisted under the store root (restart-safe).
    if pdf_session_store is not None:
        app.state.pdf_session_store = pdf_session_store
    else:
        _session_root = Path(getattr(store, "root", storage_dir)) / pdfqa.SESSION_DIRNAME
        app.state.pdf_session_store = pdfqa_sessions.SessionStore(_session_root)
    # A1: single post-ingest auto-tag hook (single image + PDF page commits).
    if auto_tag_inferrer is None and auto_tag:
        channel = settings.resolve("classify")
        provider = auto_tag_provider or channel["provider"]
        model = auto_tag_model or channel["model"]
        auto_tag_inferrer = autotag.TagInferrer(
            planner=autotag.live_planner(provider=provider, model=model),
            model=model,
            provider=provider,
            max_chars=auto_tag_max_chars,
        )
    app.state.auto_tag_inferrer = auto_tag_inferrer
    # issue A2: injectable text-model seam for weekly digests (offline tests pass
    # a recorded golden planner; production leaves None and uses the gateway).
    app.state.digest_planner = digest_planner
    for _persisted in pdflib.load_jobs(store):
        pdflib.save_job(_persisted)  # persist the reconciled 'interrupted' state
        app.state.pdf_jobs[_persisted.pdf_id] = _persisted

    # R1: black-image repair runs (durable, per-document results, retryable).
    app.state.repair_jobs: dict[str, repairlib.RepairJob] = {}
    app.state.repair_jobs_lock = threading.Lock()
    for _repair in repairlib.load_jobs(store):
        repairlib.save_job(_repair)
        app.state.repair_jobs[_repair.repair_id] = _repair

    def _get_job(job_id: str) -> Job:
        with app.state.jobs_lock:
            job = app.state.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="任务不存在或会话已清空。")
        return job

    @app.post("/api/parse")
    async def parse_upload(file: UploadFile = File(...)):
        data = await file.read()
        if len(data) > MAX_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"文件超过 10MB 上限（收到 {len(data) / 1048576:.1f}MB），请压缩后再上传。",
            )
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="空文件，无法解析。")
        ext = _validate_upload(file.filename or "")

        job_id = uuid.uuid4().hex[:12]
        title = (Path(file.filename).stem or job_id)[:60]
        document_id = "doc-" + uuid.uuid4().hex[:10]
        original = store.save_original(job_id, data, ext)
        if not _looks_like_image(original):
            store.remove(job_id)
            raise HTTPException(status_code=415, detail="文件不是有效的 JPG/JPEG/PNG 图片。")

        # one stable document_id per upload (reparse reuses it, never a dup doc)
        channel = app.state.llm_settings.resolve("parse_visual")
        selected_model = app.state.model_override or channel["model"]
        job = Job(job_id=job_id, model=selected_model, provider=channel["provider"], original_ext=ext,
                  title=title, document_id=document_id)
        with app.state.jobs_lock:
            app.state.jobs[job_id] = job
        app.state.runner.trigger(job)
        return {"job_id": job_id, "status": job.status, "model": selected_model,
                "provider": channel["provider"],
                "document_id": document_id}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str):
        return _get_job(job_id).public()

    @app.post("/api/jobs/{job_id}/reparse")
    def reparse(job_id: str):
        job = _get_job(job_id)
        original = store.get_original(job_id)
        if original is None:
            raise HTTPException(status_code=404, detail="原图已丢失，无法重新解析。")
        with job.lock:
            job.status = "queued"
            job.error = None
            job.error_kind = None
            job.markdown = None
            job.warnings = []
            job.degraded = []
            job.timing = None
            job.preprocessed_path = None
            job.assets_dir = None
            job._cancelled = False
            job.started_at = None
        app.state.runner.trigger(job)
        return {"job_id": job_id, "status": "queued"}

    # ---- serving artifacts ----------------------------------------------------

    @app.get("/api/jobs/{job_id}/original")
    def original(job_id: str):
        _get_job(job_id)
        p = store.get_original(job_id)
        if p is None or not p.exists():
            raise HTTPException(status_code=404, detail="原图缺失。")
        return FileResponse(p, media_type="image/jpeg")

    @app.get("/api/jobs/{job_id}/preprocessed")
    def preprocessed(job_id: str):
        job = _get_job(job_id)
        with job.lock:
            p = job.preprocessed_path
        if not p or not Path(p).exists():
            raise HTTPException(status_code=404, detail="预处理图尚未就绪。")
        return FileResponse(p, media_type="image/png")

    @app.get("/api/jobs/{job_id}/assets/{name}")
    def asset(job_id: str, name: str):
        job = _get_job(job_id)
        with job.lock:
            assets = job.assets_dir
        if not assets:
            raise HTTPException(status_code=404, detail="附件尚未就绪。")
        # assets_dir is the parse out-dir (root); files live under assets/
        safe = Path(name).name  # prevent path traversal (local app, but be safe)
        target = Path(assets) / "assets" / safe
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"附件 {safe} 不存在。")
        return FileResponse(target, media_type="image/png")

    @app.post("/api/jobs/{job_id}/export")
    def export(job_id: str, body: dict | None = None):
        """Zip of the (edited) markdown + all referenced attachment files."""
        job = _get_job(job_id)
        with job.lock:
            status = job.status
            assets = job.assets_dir
            doc_id = job.doc_id or job_id
        if status != "done":
            raise HTTPException(status_code=409, detail="尚未解析完成，无法导出。")
        md = (body or {}).get("markdown") or job.markdown
        if md is None:
            raise HTTPException(status_code=409, detail="尚未解析完成，无法导出。")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            fn = _safe_filename(doc_id) + ".md"
            zf.writestr(fn, md)
            missing: list[str] = []
            # assets_dir is the out-dir root; attachment files live under assets/
            leaf = Path(assets) / "assets"
            if leaf.is_dir():
                for f in sorted(p for p in leaf.iterdir() if p.is_file()):
                    zf.write(str(f), f"assets/{Path(f).name}")
                if md:
                    missing = missing_attachments(md, assets)
            zf.writestr("export-notes.json", json.dumps(
                {"missing_attachments": missing}, ensure_ascii=False))
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={_safe_filename(doc_id)}.zip"},
        )

    # ---- document library (issue 07) -----------------------------------------

    def _get_document(document_id: str) -> dict:
        rec = store.get_document(document_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        rec = dict(rec)
        rec["tags_detail"] = _tag_payload(rec)["tags_detail"]
        return rec

    @app.get("/api/documents")
    def documents_list(
        collection_id: str | None = None,
        collection: str | None = None,
        tag: str | None = None,
        tag_id: str | None = None,
        topic: str | None = None,
        topic_id: str | None = None,
    ):
        selected = collection_id or collection
        selected_tag = tag_id or tag
        selected_topic = topic_id or topic
        documents = store.list_documents()
        if selected:
            documents = [
                item for item in documents
                if selected in (item.get("collections") or [])
            ]
        if not selected_tag and not selected_topic:
            return [item | _library_card_fields(item) for item in documents]
        filtered = []
        for item in documents:
            record = store.get_document(item["document_id"])
            if record is None:
                continue
            if selected_tag and selected_tag not in (record.get("tags") or []):
                continue
            if selected_topic and selected_topic not in (record.get("topics") or []):
                continue
            filtered.append(item)
        return [item | _library_card_fields(item) for item in filtered]

    @app.get("/api/timeline")
    def timeline_list(
        group_by: str = "day",
        collection_id: str | None = None,
        collection: str | None = None,
    ):
        if group_by not in GROUPINGS:
            raise HTTPException(status_code=422, detail="group_by 必须是 day 或 week")
        selected = collection_id or collection
        records = []
        for summary in store.list_documents():
            record = store.get_document(summary["document_id"])
            if record is None:
                continue
            if selected and selected not in (record.get("collections") or []):
                continue
            record = dict(record)
            # U5: resolve the read-only preview against the filesystem here (so
            # the pure projection can stay pure) — preprocessed page first, then
            # the original; none when neither exists.
            record["thumbnail_url"] = _resolve_thumbnail_url(record, summary["document_id"])
            records.append(record)
        return build_timeline(records, group_by=group_by)

    @app.get("/api/graph")
    def graph_list(collection_id: str | None = None, collection: str | None = None):
        selected = collection_id or collection
        collection_names = {
            item["collection_id"]: item["name"]
            for item in store.list_collections()
        }
        records = []
        for summary in store.list_documents():
            record = store.get_document(summary["document_id"])
            if record is None:
                continue
            if selected and selected not in (record.get("collections") or []):
                continue
            record = dict(record)
            record["collection_names"] = collection_names
            records.append(record)
        return build_graph(records)

    @app.get("/api/stats")
    def stats(as_of: str | None = None):
        now = None
        if as_of:
            normalized_as_of = as_of.strip().replace("Z", "+00:00")
            try:
                now = datetime.fromisoformat(normalized_as_of)
            except ValueError as exc:
                # A raw ``+08:00`` in a query string is decoded as a space by
                # URL parsers.  Accept that common hand-written URL form too.
                match = re.match(r"^(.*) ([+-]?\d{2}:\d{2})$", normalized_as_of)
                if not match:
                    raise HTTPException(status_code=422, detail="as_of 不是合法 ISO 时间") from exc
                offset = match.group(2)
                if not offset.startswith(("+", "-")):
                    offset = "+" + offset
                try:
                    now = datetime.fromisoformat(match.group(1) + offset)
                except ValueError as offset_exc:
                    raise HTTPException(status_code=422, detail="as_of 不是合法 ISO 时间") from offset_exc
        records = []
        for summary in store.list_documents():
            record = store.get_document(summary["document_id"])
            if record is not None:
                records.append(record)
        return build_stats(
            records,
            now=now,
            price_table=app.state.price_table,
            digest_records=digest.list_digests(app.state.storage_dir),
        )

    # ---- weekly digests (issue A2) -----------------------------------------

    def _all_records() -> list[dict]:
        records = []
        for summary in store.list_documents():
            record = store.get_document(summary["document_id"])
            if record is not None:
                records.append(record)
        return records

    @app.post("/api/digests")
    def digest_create(body: dict | None = None):
        """Generate (or fingerprint-cache reuse) one weekly digest."""
        payload = body or {}
        spec = payload.get("range") or payload.get("kind") or "this_week"
        if isinstance(spec, dict):
            kind = spec.get("kind") or spec.get("range") or "custom"
            from_ = payload.get("from") or spec.get("from") or spec.get("start")
            to = payload.get("to") or spec.get("to") or spec.get("end")
        else:
            kind, from_, to = spec, payload.get("from"), payload.get("to")
        try:
            range_spec = digest.resolve_range(kind, from_=from_, to=to)
        except digest.RangeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        result = digest.generate_digest(
            _all_records(),
            range_spec,
            storage_dir=app.state.storage_dir,
            planner=app.state.digest_planner,
            force=bool(payload.get("force")),
        )
        if result["status"] == "error":
            raise HTTPException(status_code=502, detail=result["message"]) from None
        return result

    @app.get("/api/digests")
    def digest_list():
        metas = digest.list_digests(app.state.storage_dir)
        return {"digests": metas, "total": len(metas)}

    @app.get("/api/digests/{digest_id}")
    def digest_get(digest_id: str):
        stored = digest.load_digest(app.state.storage_dir, digest_id)
        if stored is None:
            raise HTTPException(status_code=404, detail="小结不存在。")
        return {"meta": stored["meta"], "markdown": stored["markdown"]}

    # ---- LLM provider/model settings (issue 16) ----------------------------

    @app.get("/api/config")
    def config_get():
        """Effective runtime config: support/storage/settings locations."""
        return config.describe(app.state.storage_dir)

    @app.get("/api/llm/settings")
    def llm_settings_get():
        return app.state.llm_settings.snapshot()

    @app.put("/api/llm/settings")
    @app.patch("/api/llm/settings")
    def llm_settings_update(body: dict | None = None):
        try:
            return app.state.llm_settings.update(body or {})
        except SettingsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ---- Custom OpenAI-compatible providers (issue A3) --------------------
    # The API key is write-only: create/update accept it, every response only
    # carries a configured/not-configured boolean.

    @app.post("/api/llm/providers")
    def llm_provider_create(body: dict | None = None):
        try:
            return app.state.llm_settings.add_provider(body or {})
        except SettingsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/llm/providers/{provider_id}")
    @app.patch("/api/llm/providers/{provider_id}")
    def llm_provider_update(provider_id: str, body: dict | None = None):
        try:
            return app.state.llm_settings.update_provider(provider_id, body or {})
        except SettingsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/llm/providers/{provider_id}")
    def llm_provider_delete(provider_id: str):
        try:
            return app.state.llm_settings.delete_provider(provider_id)
        except SettingsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/llm/providers/{provider_id}/models")
    def llm_provider_refresh_models(provider_id: str):
        try:
            return app.state.llm_settings.refresh_provider_models(provider_id)
        except SettingsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/llm/health")
    @app.post("/api/llm/health")
    def llm_health():
        channels = app.state.llm_settings.snapshot()["channels"]
        results = [
            probe_channel(
                channel["provider"], purpose, channel["model"],
                probe=app.state.llm_probe,
            )
            for purpose, channel in channels.items()
            if purpose in MODEL_PURPOSES
        ]
        return {"channels": results, "statuses": {item["purpose"]: item for item in results}}

    @app.get("/api/inbox")
    def inbox_list():
        records = []
        for summary in store.list_documents():
            record = store.get_document(summary["document_id"])
            if record is not None:
                records.append(record)
        return build_inbox(records)

    @app.get("/api/documents/{document_id}")
    def document_get(document_id: str):
        return _get_document(document_id)

    # ---- evolution anchoring (issue S2) -------------------------------------

    def _bounded_max_distance(value: int | None) -> int:
        if value is None:
            return evolution.PHASH_SUGGEST_MAX_DISTANCE
        if value < 0 or value > evolution.HASH_BITS:
            raise HTTPException(
                status_code=422,
                detail=f"max_distance 必须在 0..{evolution.HASH_BITS} 之间（Hamming 位）。",
            )
        return value

    @app.get("/api/documents/{document_id}/versions")
    def document_versions(document_id: str):
        """Time-ordered evolution timeline (source + DiffReport summary)."""
        _get_document(document_id)
        return evolution.build_version_chain(store, document_id)

    # ---- version comparison (issue S3) --------------------------------------

    @app.get("/api/documents/{document_id}/diff")
    def document_diff(document_id: str, a: str | None = None, b: str | None = None):
        """Read-only block-level comparison of two versions (S1 DiffReport).

        Defaults to newest vs the version before it.  Returns per-block
        Markdown + S1 anchors for the highlight/jump UI and a templated,
        model-free summary derived from the same report numbers.
        """
        _get_document(document_id)
        try:
            payload = versiondiff.build_compare(store, document_id, version_a=a, version_b=b)
        except versiondiff.VersionDiffError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if payload is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return payload

    @app.get("/api/documents/{document_id}/versions/{version_id}/preprocessed")
    def document_version_preprocessed(document_id: str, version_id: str):
        """Enhanced page image for one version (original-image side-by-side)."""
        rec = _get_document(document_id)
        chain = evolution.build_version_chain(store, document_id) or {}
        known = {str(v.get("version_id")) for v in chain.get("versions") or []}
        target = version_id
        if version_id == versiondiff.EDIT_VERSION_ID:
            target = chain.get("latest_version_id") or (rec.get("latest") or {}).get("version_id")
        elif version_id not in known:
            raise HTTPException(status_code=404, detail="版本不存在。")
        path = versiondiff.version_preprocessed_path(store, document_id, target) if target else None
        if not path:
            raise HTTPException(status_code=404, detail="该版本预处理图尚未就绪。")
        return FileResponse(path, media_type="image/png")

    @app.get("/api/documents/{document_id}/candidates")
    def document_candidates(document_id: str, max_distance: int | None = None):
        """Read-only pHash cross-document suggestions (never auto-linked)."""
        _get_document(document_id)
        return evolution.find_phash_candidates(
            store, document_id, max_distance=_bounded_max_distance(max_distance)
        )

    @app.post("/api/documents/{document_id}/relations")
    def document_confirm_relation(document_id: str, body: dict | None = None):
        """Confirm a suggestion; persists a regular ``manual`` edge both ways."""
        payload = body or {}
        target_id = payload.get("target_id") or payload.get("target") or payload.get("document_id")
        if not target_id:
            raise HTTPException(status_code=422, detail="target_id 必填。")
        if target_id == document_id:
            raise HTTPException(status_code=422, detail="不能把文档关联到自身。")
        _get_document(document_id)
        _get_document(target_id)
        distance = payload.get("distance")
        if distance is not None:
            try:
                distance = _bounded_max_distance(int(distance))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="distance 必须是整数。") from exc
        result = evolution.confirm_relation(
            store, document_id, target_id, distance=distance)
        if result is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return result

    @app.post("/api/documents/{document_id}/candidates/reject")
    def document_reject_candidate(document_id: str, body: dict | None = None):
        """Remember a rejected suggestion so the pair is never suggested again."""
        payload = body or {}
        target_id = payload.get("target_id") or payload.get("target") or payload.get("document_id")
        if not target_id:
            raise HTTPException(status_code=422, detail="target_id 必填。")
        if target_id == document_id:
            raise HTTPException(status_code=422, detail="不能拒绝与自身的关联。")
        _get_document(document_id)
        _get_document(target_id)
        distance = payload.get("distance")
        if distance is not None:
            try:
                distance = int(distance)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail="distance 必须是整数。") from exc
        return evolution.reject_candidate(
            store, document_id, target_id, distance=distance)

    # ---- tag vocabulary + document memberships (issue 02) -------------------

    @app.get("/api/tags")
    def tags_list():
        return store.list_tags()

    @app.post("/api/tags")
    def tag_create(body: dict | None = None):
        payload = body or {}
        tag = payload.get("tag", payload.get("name"))
        try:
            return {"tags": store.create_tag(tag)}
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/tags/rename")
    def tag_rename(body: dict | None = None):
        payload = body or {}
        try:
            tags = store.rename_tag(payload.get("source"), payload.get("target", payload.get("name")))
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"tags": tags}

    @app.post("/api/tags/merge")
    def tag_merge(body: dict | None = None):
        payload = body or {}
        try:
            tags = store.merge_tags(payload.get("source"), payload.get("target"))
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"tags": tags}

    # ---- collections + workspace navigation (issue 03) ---------------------

    @app.get("/api/collections")
    def collections_list():
        return store.list_collections()

    @app.post("/api/collections")
    def collection_create(body: dict | None = None):
        try:
            return store.create_collection((body or {}).get("name"))
        except (CollectionError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.put("/api/collections/{collection_id}")
    @app.patch("/api/collections/{collection_id}")
    def collection_rename(collection_id: str, body: dict | None = None):
        try:
            return store.rename_collection(collection_id, (body or {}).get("name"))
        except (CollectionError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/collections/{collection_id}")
    def collection_delete(collection_id: str):
        try:
            deleted = store.delete_collection(collection_id)
        except CollectionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="集合不存在。")
        return {"deleted": True, "collection_id": collection_id}

    @app.put("/api/documents/{document_id}/metadata")
    @app.patch("/api/documents/{document_id}/metadata")
    def document_update_metadata(document_id: str, body: dict | None = None):
        updates = (body or {}).get("metadata", body or {})
        if not isinstance(updates, dict):
            raise HTTPException(status_code=422, detail="metadata 必须是对象。")
        try:
            rec = store.update_metadata(document_id, updates)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return {
            "document_id": document_id,
            "metadata": rec.get("metadata"),
            "effective_time": rec.get("effective_time"),
        }

    @app.put("/api/documents/{document_id}/tags")
    def document_set_tags(document_id: str, body: dict | None = None):
        payload = body or {}
        tags = payload.get("tags")
        if tags is None and "tag" in payload:
            tags = [payload.get("tag")]
        try:
            rec = store.set_tags(document_id, tags or [])
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return _tag_payload(rec)

    @app.post("/api/documents/{document_id}/tags")
    def document_add_auto_tags(document_id: str, body: dict | None = None):
        payload = body or {}
        raw_tags = payload.get("tags", payload.get("tag", []))
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        try:
            rec = store.add_auto_tags(document_id, raw_tags)
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return _tag_payload(rec)

    @app.post("/api/documents/{document_id}/tags/manual")
    def document_add_manual_tags(document_id: str, body: dict | None = None):
        payload = body or {}
        raw_tags = payload.get("tags", payload.get("tag", []))
        try:
            rec = store.add_manual_tags(document_id, raw_tags)
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return _tag_payload(rec)

    @app.patch("/api/documents/{document_id}/tags/{tag}")
    def document_update_tag(document_id: str, tag: str, body: dict | None = None):
        payload = body or {}
        if payload.get("provenance") != "manual":
            raise HTTPException(status_code=422, detail="provenance 只能是 manual。")
        try:
            rec = store.promote_tag(document_id, tag)
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return _tag_payload(rec)

    @app.delete("/api/documents/{document_id}/tags/{tag}")
    def document_remove_tag(document_id: str, tag: str):
        try:
            updated = store.remove_tag(document_id, tag)
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return _tag_payload(updated)

    @app.put("/api/documents/{document_id}/collections")
    def document_set_collections(document_id: str, body: dict | None = None):
        payload = body or {}
        collection_ids = payload.get("collection_ids", payload.get("collections", []))
        if isinstance(collection_ids, str):
            collection_ids = [collection_ids]
        try:
            rec = store.set_collections(document_id, collection_ids or [])
        except (CollectionError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return {"document_id": document_id, "collections": rec.get("collections", [])}

    @app.post("/api/documents/{document_id}/markdown")
    def document_save_markdown(document_id: str, body: dict | None = None):
        rec = store.save_edits(document_id, (body or {}).get("markdown", ""))
        if rec is None:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return {"ok": True, "updated_at": rec.get("updated_at")}

    @app.delete("/api/documents/{document_id}")
    def document_delete(document_id: str):
        existed = store.delete_document(document_id)
        if not existed:
            raise HTTPException(status_code=404, detail="文档不存在或已被删除。")
        return {"deleted": True, "document_id": document_id}

    @app.post("/api/documents/{document_id}/reparse")
    def document_reparse(document_id: str):
        rec = _get_document(document_id)
        op = rec.get("original_path")
        if not op or not Path(op).is_file():
            raise HTTPException(status_code=404, detail="原图已丢失，无法重新解析。")
        ext = rec.get("original_ext") or Path(op).suffix or ".jpg"
        job_id = uuid.uuid4().hex[:12]
        store.save_original(job_id, Path(op).read_bytes(), ext)
        channel = app.state.llm_settings.resolve("parse_visual")
        selected_model = app.state.model_override or channel["model"]
        job = Job(job_id=job_id, model=selected_model, provider=channel["provider"], original_ext=ext,
                  title=rec.get("title") or document_id, document_id=document_id)
        with app.state.jobs_lock:
            app.state.jobs[job_id] = job
        app.state.runner.trigger(job)
        return {"job_id": job_id, "document_id": document_id, "status": job.status}

    @app.get("/api/documents/{document_id}/original")
    def document_original(document_id: str):
        rec = _get_document(document_id)
        p = rec.get("original_path")
        if not p or not Path(p).is_file():
            raise HTTPException(status_code=404, detail="原图缺失。")
        return FileResponse(p)

    @app.get("/api/documents/{document_id}/preprocessed")
    def document_preprocessed(document_id: str):
        rec = _get_document(document_id)
        latest = rec.get("latest")
        p = latest and latest.get("preprocessed_path")
        if not p or not Path(p).is_file():
            raise HTTPException(status_code=404, detail="预处理图尚未就绪。")
        return FileResponse(p, media_type="image/png")

    @app.get("/api/documents/{document_id}/thumbnail")
    def document_thumbnail(document_id: str):
        """U2: downscaled card thumbnail, cached next to the preprocessed page."""

        rec = _get_document(document_id)
        latest = rec.get("latest") or {}
        source = latest.get("preprocessed_path")
        if not source or not Path(source).is_file():
            raise HTTPException(status_code=404, detail="缩略图尚未就绪。")
        source_path = Path(source)
        target = source_path.with_name("thumbnail.png")
        try:
            if (not target.is_file()
                    or target.stat().st_mtime < source_path.stat().st_mtime):
                _write_thumbnail(source_path, target)
        except Exception:
            # A missing/broken cache must not hide the page: fall back to the
            # full preprocessed image (CSS still constrains its display size).
            return FileResponse(str(source_path), media_type="image/png")
        return FileResponse(str(target), media_type="image/png")

    @app.get("/api/documents/{document_id}/assets/{name}")
    def document_asset(document_id: str, name: str):
        rec = _get_document(document_id)
        latest = rec.get("latest")
        assets_root = latest and latest.get("assets_root")
        if not assets_root:
            raise HTTPException(status_code=404, detail="附件尚未就绪。")
        safe = Path(name).name  # prevent path traversal (local app, but be safe)
        target = Path(assets_root) / "assets" / safe
        if not target.is_file():
            raise HTTPException(status_code=404, detail=f"附件 {safe} 不存在。")
        return FileResponse(target, media_type="image/png")

    @app.post("/api/documents/{document_id}/export")
    def document_export(document_id: str, body: dict | None = None):
        rec = _get_document(document_id)
        md = (body or {}).get("markdown") or rec.get("current_markdown")
        doc_id = rec.get("title") or document_id
        latest = rec.get("latest") or {}
        assets_root = latest.get("assets_root")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(_safe_filename(doc_id) + ".md", md or "")
            missing: list[str] = []
            if assets_root:
                leaf = Path(assets_root) / "assets"
                if leaf.is_dir():
                    for f in sorted(p for p in leaf.iterdir() if p.is_file()):
                        zf.write(str(f), f"assets/{Path(f).name}")
                    if md:
                        missing = missing_attachments(md, assets_root)
            zf.writestr("export-notes.json", json.dumps(
                {"missing_attachments": missing}, ensure_ascii=False))
        buf.seek(0)
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={_safe_filename(doc_id)}.zip"},
        )

    # ---- Obsidian vault export (baseline issue 06) --------------------------
    # One-way export of the *current* document library into an Obsidian vault
    # on a server-local target directory (the app binds to 127.0.0.1, so the
    # browser and the server share the machine).  Reuses the incremental
    # exporter + rule classification + user-edit protection from
    # ``graph2note.notes``; it does NOT sync anything back into graph2note.

    def _run_vault_export(target: str, task_id: str) -> None:
        from .notes.loop import run_incremental_export

        before = _dir_fingerprint(Path(target))
        try:
            report, vault, entries = run_incremental_export(
                app.state.store, target)
            app.state.vault_export = {
                "status": "done",
                "task_id": task_id,
                "target_dir": target,
                "started_at": app.state.vault_export.get("started_at"),
                "report": _enrich_export_report(report, vault, task_id),
                "vault_root": str(vault.root),
                "exported_documents": len(entries),
                "partial": False,
                "error": None,
            }
        except Exception as exc:  # never present a failure as success
            app.state.vault_export = {
                "status": "failed",
                "task_id": task_id,
                "target_dir": target,
                "started_at": app.state.vault_export.get("started_at"),
                "report": None,
                "vault_root": None,
                "exported_documents": 0,
                # a failure after some files were written is a partial export,
                # never a clean success
                "partial": _dir_fingerprint(Path(target)) != before,
                "error": str(exc),
            }

    @app.post("/api/vault/export")
    def vault_export(body: dict | None = None):
        payload = body or {}
        target = str(payload.get("target_dir") or "").strip()
        if not target:
            raise HTTPException(status_code=422, detail="请填写目标目录路径。")

        with app.state.vault_export_lock:
            if app.state.vault_export.get("status") == "running":
                raise HTTPException(status_code=409, detail="导出正在进行中，请稍候。")

            # Empty library is a distinct, non-error state.  Clear any stale
            # report so GET never serves a previous run's result as current.
            if not app.state.store.list_documents():
                app.state.vault_export = {
                    "status": "idle", "task_id": None, "target_dir": None,
                    "started_at": None, "report": None, "vault_root": None,
                    "exported_documents": 0, "partial": False, "error": None,
                }
                return {"status": "empty", "exported_documents": 0,
                        "message": "文档库为空，没有可导出的文档。"}

            try:
                out_path = _ensure_writable_dir(target)
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            task_id = uuid.uuid4().hex[:12]
            app.state.vault_export = {
                "status": "running",
                "task_id": task_id,
                "target_dir": str(out_path),
                "started_at": time.time(),
                "report": None,
                "vault_root": None,
                "exported_documents": 0,
                "partial": False,
                "error": None,
            }

        threading.Thread(target=_run_vault_export, args=(str(out_path), task_id),
                         daemon=True).start()
        return {"status": "running", "task_id": task_id,
                "target_dir": str(out_path), "exported_documents": 0}

    @app.get("/api/vault/export")
    def vault_export_status():
        return app.state.vault_export
    # ---- PDF upload -> split -> parse -> library (issue 08) ------------------

    def _get_pdf_job(pdf_id: str) -> pdflib.PdfJob:
        job = _get_or_load_pdf_job(pdf_id)
        if job is None:
            raise HTTPException(status_code=404, detail="PDF 任务不存在。")
        return job

    def _get_or_load_pdf_job(pdf_id: str) -> pdflib.PdfJob | None:
        """Memory first, then the durable job.json (issue 09 AC1).

        A job loaded from disk has no live worker, so an in-flight status is
        reconciled to 'interrupted' before it is returned.
        """
        with app.state.pdf_jobs_lock:
            job = app.state.pdf_jobs.get(pdf_id)
        if job is not None:
            return job
        try:
            work_dir = pdflib.pdf_dir(app.state.store, pdf_id)
        except RuntimeError:
            return None
        job = pdflib.load_job(work_dir)
        if job is None:
            return None
        job.mark_interrupted()
        pdflib.save_job(job)
        with app.state.pdf_jobs_lock:
            existing = app.state.pdf_jobs.get(pdf_id)
            if existing is not None:
                return existing
            app.state.pdf_jobs[pdf_id] = job
        return job

    @app.post("/api/pdf")
    async def pdf_upload(file: UploadFile = File(...)):
        data = await file.read()
        filename = file.filename or "upload.pdf"
        # validate synchronously so every rejectable condition (type/size/page
        # count/encrypted/corrupt) returns an actionable 4xx before any async work
        try:
            total_pages = pdflib.validate_pdf(data, filename)
        except pdflib.PdfError as exc:
            raise HTTPException(
                status_code=_pdf_error_status(exc.kind), detail=str(exc)) from exc

        pdf_id = pdflib.stable_pdf_id(data)
        job = _get_or_load_pdf_job(pdf_id)
        if job is None:
            job = pdflib.PdfJob(
                pdf_id=pdf_id, filename=filename, model=model,
                total_pages=total_pages,
                max_page_attempts=app.state.pdf_max_page_attempts,
                page_timeout=app.state.pdf_page_timeout,
                workers=app.state.pdf_workers,
            )
            with app.state.pdf_jobs_lock:
                app.state.pdf_jobs[pdf_id] = job

        # stable pdf identity: a re-upload of the same bytes reuses the job and
        # only resumes pages that are not yet successful (idempotent; AC2/AC3).
        with job.lock:
            job.total_pages = total_pages
        retryable = job.retryable_page_indexes()
        if job.pages and not retryable and job.status == "done":
            return {"pdf_id": pdf_id, "status": "done",
                    "total_pages": total_pages,
                    "retryable": False, "retryable_pages": []}
        with job.lock:
            job.status = "queued"
            job.error = None
            job.error_kind = None
            job._cancelled = False
        triggered = app.state.runner.trigger_pdf(job, data)
        return {"pdf_id": pdf_id, "status": job.status, "total_pages": total_pages,
                "retryable": bool(retryable), "retryable_pages": retryable,
                "triggered": triggered}

    @app.post("/api/pdf/{pdf_id}/retry")
    def pdf_retry(pdf_id: str):
        """Retry only the failed/incomplete pages of an existing job (AC2/AC4)."""
        job = _get_pdf_job(pdf_id)
        original = pdflib.original_pdf_path(app.state.store, pdf_id)
        if not original.is_file():
            raise HTTPException(status_code=404, detail="原 PDF 缺失，无法重试。")
        retryable = job.retryable_page_indexes()
        if job.pages and not retryable and job.status == "done":
            exhausted = job.exhausted_page_indexes()
            msg = "没有可重试的页面。"
            if exhausted:
                msg = (f"{len(exhausted)} 页已达 {job.attempts_cap()} 次尝试上限，"
                       f"已停止自动重试。")
            return {"pdf_id": pdf_id, "status": job.status, "triggered": False,
                    "retryable_pages": [], "exhausted_pages": exhausted,
                    "message": msg}
        with job.lock:
            if job._running:
                return {"pdf_id": pdf_id, "status": job.status, "triggered": False,
                        "retryable_pages": retryable,
                        "message": "任务正在处理中，请稍候。"}
            job.status = "queued"
            job.error = None
            job.error_kind = None
            job._cancelled = False
        triggered = app.state.runner.trigger_pdf(job, original.read_bytes())
        return {"pdf_id": pdf_id, "status": job.status, "triggered": triggered,
                "retryable_pages": retryable,
                "max_page_attempts": job.attempts_cap()}

    @app.get("/api/pdf/{pdf_id}")
    def pdf_status(pdf_id: str):
        return _get_pdf_job(pdf_id).public()

    @app.get("/api/pdf/{pdf_id}/original")
    def pdf_original(pdf_id: str):
        job = _get_pdf_job(pdf_id)
        p = pdflib.original_pdf_path(app.state.store, pdf_id)
        if not p.is_file():
            raise HTTPException(status_code=404, detail="原 PDF 缺失。")
        return FileResponse(p, media_type="application/pdf",
                            filename=Path(job.filename).name)

    @app.get("/api/pdf/{pdf_id}/page/{page_index}")
    def pdf_page(pdf_id: str, page_index: int):
        job = _get_pdf_job(pdf_id)
        if page_index < 0 or page_index >= job.total_pages:
            raise HTTPException(status_code=404, detail="页码超出范围。")
        try:
            png = pdflib.render_pdf_page(app.state.store, pdf_id, page_index)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="原 PDF 缺失。") from None
        except IndexError:
            raise HTTPException(status_code=404, detail="页码超出范围。") from None
        except Exception:
            raise HTTPException(status_code=500, detail="无法渲染该页。") from None
        return Response(content=png, media_type="image/png")

    @app.get("/api/documents/{document_id}/source-page")
    def document_source_page(document_id: str):
        """Open the original PDF page a page-document came from (AC2)."""
        rec = _get_document(document_id)
        pdf_id = rec.get("pdf_id")
        page_index = rec.get("page_index")
        if not pdf_id or page_index is None:
            raise HTTPException(status_code=404, detail="该文档无 PDF 来源映射。")
        try:
            png = pdflib.render_pdf_page(app.state.store, pdf_id, int(page_index))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="原 PDF 缺失。") from None
        except IndexError:
            raise HTTPException(status_code=404, detail="页码超出范围。") from None
        except Exception:
            raise HTTPException(status_code=500, detail="无法渲染该页。") from None
        return Response(content=png, media_type="image/png")

    # ---- PDF content search -> original page (issue 10) ----------------------

    @app.get("/api/pdf")
    def pdf_list():
        """Imported PDFs + per-page counts (scope picker for search)."""
        with app.state.pdf_jobs_lock:
            jobs = list(app.state.pdf_jobs.values())
        jobs.sort(key=lambda j: (j.filename or "", j.pdf_id))
        return [j.summary() for j in jobs]

    @app.get("/api/search/pdf")
    def pdf_search(q: str = "", pdf_id: str | None = None, limit: int = 50):
        """Keyword search over parsed PDF pages; scope = one PDF or all (AC1)."""
        return pdfsearch.search(app.state.store, q, pdf_id=pdf_id or None,
                                limit=limit)

    @app.post("/api/search/pdf/reindex")
    def pdf_search_reindex():
        """Rebuild the keyword index from the current library (AC4)."""
        index = pdfsearch.build_index(app.state.store, persist=True)
        return {
            "indexed_documents": len(index.get("documents", {})),
            "built_at": index.get("built_at"),
            "fingerprint": index.get("fingerprint"),
        }

    # ---- PDF grounded Q&A (issue 11) ----------------------------------------

    @app.post("/api/pdf/ask")
    def pdf_ask(body: dict | None = None):
        """Grounded Q&A over parsed PDF content; multi-turn when a session is given.

        Backward compatible single-turn call: omit ``session_id``.  Pass
        ``pdf_id`` (one PDF) or ``pdf_ids`` (list; P3 scope shape) to bind the
        retrieval scope.  Session endpoints list/inspect persisted sessions.
        """
        payload = body or {}
        question = str(payload.get("question") or "").strip()
        pdf_id = payload.get("pdf_id") or None
        pdf_ids = payload.get("pdf_ids")
        session_id = payload.get("session_id")
        try:
            answer = pdfqa.answer_question(
                app.state.store,
                question,
                pdf_id=pdf_id,
                pdf_ids=pdf_ids,
                session_id=session_id,
                session_store=app.state.pdf_session_store,
                answerer=app.state.pdf_answerer,
                model=app.state.pdf_qa_model,
                provider=app.state.pdf_qa_provider,
                session=app.state.pdf_qa_session,
                timeout=app.state.pdf_qa_timeout,
                max_attempts=app.state.pdf_qa_max_attempts,
            )
        except pdfqa.QaError as exc:
            status_code = 409 if exc.kind == "scope_conflict" else 422
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        return answer.public()

    @app.get("/api/pdf/ask/sessions")
    def pdf_qa_sessions_list():
        """Persisted Q&A conversations (P1); consumed by the P2 conversation UI."""
        store = app.state.pdf_session_store
        return {
            "sessions": store.list_sessions(),
            "capacity": store.max_sessions,
            "max_context_turns": pdfqa.MAX_CONTEXT_TURNS,
            "max_session_turns": pdfqa.MAX_SESSION_TURNS,
        }

    @app.get("/api/pdf/ask/sessions/{session_id}")
    def pdf_qa_session_get(session_id: str):
        """One session with its turns and aggregate telemetry."""
        session = app.state.pdf_session_store.get(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在。")
        return session.public()

    # ---- R1 black-image repair loop -----------------------------------------
    # detect -> report -> confirm -> re-run from preprocessed_raw.png -> verify.
    # ``scan`` is read-only (no LLM call); ``run`` requires an explicit document
    # id list *and* ``confirm=true`` so a whole-library run can never be triggered
    # implicitly.

    def _get_repair_job(repair_id: str) -> repairlib.RepairJob:
        with app.state.repair_jobs_lock:
            job = app.state.repair_jobs.get(repair_id)
        if job is None:
            try:
                work_dir = repairlib.repair_dir(app.state.store, repair_id)
            except RuntimeError:
                work_dir = None
            job = repairlib.load_job(work_dir) if work_dir else None
            if job is None:
                raise HTTPException(status_code=404, detail="修复任务不存在。")
            job.mark_interrupted()
            repairlib.save_job(job)
            with app.state.repair_jobs_lock:
                existing = app.state.repair_jobs.get(repair_id)
                if existing is not None:
                    return existing
                app.state.repair_jobs[repair_id] = job
        return job

    @app.post("/api/repair/scan")
    def repair_scan(body: dict | None = None):
        payload = body or {}
        ids = payload.get("document_ids") or None
        return repairlib.scan_library(app.state.store, ids)

    @app.get("/api/repair")
    def repair_list():
        with app.state.repair_jobs_lock:
            jobs = list(app.state.repair_jobs.values())
        jobs.sort(key=lambda j: (j.created_at or 0), reverse=True)
        return [j.summary() for j in jobs]

    @app.post("/api/repair/run")
    def repair_run(body: dict | None = None):
        payload = body or {}
        raw_ids = payload.get("document_ids") or []
        ids = [str(x).strip() for x in raw_ids if str(x).strip()]
        if not ids:
            raise HTTPException(
                status_code=422,
                detail="repair run 必须携带明确的文档 id 列表（document_ids），不接受全库隐式执行。",
            )
        if payload.get("confirm") is not True:
            raise HTTPException(
                status_code=400,
                detail="repair run 需要确认参数 confirm=true 才会真实调用解析。",
            )
        unknown = [d for d in ids if app.state.store.get_document(d) is None]
        if unknown:
            raise HTTPException(status_code=404,
                                detail=f"文档不存在：{', '.join(unknown)}")

        channel = app.state.llm_settings.resolve("parse_visual")
        model = app.state.model_override or channel["model"]
        job = repairlib.create_repair_job(app.state.store, ids, model=model)
        with app.state.repair_jobs_lock:
            app.state.repair_jobs[job.repair_id] = job
        repairlib.save_job(job)
        triggered = app.state.runner.trigger_repair(job)
        return {"repair_id": job.repair_id, "status": job.status,
                "triggered": triggered, "total": len(job.items),
                "estimated_vlm_calls": job.estimated_vlm_calls}

    @app.get("/api/repair/{repair_id}")
    def repair_status(repair_id: str):
        return _get_repair_job(repair_id).public()

    @app.post("/api/repair/{repair_id}/retry")
    def repair_retry(repair_id: str):
        """Retry only the documents whose repair failed / did not verify."""
        job = _get_repair_job(repair_id)
        with job.lock:
            if job._running:
                return {"repair_id": repair_id, "triggered": False,
                        "status": job.status,
                        "retryable": job.retryable_ids(),
                        "message": "修复任务正在处理中，请稍候。"}
            retryable = []
            for item in job.items.values():
                if item.status == "failed":
                    item.status = "pending"
                    item.error = None
                    item.error_kind = None
                    item.verified = None
                    retryable.append(item.document_id)
        repairlib.save_job(job)
        triggered = app.state.runner.trigger_repair(job) if retryable else False
        return {"repair_id": repair_id, "triggered": triggered,
                "status": job.status, "retryable": retryable,
                "message": "" if retryable else "没有可重试的文档。"}

    # ---- static frontend ------------------------------------------------------

    static_dir = Path(__file__).parent / "webstatic"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/")
        def index():
            return FileResponse(str(static_dir / "index.html"))

    return app


def _safe_filename(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "-", name or "doc")
    return s or "doc"


def _ensure_writable_dir(target: str) -> Path:
    """Create the vault target dir and prove it is writable (probe write)."""
    path = Path(target).expanduser()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OSError(f"目标目录不可用：{exc}") from exc
    probe = path / ".__graph2note_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise OSError(f"目标目录不可写：{exc}") from exc
    return path


def _dir_fingerprint(root: Path) -> str:
    """Coarse snapshot of a dir's files (relative path + size), to detect
    whether a failed export already wrote/overwrote some files (partial)."""
    if not root.is_dir():
        return ""
    parts = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            try:
                parts.append(f"{p.relative_to(root)}:{p.stat().st_size}")
            except OSError:
                continue
    return "\n".join(parts)


def _vault_user_files(root: Path, managed: set[str]) -> list[str]:
    """Files under notes/mocs/collections that the exporter does not manage
    (user-created or user-renamed files that the export preserved in place)."""
    out: list[str] = []
    for top in ("notes", "mocs", "collections"):
        d = root / top
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*")):
            if p.is_file():
                rel = str(p.relative_to(root))
                if rel not in managed:
                    out.append(rel)
    return out


def _enrich_export_report(report: dict, vault, task_id: str) -> dict:
    """Turn the raw incremental report into a UI-ready report.

    ``conflicts`` becomes ``[{managed, backup}]`` with full vault-relative
    paths (the raw report only carries the backup *filename*); ``user_files``
    lists preserved user-created/renamed files so they are locatable.
    """
    conflicts = []
    for rel in report.get("conflicts", []):
        backup_name = (report.get("conflict_backups") or {}).get(rel, "")
        backup_rel = str(Path(rel).parent / backup_name) if backup_name else ""
        conflicts.append({"managed": rel, "backup": backup_rel})
    return {
        "task_id": task_id,
        "exported_at": report.get("exported_at"),
        "added": report.get("added", []),
        "updated": report.get("updated", []),
        "deleted": report.get("deleted", []),
        "unchanged": report.get("unchanged", []),
        "conflicts": conflicts,
        "kept_user": report.get("kept_user", []),
        "user_files": _vault_user_files(vault.root, set(vault.all_files)),
    }


def _looks_like_image(path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(path) as im:
            im.load()
            w, h = im.size
        if w < 16 or h < 16:  # resolution too low — reject (Edge Cases)
            return False
        return True
    except Exception:
        return False


def _validate_upload(filename: str) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的格式：仅支持 JPG/JPEG/PNG（收到 {ext or '未知'}）",
        )
    return ext


__all__ = [
    "create_app",
    "DocumentStore",
    "SessionDocumentStore",
    "FileDocumentStore",
    "Job",
    "JobRunner",
    "DEFAULT_MODEL",
    "MAX_SIZE",
    "ALLOWED_EXT",
    "JOB_TIMEOUT",
    "PDF_JOB_TIMEOUT",
]
