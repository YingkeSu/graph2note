"""Offline tests for the Obsidian vault exporter (notes-organizer issue 01).

Covers the acceptance criteria:
- fixture snapshot: directory tree, frontmatter fields, attachment placement
- traceability fields + source_image back to the system DocumentRecord
- embedded original image + all attachment references reachable (no dead links)
- same-source duplicates export only the latest version
- integration from a real (small) FileDocumentStore to a temp dir
- idempotency: two exports are byte-for-byte identical (deterministic exported_at)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graph2note.notes import exporter as ex
from graph2note.notes.loader import load_entries
from graph2note.store import FileDocumentStore


# ---------- fixtures ----------

def make_entry(tmp, document_id, *, title=None, topics=None, markdown="# Hi",
               updated_at="2026-09-08T10:00:00", parsed_at="2026-09-08T09:00:00",
               preprocessed=None, original=None, attachments=None, source_ext=".jpg"):
    d = Path(tmp)
    orig = original if original is not None else (d / f"{document_id}_orig{source_ext}")
    if not Path(orig).exists():
        Path(orig).write_bytes(b"fake-original-image")
    pre = preprocessed if preprocessed is not None else d / f"{document_id}_pre.png"
    if not Path(pre).exists():
        Path(pre).write_bytes(b"fake-preprocessed")
    atts = {}
    for name, path in (attachments or {}).items():
        atts[name] = str(path)
    return ex.ExportEntry(
        document_id=document_id,
        title=title or document_id,
        markdown=markdown,
        parsed_at=parsed_at,
        updated_at=updated_at,
        original_path=str(orig),
        source_ext=source_ext,
        preprocessed_path=str(pre),
        topics=topics or [],
        attachments=atts,
    )


@pytest.fixture
def lib(tmp_path):
    """3 real-ish documents on disk: general + algebra + calculus."""
    assets_a = tmp_path / "a_assets" / "assets"
    assets_a.mkdir(parents=True)
    fig = assets_a / "fig1.png"
    fig.write_bytes(b"PNGDATA")
    e1 = make_entry(
        tmp_path, "doc-a", title="Algebra Notes", topics=["math", "algebra"],
        markdown="Linear equations are fundamental.\n\n![第一张图](assets/fig1.png)",
        updated_at="2026-09-08T10:00:00", attachments={"fig1.png": fig},
    )
    flow = tmp_path / "flow" / "assets"
    flow.mkdir(parents=True)
    fl = flow / "flow.png"
    fl.write_bytes(b"FLOWDATA")
    e2 = make_entry(
        tmp_path, "doc-b", title="Calculus Notes",
        markdown="Derivatives describe change.\n\n![流程](assets/flow.png)",
        updated_at="2026-09-08T11:00:00", source_ext=".png",
        attachments={"flow.png": fl},
    )
    e3 = make_entry(
        tmp_path, "doc-c", title="Scratch", topics=["scratch"],
        markdown="A quick note with no attachments.",
        updated_at="2026-09-08T09:00:00",
    )
    return [e1, e2, e3]


def read_note(vault_root, doc_id):
    return (vault_root / "notes" / doc_id / "note.md").read_text(encoding="utf-8")


# ---------- AC: fixture snapshot ----------

def test_snapshot_tree_and_frontmatter(lib, tmp_path):
    out = ex.export_vault(lib, tmp_path / "vault")
    assert (out.root / "notes").is_dir()
    for e in lib:
        d = out.notes_dir / e.safe_id
        assert (d / "note.md").is_file()
        assert (d / f"source{e.source_ext}").is_file()
    # attachments land inside the doc's assets/ dir
    assert (out.notes_dir / "doc-a" / "assets" / "fig1.png").is_file()
    assert (out.notes_dir / "doc-b" / "assets" / "flow.png").is_file()
    # manifest deterministic
    mj = json.loads((out.root / "export-manifest.json").read_text())
    assert sorted(mj["documents"]) == ["doc-a", "doc-b", "doc-c"]


def test_frontmatter_traceability_fields(lib, tmp_path):
    out = ex.export_vault(lib, tmp_path / "vault")
    note = read_note(out.root, "doc-a")
    assert "document_id: doc-a" in note
    assert "source_image: source.jpg" in note
    assert "parsed_at: 2026-09-08T09:00:00" in note
    assert "exported_at:" in note
    assert "- algebra" in note and "- math" in note
    assert "source_original_path:" in note  # back to the system DocumentRecord
    # source image embedded at the top of the body (right after frontmatter)
    assert ")\n\n![Algebra Notes 原稿](source.jpg)" in note or "原稿](source.jpg)" in note


# ---------- AC: no dead links ----------

def test_all_references_resolve(lib, tmp_path):
    out = ex.export_vault(lib, tmp_path / "vault")  # raises if a dead link
    # spot-check the attachment reference resolves relative to the note dir
    assert (out.notes_dir / "doc-a" / "assets" / "fig1.png").is_file()


def test_dead_link_raises(lib, tmp_path):
    broken = list(lib)
    broken.append(make_entry(
        tmp_path, "bad", markdown="![missing](assets/ghost.png)",
        attachments={},
    ))
    with pytest.raises(ex.VaultExportError):
        ex.export_vault(broken, tmp_path / "bad")


# ---------- AC: same-source dedup (latest only) ----------

def test_dedupe_latest_only(tmp_path):
    hex0 = "0" * 16
    same = [
        make_entry(tmp_path, "d1", updated_at="2026-09-08T08:00:00"),
        make_entry(tmp_path, "d2", updated_at="2026-09-08T12:00:00"),
    ]
    deduped = ex.dedupe_documents(same, threshold=6,
                                  hash_of=lambda e: hex0)
    assert len(deduped) == 1
    assert deduped[0].document_id == "d2"  # newest wins

    # distinct (present) hashes stay apart
    distinct = [
        make_entry(tmp_path, "x", updated_at="2026-09-08T08:00:00"),
        make_entry(tmp_path, "y", updated_at="2026-09-08T12:00:00"),
    ]
    hx, hy = "f" * 16, "0" * 16
    got = ex.dedupe_documents(distinct, hash_of=lambda e: hx if e.document_id == "x" else hy)
    assert len(got) == 2


def test_export_dedupes_duplicates(tmp_path, lib):
    dup = list(lib)
    dup.append(make_entry(
        tmp_path, "doc-a-copy", title="Algebra Again",
        markdown="same page re-parsed",
        updated_at="2026-09-08T13:00:00",
        preprocessed=Path(lib[0].preprocessed_path),  # identical hash source
    ))
    # dedup by hash: the newest of the identical-content pair wins,
    # and a distinct doc survives.
    def fake_hash(e):
        if e.title.startswith("Algebra"):
            return "0" * 16
        return ("f" if e.document_id.endswith("b") else "c") * 16
    d = ex.dedupe_documents(dup, threshold=6, hash_of=fake_hash)
    ids = [x.document_id for x in d]
    assert "doc-a-copy" in ids and "doc-a" not in ids  # newest of the dup pair kept
    assert "doc-b" in ids and "doc-c" in ids

    # exporting the deduped set emits exactly one algebra note
    out = ex.export_vault(d, tmp_path / "vault")
    assert (out.notes_dir / "doc-a-copy" / "note.md").is_file()
    assert not (out.notes_dir / "doc-a" / "note.md").exists()


# ---------- AC: real library integration ----------

@pytest.fixture
def seeded_store(tmp_path):
    store = FileDocumentStore(str(tmp_path / "storage"))
    _seed(store, "doc-1", "Geometry", "# A note\n\n![diagram](assets/diag.png)",
           topics=["geometry"], ext=".jpg", atts={"diag.png": b"DIAG"},
           pre=b"PRE1", orig=b"ORIG1")
    _seed(store, "doc-2", "Analysis", "# Analysis note", topics=["analysis"],
           ext=".png", atts={}, pre=b"PRE2", orig=b"ORIG2")
    return store


def _seed(store, doc_id, title, markdown, *, topics, ext, atts, pre, orig):
    base = Path(store.root)
    orig_path = base / f"{doc_id}_orig{ext}"
    orig_path.write_bytes(orig)
    pre_path = base / f"{doc_id}_pre.png"
    pre_path.write_bytes(pre)
    assets_dir = base / f"{doc_id}_assets"
    (assets_dir / "assets").mkdir(parents=True, exist_ok=True)
    for name, data in atts.items():
        (assets_dir / "assets" / name).write_bytes(data)
    store.save_document(
        document_id=doc_id, title=title, source_job_id=f"job-{doc_id}",
        model="test", markdown=markdown, ir_json=json.dumps({"ok": True}),
        original_path=str(orig_path), original_ext=ext,
        preprocessed_path=str(pre_path), preprocessed_raw_path="",
        assets_dir=str(assets_dir), timing_json={},
    )


def test_integration_from_real_library(seeded_store, tmp_path):
    entries = load_entries(seeded_store)
    assert len(entries) == 2
    out = ex.export_vault(entries, tmp_path / "vault")
    n1 = (out.notes_dir / "doc-1" / "note.md").read_text()
    assert "document_id: doc-1" in n1
    assert "topics:" in n1  # frontmatter always carries topics (may be []) until classification
    assert (out.notes_dir / "doc-1" / "assets" / "diag.png").is_file()


def test_integration_reparse_same_record_no_duplicate(seeded_store, tmp_path):
    # reparse updates the SAME record -> still one export entry, latest only
    _seed(seeded_store, "doc-1", "Geometry", "# Updated note", topics=["geometry"],
          ext=".jpg", atts={"diag.png": b"NEW"}, pre=b"PRE1b", orig=b"ORIG1b")
    entries = load_entries(seeded_store)
    assert len(entries) == 2  # still two docs, doc-1 not duplicated
    doc1 = next(e for e in entries if e.document_id == "doc-1")
    assert "Updated note" in doc1.markdown  # latest version wins


# ---------- AC: idempotency ----------

def test_idempotent_exports_byte_identical(lib, tmp_path):
    v1 = ex.export_vault(lib, tmp_path / "v1")
    v2 = ex.export_vault(lib, tmp_path / "v2")
    files1 = sorted(str(p.relative_to(v1.root)) for p in v1.root.rglob("*") if p.is_file())
    files2 = sorted(str(p.relative_to(v2.root)) for p in v2.root.rglob("*") if p.is_file())
    assert files1 == files2
    for rel in files1:
        b1 = (v1.root / rel).read_bytes()
        b2 = (v2.root / rel).read_bytes()
        assert b1 == b2, rel


def test_export_timestamp_is_deterministic(lib, tmp_path):
    v1 = ex.export_vault(lib, tmp_path / "v1")
    v2 = ex.export_vault(lib, tmp_path / "v2")
    for eid in ("doc-a", "doc-b", "doc-c"):
        a = read_note(v1.root, eid)
        b = read_note(v2.root, eid)
        # same exported_at across runs (not wall-clock drift)
        m1 = [l for l in a.splitlines() if l.startswith("exported_at:")]
        m2 = [l for l in b.splitlines() if l.startswith("exported_at:")]
        assert m1 == m2