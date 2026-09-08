"""Durable local document library (issue 07).

Adds a file-system-backed ``DocumentRecord`` lifecycle on top of the issue-06
upload/parse seam.  Personal, local, single-user: plain directories, no
database.

On-disk layout under the storage root::

    storage/
      jobs/<job_id>/            <- transient parse workspace (issue 06 seam)
        original.<ext>
        out/...
      documents/<document_id>/  <- durable library records (issue 07)
        original.<ext>          <- copy of the uploaded page
        record.json             <- metadata + historical version index
        markdown.md             <- LIVE (user-edited) markdown
        versions/<version_id>/  <- one immutable snapshot per successful parse
          markdown.md           <- parsed markdown at that version
          ir.json               <- Document IR (canonical)
          preprocessed.png
          preprocessed_raw.png
          assets/               <- attachment files (referenced as assets/<name>)
          timing.json

A successful parse commits a new immutable *version* into an existing
``DocumentRecord`` (same image -> same ``document_id`` -> versions accumulate,
latest is default; candidate-version semantics of FR-022 in minimal form).
Failures/timeouts never produce a library record (no half-finished docs).
Edited markdown autosaves to ``markdown.md`` so a reload reopens the latest
edits.  Deleting a document removes its whole directory (original, IR, MD,
attachments, versions) plus its originating job workspace, leaving no orphans.

``SessionDocumentStore`` keeps the same seam but holds documents in memory only
(non-durable, for tests that don't require reload persistence).
"""

from __future__ import annotations

import json
import re
import shutil
import time
from abc import ABC, abstractmethod
from pathlib import Path


def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-]", "-", name or "doc")
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "doc"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


class DocumentStore(ABC):
    """Job workspace seam (issue 06) + durable document library (issue 07)."""

    # --- job workspace (issue 06) ---------------------------------------------
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
        """Remove all artifacts for a job."""

    # --- document library (issue 07) ------------------------------------------
    @abstractmethod
    def list_documents(self) -> list[dict]:
        """Metadata for every library document (list page)."""

    @abstractmethod
    def get_document(self, document_id: str) -> dict | None:
        """Full record (paths + current markdown + versions) or None."""

    @abstractmethod
    def save_document(self, *, document_id, title, source_job_id, model,
                      markdown, ir_json, original_path, original_ext,
                      preprocessed_path, preprocessed_raw_path, assets_dir,
                      timing_json) -> dict:
        """Commit a successful parse as the latest version of a record."""

    @abstractmethod
    def save_edits(self, document_id: str, markdown: str) -> dict | None:
        """Persist (autosave) edited markdown; return updated record or None."""

    @abstractmethod
    def set_topics(self, document_id: str, topics: list[str]) -> dict | None:
        """Persist the document's topic tags (notes-organizer classification).

        Returns the updated record or None if unknown. Does not touch
        ``updated_at`` (classification is metadata, not a content edit, so it
        must not re-order the library list).
        """

    @abstractmethod
    def delete_document(self, document_id: str) -> bool:
        """Remove a document entirely; True if it existed."""


# ---------------------------------------------------------------------------
# In-memory session store (same seam, non-durable)
# ---------------------------------------------------------------------------


