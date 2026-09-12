"""Black-image detection and re-parse repair loop (usable-product-iteration R1).

The perspective-homography bug (fixed in ``c6f8c52``) left legacy documents
whose ``preprocessed.png`` is a pure-black canvas; the downstream VLM then
transcribed them as "blank page".  The original upload is still intact in
``preprocessed_raw.png``, so those documents can be re-run through the fixed
pipeline without asking the user to upload again.

This module productises that repair as a closed loop:

1. **detect** — :func:`scan_library` classifies every library document from the
   *latest* version only (nothing is mutated, no LLM is called):

   * ``black`` — latest ``preprocessed.png`` grayscale mean < 10;
   * ``suspected`` — Markdown carries a "blank page" placeholder signature;
   * ``needs_reupload`` — ``preprocessed_raw.png`` is missing (cannot be
     re-run automatically and is reported separately);
   * ``healthy`` — everything else.

2. **report** — :func:`plan_repair` turns a scan into an executable plan with
   the document list, page count and an explicit VLM-call budget.

3. **confirm + run** — :func:`run_repair` / :func:`run_job` re-run each selected
   document from its ``preprocessed_raw.png`` through
   :func:`graph2note.pipeline.parse_document` (preprocess → parse → new version)
   and commit the result as a **new immutable version** on the same
   ``document_id``.  The old version — including its black ``preprocessed.png``
   and the ``preprocessed_raw.png`` — is never overwritten or deleted, so the
   repair stays reversible.

4. **verify** — each committed version is checked against the acceptance bar
   (``preprocessed.png`` mean > 150, ink ratio > 0.005 for pages that carry ink,
   Markdown not a blank placeholder).  Failures are reported per document and
   can be retried.

Durability: a repair run writes ``<storage>/repair/<repair_id>/job.json`` after
every document, so per-document results survive a reload and can be queried or
retried (same job-state pattern as the PDF batch jobs).

Provenance contract (shared with S2 evolution anchoring): every repair version
is stamped with ``provenance == "repair"`` plus a ``provenance_detail`` object
(``source``, ``repair_id``, ``old_version_id``, ``repaired_at``, ``model``).
A1 (auto-tagging) can hook the single commit site via the ``after_commit``
callback of :func:`run_job`.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# --- acceptance thresholds (R1 verification bar) ---------------------------
BLACK_MEAN_THRESHOLD = 10.0        # grayscale mean < 10 -> black canvas
HEALTHY_MEAN_TARGET = 150.0        # repaired page must be bright paper
HEALTHY_INK_TARGET = 0.005         # repaired page must retain ink
INK_PIXEL_LEVEL = 128              # pixel < 128 counts as ink

# --- provenance contract (S2 reads this) -----------------------------------
PROVENANCE_REPAIR = "repair"

# --- detection statuses ----------------------------------------------------
STATUS_BLACK = "black"
STATUS_SUSPECTED = "suspected"
STATUS_NEEDS_REUPLOAD = "needs_reupload"
STATUS_HEALTHY = "healthy"

STATUS_LABELS = {
    STATUS_BLACK: "黑图",
    STATUS_SUSPECTED: "疑似空白",
    STATUS_NEEDS_REUPLOAD: "需重新上传",
    STATUS_HEALTHY: "正常",
}

REPAIRABLE_STATUSES = (STATUS_BLACK, STATUS_SUSPECTED)
_STATUS_RANK = {
    STATUS_BLACK: 0,
    STATUS_SUSPECTED: 1,
    STATUS_NEEDS_REUPLOAD: 2,
    STATUS_HEALTHY: 3,
}

# Markdown "blank page" placeholder signatures observed in the real library
# (the VLM was fed a black canvas and answered "this page is blank").  Patterns
# stay specific so a legitimate note that merely mentions 空白 is not flagged.
_BLANK_PLACEHOLDER_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"纯黑",
        r"全黑",
        r"空白页",
        r"图像为空白",
        r"图像为纯黑",
        r"本页为空白",
        r"页面为空白",
        r"此页无内容",
        r"本页无内容",
        r"无可见文字",
        r"无可见文本",
        r"无可识别",
        r"无可辨识",
        r"无可辨认",
        r"无可读文字",
        r"无法转录",
        r"无可转录",
        r"无任何可读",
        r"未包含任何可识别",
        r"未检测到任何文字",
        r"没有可识别",
        r"图中没有可识别",
        r"没有收到任何图片",
        r"未收到任何图片",
        r"无法进行\s*Markdown\s*转录",
        r"无法进行转录",
    )
)


class RepairError(RuntimeError):
    """Raised when a repair cannot be planned or executed."""


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def looks_blank_placeholder(markdown: str | None) -> bool:
    """True when Markdown looks like a blank/black page placeholder.

    Empty Markdown is treated as suspected too: a successful parse of a real
    page never yields zero content.
    """
    text = (markdown or "").strip()
    if not text:
        return True
    return any(p.search(text) for p in _BLANK_PLACEHOLDER_PATTERNS)


def gray_stats(path: str | Path | None) -> tuple[float, float] | None:
    """Return ``(grayscale_mean, ink_ratio)`` for an image, or None if unreadable."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        import numpy as np
        from PIL import Image

        with Image.open(p) as im:
            arr = np.asarray(im.convert("L"), dtype=np.uint8)
    except Exception:
        return None
    if arr.size == 0:
        return None
    return float(arr.mean()), float((arr < INK_PIXEL_LEVEL).mean())


