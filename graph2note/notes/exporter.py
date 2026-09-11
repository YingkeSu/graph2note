"""Obsidian vault exporter — a pure function from document records to a vault tree.

The exporter is deliberately decoupled from any storage backend: it takes
:class:`ExportEntry` value objects (one per document, already normalized to the
*latest* parsed version) and writes a self-contained Obsidian vault directory.

Core guarantees:

* **One note per document** under ``notes/<safe_document_id>/note.md`` with the
  required traceability frontmatter (``document_id`` / ``source_image`` /
  ``parsed_at`` / ``exported_at`` / ``topics`` / ``tags``).
* **溯源对照**: the original manuscript image is copied beside the note and
  embedded at the top of the body via a relative path; an absolute
  ``source_original_path`` field keeps the link to the system DocumentRecord.
* **Attachments** (diagram rebuilds etc.) are copied into ``assets/`` beside the
  note; the note's existing ``assets/<name>`` references keep resolving
  (relative to the note dir).
* **Same-source dedup**: only the latest version is exported — intra-record it is
  the record's ``current_markdown`` (the exporter only ever sees one entry per
  record), and inter-record it is a perceptual-hash cluster that collapses
  separate records of the same physical page to the newest one.
* **Link validation**: every relative ``](...)`` / ``![...]`` / ``[[...]]`` in a
  note must resolve to an existing file in the vault, or the export fails.
* **Idempotent**: ``exported_at`` is not wall-clock — it comes from an explicit
  parameter or is derived deterministically from the input, so two exports of
  the same input are byte-for-byte identical.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..ingest.hash import hamming, phash  # 09's perceptual hash (same-source判据)


# ---------------------------------------------------------------------------
# byte helpers shared by the full exporter and the incremental path
# ---------------------------------------------------------------------------


def _bhash(data: bytes) -> str:
    """sha256 fingerprint of a system-generated file's bytes."""
    return hashlib.sha256(data).hexdigest()


def _read_bytes(path: str | Path) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        data = data.encode("utf-8")
    path.write_bytes(data)


