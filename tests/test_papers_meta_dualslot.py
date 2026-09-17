"""SPW Y2 — dual-slot contract: P1 ``paper.json`` vs P2 ``record.json.paper``.

The maintainer ruling (2026-09-15) is option **(b)**: keep both landings and
turn "two accessors + their field sets" into a formal contract (SPEC §2)
instead of collapsing them into a single file.  This module pins that
contract; the SPEC table is the source of truth and these tests are its teeth.

* **I1** P2 writes never touch the P1 slot's structure fields (both stores),
  and leave ``paper.json`` byte-identical on the durable store.
* **I2** P1 writes never touch the P2 slot of ``record.json``.
* **I3** P2's own writes (meta / references / resolution) do not clobber each
  other.
* **I4** ``webapp._paper_view_payload`` merges the two slots field by field,
  and a P2 slot can never smuggle ``sections`` into the view.
* **I5** both accessors and the view payload survive a durable reload.

Every assertion reads through the real accessors (``get_paper_payload`` /
``paper_payload`` / ``GET /api/papers/{id}/view``), so blanking either landing
(``paper_payload`` → ``{}`` or ``get_paper_payload`` → ``{}``) turns this
module red.  Zero network, zero LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import graph2note.webapp as webapp
from graph2note.store import FileDocumentStore, SessionDocumentStore

# ---------------------------------------------------------------------------
# Fixtures — the exact shapes the two landings carry
# ---------------------------------------------------------------------------

#: P1's ``PaperPayload.as_dict()`` (see ``papers/model.py``).
PAPER_PAYLOAD = {
    "schema_version": 1,
    "source": "text-layer",
    "sections": [
        {"level": 1, "title": "1 Introduction", "text": "Recurrent models...",
         "page_start": 0, "page_end": 0},
        {"level": 2, "title": "1.1 Background", "text": "Background text",
         "page_start": 0, "page_end": 1},
    ],
    "fulltext": "Recurrent models... Background text",
    "page_map": [
        {"page_index": 0, "page_number": 1, "char_count": 120},
        {"page_index": 1, "page_number": 2, "char_count": 80},
    ],
    "meta": {},
    "references": [],
    "provenance": {"source": "text-layer", "pdf_id": "pdf-1", "sections": 2},
}

PAPER_META = {
    "title": "Attention Is All You Need",
    "authors": ["Ashish Vaswani", "Noam Shazeer"],
    "year": 2017,
    "venue": "NeurIPS",
    "doi": "10.5555/3295222.3295349",
    "abstract": "The dominant sequence transduction models are based on recurrent networks.",
    "keywords": ["transformer", "attention"],
    "source": "text-layer",
}
META_PROVENANCE = {
    "title": {"source": "text-layer", "confidence": "high", "evidence": "front page"},
    "doi": {"source": "text-layer", "confidence": "medium", "evidence": "footer"},
}
REFERENCES = [
    {"raw": "[1] Bahdanau et al. 2015", "title": "Neural Machine Translation",
     "authors": ["Dzmitry Bahdanau"], "year": 2015, "doi": "",
     "resolved_document_id": "doc-ref-1"},
    {"raw": "[2] Anonymous", "title": "", "authors": [], "year": None,
     "doi": "", "resolved_document_id": None},
]
REFERENCE_PROVENANCE = [
    {"index": 0, "style": "numbered", "fragments": 1, "notes": []},
    {"index": 1, "style": "numbered", "fragments": 1, "notes": ["unparseable"]},
]

#: Field ownership, straight from the SPEC §2 landing table.
P1_SLOT_KEYS = {"schema_version", "source", "sections", "fulltext", "page_map",
                "meta", "references", "provenance"}
P2_SLOT_KEYS = {"meta", "meta_provenance", "source", "notes", "parse",
                "references", "references_provenance"}
#: Keys only P1 may write; the shared names (meta/references/source) are the
#: ones the consumer resolves in P3's favour of the P2 slot.
P1_ONLY_KEYS = {"schema_version", "sections", "fulltext", "page_map", "provenance"}
#: I1 guards exactly these fields inside the P1 slot.
P1_STRUCTURE_KEYS = ("sections", "fulltext", "page_map", "schema_version", "provenance")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_paper(store, document_id: str = "paper-1", paper: dict | None = None):
    """Commit a paper through P1's real durable API (not a record fixture)."""

    return store.save_paper_document(
        document_id=document_id, title=f"论文 {document_id}", markdown="# t\n",
        paper=dict(paper if paper is not None else PAPER_PAYLOAD),
        model="text-layer", ir_json="{}", original_path=None, original_ext=".pdf",
    )