def _latest_version_id(rec: dict) -> str | None:
    vid = rec.get("latest_version_id")
    if vid:
        return vid
    versions = rec.get("versions") or []
    if versions and isinstance(versions[-1], dict):
        return versions[-1].get("version_id")
    return None


def _latest_paths(rec: dict) -> tuple[str | None, str | None]:
    """Latest ``(preprocessed.png, preprocessed_raw.png)`` paths.

    Handles both store shapes: :class:`FileDocumentStore` enriches a ``latest``
    block, :class:`SessionDocumentStore` keeps the full version dicts.
    """
    latest = rec.get("latest") or {}
    pp = latest.get("preprocessed_path")
    raw = latest.get("preprocessed_raw_path")
    if pp or raw:
        return pp, raw
    versions = rec.get("versions") or []
    if versions and isinstance(versions[-1], dict):
        v = versions[-1]
        return v.get("preprocessed_path"), v.get("preprocessed_raw_path")
    return None, None


def _latest_markdown(rec: dict) -> str:
    latest = rec.get("latest") or {}
    mp = latest.get("markdown_path")
    if mp and Path(mp).is_file():
        try:
            return Path(mp).read_text(encoding="utf-8")
        except OSError:
            pass
    versions = rec.get("versions") or []
    if versions and isinstance(versions[-1], dict):
        md = versions[-1].get("markdown")
        if isinstance(md, str):
            return md
    cur = rec.get("current_markdown")
    return cur if isinstance(cur, str) else ""


def _latest_original(rec: dict) -> tuple[str | None, str]:
    """Latest source-page path + extension (for the new version's original copy)."""
    latest = rec.get("latest") or {}
    op = rec.get("original_path") or latest.get("source_page_path")
    if not op:
        op = latest.get("page_path")
    ext = rec.get("original_ext") or (Path(op).suffix if op else "") or ".jpg"
    return op, ext


@dataclass
class DocumentFinding:
    """Detection result for one library document's latest version."""

    document_id: str
    title: str
    status: str
    reasons: list[str] = field(default_factory=list)
    pages: int = 1
    version_id: str | None = None
    mean: float | None = None
    ink_ratio: float | None = None
    markdown_chars: int = 0
    raw_available: bool = False
    preprocessed_path: str | None = None
    raw_path: str | None = None

    def as_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "status": self.status,
            "status_label": STATUS_LABELS.get(self.status, self.status),
            "reasons": list(self.reasons),
            "pages": self.pages,
            "estimated_vlm_calls": self.pages if self.status in REPAIRABLE_STATUSES else 0,
            "version_id": self.version_id,
            "mean": None if self.mean is None else round(self.mean, 3),
            "ink_ratio": None if self.ink_ratio is None else round(self.ink_ratio, 6),
            "markdown_chars": self.markdown_chars,
            "raw_available": self.raw_available,
            "preprocessed_path": self.preprocessed_path,
            "raw_path": self.raw_path,
            "repairable": self.status in REPAIRABLE_STATUSES,
        }


