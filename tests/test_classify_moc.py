"""Offline tests for topic classification + MOC (notes-organizer issue 02).

Covers the acceptance criteria:
- classification scheme schema validation (invalid schemes rejected)
- MOC covers all categories & all documents (every note in >=1 MOC, links valid)
- first-level category cap (max 8); >8 rejected
- human-adjusted schemes re-export and take effect; topics persist on the record
- golden fixtures: empty / single-topic / multi-topic / CN+EN naming
- all tests offline (LLM planner is injected; no live gateway calls)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graph2note.notes import classify as C
from graph2note.notes import exporter as X
from graph2note.notes import llm
from graph2note.notes.exporter import ExportEntry, VaultExportError
from graph2note.notes.loader import load_entries
from graph2note.notes.moc import build_mocs
from graph2note.store import FileDocumentStore

GOLDEN = Path(__file__).parent / "golden"


# shared scratch dir so entries always have a real original image on disk
_TMP = Path(tempfile.mkdtemp())


def mk(doc_id, title, markdown="", updated_at="2026-09-08T10:00:00"):
    op = _TMP / f"{doc_id}.jpg"
    op.write_bytes(b"img")
    return ExportEntry(
        document_id=doc_id, title=title, markdown=markdown,
        parsed_at="2026-09-08T09:00:00", updated_at=updated_at,
        original_path=str(op), source_ext=".jpg", preprocessed_path=str(op),
        topics=[], attachments={},
    )


# ---------- schema validation ----------

def test_validate_allows_good_scheme():
    scheme = C.ClassificationScheme(
        topics=["数学", "物理"],
        assignments={"数学": ["a"], "物理": ["b"]},
        summaries={"a": "方程解", "b": "力学"},
    )
    out = C.validate_scheme(scheme, ["a", "b"])
    assert out.topics == ["数学", "物理"]


@pytest.mark.parametrize("build,ids", [
    # too many first-level topics (> cap)
    (lambda: C.ClassificationScheme(
        topics=[f"t{i}" for i in range(9)],
        assignments={f"t{i}": [f"d{i}"] for i in range(9)},
        summaries={f"d{i}": "s" for i in range(9)}),
     [f"d{i}" for i in range(9)]),
    # assignment references an unknown topic
    (lambda: C.ClassificationScheme(
        topics=["数学"], assignments={"物理": ["a"]}, summaries={"a": "s"}),
     ["a"]),
    # assignment references an unknown document
    (lambda: C.ClassificationScheme(
        topics=["数学"], assignments={"数学": ["ghost"]}, summaries={"ghost": "s"}),
     ["a"]),
    # a document is never assigned any topic
    (lambda: C.ClassificationScheme(
        topics=["数学"], assignments={"数学": ["a"]}, summaries={"a": "s", "b": "s"}),
     ["a", "b"]),
    # a document is missing its summary
    (lambda: C.ClassificationScheme(
        topics=["数学"], assignments={"数学": ["a"]}, summaries={}),
     ["a"]),
])
def test_validate_rejects_invalid(build, ids):
    with pytest.raises(C.SchemeError):
        C.validate_scheme(build(), ids)


def test_empty_docset_is_valid():
    scheme = C.ClassificationScheme(topics=[], assignments={}, summaries={})
    assert C.validate_scheme(scheme, []) == scheme


def test_exactly_max_topics_ok():
    n = 8
    scheme = C.ClassificationScheme(
        topics=[f"t{i}" for i in range(n)],
        assignments={f"t{i}": [f"d{i}"] for i in range(n)},
        summaries={f"d{i}": "s" for i in range(n)})
    C.validate_scheme(scheme, [f"d{i}" for i in range(n)])


# ---------- deterministic rule classifier ----------

def test_rule_classify_is_valid_and_deterministic(tmp_path):
    es = [
        mk("a", "代数学讲义", "方程与代数结构是数学基础"),
        mk("b", "Python 算法", "算法与数据结构、并发编程"),
        mk("c", "备忘录", "一点研究备忘"),
    ]
    a = C.classify_documents(es)
    b = C.classify_documents(es)
    assert a.to_dict() == b.to_dict()  # deterministic
    # every doc covered by some topic
    covered = {d for ds in a.assignments.values() for d in ds}
    assert covered == {"a", "b", "c"}


def test_rule_classify_untagged_binned(tmp_path):
    es = [mk("z", "nothing", "qqqzzz unknown gibberish abc")]
    s = C.classify_documents(es)
    cover = {d for ds in s.assignments.values() for d in ds}
    assert cover == {"z"}


# ---------- MOC ----------

def test_moc_covers_all_docs_and_categories(tmp_path):
    es = [
        mk("a", "代数学", "方程是基础"),
        mk("b", "物理力学", "运动与力"),
        mk("c", "算法", "排序与搜索"),
    ]
    scheme = C.classify_documents(es)
    out = X.export_vault(es, tmp_path / "vault", scheme=scheme)
    assert len(out.moc_files) == len(scheme.topics)
    for rel in out.moc_files:
        p = out.root / rel
        assert p.is_file()
        assert "type: moc" in p.read_text()

    # every note appears in at least one MOC
    linked = set()
    for rel in out.moc_files:
        text = (out.root / rel).read_text()
        for part in text.splitlines():
            if "../notes/" in part:
                safe = part.split("../notes/")[1].split("/")[0]
                linked.add(safe)
    assert linked == {e.safe_id for e in es}


def test_moc_snapshot_content(tmp_path):
    es = [mk("d1", "代数笔记", "线性代数")]
    scheme = C.ClassificationScheme(
        topics=["数学"], assignments={"数学": ["d1"]}, summaries={"d1": "线性代数基础"})
    out = X.export_vault(es, tmp_path / "vault", scheme=scheme)
    text = (out.root / "mocs" / "数学.md").read_text()
    assert "数学（MOC）" in text
    assert "收录 1 篇笔记" in text
    assert "../notes/d1/note.md" in text
    assert "线性代数基础" in text


def test_export_without_scheme_has_no_moc(tmp_path):
    es = [mk("d1", "x", "y")]
    out = X.export_vault(es, tmp_path / "vault")
    assert out.moc_files == []
    assert not (out.root / "mocs").exists() or not list((out.root / "mocs").glob("*.md"))


# ---------- persist topics to record + human adjustment ----------

def _seed(store, doc_id, title, markdown):
    base = Path(store.root)
    op = base / f"{doc_id}.jpg"; op.write_bytes(b"img")
    pp = base / f"{doc_id}.png"; pp.write_bytes(b"pre")
    ad = base / f"{doc_id}_assets"; (ad / "assets").mkdir(parents=True, exist_ok=True)
    store.save_document(
        document_id=doc_id, title=title, source_job_id=f"job-{doc_id}",
        model="test", markdown=markdown, ir_json=json.dumps({"ok": 1}),
        original_path=str(op), original_ext=".jpg",
        preprocessed_path=str(pp), preprocessed_raw_path="", assets_dir=str(ad),
        timing_json={})


def test_persist_topics_and_human_adjust(tmp_path):
    store = FileDocumentStore(str(tmp_path / "storage"))
    _seed(store, "a", "代数讲义", "方程是数学的基础")
    _seed(store, "b", "算法", "算法与数据结构")

    C.apply_scheme(store, C.ClassificationScheme(
        topics=["数学", "计算机"],
        assignments={"数学": ["a"], "计算机": ["b"]},
        summaries={"a": "代数", "b": "算法"}))

    # topics persisted on the record -> flow through loader into the export
    entries = load_entries(store)
    by_id = {e.document_id: e for e in entries}
    assert by_id["a"].topics == ["数学"]
    assert by_id["b"].topics == ["计算机"]

    # a human-edited scheme (moves doc b under 数学 too) re-applies and persists
    C.apply_scheme(store, C.ClassificationScheme(
        topics=["数学"],
        assignments={"数学": ["a", "b"]},
        summaries={"a": "代数", "b": "算法"}))
    reloaded = load_entries(FileDocumentStore(str(tmp_path / "storage")))
    by_id2 = {e.document_id: e for e in reloaded}
    assert by_id2["b"].topics == ["数学"]

    # and the adjusted scheme drives the MOC when exported
    out = X.export_vault(reloaded, tmp_path / "vault", scheme=C.ClassificationScheme(
        topics=["数学"], assignments={"数学": ["a", "b"]},
        summaries={"a": "代数", "b": "算法"}))
    moc = (out.root / "mocs" / "数学.md").read_text()
    assert "../notes/b/note.md" in moc  # adjusted doc now in the MOC


# ---------- golden fixtures (offline, from recorded schemes) ----------

def _load_golden(name):
    return C.ClassificationScheme.from_dict(
        json.loads((GOLDEN / name).read_text()))


@pytest.mark.parametrize("name,entries", [
    ("classify-empty.json", []),
    ("classify-single.json", [mk("d1", "代数笔记", "方程与代数")]),
    ("classify-multi.json", [
        mk("d1", "代数笔记", "方程与代数"), mk("d2", "物理", "力学"),
        mk("d3", "算法", "排序")]),
    ("classify-cn.json", [mk("d1", "中文笔记", "中文内容")]),
    ("classify-en.json", [mk("d1", "note", "equations and algebra")]),
])
def test_golden_scheme_export_offline(name, entries, tmp_path):
    scheme = _load_golden(name)
    doc_ids = [e.document_id for e in entries]
    validated = C.validate_scheme(scheme, doc_ids)
    out = X.export_vault(entries, tmp_path / "vault", scheme=validated)
    manifest = json.loads((out.root / "export-manifest.json").read_text())
    assert set(manifest["moc_files"]) == {
        f"mocs/{X._safe_name(t)}.md" for t in validated.topics
    }
    # each golden MOC links to its assigned docs
    for t in validated.topics:
        text = (out.root / "mocs" / f"{X._safe_name(t)}.md").read_text()
        for d in validated.assignments[t]:
            assert f"../notes/{X._safe_name(d)}/note.md" in text


def test_golden_empty_export(tmp_path):
    scheme = _load_golden("classify-empty.json")
    out = X.export_vault([], tmp_path / "vault", scheme=scheme)
    assert out.moc_files == []


# ---------- LLM path: injected planner (offline) ----------

def test_llm_classify_with_injected_planner(tmp_path):
    es = [mk("d1", "代数", "方程")]
    golden = json.dumps({"topics": ["数学"], "assignments": {"数学": ["d1"]},
                         "summaries": {"d1": "方程基础"}})
    scheme = llm.classify_via_llm(es, planner=lambda prompt, model: golden)
    assert scheme.topics == ["数学"]


def test_llm_classify_rejects_invalid_reply(tmp_path):
    es = [mk("d1", "代数", "方程")]
    # reply with a scheme missing a summary -> must be rejected before export
    bad = json.dumps({"topics": ["数学"], "assignments": {"数学": ["d1"]},
                      "summaries": {}})
    with pytest.raises(C.SchemeError):
        llm.classify_via_llm(es, planner=lambda prompt, model: bad)


def test_llm_parse_garbage():
    with pytest.raises(C.SchemeError):
        llm.parse_scheme_json("not json at all")