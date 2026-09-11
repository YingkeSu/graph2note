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
from .store import (
    DocumentStore,
    FileDocumentStore,
    SessionDocumentStore,
)
from . import config
from . import pipeline

DEFAULT_MODEL = os.environ.get("GRAPH2NOTE_MODEL", "glm-5.3-flash")
MAX_SIZE = 10 * 1024 * 1024  # 10 MB (FR-015)
ALLOWED_EXT = {".jpg", ".jpeg", ".png"}
# Server-side single page budget (FR-025 target P95 <= 60s; allow slack for
# the gateway + a retry).  On expiry the job fails with a clear "timeout".
JOB_TIMEOUT = int(os.environ.get("GRAPH2NOTE_JOB_TIMEOUT", "180"))


# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------


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
) -> FastAPI:
    """Build the FastAPI app.

    ``router_factory(image_path, model) -> RecognitionRouter`` lets tests inject
    an offline (golden/cache) router; when None, the real pipeline router with a
    VLM gateway is used.  ``document_store`` is the issue-07 persistence seam.
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
            return documents
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
        return filtered

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
        return build_stats(records, now=now, price_table=app.state.price_table)

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
        return {"document_id": document_id, "tags": rec.get("tags", [])}

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
        return {"document_id": document_id, "tags": rec.get("tags", [])}

    @app.delete("/api/documents/{document_id}/tags/{tag}")
    def document_remove_tag(document_id: str, tag: str):
        rec = _get_document(document_id)
        kept = [item for item in (rec.get("tags") or []) if item != tag]
        try:
            updated = store.set_tags(document_id, kept)
        except (TagError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"document_id": document_id, "tags": updated.get("tags", [])}

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
]