def classify_document(rec: dict) -> DocumentFinding:
    """Classify one document record (no I/O beyond reading the version files)."""
    document_id = rec.get("document_id") or ""
    pp, raw = _latest_paths(rec)
    raw_available = bool(raw) and Path(raw).is_file()
    markdown = _latest_markdown(rec)
    stats = gray_stats(pp)
    mean, ink = stats if stats is not None else (None, None)

    reasons: list[str] = []
    if not raw_available:
        status = STATUS_NEEDS_REUPLOAD
        reasons.append("preprocessed_raw_missing")
    elif stats is None:
        status = STATUS_BLACK
        reasons.append("preprocessed_missing")
    elif mean is not None and mean < BLACK_MEAN_THRESHOLD:
        status = STATUS_BLACK
        reasons.append("preprocessed_black")
    elif looks_blank_placeholder(markdown):
        status = STATUS_SUSPECTED
        reasons.append("markdown_blank_placeholder")
    else:
        status = STATUS_HEALTHY

    return DocumentFinding(
        document_id=document_id,
        title=rec.get("title") or document_id,
        status=status,
        reasons=reasons,
        pages=1,
        version_id=_latest_version_id(rec),
        mean=mean,
        ink_ratio=ink,
        markdown_chars=len(markdown or ""),
        raw_available=raw_available,
        preprocessed_path=pp,
        raw_path=raw,
    )


# ---------------------------------------------------------------------------
# Scan / plan
# ---------------------------------------------------------------------------


def scan_library(store, document_ids=None) -> dict:
    """Classify the library (or a subset) into the four R1 categories.

    Pure offline: only reads existing image/Markdown files, never calls a model.
    """
    wanted = {str(d) for d in document_ids} if document_ids else None
    findings: list[DocumentFinding] = []
    for meta in store.list_documents() or []:
        document_id = meta.get("document_id") if isinstance(meta, dict) else None
        if not document_id:
            continue
        if wanted is not None and document_id not in wanted:
            continue
        rec = store.get_document(document_id)
        if not rec:
            continue
        findings.append(classify_document(rec))

    findings.sort(key=lambda f: (_STATUS_RANK.get(f.status, 9), f.document_id))

    counts = {status: 0 for status in _STATUS_RANK}
    for f in findings:
        counts[f.status] = counts.get(f.status, 0) + 1
    repairable = [f for f in findings if f.status in REPAIRABLE_STATUSES]
    estimated = sum(f.pages for f in repairable)

    return {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "thresholds": {
            "black_mean": BLACK_MEAN_THRESHOLD,
            "healthy_mean_target": HEALTHY_MEAN_TARGET,
            "healthy_ink_target": HEALTHY_INK_TARGET,
            "ink_pixel_level": INK_PIXEL_LEVEL,
        },
        "summary": {
            "total": len(findings),
            "black": counts.get(STATUS_BLACK, 0),
            "suspected": counts.get(STATUS_SUSPECTED, 0),
            "needs_reupload": counts.get(STATUS_NEEDS_REUPLOAD, 0),
            "healthy": counts.get(STATUS_HEALTHY, 0),
            "repairable": len(repairable),
            "pages": estimated,
            "estimated_vlm_calls": estimated,
        },
        "documents": [f.as_dict() for f in findings],
        "black": [f.document_id for f in findings if f.status == STATUS_BLACK],
        "suspected": [f.document_id for f in findings if f.status == STATUS_SUSPECTED],
        "needs_reupload": [f.document_id for f in findings
                           if f.status == STATUS_NEEDS_REUPLOAD],
        "repairable": [f.document_id for f in repairable],
    }