class SessionDocumentStore(DocumentStore):
    def __init__(self, storage_dir: str | Path):
        self.root = Path(storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._docs: dict[str, dict] = {}

    # --- job workspace ---------------------------------------------------------
    def job_out_dir(self, job_id: str) -> Path:
        d = self.root / "jobs" / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save_original(self, job_id: str, data: bytes, ext: str) -> Path:
        out = self.job_out_dir(job_id)
        p = out / f"original{ext}"
        p.write_bytes(data)
        return p

    def get_original(self, job_id: str) -> Path | None:
        d = self.root / "jobs" / job_id
        if not d.is_dir():
            return None
        matches = list(d.glob("original.*"))
        return matches[0] if matches else None

    def remove(self, job_id: str) -> None:
        shutil.rmtree(self.root / "jobs" / job_id, ignore_errors=True)

    # --- document library ------------------------------------------------------
    def list_documents(self) -> list[dict]:
        return [
            {k: d[k] for k in ("document_id", "title", "created_at",
                               "updated_at", "versions")}
            for d in self._docs.values()
        ]

    def get_document(self, document_id: str) -> dict | None:
        return self._docs.get(document_id)

    def save_document(self, *, document_id, title, source_job_id, model,
                      markdown, ir_json, original_path, original_ext,
                      preprocessed_path, preprocessed_raw_path, assets_dir,
                      timing_json) -> dict:
        now = _now()
        version_id = f"v{int(time.time() * 1000)}"
        rec = self._docs.get(document_id)
        if rec is None:
            rec = {
                "document_id": document_id,
                "title": title,
                "created_at": now,
                "source_job_id": source_job_id,
                "original_ext": original_ext,
                "original_path": original_path,
                "current_markdown": markdown,
                "current_markdown_path": None,
                "versions": [],
            }
        rec["updated_at"] = now
        rec["current_markdown"] = markdown
        rec["versions"].append({
            "version_id": version_id,
            "created_at": now,
            "model": model,
            "markdown": markdown,
            "ir_json": ir_json,
            "preprocessed_path": preprocessed_path,
            "preprocessed_raw_path": preprocessed_raw_path,
            "assets_dir": assets_dir,
            "timing_json": timing_json,
        })
        self._docs[document_id] = rec
        return rec

    def save_edits(self, document_id: str, markdown: str) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        rec["current_markdown"] = markdown
        rec["updated_at"] = _now()
        self._docs[document_id] = rec
        return rec

    def set_topics(self, document_id: str, topics: list[str]) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        rec["topics"] = list(topics)
        self._docs[document_id] = rec
        return rec

    def delete_document(self, document_id: str) -> bool:
        rec = self._docs.pop(document_id, None)
        if rec is None:
            return False
        if rec.get("source_job_id"):
            self.remove(rec["source_job_id"])
        return True


# ---------------------------------------------------------------------------
# File-system backed (durable) store
# ---------------------------------------------------------------------------


class FileDocumentStore(SessionDocumentStore):
    """Durable variant of :class:`SessionDocumentStore`.

    Records live under ``<root>/documents/<document_id>/`` and are re-scanable
    on process restart, so a page reload reopens the latest edits.
    """

    def _doc_dir(self, document_id: str) -> Path:
        d = self.root / "documents" / _safe(document_id)
        return d

    # --- library (durable) ------------------------------------------------------
    def list_documents(self) -> list[dict]:
        items = []
        docs = self.root / "documents"
        if not docs.is_dir():
            return []
        for p in sorted(docs.iterdir(), key=lambda d: d.stat().st_mtime,
                         reverse=True):
            r = self._read_record(p.name)
            if r:
                items.append({
                    "document_id": r["document_id"],
                    "title": r["title"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "version_count": len(r["versions"]),
                })
        return items

    def _read_record(self, document_id: str) -> dict | None:
        rp = self._doc_dir(document_id) / "record.json"
        if not rp.is_file():
            return None
        try:
            return json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            return None

    def get_document(self, document_id: str) -> dict | None:
        rec = self._read_record(document_id)
        if rec is None:
            return None
        rec = dict(rec)  # shallow copy
        base = self._doc_dir(document_id)
        rec["document_id"] = document_id
        rec["original_path"] = str(self._find_original(base))
        vdir = base / "versions" / rec.get("latest_version", "")
        rec["current_markdown_path"] = str(base / "markdown.md")
        latest = rec.get("versions") or []
        if latest:
            lv = latest[-1]
            rec["latest"] = {
                "version_id": lv["version_id"],
                "created_at": lv["created_at"],
                "model": lv["model"],
                "markdown_path": str(vdir / "markdown.md"),
                "ir_path": str(vdir / "ir.json"),
                "preprocessed_path": str(vdir / "preprocessed.png"),
                "preprocessed_raw_path": str(vdir / "preprocessed_raw.png"),
                "assets_root": str(vdir),
                "timing_path": str(vdir / "timing.json"),
            }
        # live (edited) markdown
        mp = base / "markdown.md"
        rec["current_markdown"] = mp.read_text(encoding="utf-8") if mp.is_file() else (
            (vdir / "markdown.md").read_text(encoding="utf-8")
            if (vdir / "markdown.md").is_file() else ""
        )
        return rec

    def _find_original(self, base: Path) -> Path | None:
        m = list(base.glob("original.*"))
        return m[0] if m else None

    def save_document(self, *, document_id, title, source_job_id, model,
                      markdown, ir_json, original_path, original_ext,
                      preprocessed_path, preprocessed_raw_path, assets_dir,
                      timing_json) -> dict:
        document_id = _safe(document_id)
        base = self._doc_dir(document_id)
        base.mkdir(parents=True, exist_ok=True)
        now = _now()
        version_id = f"v{int(time.time() * 1000)}"
        vdir = base / "versions" / version_id
        (vdir / "assets").mkdir(parents=True, exist_ok=True)

        # copy attachments from the parse assets leaf into this version
        astleaf = Path(assets_dir) / "assets"
        if astleaf.is_dir():
            _copy_dir_files(astleaf, vdir / "assets")

        (vdir / "markdown.md").write_text(markdown, encoding="utf-8")
        (vdir / "ir.json").write_text(ir_json, encoding="utf-8")
        (vdir / "timing.json").write_text(
            json.dumps(timing_json or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _copy_if_exists(preprocessed_path, vdir / "preprocessed.png")
        _copy_if_exists(preprocessed_raw_path, vdir / "preprocessed_raw.png")

        # record.json
        rec = self._read_record(document_id) or {
            "document_id": document_id,
            "title": title,
            "created_at": now,
            "source_job_id": source_job_id,
            "original_ext": original_ext,
        }
        rec["title"] = title or rec.get("title", document_id)
        rec["updated_at"] = now
        rec["source_job_id"] = source_job_id
        rec["original_ext"] = original_ext
        rec["latest_version"] = version_id
        versions = rec.setdefault("versions", [])
        versions.append({
            "version_id": version_id,
            "created_at": now,
            "model": model,
        })
        rec["versions"] = versions
        (base / "record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

        # keep original copy + live markdown
        _copy_if_exists(str(original_path), base / f"original{original_ext}")
        (base / "markdown.md").write_text(markdown, encoding="utf-8")
        # remove the just-created version dir copy leaving only tracked assets
        return self.get_document(document_id) or rec

    def save_edits(self, document_id: str, markdown: str) -> dict | None:
        base = self._doc_dir(document_id)
        if not (base / "record.json").is_file():
            return None
        (base / "markdown.md").write_text(markdown, encoding="utf-8")
        rec = self._read_record(document_id)
        if rec is not None:
            rec["updated_at"] = _now()
            (base / "record.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_document(document_id)

    def set_topics(self, document_id: str, topics: list[str]) -> dict | None:
        rp = self._doc_dir(document_id) / "record.json"
        if not rp.is_file():
            return None
        rec = self._read_record(document_id)
        if rec is None:
            return None
        rec["topics"] = list(topics)
        rp.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        return rec

    def delete_document(self, document_id: str) -> bool:
        rec = self._read_record(document_id)
        d = self._doc_dir(document_id)
        existed = d.is_dir()
        shutil.rmtree(d, ignore_errors=True)
        if rec and rec.get("source_job_id"):
            self.remove(rec["source_job_id"])
        return existed


def _copy_if_exists(src: str | None, dst: Path) -> None:
    if src and Path(src).is_file():
        try:
            shutil.copy2(src, dst)
        except OSError:
            pass


def _copy_dir_files(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            try:
                shutil.copy2(str(f), dst / f.name)
            except OSError:
                pass


__all__ = [
    "DocumentStore",
    "SessionDocumentStore",
    "FileDocumentStore",
]