def _dump(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"


def _conflict_name(path: Path, disk_fp: str) -> Path:
    """Deterministic-but-unique name for a user-edited file we must preserve."""
    base = path.name
    cand = path.with_name(f"{base}.user-{disk_fp[:8]}")
    n = 1
    while cand.exists():
        cand = path.with_name(f"{base}.user-{disk_fp[:8]}-{n}")
        n += 1
    return cand


def _prune_empty_dirs(root: Path) -> None:
    """Remove directories under notes/ and mocs/ that became empty after cleanup."""
    for top in (root / "notes", root / "mocs"):
        if not top.is_dir():
            continue
        for p in sorted(top.rglob("*"), key=lambda x: len(x.parts), reverse=True):
            if p.is_dir():
                try:
                    p.rmdir()
                except OSError:
                    pass  # not empty (user files still inside) — keep it


def render_vault_files(
    entries: Iterable[ExportEntry],
    *,
    exported_at: str,
    scheme=None,
) -> tuple[dict[str, bytes], dict[str, list[str]]]:
    """Render every system-generated file as ``{relative_path: bytes}``.

    This is the single deterministic render that both ``export_vault`` (full
    overwrite) and ``export_incremental`` (diff against disk/manifest) build on,
    so an incremental result is always content-equivalent to a full export of
    the same input.
    """
    from .moc import build_mocs

    files: dict[str, bytes] = {}
    lists = {"note_files": [], "source_files": [], "attachment_files": [],
             "moc_files": [], "collection_files": []}
    for e in entries:
        d = f"notes/{e.safe_id}"
        lists["note_files"].append(f"{d}/note.md")
        files[f"{d}/note.md"] = build_note(e, exported_at).encode("utf-8")
        if e.original_path:
            rel = f"{d}/source{e.source_ext}"
            lists["source_files"].append(rel)
            files[rel] = _read_bytes(e.original_path)
        for name, path in sorted(e.attachments.items()):
            safe = _safe_name(name)
            rel = f"{d}/assets/{safe}"
            lists["attachment_files"].append(rel)
            files[rel] = _read_bytes(path)
        for collection in sorted(set(e.collections)):
            collection_rel = f"collections/{_safe_name(collection)}/{e.safe_id}.md"
            lists["collection_files"].append(collection_rel)
            files[collection_rel] = (
                "---\n"
                "type: collection-link\n"
                f"collection: {collection}\n"
                f"document_id: {e.document_id}\n"
                "---\n\n"
                f"[{e.title or e.document_id}](../../notes/{e.safe_id}/note.md)\n"
            ).encode("utf-8")
    if scheme is not None:
        for topic, content in build_mocs(scheme, entries).items():
            rel = f"mocs/{_safe_name(topic)}.md"
            lists["moc_files"].append(rel)
            files[rel] = content.encode("utf-8")
    return files, lists


def _build_manifest(
    entries: list[ExportEntry],
    exported_at: str,
    lists: dict[str, list[str]],
    fingerprints: dict[str, str],
) -> dict:
    return {
        "exported_at": exported_at,
        "documents": [e.document_id for e in entries],
        "note_files": lists["note_files"],
        "moc_files": lists["moc_files"],
        "attachment_files": lists["attachment_files"],
        "source_files": lists["source_files"],
        "collection_files": lists["collection_files"],
        # content fingerprints let a later incremental diff tell "stale system
        # file" (safe to overwrite/delete) from "user-edited file" (must keep).
        "fingerprints": fingerprints,
    }


@dataclass
class ExportEntry:
    """Normalized view of one source document's LATEST version, ready to export."""

    document_id: str
    title: str
    markdown: str
    parsed_at: str          # ISO timestamp of the latest parse (溯源)
    updated_at: str         # ISO timestamp used to decide "latest" across records
    original_path: str      # system path to the original manuscript image (溯源)
    source_ext: str         # image extension (incl. dot)
    preprocessed_path: str = ""
    topics: list = field(default_factory=list)
    tags: list = field(default_factory=list)
    collections: list = field(default_factory=list)
    attachments: dict = field(default_factory=dict)  # {name: absolute path}
    metadata: dict = field(default_factory=dict)     # document-level workspace metadata

    @property
    def safe_id(self) -> str:
        return re.sub(r"[^A-Za-z0-9._-]", "_", self.document_id)


DEFAULT_DEDUP_THRESHOLD = 6  # same as ingest engine's default


class VaultExportError(Exception):
    """Raised when the generated vault has dead links or is structurally invalid."""


def _iso(t: Optional[str], fallback: str) -> str:
    return str(t) if t else fallback


def default_hash_of(entry: ExportEntry) -> str:
    """09-style pHash of a document's preprocessed image ("" when unavailable)."""
    for cand in (entry.preprocessed_path, entry.original_path):
        if cand:
            try:
                from PIL import Image
                with Image.open(cand) as im:
                    return phash(im.convert("RGB"))
            except Exception:
                continue
    return ""


def dedupe_documents(
    entries: Iterable[ExportEntry],
    threshold: int = DEFAULT_DEDUP_THRESHOLD,
    hash_of: Optional[Callable[[ExportEntry], str]] = None,
) -> list[ExportEntry]:
    """Collapse same-source documents (09 pHash clusters) to the newest one.

    Two documents whose perceptual hashes are within ``threshold`` are deemed
    the same physical page; only the one with the latest ``updated_at`` is kept.
    Documents without a usable hash are treated as singletons (never merged).
    """
    entries = list(entries)
    if not entries:
        return []
    hf = hash_of or default_hash_of
    hashes = [hf(e) for e in entries]
    n = len(entries)

    # union-find over pairwise hamming distance
    parent = list(range(n))
    rank = [0] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        if rank[ra] < rank[rb]:
            ra, rb = rb, ra
        parent[rb] = ra
        if rank[ra] == rank[rb]:
            rank[ra] += 1

    for i in range(n):
        for j in range(i + 1, n):
            if hashes[i] and hashes[j] and hamming(hashes[i], hashes[j]) <= threshold:
                union(i, j)

    groups: dict[int, list[ExportEntry]] = {}
    for idx, e in enumerate(entries):
        groups.setdefault(find(idx), []).append(e)

    out = []
    for members in groups.values():
        # newest source wins
        rep = max(members, key=lambda e: (e.updated_at, e.parsed_at))
        out.append(rep)
    return sorted(out, key=lambda e: e.safe_id)


def _yaml_list(name: str, items: Iterable[str]) -> str:
    items = [str(i) for i in items]
    if not items:
        return f"{name}: []\n"
    body = "\n".join(f"  - {i}" for i in items)
    return f"{name}:\n{body}\n"


def note_body(markdown: str) -> str:
    """Sanitize away any leading frontmatter already present in the source markdown."""
    md = markdown.lstrip()
    if md.startswith("---"):
        # drop an existing frontmatter block: we write our own
        m = re.match(r"^---\n.*?\n---\n?", md, flags=re.DOTALL)
        if m:
            md = md[m.end():]
    return md.strip()


def build_note(
    entry: ExportEntry,
    exported_at: str,
) -> str:
    """Render one note (frontmatter + embedded original + body) as a string."""
    title = entry.title or entry.document_id
    src = f"source{entry.source_ext}"
    metadata = entry.metadata if isinstance(entry.metadata, dict) else {}

    def metadata_value(field: str) -> str:
        slot = metadata.get(field)
        if isinstance(slot, dict):
            return str(slot.get("value") or "")
        return str(slot or "")

    effective = metadata.get("effective_time")
    effective_value = effective.get("value") if isinstance(effective, dict) else ""
    effective_field = effective.get("field") if isinstance(effective, dict) else ""
    lines = [
        "---",
        f"document_id: {entry.document_id}",
        f"title: {title}",
        f"source_image: {src}",
        f"source_original_path: {entry.original_path}",
        f"parsed_at: {_iso(entry.parsed_at, '')}",
        f"exported_at: {exported_at}",
        f"capture_time: {metadata_value('capture_time')}",
        f"document_time: {metadata_value('document_time')}",
        f"import_time: {metadata_value('import_time')}",
        f"modified_time: {metadata_value('modified_time')}",
        f"effective_time: {effective_value or ''}",
        f"effective_time_field: {effective_field or ''}",
        f"needs_organization: {'true' if metadata.get('needs_organization') else 'false'}",
    ]
    body = "\n".join(lines) + "\n\n"
    body += _yaml_list("topics", entry.topics)
    body += _yaml_list("tags", entry.tags)
    body += _yaml_list("collections", entry.collections)
    body += "---\n\n"
    body += f"![{title} 原稿]({src})\n\n"
    md = note_body(entry.markdown)
    body += md + ("\n" if md else "")
    return body


# relative ``ref`` target inside a markdown note (image / link / wiki-link)
_REF = re.compile(r"!?\[[^\]]*\]\((?!\S+://)([^)]*)\)|!\[\[([^\]|#]+)")



def collect_refs(markdown: str) -> list[str]:
    """Relative paths referenced from one note's markdown body."""
    refs = []
    for m in _REF.finditer(markdown):
        if m.group(1):
            refs.append(m.group(1))
        elif m.group(2):
            refs.append(m.group(2))
    return [r.strip() for r in refs if r.strip() and not r.startswith("#")]


def _safe_name(s: str) -> str:
    """Sanitize a name for use as a filename, keeping Unicode word chars.

    ``-`` is kept because the renderer's deterministic asset paths
    (``assets/<doc>-diagram-<n>.png``) and other filenames use hyphens; mangle
    only characters that are not filename-safe (whitespace / path separators
    etc.).  The note body references attachments by their original names, so
    sanitizing here must not rename ``-`` or the link would dead-link.
    """
    s = re.sub(r"[^\w.-]+", "_", str(s), flags=re.UNICODE).strip("_")
    return s or "untitled"


@dataclass
class Vault:
    """A fully-materialized vault on disk."""

    root: Path
    notes_dir: Path
    moc_dir: Path
    documentation: list[str]           # rendered note + moc files (relative)
    attachments: list[str]             # copied attachments (relative)
    sources: list[str]                 # copied original images (relative)
    moc_files: list[str]               # generated MOC index notes (relative)
    collection_files: list[str]        # deterministic membership links (relative)
    manifest_path: Path

    @property
    def all_files(self) -> list[str]:
        return self.documentation + self.attachments + self.sources


def export_vault(
    entries: Iterable[ExportEntry],
    out_dir: str | Path,
    *,
    exported_at: Optional[str] = None,
    scheme=None,  # ClassificationScheme | None -> also emit per-topic MOCs
    messages: Optional[list[str]] = None,
) -> Vault:
    """Write a complete (full-overwrite) vault into ``out_dir`` and validate links.

    Every system-generable file is (re)written and fingerprinted.  When
    ``scheme`` is given, a MOC is written per topic and included in link
    validation.  Raises :class:`VaultExportError` if any note has a dead link.
    """
    entries = list(entries)
    root = Path(out_dir)

    # deterministic exported_at: explicit arg, else newest record timestamp
    if not exported_at:
        exported_at = max(
            (str(e.updated_at) for e in entries if e.updated_at), default=""
        )
    exported_at = str(exported_at)

    files, lists = render_vault_files(entries, exported_at=exported_at, scheme=scheme)
    fingerprints = {rel: _bhash(data) for rel, data in files.items()}
    for rel in sorted(files):
        _write(root / rel, files[rel])

    mpath = root / "export-manifest.json"
    _write(mpath, _dump(_build_manifest(entries, exported_at, lists, fingerprints)))

    documentation = lists["note_files"] + lists["moc_files"] + lists["collection_files"]
    vault = Vault(
        root=root, notes_dir=root / "notes", moc_dir=root / "mocs",
        documentation=documentation, attachments=lists["attachment_files"],
        sources=lists["source_files"], moc_files=lists["moc_files"],
        collection_files=lists["collection_files"],
        manifest_path=mpath,
    )

    _validate_all_links(vault, exported_at)
    if messages is not None:
        mocs_note = f" + {len(lists['moc_files'])} MOC" if lists["moc_files"] else ""
        messages.append(
            f"Exported {len(lists['note_files'])} note(s){mocs_note}, "
            f"{len(lists['source_files'])} source image(s), "
            f"{len(lists['attachment_files'])} attachment(s) to {root}"
        )
    return vault


def export_incremental(
    entries: Iterable[ExportEntry],
    out_dir: str | Path,
    *,
    exported_at: Optional[str] = None,
    scheme=None,  # ClassificationScheme | None -> also emit/refresh MOCs
    messages: Optional[list[str]] = None,
) -> tuple[dict, Vault]:
    """Apply only the changed system files onto an existing vault; preserve user edits.

    Diff is anchored on ``document_id`` paths plus content fingerprints from the
    previous ``export-manifest.json``:

    * missing file                 -> write (``added``)
    * byte-identical               -> untouched (``unchanged``; stable mtime)
    * differs but == previous      -> stale system file -> overwrite (``updated``)
    * differs and not previous     -> user-edited    -> rename to preserve both,
                                     then write ours (``conflicts``)
    * a previous system file with
      no counterpart today and
      still unchanged on disk      -> delete (``deleted``)

    Returns ``(report, vault)``; the report lists ``added/updated/unchanged/
    conflicts(conflict_backups)/deleted/kept_user``.  Dead links still fail via
    :class:`VaultExportError`.
    """
    entries = list(entries)
    root = Path(out_dir)
    mpath = root / "export-manifest.json"

    if not exported_at:
        exported_at = max(
            (str(e.updated_at) for e in entries if e.updated_at), default=""
        )
    exported_at = str(exported_at)

    files, lists = render_vault_files(entries, exported_at=exported_at, scheme=scheme)
    desired_fp = {rel: _bhash(data) for rel, data in files.items()}

    prev = {}
    if mpath.exists():
        try:
            prev = json.loads(mpath.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            prev = {}
    prev_fp = prev.get("fingerprints") or {}

    report: dict = {
        "added": [], "updated": [], "unchanged": [],
        "conflicts": [], "conflict_backups": {}, "deleted": [],
        "kept_user": [], "exported_at": exported_at,
    }

    for rel, data in files.items():
        p = root / rel
        if not p.is_file():
            _write(p, data)
            report["added"].append(rel)
            continue
        disk = p.read_bytes()
        if disk == data:
            report["unchanged"].append(rel)
        elif _bhash(disk) == prev_fp.get(rel):
            _write(p, data)  # stale system file we produced before -> refresh
            report["updated"].append(rel)
        else:
            backup = _conflict_name(p, _bhash(disk))
            p.rename(backup)  # keep the user's version, both survive
            _write(p, data)
            report["conflicts"].append(rel)
            report["conflict_backups"][rel] = backup.name

    # cleanup of removed documents: only delete files that still match the
    # previous system fingerprint (safe = never user-edited / user-renamed).
    for rel in list(prev_fp):
        if rel in files:
            continue
        p = root / rel
        if not p.exists():
            continue
        if p.is_file() and _bhash(p.read_bytes()) == prev_fp.get(rel):
            p.unlink()
            report["deleted"].append(rel)
        else:
            # user-edited / user-renamed file at a now-unmanaged path -> keep
            report["kept_user"].append(rel)
    _prune_empty_dirs(root)

    # manifest: write only when the (deterministic) content actually changed.
    manifest = _build_manifest(entries, exported_at, lists, desired_fp)
    manifest_str = _dump(manifest)
    if not (mpath.exists() and mpath.read_text(encoding="utf-8") == manifest_str):
        _write(mpath, manifest_str)

    documentation = lists["note_files"] + lists["moc_files"] + lists["collection_files"]
    vault = Vault(
        root=root, notes_dir=root / "notes", moc_dir=root / "mocs",
        documentation=documentation, attachments=lists["attachment_files"],
        sources=lists["source_files"], moc_files=lists["moc_files"],
        collection_files=lists["collection_files"],
        manifest_path=mpath,
    )
    _validate_all_links(vault, exported_at)

    if messages is not None:
        messages.append(
            f"Incremental: +{len(report['added'])} added, "
            f"~{len(report['updated'])} updated, {len(report['deleted'])} deleted, "
            f"!{len(report['conflicts'])} conflicts, "
            f"{len(report['kept_user'])} kept-user -> {root}"
        )
    return report, vault


def _validate_all_links(vault: Vault, exported_at: str) -> None:
    """Resolve every relative reference in every note; dead link => error."""
    dead: list[str] = []
    for rel in vault.documentation:
        note_path = vault.root / rel
        text = note_path.read_text(encoding="utf-8")
        for ref in collect_refs(text):
            if ref.startswith("#"):
                continue
            # resolve relative to the note's directory; strip anchor
            target = ref.split("#", 1)[0]
            resolved = (note_path.parent / target).resolve()
            if not resolved.is_file():
                dead.append(f"{rel}: missing reference {target!r}")
    # frontmatter source_image must exist too
    if dead:
        raise VaultExportError(
            "Dead link(s) in generated vault:\n" + "\n".join(dead)
        )