def plan_repair(store, document_ids=None) -> dict:
    """Build the executable repair plan (dry-run friendly).

    With explicit ``document_ids`` the selection is honoured for any document
    that still has ``preprocessed_raw.png`` — including healthy ones, which the
    user may force.  Without ids, only ``black``/``suspected`` documents are
    planned.  ``needs_reupload`` documents are always reported as skipped.
    """
    report = scan_library(store)
    by_id = {f["document_id"]: f for f in report["documents"]}
    selected: list[dict] = []
    skipped: list[dict] = []

    if document_ids:
        for document_id in dict.fromkeys(str(d) for d in document_ids):
            finding = by_id.get(document_id)
            if finding is None:
                skipped.append({"document_id": document_id, "reason": "not_found"})
            elif finding["status"] == STATUS_NEEDS_REUPLOAD:
                skipped.append({"document_id": document_id,
                                "reason": "needs_reupload"})
            else:
                selected.append(finding)
    else:
        selected = [f for f in report["documents"] if f["status"] in REPAIRABLE_STATUSES]

    estimated = sum(f.get("pages", 1) for f in selected)
    return {
        "scanned_at": report["scanned_at"],
        "thresholds": report["thresholds"],
        "scan_summary": report["summary"],
        "documents": selected,
        "document_ids": [f["document_id"] for f in selected],
        "skipped": skipped,
        "pages": estimated,
        "estimated_vlm_calls": estimated,
    }


# ---------------------------------------------------------------------------
# Durable repair job state
# ---------------------------------------------------------------------------


def _safe_id(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-]", "-", name or "repair")
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "repair"


def repair_dir(store, repair_id: str) -> Path:
    """Durable directory for one repair run (job state + parse workspace)."""
    root = getattr(store, "root", None)
    if root is None:
        raise RuntimeError("document store has no filesystem root")
    return Path(root) / "repair" / _safe_id(repair_id)


@dataclass
class RepairItem:
    """Per-document repair state (durable)."""

    document_id: str
    title: str | None = None
    status: str = "pending"          # pending|processing|success|failed|skipped
    reason: str | None = None
    old_version_id: str | None = None
    new_version_id: str | None = None
    attempts: int = 0
    error: str | None = None
    error_kind: str | None = None   # parse|timeout|verify|commit|needs_reupload
    pre_mean: float | None = None
    pre_ink: float | None = None
    post_mean: float | None = None
    post_ink: float | None = None
    markdown_chars: int = 0
    blank_placeholder: bool | None = None
    verified: bool | None = None
    started_at: float | None = None
    finished_at: float | None = None

    def retryable(self) -> bool:
        return self.status in ("pending", "failed")

    def as_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "status": self.status,
            "reason": self.reason,
            "old_version_id": self.old_version_id,
            "new_version_id": self.new_version_id,
            "attempts": self.attempts,
            "error": self.error,
            "error_kind": self.error_kind,
            "pre_mean": None if self.pre_mean is None else round(self.pre_mean, 3),
            "pre_ink": None if self.pre_ink is None else round(self.pre_ink, 6),
            "post_mean": None if self.post_mean is None else round(self.post_mean, 3),
            "post_ink": None if self.post_ink is None else round(self.post_ink, 6),
            "markdown_chars": self.markdown_chars,
            "blank_placeholder": self.blank_placeholder,
            "verified": self.verified,
            "retryable": self.retryable(),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RepairItem":
        return cls(
            document_id=d["document_id"],
            title=d.get("title"),
            status=d.get("status", "pending"),
            reason=d.get("reason"),
            old_version_id=d.get("old_version_id"),
            new_version_id=d.get("new_version_id"),
            attempts=d.get("attempts", 0),
            error=d.get("error"),
            error_kind=d.get("error_kind"),
            pre_mean=d.get("pre_mean"),
            pre_ink=d.get("pre_ink"),
            post_mean=d.get("post_mean"),
            post_ink=d.get("post_ink"),
            markdown_chars=d.get("markdown_chars", 0),
            blank_placeholder=d.get("blank_placeholder"),
            verified=d.get("verified"),
            started_at=d.get("started_at"),
            finished_at=d.get("finished_at"),
        )


