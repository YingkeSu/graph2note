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

from .metadata import (
    apply_metadata_updates,
    ensure_record_metadata,
    extract_headline,
    merge_record_metadata,
)
from .collections import (
    CollectionError,
    apply_topic_defaults,
    collection_entries,
    collection_id_for,
    ensure_collection,
    new_registry,
    normalize_registry,
    set_manual_memberships,
)
from .tags import (
    TagError,
    canonicalize_tags,
    merge_vocabulary_tags,
    new_vocabulary,
    rename_vocabulary_tag,
    resolve_tag,
    validate_tag_inference,
    vocabulary_entries,
)
from .telemetry import normalize_telemetry

MANUAL_TAG_PROVENANCE = "manual"
AUTO_TAG_PROVENANCE = "auto"


def ensure_tag_provenance(record: dict) -> dict[str, str]:
    """Return a tag->provenance map aligned with ``record['tags']``.

    Legacy records (and tags added before A1) have no provenance entry and are
    treated as ``manual``: the conservative default, since only tags the auto
    pipeline explicitly added carry the ``auto`` marker.
    """

    tags = list(record.get("tags") or [])
    raw = record.get("tag_provenance")
    provenance = dict(raw) if isinstance(raw, dict) else {}
    for key in list(provenance):
        if key not in tags:
            provenance.pop(key, None)
    for tag in tags:
        provenance.setdefault(tag, MANUAL_TAG_PROVENANCE)
    record["tags"] = tags
    record["tag_provenance"] = provenance
    return provenance


def _merge_tag_provenance(
    record: dict,
    added: list[str],
    provenance: str,
) -> dict[str, str]:
    """Append ``added`` tags to a record, keeping the stronger provenance.

    An existing ``manual`` tag never gets downgraded by a later auto pass (the
    user's explicit choice wins); a tag that only ever came from auto stays
    ``auto`` unless the user promotes it.
    """

    current = ensure_tag_provenance(record)
    tags = record["tags"]
    for tag in added:
        if tag not in tags:
            tags.append(tag)
        if current.get(tag) != MANUAL_TAG_PROVENANCE or provenance == MANUAL_TAG_PROVENANCE:
            current[tag] = provenance
    record["tags"] = tags
    record["tag_provenance"] = current
    return current


def _safe(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-]", "-", name or "doc")
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "doc"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _library_summary_fields(record: dict) -> dict:
    """U2 additive fields for ``/api/documents`` summaries (never removes).

    The card needs a readable headline, tag chips and source provenance; all
    of these already live on the record.  ``version_count`` is normalised here
    so both stores expose the same key.
    """

    markdown = record.get("current_markdown")
    if markdown is None:
        markdown = record.get("markdown")
    return {
        "headline": extract_headline(markdown),
        "tags": list(record.get("tags") or []),
        "source_pdf": record.get("source_pdf"),
        "page_number": record.get("page_number"),
        "version_count": len(record.get("versions") or []),
    }


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
                      timing_json, metadata=None, source_pdf=None, pdf_id=None,
                      page_index=None, page_number=None, provenance=None,
                      provenance_detail=None) -> dict:
        """Commit a successful parse as the latest version of a record.

        ``source_pdf`` / ``pdf_id`` / ``page_index`` / ``page_number`` carry the
        PDF provenance (issue 08) so a page document can be traced back to its
        page in the original PDF, and the mapping survives a reload.

        ``provenance`` labels how this version was produced (e.g. ``"repair"``
        for R1 black-image re-runs); ``provenance_detail`` carries the matching
        evidence.  Both are stored on the version itself so the evolution
        anchoring work (S2) can classify a version chain without guessing.
        """

    @abstractmethod
    def save_edits(self, document_id: str, markdown: str) -> dict | None:
        """Persist (autosave) edited markdown; return updated record or None."""

    @abstractmethod
    def update_metadata(self, document_id: str, updates: dict) -> dict | None:
        """Persist user-managed document metadata without making a new version."""

    @abstractmethod
    def list_tags(self) -> list[dict]:
        """Return vocabulary entries with aliases and document usage counts."""

    @abstractmethod
    def create_tag(self, tag: str) -> list[dict]:
        """Create/reuse a vocabulary entry without assigning it to a document."""

    @abstractmethod
    def set_tags(self, document_id: str, tags: list[str]) -> dict | None:
        """Replace a document's fine-grained tags after normalization."""

    @abstractmethod
    def add_auto_tags(self, document_id: str, raw_tags) -> dict | None:
        """Validate and append recorded auto-tag output (provenance=auto)."""

    @abstractmethod
    def add_manual_tags(self, document_id: str, raw_tags) -> dict | None:
        """Append user-entered tags (provenance=manual)."""

    @abstractmethod
    def promote_tag(self, document_id: str, tag: str) -> dict | None:
        """Mark one existing tag as manual (user kept an auto suggestion)."""

    @abstractmethod
    def remove_tag(self, document_id: str, tag: str) -> dict | None:
        """Remove one tag without dropping it from the vocabulary."""

    @abstractmethod
    def tag_vocabulary(self) -> dict:
        """Current normalized vocabulary (canonical names + aliases)."""

    @abstractmethod
    def add_tag_alias(self, tag: str, alias: str) -> list[dict]:
        """Attach one alias to an existing canonical tag."""

    @abstractmethod
    def set_auto_tag_meta(self, document_id: str, payload: dict) -> dict | None:
        """Persist the last auto-tag inference result/telemetry on a record."""

    @abstractmethod
    def rename_tag(self, source: str, target: str) -> list[dict]:
        """Rename a vocabulary tag and update all document memberships."""

    @abstractmethod
    def merge_tags(self, source: str, target: str) -> list[dict]:
        """Merge one vocabulary tag into another."""

    @abstractmethod
    def list_collections(self) -> list[dict]:
        """Return collections with stable ids, folders, and document counts."""

    @abstractmethod
    def create_collection(self, name: str) -> dict:
        """Create or reject a duplicate logical collection."""

    @abstractmethod
    def rename_collection(self, collection_id: str, name: str) -> dict:
        """Rename a collection and update memberships without moving files."""

    @abstractmethod
    def delete_collection(self, collection_id: str) -> bool:
        """Delete a logical collection and detach its documents."""

    @abstractmethod
    def set_collections(self, document_id: str, collection_ids: list[str]) -> dict | None:
        """Replace manual collection memberships for one document."""

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

    # --- ingest/store bridge (issue 13) ---------------------------------------
    @abstractmethod
    def document_hashes(self) -> dict:
        """``{document_id: pg_hash}`` for every record (near-dup matching)."""

    @abstractmethod
    def version_hashes(self, document_id: str) -> list:
        """Candidate-version metadata (hashes + content) for one record."""

    @abstractmethod
    def remove_versions(self, document_id: str, version_ids: list) -> bool:
        """Drop candidate versions (used when splitting a false merge)."""

    # --- evolution anchoring (S2) ---------------------------------------------
    @abstractmethod
    def set_manual_relations(self, document_id: str, relations: list) -> dict | None:
        """Replace the document's persisted manual relation edges (S2).

        These are the user-confirmed "same manuscript evolution" links the
        graph projects as ``manual`` edges; nothing inferred is ever written
        here.
        """