def _seed_note(store, document_id: str = "note-1"):
    return store.save_document(
        document_id=document_id, title=f"笔记 {document_id}",
        source_job_id=f"job-{document_id}", model="fixture",
        markdown=f"# {document_id}\n", ir_json=json.dumps({"blocks": []}),
        original_path="", original_ext=".jpg", preprocessed_path="",
        preprocessed_raw_path="", assets_dir="", timing_json={},
    )


def _write_meta_and_references(store, document_id: str = "paper-1"):
    """Run P2's three writes in their natural order."""

    store.set_paper_meta(document_id, PAPER_META, provenance=META_PROVENANCE,
                         source="text-layer", notes=["front page parses clean"],
                         parse={"pages": 2})
    store.set_paper_references(document_id, REFERENCES,
                               provenance=REFERENCE_PROVENANCE)


def _client(store) -> TestClient:
    return TestClient(webapp.create_app(document_store=store, storage_dir=store.root))


def _view(store, document_id: str = "paper-1") -> dict:
    response = _client(store).get(f"/api/papers/{document_id}/view")
    assert response.status_code == 200, response.text
    return response.json()


def _record_path(root: Path, document_id: str = "paper-1") -> Path:
    return root / "documents" / document_id / "record.json"


def _paper_json_path(root: Path, document_id: str = "paper-1") -> Path:
    return root / "documents" / document_id / "paper.json"


# ---------------------------------------------------------------------------
# I1 — P2 writes never touch the P1 slot
# ---------------------------------------------------------------------------