@dataclass
class RepairJob:
    """State of one repair run (durable via ``job.json``)."""

    repair_id: str
    status: str = "queued"          # queued|processing|done|failed|interrupted
    model: str = ""
    estimated_vlm_calls: int = 0
    vlm_calls: int = 0
    items: dict[str, RepairItem] = field(default_factory=dict)
    work_dir: str | None = None
    error: str | None = None
    error_kind: str | None = None
    created_at: float | None = None
    started_at: float | None = None
    finished_at: float | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    save_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _running: bool = field(default=False, repr=False)

    def counts(self) -> dict:
        c = {"success": 0, "failed": 0, "skipped": 0, "pending": 0, "processing": 0}
        for item in self.items.values():
            c[item.status] = c.get(item.status, 0) + 1
        return c

    def retryable_ids(self) -> list[str]:
        return [i.document_id for i in self._sorted_items() if i.status == "failed"]

    def _sorted_items(self) -> list[RepairItem]:
        order = [i["document_id"] for i in (self._order or [])]
        rank = {d: n for n, d in enumerate(order)}

        def key(item: RepairItem):
            return (rank.get(item.document_id, len(rank)), item.document_id)

        return sorted(self.items.values(), key=key)

    _order: list[dict] = field(default_factory=list, repr=False)

    def mark_interrupted(self) -> bool:
        """Reconcile a load-from-disk job that has no live worker."""
        changed = False
        with self.lock:
            if self.status in ("queued", "processing"):
                self.status = "interrupted"
                self.error = self.error or "修复任务被中断（服务重启或进程退出），可重试未完成文档。"
                self.error_kind = "interrupted"
                changed = True
            for item in self.items.values():
                if item.status == "processing":
                    item.status = "failed"
                    item.error = item.error or "上次尝试被中断，可重试。"
                    item.error_kind = "interrupted"
                    changed = True
        return changed

    def public(self) -> dict:
        with self.lock:
            items = [i.as_dict() for i in self._sorted_items()]
            counts = self.counts()
            return {
                "repair_id": self.repair_id,
                "status": self.status,
                "model": self.model,
                "error": self.error,
                "error_kind": self.error_kind,
                "estimated_vlm_calls": self.estimated_vlm_calls,
                "vlm_calls": self.vlm_calls,
                "counts": counts,
                "total": len(items),
                "items": items,
                "retryable": [i["document_id"] for i in items if i["retryable"]],
                "running": self._running,
                "interrupted": self.status == "interrupted",
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
            }

    def summary(self) -> dict:
        with self.lock:
            return {
                "repair_id": self.repair_id,
                "status": self.status,
                "model": self.model,
                "total": len(self.items),
                "counts": self.counts(),
                "estimated_vlm_calls": self.estimated_vlm_calls,
                "vlm_calls": self.vlm_calls,
                "running": self._running,
                "created_at": self.created_at,
            }

    def to_dict(self) -> dict:
        with self.lock:
            return {
                "repair_id": self.repair_id,
                "status": self.status,
                "model": self.model,
                "estimated_vlm_calls": self.estimated_vlm_calls,
                "vlm_calls": self.vlm_calls,
                "work_dir": self.work_dir,
                "error": self.error,
                "error_kind": self.error_kind,
                "created_at": self.created_at,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "order": [i.document_id for i in self._sorted_items()],
                "items": [i.as_dict() for i in self._sorted_items()],
            }

    @classmethod
    def from_dict(cls, d: dict) -> "RepairJob":
        job = cls(repair_id=d["repair_id"], status=d.get("status", "queued"),
                  model=d.get("model", ""))
        job.estimated_vlm_calls = d.get("estimated_vlm_calls", 0)
        job.vlm_calls = d.get("vlm_calls", 0)
        job.work_dir = d.get("work_dir")
        job.error = d.get("error")
        job.error_kind = d.get("error_kind")
        job.created_at = d.get("created_at")
        job.started_at = d.get("started_at")
        job.finished_at = d.get("finished_at")
        for item in d.get("items", []):
            it = RepairItem.from_dict(item)
            job.items[it.document_id] = it
        order = d.get("order") or list(job.items)
        job._order = [{"document_id": str(x)} for x in order]
        return job