# ---------------------------------------------------------------------------
# In-memory session store (same seam, non-durable)
# ---------------------------------------------------------------------------


class SessionDocumentStore(DocumentStore):
    def __init__(self, storage_dir: str | Path):
        self.root = Path(storage_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        self._docs: dict[str, dict] = {}
        self._tag_vocab = new_vocabulary()
        self._collection_registry = new_registry()

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
        items = []
        for record in self._docs.values():
            record, _ = ensure_record_metadata(
                record,
                original_path=record.get("original_path"),
                markdown=record.get("current_markdown"),
            )
            ensure_tag_provenance(record)
            apply_topic_defaults(record, self._collection_registry)
            items.append({
                k: record[k] for k in ("document_id", "title", "created_at",
                                       "updated_at", "versions")
            } | {
                "metadata": record.get("metadata"),
                "effective_time": record.get("effective_time"),
                "collections": list(record.get("collections") or []),
                **_library_summary_fields(record),
            })
        return items

    def get_document(self, document_id: str) -> dict | None:
        record = self._docs.get(document_id)
        if record is None:
            return None
        record, _ = ensure_record_metadata(
            record,
            original_path=record.get("original_path"),
            markdown=record.get("current_markdown"),
        )
        ensure_tag_provenance(record)
        for version in record.get("versions") or []:
            if isinstance(version, dict) and "telemetry" not in version:
                version["telemetry"] = normalize_telemetry(
                    version.get("timing_json"), model=version.get("model")
                )
        apply_topic_defaults(record, self._collection_registry)
        return record

    def save_document(self, *, document_id, title, source_job_id, model,
                      markdown, ir_json, original_path, original_ext,
                      preprocessed_path, preprocessed_raw_path, assets_dir,
                      timing_json, pg_hash="", metadata=None, source_pdf=None,
                      pdf_id=None, page_index=None, page_number=None,
                      provenance=None, provenance_detail=None) -> dict:
        now = _now()
        rec = self._docs.get(document_id)
        version_id = f"v{int(time.time() * 1000)}-{len(rec.get('versions')) if rec else 0}"
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
                "tags": [],
            }
        rec["source_pdf"] = source_pdf
        rec["pdf_id"] = pdf_id
        rec["page_index"] = page_index
        rec["page_number"] = page_number
        rec["updated_at"] = now
        rec["current_markdown"] = markdown
        rec["current_hash"] = pg_hash  # issue 13: perceptual hash of the page
        rec.setdefault("tags", [])
        apply_topic_defaults(rec, self._collection_registry)
        rec["latest_version"] = version_id
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
            "telemetry": normalize_telemetry(timing_json, model=model),
            "pg_hash": pg_hash,
            "original_path": original_path,
            "original_ext": original_ext,
            **({"provenance": provenance} if provenance is not None else {}),
            **({"provenance_detail": provenance_detail}
               if provenance_detail is not None else {}),
            "current": True,  # refreshed below to be exact
        })
        for i, v in enumerate(rec["versions"]):
            v["current"] = (v["version_id"] == rec["latest_version"])
        merge_record_metadata(
            rec,
            markdown=markdown,
            original_path=original_path,
            import_time=rec.get("created_at") or now,
            modified_time=now,
            candidate=metadata,
        )
        self._docs[document_id] = rec
        return rec

    def save_edits(self, document_id: str, markdown: str) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        rec["current_markdown"] = markdown
        now = _now()
        rec["updated_at"] = now
        merge_record_metadata(
            rec,
            markdown=markdown,
            original_path=rec.get("original_path"),
            import_time=rec.get("created_at") or now,
            modified_time=now,
        )
        self._docs[document_id] = rec
        return rec

    def update_metadata(self, document_id: str, updates: dict) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        ensure_record_metadata(
            rec,
            original_path=rec.get("original_path"),
            markdown=rec.get("current_markdown"),
        )
        apply_metadata_updates(rec, updates)
        self._docs[document_id] = rec
        return rec

    def list_tags(self) -> list[dict]:
        counts: dict[str, int] = {}
        for rec in self._docs.values():
            rec.setdefault("tags", [])
            for tag in rec["tags"]:
                counts[tag] = counts.get(tag, 0) + 1
        return vocabulary_entries(self._tag_vocab, counts)

    def create_tag(self, tag: str) -> list[dict]:
        canonicalize_tags(self._tag_vocab, [tag])
        return self.list_tags()

    def set_tags(self, document_id: str, tags: list[str]) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        normalized, _ = canonicalize_tags(self._tag_vocab, tags)
        rec["tags"] = normalized
        rec["tag_provenance"] = {tag: MANUAL_TAG_PROVENANCE for tag in normalized}
        self._docs[document_id] = rec
        return rec

    def add_auto_tags(self, document_id: str, raw_tags) -> dict | None:
        tags = validate_tag_inference(raw_tags)
        if tags is None:
            raise TagError("自动标签输出不符合 schema")
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        normalized, _ = canonicalize_tags(self._tag_vocab, tags)
        _merge_tag_provenance(rec, normalized, AUTO_TAG_PROVENANCE)
        self._docs[document_id] = rec
        return rec

    def add_manual_tags(self, document_id: str, raw_tags) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        if raw_tags is None:
            raw_tags = []
        if not isinstance(raw_tags, list):
            raise TagError("tags 必须是数组")
        normalized, _ = canonicalize_tags(self._tag_vocab, raw_tags)
        _merge_tag_provenance(rec, normalized, MANUAL_TAG_PROVENANCE)
        self._docs[document_id] = rec
        return rec

    def promote_tag(self, document_id: str, tag: str) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        canonical = resolve_tag(self._tag_vocab, tag)
        ensure_tag_provenance(rec)
        if canonical not in rec["tags"]:
            raise TagError(f"文档没有标签：{canonical}")
        rec["tag_provenance"][canonical] = MANUAL_TAG_PROVENANCE
        self._docs[document_id] = rec
        return rec

    def remove_tag(self, document_id: str, tag: str) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        try:
            canonical = resolve_tag(self._tag_vocab, tag)
        except TagError:
            canonical = tag
        rec["tags"] = [item for item in (rec.get("tags") or []) if item != canonical]
        ensure_tag_provenance(rec)
        self._docs[document_id] = rec
        return rec

    def tag_vocabulary(self) -> dict:
        return json.loads(json.dumps(self._tag_vocab, ensure_ascii=False))

    def add_tag_alias(self, tag: str, alias: str) -> list[dict]:
        canonical = resolve_tag(self._tag_vocab, tag)
        text = str(alias or "").strip()
        if text and text != canonical:
            entry = self._tag_vocab.setdefault("tags", {}).setdefault(canonical, {"aliases": []})
            aliases = entry.setdefault("aliases", [])
            if text not in aliases:
                aliases.append(text)
        return self.list_tags()

    def set_auto_tag_meta(self, document_id: str, payload: dict) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        rec["auto_tag"] = dict(payload)
        self._docs[document_id] = rec
        return rec

    def rename_tag(self, source: str, target: str) -> list[dict]:
        records = list(self._docs.values())
        rename_vocabulary_tag(self._tag_vocab, records, source, target)
        for record in records:
            ensure_tag_provenance(record)
        return self.list_tags()

    def merge_tags(self, source: str, target: str) -> list[dict]:
        records = list(self._docs.values())
        merge_vocabulary_tags(self._tag_vocab, records, source, target)
        return self.list_tags()

    def list_collections(self) -> list[dict]:
        counts: dict[str, int] = {}
        for record in self._docs.values():
            apply_topic_defaults(record, self._collection_registry)
            for cid in record.get("collections") or []:
                counts[cid] = counts.get(cid, 0) + 1
        return collection_entries(self._collection_registry, counts)

    def create_collection(self, name: str) -> dict:
        cid = collection_id_for(name)
        if cid in self._collection_registry.get("collections", {}):
            raise CollectionError(f"集合已存在：{name}")
        ensure_collection(self._collection_registry, name)
        return next(item for item in self.list_collections() if item["collection_id"] == cid)

    def rename_collection(self, collection_id: str, name: str) -> dict:
        collections = self._collection_registry.get("collections", {})
        if collection_id not in collections:
            raise CollectionError(f"集合不存在：{collection_id}")
        target_id = collection_id_for(name)
        if target_id != collection_id and target_id in collections:
            raise CollectionError(f"集合已存在：{name}")
        entry = collections.pop(collection_id)
        entry.update({"collection_id": target_id, "name": str(name).strip(), "source": "manual", "topic": None})
        collections[target_id] = entry
        for record in self._docs.values():
            record["manual_collections"] = [target_id if cid == collection_id else cid
                                             for cid in (record.get("manual_collections") or [])]
            record["collections"] = [target_id if cid == collection_id else cid
                                      for cid in (record.get("collections") or [])]
            apply_topic_defaults(record, self._collection_registry)
        return next(item for item in self.list_collections() if item["collection_id"] == target_id)

    def delete_collection(self, collection_id: str) -> bool:
        collections = self._collection_registry.get("collections", {})
        entry = collections.get(collection_id)
        if entry is None:
            return False
        if entry.get("source") == "topic":
            raise CollectionError("主题派生集合不能单独删除，请先调整主题分类")
        collections.pop(collection_id, None)
        for record in self._docs.values():
            record["manual_collections"] = [cid for cid in (record.get("manual_collections") or []) if cid != collection_id]
            apply_topic_defaults(record, self._collection_registry)
        return True

    def set_collections(self, document_id: str, collection_ids: list[str]) -> dict | None:
        record = self._docs.get(document_id)
        if record is None:
            return None
        set_manual_memberships(record, collection_ids, self._collection_registry)
        self._docs[document_id] = record
        return record

    def set_topics(self, document_id: str, topics: list[str]) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        rec["topics"] = list(topics)
        apply_topic_defaults(rec, self._collection_registry)
        self._docs[document_id] = rec
        return rec

    def delete_document(self, document_id: str) -> bool:
        rec = self._docs.pop(document_id, None)
        if rec is None:
            return False
        if rec.get("source_job_id"):
            self.remove(rec["source_job_id"])
        return True

    # --- ingest/store bridge (issue 13) ---------------------------------------
    def document_hashes(self) -> dict:
        return {d: (r.get("current_hash") or "") for d, r in self._docs.items()}

    def version_hashes(self, document_id: str) -> list:
        rec = self._docs.get(document_id)
        if rec is None:
            return []
        return [
            {"version_id": v["version_id"],
             "pg_hash": v.get("pg_hash") or "",
             "markdown": v.get("markdown") or "",
             "ir_json": v.get("ir_json") or "",
             "model": v.get("model") or "",
             "original_path": v.get("original_path"),
             "original_ext": v.get("original_ext") or rec.get("original_ext") or ".jpg",
             "created_at": v.get("created_at") or ""}
            for v in rec.get("versions", [])
        ]

    def remove_versions(self, document_id: str, version_ids: list) -> bool:
        rec = self._docs.get(document_id)
        if rec is None:
            return False
        drop = set(version_ids)
        keep = [v for v in rec.get("versions", []) if v["version_id"] not in drop]
        rec["versions"] = keep
        rec["latest_version"] = keep[-1]["version_id"] if keep else None
        rec["current_hash"] = keep[-1].get("pg_hash") if keep else ""
        for v in keep:
            v["current"] = v["version_id"] == rec["latest_version"]
        self._docs[document_id] = rec
        return True

    # --- evolution anchoring (S2) ---------------------------------------------
    def set_manual_relations(self, document_id: str, relations: list) -> dict | None:
        rec = self._docs.get(document_id)
        if rec is None:
            return None
        rec["manual_relations"] = [dict(item) for item in relations or []
                                   if isinstance(item, dict)]
        self._docs[document_id] = rec
        return rec


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

    def _tag_vocab_path(self) -> Path:
        return self.root / "tag-vocabulary.json"

    def _load_tag_vocab(self) -> dict:
        from .tags import normalize_vocabulary

        path = self._tag_vocab_path()
        if not path.is_file():
            return new_vocabulary()
        try:
            return normalize_vocabulary(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return new_vocabulary()

    def _save_tag_vocab(self, vocabulary: dict) -> None:
        self._tag_vocab_path().write_text(
            json.dumps(vocabulary, ensure_ascii=False, indent=2), encoding="utf-8")

    def _all_tag_records(self) -> list[dict]:
        docs = self.root / "documents"
        if not docs.is_dir():
            return []
        records = []
        for path in sorted(docs.iterdir()):
            if path.is_dir():
                record = self._load_record_with_metadata(path.name)
                if record is not None:
                    record.setdefault("tags", [])
                    records.append(record)
        return records

    def _write_tag_record(self, record: dict) -> None:
        self._doc_dir(record["document_id"]).joinpath("record.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def _collection_registry_path(self) -> Path:
        return self.root / "collections.json"

    def _load_collection_registry(self) -> dict:
        path = self._collection_registry_path()
        if not path.is_file():
            return new_registry()
        try:
            return normalize_registry(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return new_registry()

    def _save_collection_registry(self, registry: dict) -> None:
        self._collection_registry_path().write_text(
            json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")

    def _apply_file_collections(self, record: dict, registry: dict) -> bool:
        before = (record.get("collections"), record.get("manual_collections"))
        registry_before = json.dumps(registry, ensure_ascii=False, sort_keys=True)
        changed = apply_topic_defaults(record, registry)
        registry_changed = registry_before != json.dumps(registry, ensure_ascii=False, sort_keys=True)
        changed = changed or before != (record.get("collections"), record.get("manual_collections"))
        if changed:
            self._write_tag_record(record)
        if registry_changed:
            self._save_collection_registry(registry)
        return changed or registry_changed

    # --- library (durable) ------------------------------------------------------
    def list_documents(self) -> list[dict]:
        items = []
        docs = self.root / "documents"
        if not docs.is_dir():
            return []
        registry = self._load_collection_registry()
        registry_changed = False
        for p in sorted(docs.iterdir(), key=lambda d: d.stat().st_mtime,
                         reverse=True):
            r = self._load_record_with_metadata(p.name)
            if r:
                before = json.dumps(registry, ensure_ascii=False, sort_keys=True)
                apply_topic_defaults(r, registry)
                if before != json.dumps(registry, ensure_ascii=False, sort_keys=True):
                    registry_changed = True
                if r.get("collections") != self._read_record(p.name).get("collections"):
                    self._write_tag_record(r)
                items.append({
                    "document_id": r["document_id"],
                    "title": r["title"],
                    "created_at": r["created_at"],
                    "updated_at": r["updated_at"],
                    "metadata": r.get("metadata"),
                    "effective_time": r.get("effective_time"),
                    "collections": list(r.get("collections") or []),
                    **_library_summary_fields(r),
                })
        if registry_changed:
            self._save_collection_registry(registry)
        return items

    def _read_record(self, document_id: str) -> dict | None:
        rp = self._doc_dir(document_id) / "record.json"
        if not rp.is_file():
            return None
        try:
            return json.loads(rp.read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load_record_with_metadata(self, document_id: str) -> dict | None:
        """Read and lazily persist metadata for pre-workspace records."""
        rec = self._read_record(document_id)
        if rec is None:
            return None
        base = self._doc_dir(document_id)
        original = self._find_original(base)
        markdown_path = base / "markdown.md"
        markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
        rec, changed = ensure_record_metadata(
            rec,
            original_path=original,
            markdown=markdown,
        )
        if changed:
            (base / "record.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        # Keep the live markdown available to summary builders (U2 headline)
        # without persisting a second copy of it into record.json.
        rec["current_markdown"] = markdown
        return rec

    def get_document(self, document_id: str) -> dict | None:
        rec = self._load_record_with_metadata(document_id)
        if rec is None:
            return None
        registry = self._load_collection_registry()
        before = json.dumps(registry, ensure_ascii=False, sort_keys=True)
        memberships_before = (rec.get("collections"), rec.get("manual_collections"))
        apply_topic_defaults(rec, registry)
        if memberships_before != (rec.get("collections"), rec.get("manual_collections")):
            self._write_tag_record(rec)
        if before != json.dumps(registry, ensure_ascii=False, sort_keys=True):
            self._save_collection_registry(registry)
        rec = dict(rec)  # shallow copy
        ensure_tag_provenance(rec)
        base = self._doc_dir(document_id)
        rec["document_id"] = document_id
        original = self._find_original(base)
        rec["original_path"] = str(original) if original else ""
        latest = rec.get("versions") or []
        rec["hash"] = rec.get("current_hash") or (
            latest[-1].get("pg_hash") if latest else "")
        lv = latest[-1] if latest else None
        # enrich each candidate version with its source-page path + hash
        versions = []
        for v in latest:
            vid = v["version_id"]
            vdir = base / "versions" / vid
            timing_path = vdir / "timing.json"
            timing_json = {}
            if timing_path.is_file():
                try:
                    timing_json = json.loads(timing_path.read_text(encoding="utf-8"))
                except (OSError, TypeError, ValueError, json.JSONDecodeError):
                    timing_json = {}
            telemetry = v.get("telemetry")
            if not isinstance(telemetry, dict) or "schema_version" not in telemetry:
                telemetry = normalize_telemetry(timing_json, model=v.get("model"))
            versions.append({
                "version_id": vid,
                "created_at": v.get("created_at"),
                "model": v.get("model"),
                "pg_hash": v.get("pg_hash") or "",
                "page_path": str(_first(vdir, "page.*") or vdir / "markdown.md"),
                "timing_path": str(timing_path),
                "telemetry": telemetry,
                "provenance": v.get("provenance"),
                "provenance_detail": v.get("provenance_detail"),
                "current": vid == lv["version_id"],
            })
        rec["versions"] = versions
        rec["latest_version_id"] = lv["version_id"] if lv else None
        if lv:
            vdir = base / "versions" / lv["version_id"]
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
                "telemetry": versions[-1].get("telemetry") if versions else None,
                "provenance": lv.get("provenance"),
                "provenance_detail": lv.get("provenance_detail"),
            }
        # live (edited) markdown
        mp = base / "markdown.md"
        rec["current_markdown"] = mp.read_text(encoding="utf-8") if mp.is_file() else (
            (vdir / "markdown.md").read_text(encoding="utf-8")
            if lv and (vdir / "markdown.md").is_file() else ""
        )
        vdir2 = base / "versions" / (rec.get("latest_version") or "")
        rec["current_markdown_path"] = str(base / "markdown.md")
        return rec

    def _find_original(self, base: Path) -> Path | None:
        m = list(base.glob("original.*"))
        return m[0] if m else None

    def save_document(self, *, document_id, title, source_job_id, model,
                      markdown, ir_json, original_path, original_ext,
                      preprocessed_path, preprocessed_raw_path, assets_dir,
                      timing_json, pg_hash="", metadata=None, source_pdf=None,
                      pdf_id=None, page_index=None, page_number=None,
                      provenance=None, provenance_detail=None) -> dict:
        document_id = _safe(document_id)
        base = self._doc_dir(document_id)
        base.mkdir(parents=True, exist_ok=True)
        now = _now()
        rec0 = self._load_record_with_metadata(document_id)
        version_id = f"v{int(time.time() * 1000)}-{len(rec0.get('versions')) if rec0 else 0}"
        vdir = base / "versions" / version_id
        (vdir / "assets").mkdir(parents=True, exist_ok=True)

        # copy attachments from the parse assets leaf into this version
        astleaf = Path(assets_dir) / "assets" if assets_dir else None
        if astleaf and astleaf.is_dir():
            _copy_dir_files(astleaf, vdir / "assets")

        (vdir / "markdown.md").write_text(markdown, encoding="utf-8")
        (vdir / "ir.json").write_text(ir_json, encoding="utf-8")
        (vdir / "timing.json").write_text(
            json.dumps(timing_json or {}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _copy_if_exists(preprocessed_path, vdir / "preprocessed.png")
        _copy_if_exists(preprocessed_raw_path, vdir / "preprocessed_raw.png")
        # source page of THIS candidate version is retained inside the version dir
        _copy_if_exists(str(original_path), vdir / f"page{original_ext}")

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
        rec.setdefault("tags", [])
        registry = self._load_collection_registry()
        apply_topic_defaults(rec, registry)
        rec["source_pdf"] = source_pdf
        rec["pdf_id"] = pdf_id
        rec["page_index"] = page_index
        rec["page_number"] = page_number
        rec["latest_version"] = version_id
        rec["current_hash"] = pg_hash
        versions = rec.setdefault("versions", [])
        version_entry = {
            "version_id": version_id,
            "created_at": now,
            "model": model,
            "pg_hash": pg_hash,
            "telemetry": normalize_telemetry(timing_json, model=model),
        }
        if provenance is not None:
            version_entry["provenance"] = provenance
        if provenance_detail is not None:
            version_entry["provenance_detail"] = provenance_detail
        versions.append(version_entry)
        rec["versions"] = versions
        merge_record_metadata(
            rec,
            markdown=markdown,
            original_path=original_path,
            import_time=rec.get("created_at") or now,
            modified_time=now,
            candidate=metadata,
        )
        (base / "record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self._save_collection_registry(registry)

        # keep original copy (== effective/latest source) + live markdown
        _copy_if_exists(str(original_path), base / f"original{original_ext}")
        (base / "markdown.md").write_text(markdown, encoding="utf-8")
        return self.get_document(document_id) or rec

    def save_edits(self, document_id: str, markdown: str) -> dict | None:
        base = self._doc_dir(document_id)
        if not (base / "record.json").is_file():
            return None
        (base / "markdown.md").write_text(markdown, encoding="utf-8")
        rec = self._read_record(document_id)
        if rec is not None:
            now = _now()
            rec["updated_at"] = now
            merge_record_metadata(
                rec,
                markdown=markdown,
                original_path=self._find_original(base),
                import_time=rec.get("created_at") or now,
                modified_time=now,
            )
            (base / "record.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_document(document_id)

    def create_tag(self, tag: str) -> list[dict]:
        vocabulary = self._load_tag_vocab()
        canonicalize_tags(vocabulary, [tag])
        self._save_tag_vocab(vocabulary)
        return self.list_tags()

    def update_metadata(self, document_id: str, updates: dict) -> dict | None:
        base = self._doc_dir(document_id)
        if not (base / "record.json").is_file():
            return None
        rec = self._load_record_with_metadata(document_id)
        if rec is None:
            return None
        apply_metadata_updates(rec, updates)
        (base / "record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_document(document_id)

    def list_tags(self) -> list[dict]:
        vocabulary = self._load_tag_vocab()
        records = self._all_tag_records()
        counts: dict[str, int] = {}
        changed = False
        for record in records:
            normalized, tags_changed = canonicalize_tags(vocabulary, record.get("tags") or [])
            before_prov = json.dumps(record.get("tag_provenance") or {}, ensure_ascii=False, sort_keys=True)
            record_changed = False
            if tags_changed or normalized != record.get("tags"):
                record["tags"] = normalized
                record_changed = True
            ensure_tag_provenance(record)
            if before_prov != json.dumps(record.get("tag_provenance") or {}, ensure_ascii=False, sort_keys=True):
                record_changed = True
            if record_changed and record.get("document_id"):
                self._write_tag_record(record)
                changed = True
            for tag in normalized:
                counts[tag] = counts.get(tag, 0) + 1
        if changed or vocabulary != self._load_tag_vocab():
            self._save_tag_vocab(vocabulary)
        else:
            # A missing vocabulary file still needs to be materialized when
            # the library is first observed, even if there are no documents.
            if not self._tag_vocab_path().is_file():
                self._save_tag_vocab(vocabulary)
        return vocabulary_entries(vocabulary, counts)

    def set_tags(self, document_id: str, tags: list[str]) -> dict | None:
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        vocabulary = self._load_tag_vocab()
        normalized, _ = canonicalize_tags(vocabulary, tags)
        record["tags"] = normalized
        record["tag_provenance"] = {tag: MANUAL_TAG_PROVENANCE for tag in normalized}
        self._write_tag_record(record)
        self._save_tag_vocab(vocabulary)
        return self.get_document(document_id)

    def add_auto_tags(self, document_id: str, raw_tags) -> dict | None:
        tags = validate_tag_inference(raw_tags)
        if tags is None:
            raise TagError("自动标签输出不符合 schema")
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        vocabulary = self._load_tag_vocab()
        normalized, _ = canonicalize_tags(vocabulary, tags)
        _merge_tag_provenance(record, normalized, AUTO_TAG_PROVENANCE)
        self._write_tag_record(record)
        self._save_tag_vocab(vocabulary)
        return self.get_document(document_id)

    def add_manual_tags(self, document_id: str, raw_tags) -> dict | None:
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        if isinstance(raw_tags, str):
            raw_tags = [raw_tags]
        if raw_tags is None:
            raw_tags = []
        if not isinstance(raw_tags, list):
            raise TagError("tags 必须是数组")
        vocabulary = self._load_tag_vocab()
        normalized, _ = canonicalize_tags(vocabulary, raw_tags)
        _merge_tag_provenance(record, normalized, MANUAL_TAG_PROVENANCE)
        self._write_tag_record(record)
        self._save_tag_vocab(vocabulary)
        return self.get_document(document_id)

    def promote_tag(self, document_id: str, tag: str) -> dict | None:
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        vocabulary = self._load_tag_vocab()
        canonical = resolve_tag(vocabulary, tag)
        ensure_tag_provenance(record)
        if canonical not in record["tags"]:
            raise TagError(f"文档没有标签：{canonical}")
        record["tag_provenance"][canonical] = MANUAL_TAG_PROVENANCE
        self._write_tag_record(record)
        return self.get_document(document_id)

    def remove_tag(self, document_id: str, tag: str) -> dict | None:
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        vocabulary = self._load_tag_vocab()
        try:
            canonical = resolve_tag(vocabulary, tag)
        except TagError:
            canonical = tag
        record["tags"] = [item for item in (record.get("tags") or []) if item != canonical]
        ensure_tag_provenance(record)
        self._write_tag_record(record)
        return self.get_document(document_id)

    def tag_vocabulary(self) -> dict:
        return self._load_tag_vocab()

    def add_tag_alias(self, tag: str, alias: str) -> list[dict]:
        vocabulary = self._load_tag_vocab()
        canonical = resolve_tag(vocabulary, tag)
        text = str(alias or "").strip()
        if text and text != canonical:
            entry = vocabulary.setdefault("tags", {}).setdefault(canonical, {"aliases": []})
            aliases = entry.setdefault("aliases", [])
            if text not in aliases:
                aliases.append(text)
            self._save_tag_vocab(vocabulary)
        return self.list_tags()

    def set_auto_tag_meta(self, document_id: str, payload: dict) -> dict | None:
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        record["auto_tag"] = dict(payload)
        self._write_tag_record(record)
        return self.get_document(document_id)

    def rename_tag(self, source: str, target: str) -> list[dict]:
        vocabulary = self._load_tag_vocab()
        records = self._all_tag_records()
        rename_vocabulary_tag(vocabulary, records, source, target)
        for record in records:
            ensure_tag_provenance(record)
            self._write_tag_record(record)
        self._save_tag_vocab(vocabulary)
        return self.list_tags()

    def merge_tags(self, source: str, target: str) -> list[dict]:
        vocabulary = self._load_tag_vocab()
        records = self._all_tag_records()
        merge_vocabulary_tags(vocabulary, records, source, target)
        for record in records:
            ensure_tag_provenance(record)
            self._write_tag_record(record)
        self._save_tag_vocab(vocabulary)
        return self.list_tags()

    def _all_collection_records(self) -> list[dict]:
        docs = self.root / "documents"
        if not docs.is_dir():
            return []
        records = []
        for path in sorted(docs.iterdir()):
            if path.is_dir():
                record = self._load_record_with_metadata(path.name)
                if record is not None:
                    records.append(record)
        return records

    def list_collections(self) -> list[dict]:
        registry = self._load_collection_registry()
        counts: dict[str, int] = {}
        changed = False
        for record in self._all_collection_records():
            before = (record.get("collections"), record.get("manual_collections"))
            apply_topic_defaults(record, registry)
            if before != (record.get("collections"), record.get("manual_collections")):
                self._write_tag_record(record)
                changed = True
            for cid in record.get("collections") or []:
                counts[cid] = counts.get(cid, 0) + 1
        if changed or not self._collection_registry_path().is_file():
            self._save_collection_registry(registry)
        return collection_entries(registry, counts)

    def create_collection(self, name: str) -> dict:
        registry = self._load_collection_registry()
        cid = collection_id_for(name)
        if cid in registry.get("collections", {}):
            raise CollectionError(f"集合已存在：{name}")
        ensure_collection(registry, name)
        self._save_collection_registry(registry)
        return next(item for item in collection_entries(registry) if item["collection_id"] == cid)

    def rename_collection(self, collection_id: str, name: str) -> dict:
        registry = self._load_collection_registry()
        collections = registry.get("collections", {})
        if collection_id not in collections:
            raise CollectionError(f"集合不存在：{collection_id}")
        target_id = collection_id_for(name)
        if target_id != collection_id and target_id in collections:
            raise CollectionError(f"集合已存在：{name}")
        entry = collections.pop(collection_id)
        entry.update({"collection_id": target_id, "name": str(name).strip(), "source": "manual", "topic": None})
        collections[target_id] = entry
        for record in self._all_collection_records():
            record["manual_collections"] = [target_id if cid == collection_id else cid
                                             for cid in (record.get("manual_collections") or [])]
            record["collections"] = [target_id if cid == collection_id else cid
                                      for cid in (record.get("collections") or [])]
            apply_topic_defaults(record, registry)
            self._write_tag_record(record)
        self._save_collection_registry(registry)
        return next(item for item in collection_entries(registry) if item["collection_id"] == target_id)

    def delete_collection(self, collection_id: str) -> bool:
        registry = self._load_collection_registry()
        entry = registry.get("collections", {}).get(collection_id)
        if entry is None:
            return False
        if entry.get("source") == "topic":
            raise CollectionError("主题派生集合不能单独删除，请先调整主题分类")
        registry["collections"].pop(collection_id, None)
        for record in self._all_collection_records():
            record["manual_collections"] = [cid for cid in (record.get("manual_collections") or []) if cid != collection_id]
            apply_topic_defaults(record, registry)
            self._write_tag_record(record)
        self._save_collection_registry(registry)
        return True

    def set_collections(self, document_id: str, collection_ids: list[str]) -> dict | None:
        record = self._load_record_with_metadata(document_id)
        if record is None:
            return None
        registry = self._load_collection_registry()
        set_manual_memberships(record, collection_ids, registry)
        self._write_tag_record(record)
        self._save_collection_registry(registry)
        return self.get_document(document_id)

    def set_topics(self, document_id: str, topics: list[str]) -> dict | None:
        rp = self._doc_dir(document_id) / "record.json"
        if not rp.is_file():
            return None
        rec = self._read_record(document_id)
        if rec is None:
            return None
        rec["topics"] = list(topics)
        registry = self._load_collection_registry()
        apply_topic_defaults(rec, registry)
        rp.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        self._save_collection_registry(registry)
        return self.get_document(document_id)

    def delete_document(self, document_id: str) -> bool:
        rec = self._read_record(document_id)
        d = self._doc_dir(document_id)
        existed = d.is_dir()
        shutil.rmtree(d, ignore_errors=True)
        if rec and rec.get("source_job_id"):
            self.remove(rec["source_job_id"])
        return existed

    # --- ingest/store bridge (issue 13, disk-backed) --------------------------
    def document_hashes(self) -> dict:
        docs = self.root / "documents"
        if not docs.is_dir():
            return {}
        out = {}
        for p in docs.iterdir():
            r = self._read_record(p.name)
            if r:
                out[r["document_id"]] = r.get("current_hash") or ""
        return out

    def version_hashes(self, document_id: str) -> list:
        rec = self._read_record(document_id)
        if rec is None:
            return []
        base = self._doc_dir(document_id)
        out = []
        for v in rec.get("versions", []):
            vdir = base / "versions" / v["version_id"]
            md = (vdir / "markdown.md").read_text(encoding="utf-8") if (vdir / "markdown.md").is_file() else ""
            ir = (vdir / "ir.json").read_text(encoding="utf-8") if (vdir / "ir.json").is_file() else "{}"
            page = _first(vdir, "page.*")
            out.append({
                "version_id": v["version_id"],
                "pg_hash": v.get("pg_hash") or "",
                "markdown": md,
                "ir_json": ir,
                "model": v.get("model") or "",
                "original_path": str(page) if page else None,
                "original_ext": _page_ext(page) or rec.get("original_ext") or ".jpg",
                "created_at": v.get("created_at") or "",
            })
        return out

    def remove_versions(self, document_id: str, version_ids: list) -> bool:
        rec = self._read_record(document_id)
        if rec is None:
            return False
        base = self._doc_dir(document_id)
        drop = set(version_ids)
        keep = [v for v in rec.get("versions", []) if v["version_id"] not in drop]
        for vid in drop:
            shutil.rmtree(base / "versions" / vid, ignore_errors=True)
        rec["versions"] = keep
        if keep:
            rec["latest_version"] = keep[-1]["version_id"]
            rec["current_hash"] = keep[-1].get("pg_hash") or ""
        else:
            rec["latest_version"] = None
            rec["current_hash"] = ""
        (base / "record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    # --- evolution anchoring (S2) ---------------------------------------------
    def set_manual_relations(self, document_id: str, relations: list) -> dict | None:
        record_path = self._doc_dir(document_id) / "record.json"
        if not record_path.is_file():
            return None
        rec = self._read_record(document_id)
        if rec is None:
            return None
        rec["manual_relations"] = [dict(item) for item in relations or []
                                   if isinstance(item, dict)]
        record_path.write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        return self.get_document(document_id)


def _copy_if_exists(src: str | None, dst: Path) -> None:
    if src and Path(src).is_file():
        try:
            shutil.copy2(src, dst)
        except OSError:
            pass


def _first(dirpath: Path, pattern: str) -> Path | None:
    if not dirpath.is_dir():
        return None
    m = list(dirpath.glob(pattern))
    return m[0] if m else None


def _page_ext(page: Path | None) -> str | None:
    return page.suffix if page is not None else None


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
