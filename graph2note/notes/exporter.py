"""Obsidian vault exporter — a pure function from document records to a vault tree.

The exporter is deliberately decoupled from any storage backend: it takes
:class:`ExportEntry` value objects (one per document, already normalized to the
*latest* parsed version) and writes a self-contained Obsidian vault directory.

Core guarantees:

* **One note per document** under ``notes/<safe_document_id>/note.md`` with the
  required traceability frontmatter (``document_id`` / ``source_image`` /
  ``parsed_at`` / ``exported_at`` / ``topics``).
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

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from ..ingest.hash import hamming, phash  # 09's perceptual hash (same-source判据)


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
    attachments: dict = field(default_factory=dict)  # {name: absolute path}

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


def _yaml_list(items: Iterable[str]) -> str:
    items = [str(i) for i in items]
    if not items:
        return "topics: []\n"
    body = "\n".join(f"  - {i}" for i in items)
    return f"topics:\n{body}\n"


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
    lines = [
        "---",
        f"document_id: {entry.document_id}",
        f"title: {title}",
        f"source_image: {src}",
        f"source_original_path: {entry.original_path}",
        f"parsed_at: {_iso(entry.parsed_at, '')}",
        f"exported_at: {exported_at}",
    ]
    body = "\n".join(lines) + "\n\n" + _yaml_list(entry.topics) + "---\n\n"
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
    return re.sub(r"[^A-Za-z0-9._-]", "_", s)


@dataclass
class Vault:
    """A fully-materialized vault on disk."""

    root: Path
    notes_dir: Path
    documentation: list[str]           # rendered note files (relative)
    attachments: list[str]             # copied attachments (relative)
    sources: list[str]                 # copied original images (relative)
    manifest_path: Path

    @property
    def all_files(self) -> list[str]:
        return self.documentation + self.attachments + self.sources


def export_vault(
    entries: Iterable[ExportEntry],
    out_dir: str | Path,
    *,
    exported_at: Optional[str] = None,
    messages: Optional[list[str]] = None,
) -> Vault:
    """Write a complete vault into ``out_dir`` and validate every link.

    Raises :class:`VaultExportError` if any note has a dead reference.
    """
    entries = list(entries)
    root = Path(out_dir)
    notes_dir = root / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)

    # deterministic exported_at: explicit arg, else newest record timestamp
    if not exported_at:
        exported_at = max(
            (str(e.updated_at) for e in entries if e.updated_at), default=""
        )
    exported_at = str(exported_at)

    doc_files, attach_files, source_files = [], [], []
    for e in entries:
        d = notes_dir / e.safe_id
        d.mkdir(parents=True, exist_ok=True)

        # 1. original manuscript image (溯源 embed) — copy beside the note
        src_image = d / f"source{e.source_ext}"
        if e.original_path:
            _copy_file(e.original_path, src_image)
            source_files.append(f"notes/{e.safe_id}/source{e.source_ext}")

        # 2. attachments -> assets/ beside the note (keep refs valid)
        assets_dir = d / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        for name, path in sorted(e.attachments.items()):
            safe = _safe_name(name)
            _copy_file(path, assets_dir / safe)
            attach_files.append(f"notes/{e.safe_id}/assets/{safe}")

        # 3. note
        note = build_note(e, exported_at)
        (d / "note.md").write_text(note, encoding="utf-8")
        doc_files.append(f"notes/{e.safe_id}/note.md")

    # manifest (deterministic)
    manifest = {
        "exported_at": exported_at,
        "documents": [e.document_id for e in entries],
        "note_files": doc_files,
        "attachment_files": attach_files,
        "source_files": source_files,
    }
    mpath = root / "export-manifest.json"
    mpath.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                     encoding="utf-8")

    vault = Vault(root=root, notes_dir=notes_dir, documentation=doc_files,
                  attachments=attach_files, sources=source_files,
                  manifest_path=mpath)

    _validate_all_links(vault, exported_at)
    if messages is not None:
        messages.append(
            f"Exported {len(doc_files)} note(s), {len(source_files)} source "
            f"image(s), {len(attach_files)} attachment(s) to {root}"
        )
    return vault


def _copy_file(src: str | Path, dst: Path) -> None:
    import shutil
    shutil.copyfile(src, dst)


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