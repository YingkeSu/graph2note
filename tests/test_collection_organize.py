"""Auto-organization issue 02: similar notes -> collections (offline contracts).

Covers the six acceptance criteria:

1. deterministic similarity (``pairwise_similarity``) is table-driven and
   boundary-exact, empty/single-library safe;
2. library classification is offline-testable with recorded goldens (new topic /
   merge into an existing collection / illegal output rejected);
3. the application layer is a pure, idempotent provenance split
   (``manual_collections`` never auto-changed);
4. ``collections organize`` defaults to a dry-run whose numbers match ``--yes``,
   which then shows up in the collection tree and graph collection edges;
5. the review UI is wired (markup + Node DOM contract in
   ``tests/collection_suggestions.mjs``) and accepted memberships persist;
6. the API contract works against a stub store, token usage is recorded, and no
   test ever calls a live model.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from graph2note import cli
from graph2note import collection_organize as CO
from graph2note import similarity as S
from graph2note.notes.classify import SchemeError
from graph2note.store import FileDocumentStore
from graph2note.webapp import create_app

HERE = Path(__file__).parent
GOLDEN = HERE / "golden"


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


USAGE = {
    "prompt_tokens": 320,
    "completion_tokens": 42,
    "total_tokens": 362,
    "completion_tokens_details": {"reasoning_tokens": 7},
}


class StubPlanner:
    """Recorded-reply planner with call/usage accounting (offline)."""

    def __init__(self, reply: str, *, usage=None):
        self.reply = reply
        self.usage = dict(USAGE if usage is None else usage)
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model):
        self.calls += 1
        self.prompts.append(prompt)
        return self.reply, self.usage


def _seed(store, document_id: str, title: str, markdown: str) -> dict:
    original = Path(store.root) / f"{document_id}.jpg"
    original.write_bytes(b"fixture-image-" + document_id.encode())
    return store.save_document(
        document_id=document_id,
        title=title,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=markdown,
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
    )


def _records(*ids: str) -> list[dict]:
    return [
        {"document_id": doc_id, "title": f"标题 {doc_id}",
         "current_markdown": f"# {doc_id}\n\n内容 {doc_id}"}
        for doc_id in ids
    ]


# ---------------------------------------------------------------------------
# AC1: deterministic similarity is a pure, table-driven function
# ---------------------------------------------------------------------------


def test_shingles_and_jaccard_are_pure_building_blocks():
    assert S.shingles(S.tokenize_markdown("alpha beta gamma"), 3) == {"alpha beta gamma"}
    assert S.shingles([], 3) == set()
    assert S.shingles(["a", "b", "c", "d"], 3) == {"a b c", "b c d"}
    assert S.jaccard_similarity(set(), set()) == 0.0
    assert S.jaccard_similarity({"x"}, {"x"}) == 1.0


@pytest.mark.parametrize("docs, shingle_size, threshold, expected", [
    # identical documents score 1.0 and clear any threshold
    ([{"document_id": "a", "title": "", "markdown": "alpha beta gamma delta"},
      {"document_id": "b", "title": "", "markdown": "alpha beta gamma delta"}],
     3, 0.5, [("a", "b", 1.0)]),
    # unrelated documents score 0.0 and stay below the threshold
    ([{"document_id": "a", "title": "", "markdown": "alpha beta gamma"},
      {"document_id": "b", "title": "", "markdown": "zeta eta theta"}],
     3, 0.08, []),
    # boundary: 1/3 overlap -> 0.333333 is included at its own threshold
    ([{"document_id": "a", "title": "", "markdown": "a b c d"},
      {"document_id": "b", "title": "", "markdown": "a b c e"}],
     3, 0.333333, [("a", "b", 0.333333)]),
    # boundary: one tick above is excluded
    ([{"document_id": "a", "title": "", "markdown": "a b c d"},
      {"document_id": "b", "title": "", "markdown": "a b c e"}],
     3, 0.333334, []),
    # empty library is safe
    ([], 3, 0.08, []),
    # single document has no pair
    ([{"document_id": "a", "title": "", "markdown": "alpha beta gamma"}],
     3, 0.0, []),
])
def test_pairwise_similarity_table(docs, shingle_size, threshold, expected):
    assert S.pairwise_similarity(
        docs, shingle_size=shingle_size, threshold=threshold
    ) == expected


def test_pairwise_scores_deterministic_and_all_pairs():
    docs = _records("c", "a", "b")
    first = S.pairwise_scores(docs)
    second = S.pairwise_scores(list(reversed(docs)))
    assert first == second                       # input order does not matter
    assert len(first) == 3                       # 3 choose 2
    assert first == sorted(first, key=lambda item: (-item[2], item[0], item[1]))


def test_similarity_ignores_markdown_scaffolding_and_truncates():
    noisy = "# 标题\n\n```python\nnot-relevant-code\n```\n[链接](http://x/y) 正文"
    tokens = S.tokenize_markdown(noisy, max_chars=1000)
    assert "not" not in tokens                   # fenced code dropped
    assert "http" not in tokens                  # url dropped
    assert "正" in tokens and "文" in tokens        # CJK is tokenized per character
    assert S.tokenize_markdown("abcdef", max_chars=3) == ["abc"]


# ---------------------------------------------------------------------------
# AC2: offline library classification via recorded goldens
# ---------------------------------------------------------------------------


def test_build_prompt_injects_collections_candidates_and_truncates():
    prompt = CO.build_organize_prompt(
        _records("doc-a", "doc-b", "doc-c"),
        collections=[{"name": "控制理论", "document_count": 9}],
        candidates=[("doc-a", "doc-b", 0.42), ("doc-b", "doc-c", 0.31)],
        max_candidates=1, max_documents=2,
    )
    assert "控制理论" in prompt and "优先并入" in prompt
    assert "doc-a ~ doc-b" in prompt and "0.420" in prompt
    assert "doc-b ~ doc-c" not in prompt          # top-N truncation
    assert "doc-c |" not in prompt                # document cap
    assert "其余 1 篇文档省略" in prompt


def test_plan_collections_golden_new_topic():
    planner = StubPlanner(_golden("organize-new.json"))
    result = CO.plan_collections(
        _records("doc-a", "doc-b", "doc-c"), planner=planner, model="stub",
    )
    assert result.scheme.topics == ["控制理论"]
    assert planner.calls == 1
    assert result.usage["total_tokens"] == 362
    assert result.usage["reasoning_tokens"] == 7


def test_plan_collections_golden_merges_into_existing_collection(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, f"# {doc_id}\n\n内容")
    store.create_collection("控制理论")
    planner = StubPlanner(_golden("organize-merge.json"))
    report = CO.generate_suggestions(store, planner=planner, dry_run=True)
    assert planner.calls == 1
    assert "控制理论" not in report["new_collections"]   # reused, not re-created
    assert "概率论" in report["new_collections"]
    assert report["pending_count"] == 3
    assert report["calls_made"] == 1


def test_plan_rejects_unknown_document_golden():
    planner = StubPlanner(_golden("organize-invalid-unknown-doc.json"))
    with pytest.raises(SchemeError):
        CO.plan_collections(_records("doc-a", "doc-b", "doc-c"), planner=planner)


def test_plan_rejects_too_many_topics_golden():
    payload = json.loads(_golden("organize-invalid-too-many.json"))
    doc_ids = [d for docs in payload["assignments"].values() for d in docs]
    planner = StubPlanner(_golden("organize-invalid-too-many.json"))
    with pytest.raises(SchemeError):
        CO.plan_collections(_records(*doc_ids), planner=planner)


def test_offline_planner_is_deterministic_and_needs_no_model(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", "代数", "方程与代数结构是数学基础")
    _seed(store, "doc-b", "算法", "算法与数据结构")
    report = CO.generate_suggestions(store, offline=True, dry_run=True)
    assert report["calls_made"] == 1
    assert report["model"] == "rule-classifier"
    assert report["pending_count"] >= 1


def test_empty_library_is_safe(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    report = CO.generate_suggestions(store, offline=True, dry_run=True)
    assert report["documents"] == 0
    assert report["topics"] == []
    assert report["groups"] == []
    assert report["applied_count"] == 0


# ---------------------------------------------------------------------------
# AC3: deterministic, idempotent provenance-split apply
# ---------------------------------------------------------------------------


def _plan(assignments: dict, candidates=()) -> dict:
    return {
        "scheme": {"topics": list(assignments), "assignments": assignments,
                   "summaries": {}, "version": 1},
        "candidates": [list(pair) for pair in candidates],
        "rejected": [],
    }


def test_apply_assignments_subset_and_manual_protection(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, "# 正文")
    store.create_collection("手工集合")
    store.set_collections("doc-a", ["手工集合"])

    plan = _plan({"控制理论": ["doc-a", "doc-b"]})
    outcome = CO.apply_assignments(store, plan, accept={"doc-b"}, include_manual=False)
    assert outcome["applied"] == ["doc-b"]

    record_a = store.get_document("doc-a")
    assert record_a["collections"] == ["手工集合"]           # untouched by default
    assert record_a["manual_collections"] == ["手工集合"]

    record_b = store.get_document("doc-b")
    assert record_b["collections"] == ["控制理论"]
    assert record_b["auto_collections"] == ["控制理论"]
    assert record_b["manual_collections"] == []             # never manual

    # explicit confirmation for the manual document appends auto membership
    outcome = CO.apply_assignments(store, plan, accept={"doc-a"}, include_manual=True)
    assert outcome["applied"] == ["doc-a"]
    record_a = store.get_document("doc-a")
    assert set(record_a["collections"]) == {"手工集合", "控制理论"}
    assert record_a["manual_collections"] == ["手工集合"]
    assert record_a["auto_collections"] == ["控制理论"]


def test_apply_assignments_is_idempotent(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    for doc_id in ("doc-a", "doc-b"):
        _seed(store, doc_id, doc_id, "# 正文")
    plan = _plan({"控制理论": ["doc-a", "doc-b"]})

    first = CO.apply_assignments(store, plan, accept=None)
    assert first["applied"] == ["doc-a", "doc-b"]
    snapshot = {doc_id: store.get_document(doc_id)["collections"] for doc_id in ("doc-a", "doc-b")}

    second = CO.apply_assignments(store, plan, accept=None)
    assert second["applied"] == []                            # nothing new to write
    assert {doc_id: store.get_document(doc_id)["collections"] for doc_id in ("doc-a", "doc-b")} == snapshot


def test_project_assignments_is_pure_and_snapshot_stable():
    from graph2note.collections import ensure_collection, new_registry

    registry = new_registry()
    ensure_collection(registry, "手工集合")
    records = [
        {"document_id": "doc-a", "collections": [], "manual_collections": [], "topics": []},
        {"document_id": "doc-b", "collections": ["手工集合"],
         "manual_collections": ["手工集合"], "topics": []},
    ]
    plan = _plan({"控制理论": ["doc-a"], "概率论": ["doc-b"]})

    first = CO.project_assignments(records, plan, registry=registry)
    second = CO.project_assignments(records, plan, registry=registry)
    assert first == second                                  # deterministic snapshot
    assert records[0]["collections"] == []                  # input untouched

    changes = {change["document_id"]: change for change in first["changes"]}
    assert changes["doc-a"]["collections"] == ["控制理论"]
    assert changes["doc-a"]["auto_collections"] == ["控制理论"]
    assert changes["doc-b"]["collections"] == ["手工集合", "概率论"]
    assert changes["doc-b"]["manual_collections"] == ["手工集合"]


def test_apply_assignments_skips_rejected(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", "doc-a", "# 正文")
    plan = _plan({"控制理论": ["doc-a"]})
    plan["rejected"] = ["doc-a"]
    outcome = CO.apply_assignments(store, plan, accept=None)
    assert outcome["applied"] == []
    assert store.get_document("doc-a")["collections"] == []


def test_auto_membership_survives_topic_recompute(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", "doc-a", "# 正文")
    CO.apply_assignments(store, _plan({"控制理论": ["doc-a"]}), accept=None)
    store.set_topics("doc-a", ["数学"])
    record = store.get_document("doc-a")
    assert "控制理论" in record["collections"]                # auto preserved
    assert "数学" in record["collections"]                    # topic-derived added
    assert record["auto_collections"] == ["控制理论"]


def test_deleting_collection_drops_auto_membership(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "doc-a", "doc-a", "# 正文")
    CO.apply_assignments(store, _plan({"控制理论": ["doc-a"]}), accept=None)
    assert store.get_document("doc-a")["auto_collections"] == ["控制理论"]
    assert store.delete_collection("控制理论") is True
    assert store.get_document("doc-a")["collections"] == []


# ---------------------------------------------------------------------------
# AC4: CLI dry-run == plan, --yes writes visible memberships
# ---------------------------------------------------------------------------


def _cli_report(capsys, argv: list[str]):
    args = cli.build_collections_parser().parse_args(argv)
    rc = cli.run_collections_organize(args)
    out = capsys.readouterr().out
    return rc, out


def test_cli_collections_organize_dry_run_then_yes(tmp_path, capsys):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "doc-a", "代数笔记", "方程 代数 矩阵 线性空间")
    _seed(store, "doc-b", "代数练习", "方程 代数 矩阵 线性空间")
    _seed(store, "doc-c", "物理力学", "力 运动 能量 动量")

    rc, out = _cli_report(capsys, ["organize", "--offline", "--dry-run", "--storage", str(root)])
    assert rc == 0 and "dry-run" in out
    rc, raw = _cli_report(capsys, ["organize", "--offline", "--dry-run", "--json", "--storage", str(root)])
    dry = json.loads(raw)
    assert rc == 0
    assert dry["dry_run"] is True
    assert dry["applied_count"] == 0
    assert dry["pending_count"] >= 1

    rc, raw = _cli_report(capsys, ["organize", "--yes", "--offline", "--json", "--storage", str(root)])
    yes = json.loads(raw)
    assert rc == 0
    # the --yes run reuses the cached plan: same numbers, zero extra calls
    assert yes["calls_made"] == 0
    assert yes["topics"] == dry["topics"]
    assert yes["applied_count"] == dry["pending_count"]

    reloaded = FileDocumentStore(root)
    collections = reloaded.list_collections()
    assert any(item["document_count"] >= 1 for item in collections)

    from fastapi.testclient import TestClient

    client = TestClient(create_app(document_store=reloaded, storage_dir=root))
    graph = client.get("/api/graph").json()
    assert any(node["kind"] == "collection" for node in graph["nodes"])
    assert any(edge["source"] == "manual" and edge.get("collection") for edge in graph["edges"])


def test_cli_collections_organize_rejects_illegal_scheme(tmp_path, capsys, monkeypatch):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, "# 正文")
    planner = StubPlanner(_golden("organize-invalid-unknown-doc.json"))
    monkeypatch.setattr(CO, "live_organize_planner", lambda **kwargs: planner)
    args = cli.build_collections_parser().parse_args(
        ["organize", "--dry-run", "--storage", str(root)]
    )
    assert cli.run_collections_organize(args) == 1
    err = capsys.readouterr().err
    assert "拒绝" in err
    assert not (root / CO.PLAN_FILENAME).exists()


def test_session_store_auto_collections_are_additive_and_preserved(tmp_path):
    from graph2note.store import SessionDocumentStore

    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "doc-a", "a", "# 正文")
    store.add_auto_collections("doc-a", ["控制理论"])
    record = store.get_document("doc-a")
    assert record["collections"] == ["控制理论"]
    assert record["auto_collections"] == ["控制理论"]
    assert record["manual_collections"] == []

    # replacing the manual set never removes a machine-owned membership
    store.create_collection("手工集合")
    store.set_collections("doc-a", ["手工集合"])
    record = store.get_document("doc-a")
    assert set(record["collections"]) == {"控制理论", "手工集合"}
    assert record["manual_collections"] == ["手工集合"]

    # idempotent
    store.add_auto_collections("doc-a", ["控制理论"])
    assert store.get_document("doc-a")["auto_collections"] == ["控制理论"]


def test_api_contract_against_in_memory_stub_store(tmp_path):
    from fastapi.testclient import TestClient

    from graph2note.store import SessionDocumentStore

    store = SessionDocumentStore(tmp_path / "session")
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, "# 正文")
    planner = StubPlanner(_golden("organize-new.json"))
    client = TestClient(
        create_app(document_store=store, storage_dir=store.root, organize_planner=planner)
    )
    generated = client.post("/api/collections/suggestions", json={}).json()
    assert generated["pending_count"] == 3
    applied = client.post(
        "/api/collections/suggestions/apply", json={"accept": ["doc-a"]}
    ).json()
    assert applied["applied"] == ["doc-a"]
    assert store.get_document("doc-a")["collections"] == ["控制理论"]


# ---------------------------------------------------------------------------
# AC5/AC6: API contract (stub store), persistence, telemetry, UI wiring
# ---------------------------------------------------------------------------


def test_suggestions_api_generate_apply_persist_and_telemetry(tmp_path):
    from fastapi.testclient import TestClient

    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, f"# {doc_id}\n\n内容")
    planner = StubPlanner(_golden("organize-new.json"))
    client = TestClient(
        create_app(document_store=store, storage_dir=root, organize_planner=planner)
    )

    assert client.get("/api/collections/suggestions").json()["status"] == "none"
    generated = client.post("/api/collections/suggestions", json={}).json()
    assert generated["status"] == "ok"
    assert generated["pending_count"] == 3
    assert generated["total_tokens"] == 362
    assert planner.calls == 1

    applied = client.post(
        "/api/collections/suggestions/apply",
        json={"accept": ["doc-a", "doc-b"], "reject": ["doc-c"]},
    ).json()
    assert set(applied["applied"]) == {"doc-a", "doc-b"}
    assert "doc-c" in applied["rejected"]

    reloaded = FileDocumentStore(root)
    assert reloaded.get_document("doc-a")["collections"] == ["控制理论"]
    assert reloaded.get_document("doc-c")["collections"] == []
    assert any(
        item["collection_id"] == "控制理论" and item["document_count"] == 2
        for item in reloaded.list_collections()
    )
    telemetry = json.loads((root / CO.TELEMETRY_FILENAME).read_text(encoding="utf-8"))
    assert telemetry["usage"]["total_tokens"] == 362
    assert telemetry["applied"] == 2
    # no key material is ever written into the telemetry
    assert "key" not in json.dumps(telemetry).lower()

    after = client.get("/api/collections/suggestions").json()
    assert after["pending_count"] == 0
    assert "doc-c" in after["rejected"]


def test_suggestions_api_rejects_illegal_scheme(tmp_path):
    from fastapi.testclient import TestClient

    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, "# 正文")
    planner = StubPlanner(_golden("organize-invalid-too-many.json"))
    client = TestClient(
        create_app(document_store=store, storage_dir=root, organize_planner=planner)
    )
    response = client.post("/api/collections/suggestions", json={})
    assert response.status_code == 422
    assert "拒绝" in response.json()["detail"]
    assert not (root / CO.PLAN_FILENAME).exists()
    assert client.get("/api/collections/suggestions").json()["status"] == "none"


def test_suggestions_api_manual_document_requires_confirmation(tmp_path):
    from fastapi.testclient import TestClient

    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        _seed(store, doc_id, doc_id, "# 正文")
    store.create_collection("手工集合")
    store.set_collections("doc-a", ["手工集合"])
    planner = StubPlanner(_golden("organize-new.json"))
    client = TestClient(
        create_app(document_store=store, storage_dir=root, organize_planner=planner)
    )
    generated = client.post("/api/collections/suggestions", json={}).json()
    statuses = {
        doc["document_id"]: doc["status"]
        for group in generated["groups"] for doc in group["documents"]
    }
    assert statuses["doc-a"] == "confirmation_required"
    assert statuses["doc-b"] == "pending"

    # accepting only doc-b leaves the manual document untouched
    client.post("/api/collections/suggestions/apply", json={"accept": ["doc-b"]})
    assert FileDocumentStore(root).get_document("doc-a")["collections"] == ["手工集合"]

    # an explicit chip/row accept for doc-a appends the auto membership
    client.post("/api/collections/suggestions/apply", json={"accept": ["doc-a"]})
    record_a = FileDocumentStore(root).get_document("doc-a")
    assert set(record_a["collections"]) == {"手工集合", "控制理论"}
    assert record_a["manual_collections"] == ["手工集合"]


def test_collection_suggestions_frontend_is_wired():
    from tests.static_assets import WEBSTATIC, static_js

    html = (WEBSTATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="collection-suggestions"' in html
    source = static_js()
    assert "collection_suggestions.js" in source
    assert "suggestionsHtml" in source and "suggestionChipHtml" in source
    assert "/api/collections/suggestions/apply" in source
    assert "data-suggestion-action" in source and "data-suggestion-chip" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_collection_suggestions_node_contract():
    proc = subprocess.run(
        ["node", str(HERE / "collection_suggestions.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