def test_i1_p2_writes_leave_the_durable_p1_slot_byte_identical(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    before = store.get_paper_payload("paper-1")
    before_bytes = _paper_json_path(root).read_bytes()

    _write_meta_and_references(store)

    assert store.get_paper_payload("paper-1") == before
    assert _paper_json_path(root).read_bytes() == before_bytes, (
        "P2 metadata/references must never rewrite paper.json")
    # ...and the P2 slot really did receive the writes (the guard is not vacuous)
    p2 = store.paper_payload("paper-1")
    assert p2["meta"] == PAPER_META
    assert p2["references"][0]["resolved_document_id"] == "doc-ref-1"


def test_i1_p2_writes_preserve_p1_owned_fields_on_the_session_store(tmp_path):
    """The in-memory store keeps one ``paper`` dict (no separate file).

    I1 still holds: the structure fields P1 owns are never replaced by a P2
    write.  I2 deliberately does not apply here — there is no second landing to
    protect, and the session store is not durable.
    """

    store = SessionDocumentStore(tmp_path / "session")
    _seed_paper(store)
    before = store.get_paper_payload("paper-1")

    _write_meta_and_references(store)

    after = store.get_paper_payload("paper-1")
    for key in P1_STRUCTURE_KEYS:
        assert after[key] == before[key], key
    # the P2 keys land in the same dict, which is exactly why P3 resolves them
    # in P2's favour
    assert after["meta"] == PAPER_META
    assert after["references"][0]["resolved_document_id"] == "doc-ref-1"


# ---------------------------------------------------------------------------
# I2 — P1 writes never touch the P2 slot (durable store)
# ---------------------------------------------------------------------------

def test_i2_p1_rewrite_leaves_the_p2_slot_untouched(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _write_meta_and_references(store)
    p2_before = store.paper_payload("paper-1")

    refreshed = {
        **PAPER_PAYLOAD,
        "fulltext": "rewritten body",
        "sections": [{"level": 1, "title": "Rewritten", "text": "x",
                      "page_start": 0, "page_end": 1}],
    }
    store.set_paper_payload("paper-1", refreshed)

    assert store.paper_payload("paper-1") == p2_before, (
        "a P1 payload write must not drop P2's meta/references from record.json")
    assert [s["title"] for s in store.get_paper_payload("paper-1")["sections"]] == [
        "Rewritten"], "the P1 slot did take the new payload"


def test_i2_reimport_and_merge_wrappers_keep_the_p2_slot(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _write_meta_and_references(store)
    p2_before = store.paper_payload("paper-1")

    # (a) the full re-import path (save_paper_document on an existing id)
    _seed_paper(store, paper={**PAPER_PAYLOAD, "fulltext": "re-imported"})
    assert store.paper_payload("paper-1") == p2_before
    assert store.get_paper_payload("paper-1")["fulltext"] == "re-imported"

    # (b) the in-place merge path
    store.update_paper_payload("paper-1", {"fulltext": "merged"})
    assert store.paper_payload("paper-1") == p2_before
    assert store.get_paper_payload("paper-1")["fulltext"] == "merged"

    # the record keeps the mirror fields P1 owns and the untouched P2 slot
    record = json.loads(_record_path(root).read_text(encoding="utf-8"))
    assert record["doc_kind"] == "paper"
    assert record["paper_source"] == "text-layer"
    assert record["paper_sections"] == 2
    assert record["paper"] == p2_before


def test_i2_p1_write_does_not_touch_a_missing_p2_slot(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)

    store.set_paper_payload("paper-1", {**PAPER_PAYLOAD, "fulltext": "again"})

    assert store.paper_payload("paper-1") == {}
    record = json.loads(_record_path(root).read_text(encoding="utf-8"))
    assert "paper" not in record, "P1 never creates the P2 slot"


# ---------------------------------------------------------------------------
# I3 — P2's own writes stay composable
# ---------------------------------------------------------------------------

def test_i3_p2_writes_do_not_clobber_each_other(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)

    store.set_paper_meta("paper-1", PAPER_META, provenance=META_PROVENANCE,
                         source="text-layer", notes=["n"], parse={"pages": 2})
    after_meta = store.paper_payload("paper-1")
    assert after_meta["meta"] == PAPER_META
    assert "references" not in after_meta, "writing meta must not invent references"

    store.set_paper_references("paper-1", REFERENCES, provenance=REFERENCE_PROVENANCE)
    after_refs = store.paper_payload("paper-1")
    for key in ("meta", "meta_provenance", "source", "notes", "parse"):
        assert after_refs[key] == after_meta[key], key

    store.set_paper_reference_resolution("paper-1", 0, "doc-resolved")
    after_resolution = store.paper_payload("paper-1")
    assert after_resolution["references"][0]["resolved_document_id"] == "doc-resolved"
    assert after_resolution["references"][1] == after_refs["references"][1]
    for key in ("meta", "meta_provenance", "source", "notes", "parse",
                "references_provenance"):
        assert after_resolution[key] == after_refs[key], key


def test_slot_field_sets_stay_on_their_side_of_the_accessor_boundary(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _write_meta_and_references(store)

    p1 = store.get_paper_payload("paper-1")
    p2 = store.paper_payload("paper-1")

    assert set(p1) == P1_SLOT_KEYS
    assert set(p2) == P2_SLOT_KEYS
    assert P1_ONLY_KEYS.isdisjoint(p2), (
        "P2's accessor must not surface P1's structure fields")
    # get_paper_payload never returns None for an unknown/non-paper document
    assert store.get_paper_payload("nope") is None
    assert store.paper_payload("nope") is None
    _seed_note(store)
    assert store.get_paper_payload("note-1") is None
    assert store.paper_payload("note-1") == {}


# ---------------------------------------------------------------------------
# I4 — P3's projection merges both slots field by field
# ---------------------------------------------------------------------------

def test_i4_view_merges_the_two_slots_field_by_field(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _write_meta_and_references(store)
    record = store.get_document("paper-1")

    assert _view(store) == {
        "document_id": "paper-1",
        "doc_kind": "paper",
        "title": record["title"],
        # every PaperMeta field comes from the P2 slot
        "meta": dict(PAPER_META),
        # sections come from the P1 slot, with the display page label derived
        # from P1's page_map (raw 0-based indexes stay on the wire)
        "sections": [
            {"level": 1, "title": "1 Introduction", "text": "Recurrent models...",
             "page_start": 0, "page_end": 0, "page_label": "p.1"},
            {"level": 2, "title": "1.1 Background", "text": "Background text",
             "page_start": 0, "page_end": 1, "page_label": "p.1–2"},
        ],
        # references come from the P2 slot, normalised (None -> "") plus the
        # per-entry parse status from references_provenance
        "references": [
            {"raw": "[1] Bahdanau et al. 2015", "title": "Neural Machine Translation",
             "authors": ["Dzmitry Bahdanau"], "year": 2015, "doi": "",
             "resolved_document_id": "doc-ref-1", "notes": []},
            {"raw": "[2] Anonymous", "title": "", "authors": [], "year": None,
             "doi": "", "resolved_document_id": "", "notes": ["unparseable"]},
        ],
    }


def test_i4_view_prefers_the_p2_slot_over_p1_placeholders(tmp_path):
    """P1 writes empty placeholders; when it does carry values P2 still wins."""

    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store, paper={
        **PAPER_PAYLOAD,
        "meta": {"title": "P1 placeholder"},
        "references": [{"raw": "P1 raw", "title": "P1 ref"}],
    })

    before_p2 = _view(store)
    assert before_p2["meta"]["title"] == "P1 placeholder", (
        "with no P2 slot yet the view degrades to P1's placeholder")
    assert [ref["title"] for ref in before_p2["references"]] == ["P1 ref"]
    assert len(before_p2["sections"]) == 2, "P1 sections are never affected"

    _write_meta_and_references(store)
    after_p2 = _view(store)
    assert after_p2["meta"]["title"] == "Attention Is All You Need"
    assert [ref["title"] for ref in after_p2["references"]] == [
        "Neural Machine Translation", ""]


def test_i4_p2_slot_cannot_smuggle_sections_into_the_view(tmp_path):
    """A hostile/legacy P2 slot carrying sections must not shadow P1's."""

    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _write_meta_and_references(store)

    data = json.loads(_record_path(root).read_text(encoding="utf-8"))
    data["paper"]["sections"] = [{"level": 1, "title": "HIJACK", "text": "x"}]
    data["paper"]["page_map"] = [{"page_index": 0, "page_number": 9}]
    _record_path(root).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    body = _view(store)
    assert [section["title"] for section in body["sections"]] == [
        "1 Introduction", "1.1 Background"]
    assert body["sections"][0]["page_label"] == "p.1"
    assert body["meta"]["title"] == "Attention Is All You Need"


def test_i4_view_degrades_to_empty_defaults_without_either_slot(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed_note(store)
    body = _view(store, "note-1")
    assert body["doc_kind"] == ""
    assert body["sections"] == [] and body["references"] == []
    assert body["meta"] == {"title": "", "authors": [], "year": None,
                            "venue": "", "doi": "", "abstract": "",
                            "keywords": [], "source": ""}


# ---------------------------------------------------------------------------
# I5 — durable reload consistency
# ---------------------------------------------------------------------------

def test_i5_durable_reload_keeps_both_slots_and_the_view_identical(tmp_path):
    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _write_meta_and_references(store)
    p1_before = store.get_paper_payload("paper-1")
    p2_before = store.paper_payload("paper-1")
    view_before = _view(store)

    reopened = FileDocumentStore(root)

    assert reopened.get_paper_payload("paper-1") == p1_before
    assert reopened.paper_payload("paper-1") == p2_before
    assert _view(reopened) == view_before


def test_legacy_record_slot_payload_is_still_readable(tmp_path):
    """Back-compat read: pre-split records kept the whole payload in record.json."""

    root = tmp_path / "library"
    store = FileDocumentStore(root)
    _seed_paper(store)
    _paper_json_path(root).unlink()

    data = json.loads(_record_path(root).read_text(encoding="utf-8"))
    data["paper"] = dict(PAPER_PAYLOAD)
    _record_path(root).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    assert not _paper_json_path(root).exists()
    legacy = store.get_paper_payload("paper-1")
    assert [section["title"] for section in legacy["sections"]] == [
        "1 Introduction", "1.1 Background"]
    assert _view(store)["sections"][0]["title"] == "1 Introduction"


# ---------------------------------------------------------------------------
# P2 verdict R2 — the duplicated contract classes stay field-identical
# ---------------------------------------------------------------------------

def _schema_without_docstring(model) -> dict:
    schema = dict(model.model_json_schema())
    schema.pop("description", None)  # the only difference between the two copies
    return schema


def test_duplicate_contract_classes_share_field_sets():
    """SPEC §2 keeps both copies; their field sets must not drift.

    ``papers/model.py`` (P1's payload schema) and
    ``papers/metadata.py`` / ``papers/references.py`` (P2's parse/validate
    types) define the same contract.  The landing contract is dict-based, so
    the two copies never meet at the store seam — but they must keep meaning
    the same thing.
    """

    from graph2note.papers import metadata, model
    from graph2note.papers import references as references_module

    assert list(model.PaperMeta.model_fields) == list(metadata.PaperMeta.model_fields)
    assert list(model.PaperReference.model_fields) == list(
        references_module.PaperReference.model_fields)
    assert _schema_without_docstring(model.PaperMeta) == _schema_without_docstring(
        metadata.PaperMeta)
    assert _schema_without_docstring(model.PaperReference) == _schema_without_docstring(
        references_module.PaperReference)