def save_job(job: RepairJob) -> Path | None:
    """Persist job state atomically enough for a single-user local app."""
    if not job.work_dir:
        return None
    with job.save_lock:
        d = Path(job.work_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = d / "job.json"
        p.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p


def load_job(work_dir: str | Path) -> RepairJob | None:
    p = Path(work_dir) / "job.json"
    if not p.is_file():
        return None
    try:
        return RepairJob.from_dict(json.loads(p.read_text(encoding="utf-8")))
    except Exception:
        return None


def load_jobs(store, *, mark_interrupted: bool = True) -> list[RepairJob]:
    """Load every durable repair job under the store (app startup/reload)."""
    root = getattr(store, "root", None)
    if root is None:
        return []
    base = Path(root) / "repair"
    if not base.is_dir():
        return []
    jobs: list[RepairJob] = []
    for job_file in sorted(base.glob("*/job.json")):
        job = load_job(job_file.parent)
        if job is None:
            continue
        if mark_interrupted:
            job.mark_interrupted()
        jobs.append(job)
    return jobs


def _new_repair_id() -> str:
    return ("repair-" + time.strftime("%Y%m%d%H%M%S") + "-"
            + uuid.uuid4().hex[:6])


def create_repair_job(store, document_ids, *, model: str = "",
                      repair_id: str | None = None) -> RepairJob:
    """Build a pending job from a plan (explicit ids or all repairable docs)."""
    plan = plan_repair(store, document_ids)
    job = RepairJob(repair_id=repair_id or _new_repair_id(), model=model)
    job.created_at = time.time()
    job.work_dir = str(repair_dir(store, job.repair_id))
    job.estimated_vlm_calls = plan["estimated_vlm_calls"]
    job._order = [{"document_id": f["document_id"]} for f in plan["documents"]]
    for finding in plan["documents"]:
        job.items[finding["document_id"]] = RepairItem(
            document_id=finding["document_id"],
            title=finding.get("title"),
            old_version_id=finding.get("version_id"),
            pre_mean=finding.get("mean"),
            pre_ink=finding.get("ink_ratio"),
        )
    for skip in plan["skipped"]:
        document_id = skip["document_id"]
        if document_id in job.items:
            continue
        job.items[document_id] = RepairItem(
            document_id=document_id, status="skipped", reason=skip["reason"],
            error_kind=skip["reason"],
            error=("缺少 preprocessed_raw.png，需重新上传后修复。"
                   if skip["reason"] == "needs_reupload"
                   else "文档不存在。" if skip["reason"] == "not_found" else None))
        job._order.append({"document_id": document_id})
    return job


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _resolve_model(model: str | None) -> str:
    if model:
        return model
    try:
        from .llm_settings import resolve_channel

        return resolve_channel("parse_visual")["model"]
    except Exception:
        return "glm-5.3-flash"


def _resolve_provider(provider: str | None) -> str | None:
    if provider:
        return provider
    try:
        from .llm_settings import resolve_channel

        return resolve_channel("parse_visual")["provider"]
    except Exception:
        return None


def _build_router(router_factory, raw_path: str, model: str, provider: str | None):
    if router_factory is not None:
        return router_factory(raw_path, model)
    from . import pipeline

    return pipeline.make_router(model, provider=provider)


def _is_low_ink_page(raw_stats: tuple[float, float] | None) -> bool:
    """True when the source page itself carries no ink (genuinely blank)."""
    if raw_stats is None:
        return False
    _mean, ink = raw_stats
    return ink <= HEALTHY_INK_TARGET


def _repair_one(
    store,
    job: RepairJob,
    item: RepairItem,
    *,
    router_factory=None,
    provider: str | None = None,
    preprocess: bool = True,
    save_preprocess_stages: bool = True,
    after_commit=None,
) -> None:
    from . import pipeline
    from .ir import dumps_ir

    item.status = "processing"
    item.attempts += 1
    item.started_at = time.time()
    item.error = None
    item.error_kind = None
    save_job(job)

    rec = store.get_document(item.document_id)
    if not rec:
        item.status = "failed"
        item.error = "文档不存在或已被删除。"
        item.error_kind = "not_found"
        item.finished_at = time.time()
        save_job(job)
        return

    pp, raw = _latest_paths(rec)
    raw_path = Path(raw) if raw else None
    if raw_path is None or not raw_path.is_file():
        item.status = "skipped"
        item.reason = "needs_reupload"
        item.error = "缺少 preprocessed_raw.png，需重新上传后修复。"
        item.error_kind = "needs_reupload"
        item.finished_at = time.time()
        save_job(job)
        return

    pre_stats = gray_stats(pp)
    if pre_stats is not None:
        item.pre_mean, item.pre_ink = pre_stats
    raw_stats = gray_stats(raw_path)

    out_dir = Path(job.work_dir) / "out" / _safe_id(item.document_id)
    try:
        router = _build_router(router_factory, str(raw_path), job.model,
                               provider or _resolve_provider(None))
        result = pipeline.parse_document(
            str(raw_path),
            str(out_dir),
            model=job.model,
            router=router,
            doc_id=item.document_id,
            preprocess=preprocess,
            save_preprocess_stages=save_preprocess_stages,
        )
        job.vlm_calls += 1
    except Exception as exc:
        item.status = "failed"
        item.error = f"重跑解析失败：{exc}"
        item.error_kind = "parse"
        item.finished_at = time.time()
        save_job(job)
        return

    post_stats = gray_stats(result.preprocessed_path)
    if post_stats is not None:
        item.post_mean, item.post_ink = post_stats
    item.markdown_chars = len(result.markdown or "")
    item.blank_placeholder = looks_blank_placeholder(result.markdown)

    mean_ok = item.post_mean is not None and item.post_mean > HEALTHY_MEAN_TARGET
    ink_ok = item.post_ink is not None and item.post_ink > HEALTHY_INK_TARGET
    if _is_low_ink_page(raw_stats):
        ink_ok = True  # genuinely blank source: no ink to preserve
    item.verified = bool(mean_ok and ink_ok and not item.blank_placeholder)

    original_path, original_ext = _latest_original(rec)
    if not original_path or not Path(original_path).is_file():
        original_path = str(raw_path)
        original_ext = raw_path.suffix or ".png"

    provenance_detail = {
        "source": "preprocessed_raw",
        "repair_id": job.repair_id,
        "old_version_id": item.old_version_id,
        "repaired_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "model": job.model,
    }
    try:
        rec_after = store.save_document(
            document_id=item.document_id,
            title=rec.get("title") or item.title or item.document_id,
            source_job_id=f"repair-{job.repair_id}",
            model=job.model,
            markdown=result.markdown,
            ir_json=dumps_ir(result.ir),
            original_path=str(original_path),
            original_ext=original_ext,
            preprocessed_path=result.preprocessed_path,
            preprocessed_raw_path=result.preprocessed_raw_path,
            assets_dir=result.assets_dir,
            timing_json=result.timing_json,
            pg_hash=rec.get("hash") or rec.get("current_hash") or "",
            metadata=None,
            source_pdf=rec.get("source_pdf"),
            pdf_id=rec.get("pdf_id"),
            page_index=rec.get("page_index"),
            page_number=rec.get("page_number"),
            provenance=PROVENANCE_REPAIR,
            provenance_detail=provenance_detail,
        )
    except Exception as exc:
        item.status = "failed"
        item.error = f"入库失败：{exc}"
        item.error_kind = "commit"
        item.finished_at = time.time()
        save_job(job)
        return

    item.new_version_id = _latest_version_id(rec_after or {}) or item.new_version_id
    if item.verified:
        item.status = "success"
        item.error = None
        item.error_kind = None
    else:
        item.status = "failed"
        item.error_kind = "verify"
        problems = []
        if not mean_ok:
            problems.append(f"均值 {item.post_mean} 未超过 {HEALTHY_MEAN_TARGET}")
        if not ink_ok:
            problems.append(f"墨迹占比 {item.post_ink} 未超过 {HEALTHY_INK_TARGET}")
        if item.blank_placeholder:
            problems.append("Markdown 仍为空白页占位")
        item.error = "验收未通过：" + "；".join(problems)
    item.finished_at = time.time()

    # A1 seam: single commit hook, called after the new version is durable.
    if after_commit is not None and item.status in ("success", "failed"):
        try:
            after_commit(store, item.document_id, result, rec_after)
        except Exception as exc:  # tagging must never break the repair loop
            item.error = (item.error + " " if item.error else "") + f"后置打标失败：{exc}"
    save_job(job)


def run_job(
    store,
    job: RepairJob,
    *,
    router_factory=None,
    provider: str | None = None,
    preprocess: bool = True,
    save_preprocess_stages: bool = True,
    after_commit=None,
    only=None,
) -> RepairJob:
    """Execute (or resume) a repair job; per-document results are checkpointed."""
    if not job.work_dir:
        job.work_dir = str(repair_dir(store, job.repair_id))
    only_set = {str(d) for d in only} if only else None

    with job.lock:
        if job.started_at is None:
            job.started_at = time.time()
        job.status = "processing"
        job.error = None
        job.error_kind = None
    save_job(job)

    for item in list(job.items.values()):
        if only_set is not None and item.document_id not in only_set:
            continue
        if not item.retryable():
            continue
        _repair_one(
            store, job, item, router_factory=router_factory, provider=provider,
            preprocess=preprocess, save_preprocess_stages=save_preprocess_stages,
            after_commit=after_commit,
        )

    counts = job.counts()
    with job.lock:
        job.finished_at = time.time()
        attempted = counts.get("success", 0) + counts.get("failed", 0)
        if attempted and counts.get("failed", 0) == attempted:
            job.status = "failed"
            job.error = "全部文档修复失败，可重试。"
            job.error_kind = "failed"
        else:
            job.status = "done"
            if counts.get("failed", 0):
                job.error = f"{counts['failed']} 篇验收未通过，可重试。"
                job.error_kind = "partial"
    save_job(job)

    report_path = Path(job.work_dir) / "report.json"
    try:
        report_path.write_text(
            json.dumps(job.public(), ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass
    return job


def run_repair(
    store,
    document_ids=None,
    *,
    model: str | None = None,
    provider: str | None = None,
    router_factory=None,
    preprocess: bool = True,
    after_commit=None,
) -> RepairJob:
    """Plan + execute a repair run (explicit ids or all repairable documents).

    This is the synchronous CLI/scripting entry point.  The web app uses
    :func:`create_repair_job` + :func:`run_job` for background progress polling.
    """
    resolved_model = _resolve_model(model)
    job = create_repair_job(store, document_ids, model=resolved_model)
    return run_job(
        store, job, router_factory=router_factory, provider=provider,
        preprocess=preprocess, after_commit=after_commit,
    )


__all__ = [
    "BLACK_MEAN_THRESHOLD",
    "HEALTHY_MEAN_TARGET",
    "HEALTHY_INK_TARGET",
    "INK_PIXEL_LEVEL",
    "PROVENANCE_REPAIR",
    "STATUS_BLACK",
    "STATUS_SUSPECTED",
    "STATUS_NEEDS_REUPLOAD",
    "STATUS_HEALTHY",
    "STATUS_LABELS",
    "REPAIRABLE_STATUSES",
    "RepairError",
    "DocumentFinding",
    "RepairItem",
    "RepairJob",
    "looks_blank_placeholder",
    "gray_stats",
    "classify_document",
    "scan_library",
    "plan_repair",
    "repair_dir",
    "save_job",
    "load_job",
    "load_jobs",
    "create_repair_job",
    "run_job",
    "run_repair",
]
