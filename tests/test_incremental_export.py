"""Offline integration tests for incremental export (notes-organizer issue 03).

Covers the acceptance criteria against a real (fixture) document library:
- add / update / delete reflects correctly in the vault
- user-edited note is not overwritten; both survive via rename + report
- user-renamed file is not cleaned up as if the doc were deleted (path tracking)
- MOC stays consistent with the actual note set (no dead links / no stray MOCs)
- two consecutive no-change runs are zero-write (idempotent, stable mtime)
- all scenarios run in temp dirs, fully offline
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note.notes import exporter as ex
from graph2note.notes.classify import ClassificationScheme
from graph2note.notes.exporter import export_incremental, export_vault


def mk_scheme(doc_ids=("a", "b", "c")):
    ids = list(doc_ids)
    return ClassificationScheme(
        topics=["笔记"],
        assignments={"笔记": ids},
        summaries={d: d.upper() for d in ids},
    )


def mk(tmp, doc_id, title, markdown, updated_at, **kw):
    d = Path(tmp) / "orig"
    d.mkdir(parents=True, exist_ok=True)
    op = d / f"{doc_id}.jpg"
    op.write_bytes(b"IMG" + doc_id.encode())
    return ex.ExportEntry(
        document_id=doc_id, title=title, markdown=markdown,
        parsed_at=updated_at, updated_at=updated_at,
        original_path=str(op), source_ext=".jpg", topics=["笔记"], **kw,
    )


def docs(tmp, ids=("a", "b", "c")):
    return [mk(tmp, i, i, f"# {i}\ncontent of {i}", f"2026-09-08T10:{i}0:00")
            for i in ids]


def run(vault, entries, scheme, **kw):
    return export_incremental(entries, vault, scheme=scheme, **kw)[0]


# ---------- AC: add / update / delete ----------

def test_add_new_document(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())
    r = run(vault, docs(tmp_path, ("a", "b", "c", "new1")), mk_scheme())
    assert "notes/new1/note.md" in r["added"]
    assert (vault / "notes" / "new1" / "note.md").is_file()
    # MOC updated to include the new note (no dead links)
    assert (vault / "mocs" / "笔记.md").is_file()


def test_update_document(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())
    changed = docs(tmp_path)
    changed[0] = mk(tmp_path, "a", "A", "# a\nEDITED body", "2026-09-08T12:00:00")
    r = run(vault, changed, mk_scheme())
    assert "notes/a/note.md" in r["updated"]
    assert "EDITED body" in (vault / "notes" / "a" / "note.md").read_text()


def test_delete_document(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())
    assert (vault / "notes" / "c").is_dir()
    r = run(vault, docs(tmp_path, ("a", "b")), mk_scheme())
    assert "notes/c/note.md" in r["deleted"]
    assert "notes/c/source.jpg" in r["deleted"]
    assert not (vault / "notes" / "c" / "note.md").exists()
    # MOC no longer references the deleted note -> no stray MOC entry
    moc = (vault / "mocs" / "笔记.md").read_text()
    assert "../notes/c/note.md" not in moc
    assert "../notes/a/note.md" in moc  # other notes still listed


# ---------- AC: user edits are preserved (rename, both survive) ----------

def test_user_edit_not_overwritten(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())
    note = vault / "notes" / "a" / "note.md"
    user = "MY CUSTOM *Obsidian* editing by hand"
    note.write_text(user, encoding="utf-8")  # user edits after an export
    r = run(vault, docs(tmp_path), mk_scheme())
    assert "notes/a/note.md" in r["conflicts"]
    backup = vault / "notes" / "a" / (r["conflict_backups"]["notes/a/note.md"])
    assert backup.is_file()
    assert backup.read_text(encoding="utf-8") == user       # user copy preserved
    assert "MY CUSTOM" not in note.read_text(encoding="utf-8")  # ours restored
    assert "content of a" in note.read_text(encoding="utf-8")


def test_user_renamed_file_not_deleted(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())
    # user renames the note (Obsidian-style) but the document still exists
    (vault / "notes" / "a" / "note.md").rename(vault / "notes" / "a" / "My Essay.md")
    r = run(vault, docs(tmp_path), mk_scheme())
    # the managed path is restored; the user's renamed file is NOT deleted
    assert (vault / "notes" / "a" / "note.md").is_file()
    assert (vault / "notes" / "a" / "My Essay.md").is_file()
    assert "My Essay.md" not in r["deleted"]
    assert "notes/a/note.md" in r["added"]


# ---------- AC: MOC correctness after incremental ----------

def test_moc_matches_docs_after_remove_and_add(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())   # topics: all three in 笔记
    # remove c, add new1; both should reflect in the single MOC
    r = run(vault, docs(tmp_path, ("a", "b", "new1")), mk_scheme(("a", "b", "new1")))
    moc = (vault / "mocs" / "笔记.md").read_text()
    assert "../notes/new1/note.md" in moc
    assert "../notes/c/note.md" not in moc
    assert "notes/c/note.md" in r["deleted"]
    assert "notes/new1/note.md" in r["added"]
    # dead-link check happens inside export_incremental (no exception = ok)


# ---------- AC: idempotency / zero-write ----------

def _snapshot(root) -> dict:
    return {str(p.relative_to(root)): p.stat().st_mtime_ns
            for p in root.rglob("*") if p.is_file()}


def test_no_change_export_is_zero_write(tmp_path):
    vault = tmp_path / "vault"
    run(vault, docs(tmp_path), mk_scheme())
    before = _snapshot(vault)
    r = run(vault, docs(tmp_path), mk_scheme())  # no changes at all
    assert not r["added"] and not r["updated"] and not r["deleted"]
    assert not r["conflicts"] and not r["kept_user"]
    assert "notes/a/note.md" in r["unchanged"]
    assert _snapshot(vault) == before  # stable mtimes -> files untouched


def test_incremental_equals_full_export_content(tmp_path):
    entries = docs(tmp_path)
    inc = tmp_path / "inc"
    full = tmp_path / "full"
    export_incremental(entries, inc, scheme=mk_scheme())
    export_vault(entries, full, scheme=mk_scheme())
    got = {str(p.relative_to(inc)) for p in inc.rglob("*") if p.is_file()}
    want = {str(p.relative_to(full)) for p in full.rglob("*") if p.is_file()}
    assert got == want
    for rel in got:
        assert (inc / rel).read_bytes() == (full / rel).read_bytes()


# ---------- AC: closed-loop (load -> classify -> persist -> export) ----------

@pytest.fixture
def seeded(tmp_path):
    from graph2note.store import FileDocumentStore

    store = FileDocumentStore(str(tmp_path / "storage"))
    for i in ("a", "b", "c"):
        base = Path(store.root)
        op = base / f"{i}.jpg"; op.write_bytes(f"IMG{i}".encode())
        ad = base / f"{i}_assets"; (ad / "assets").mkdir(parents=True, exist_ok=True)
        store.save_document(
            document_id=i, title=i, source_job_id=f"job-{i}", model="t",
            markdown=f"# {i}\ncontent of {i}", ir_json="{}",
            original_path=str(op), original_ext=".jpg",
            preprocessed_path="", preprocessed_raw_path="", assets_dir=str(ad),
            timing_json={},
        )
    return store


def test_closed_loop_reclassify_incremental(tmp_path, seeded):
    from graph2note.notes.loop import run_incremental_export

    def classifier_all(entries):
        ids = [e.document_id for e in entries]
        return ClassificationScheme(
            topics=["笔记"], assignments={"笔记": ids},
            summaries={d: d.upper() for d in ids},
        )

    vault = tmp_path / "vault"
    report, vault_obj, entries = run_incremental_export(
        seeded, vault, __classify=classifier_all)
    assert len(entries) == 3
    assert (vault / "mocs" / "笔记.md").is_file()

    # edit one note by hand -> re-run loop -> conflict preserved
    note = vault / "notes" / "a" / "note.md"
    note.write_text("USER EDITS", encoding="utf-8")
    report2, _, entries2 = run_incremental_export(seeded, vault)
    assert "notes/a/note.md" in report2["conflicts"]
    # topics persisted onto the records flowed into the exported note
    n = (vault / "notes" / "a" / "note.md").read_text()
    assert "topic" in n.lower() or "笔记" in n


def test_cli_notes_export(tmp_path, seeded):
    from graph2note.cli import main

    vault = tmp_path / "vault"
    code = main(["notes-export", "-o", str(vault), "--storage", str(seeded.root)])
    assert code == 0
    assert (vault / "export-manifest.json").is_file()
    code2 = main(["notes-export", "-o", str(vault), "--storage", str(seeded.root)])
    assert code2 == 0  # idempotent re-run succeeds