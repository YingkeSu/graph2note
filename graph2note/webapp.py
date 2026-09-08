"""Local single-user Web app: upload -> three-pane review/edit -> copy/export.

FastAPI backend wrapping ``pipeline.parse_document`` (issue 03) and the
attachment/assets organization (issue 05).  Personal/local-only: single user,
no auth, bind-free (serve on 127.0.0.1).

Scope guard: issue 07 (durable document library) is intentionally NOT built
here.  This module keeps all state in a per-process in-memory
``SessionDocumentStore`` and exposes a narrow offline-tested HTTP API; issue 07
will swap in a durable store via the ``DocumentStore`` persistence seam.

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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .attachments import missing_attachments
from . import pipeline

DEFAULT_MODEL = os.environ.get("GRAPH2NOTE_MODEL", "glm-5.3-flash")
MAX_SIZE = 10 * 1024 * 1024  # 10 MB (FR-015)
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}
# Server-side single page budget (FR-025 target P95 <= 60s; allow slack for
# the gateway + a retry).  On expiry the job fails with a clear "timeout".
JOB_TIMEOUT = int(os.environ.get("GRAPH2NOTE_JOB_TIMEOUT", "180"))


# ---------------------------------------------------------------------------
# Persistence seam (issue 07 will provide a durable implementation)
# ---------------------------------------------------------------------------


class DocumentStore(ABC):
    @abstractmethod
    def job_out_dir(self, job_id: str) -> Path:
        """Directory where this job's parse artifacts are written."""

    @abstractmethod
    def save_original(self, job_id: str, data: bytes, ext: str) -> Path:
        """Persist the uploaded original; return its path."""

    @abstractmethod
    def get_original(self, job_id: str) -> Path | None:
        """Path to the stored original, or None."""

    @abstractmethod
    def remove(self, job_id: str) -> None:
        """Remove all artifacts for a job (issue 07 delete path)."""


class SessionDocumentStore(DocumentStore):
    """Per-process in-memory/session store (MVP; not durable across restarts).

    Writes parse artifacts under ``storage_dir/<job_id>/`` so a later issue-07
    durable store can simply own/scan the same layout.
    """

    def __init__(self, storage_dir: str | Path):
        self.root = Path(storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def job_out_dir(self, job_id: str) -> Path:
        d = self.root / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_original(self, job_id: str, data: bytes, ext: str) -> Path:
        out = self.job_out_dir(job_id)
        p = out / f"original{ext}"
        p.write_bytes(data)
        return p

    def get_original(self, job_id: str) -> Path | None:
        matches = list(self.job_out_dir(job_id).glob("original.*"))
        return matches[0] if matches else None

    def remove(self, job_id: str) -> None:
        d = self.root / job_id
        if d.exists():
            import shutil

            shutil.rmtree(d, ignore_errors=True)


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------


@dataclass
class Job:
    job_id: str
    model: str
    original_ext: str
    status: str = "queued"          # queued|processing|done|failed|timeout
    error: str | None = None
    error_kind: str | None = None   # invalid|failed|timeout
    markdown: str | None = None
    doc_id: str | None = None
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
                "warnings": list(self.warnings),
                "degraded": list(self.degraded),
                "timing": self.timing,
                "model": self.model,
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

        if app.state.router_factory is not None:
            router = app.state.router_factory(str(original), app.state.model)
        else:
            router = pipeline.make_router(
                app.state.model, max_retries=app.state.max_retries
            )

        result = pipeline.parse_document(
            str(original),
            str(out_dir),
            model=app.state.model,
            router=router,
            doc_id=job.doc_id,
            preprocess=True,
            save_preprocess_stages=True,
        )

        with job.lock:
            if job._cancelled:
                return  # timed out or superseded — ignore late completion
            job.status = "done"
            job.markdown = result.markdown
            job.doc_id = result.markdown_path and Path(result.markdown_path).stem
            job.preprocessed_path = result.preprocessed_path
            job.assets_dir = result.assets_dir
            job.out_dir = str(out_dir)
            job.warnings = list(result.route.warnings)
            job.degraded = list(result.route.degraded_block_indices)
            job.timing = result.timing_json


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    *,
    model: str = DEFAULT_MODEL,
    storage_dir: str | Path | None = None,
    document_store: DocumentStore | None = None,
    router_factory=None,
    max_retries: int = 1,
) -> FastAPI:
    """Build the FastAPI app.

    ``router_factory(image_path, model) -> RecognitionRouter`` lets tests inject
    an offline (golden/cache) router; when None, the real pipeline router with a
    VLM gateway is used.  ``document_store`` is the issue-07 persistence seam.
    """
    storage_dir = storage_dir or os.environ.get("GRAPH2NOTE_STORAGE", "./.g2n-storage")
    store = document_store or SessionDocumentStore(storage_dir)

    app = FastAPI(title="graph2note", docs_url=None, redoc_url=None)
    app.state.store = store
    app.state.jobs: dict[str, Job] = {}
    app.state.jobs_lock = threading.Lock()
    app.state.model = model
    app.state.max_retries = max_retries
    app.state.router_factory = router_factory
    app.state.runner = JobRunner(app)

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
        original = store.save_original(job_id, data, ext)
        if not _looks_like_image(original):
            store.remove(job_id)
            raise HTTPException(status_code=415, detail="文件不是有效的 JPG/JPEG/PNG 图片。")

        job = Job(job_id=job_id, model=model, original_ext=ext)
        with app.state.jobs_lock:
            app.state.jobs[job_id] = job
        app.state.runner.trigger(job)
        return {"job_id": job_id, "status": job.status, "model": model}

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
    "Job",
    "JobRunner",
    "DEFAULT_MODEL",
    "MAX_SIZE",
    "ALLOWED_EXT",
    "JOB_TIMEOUT",
]
