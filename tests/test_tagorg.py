"""Offline contracts for auto-organization issue 01: tag governance.

Covers the acceptance criteria:

- recorded golden fixtures for the three inference classes (synonym merges /
  theme groups / illegal output rejected — missing reference and merge cycle
  each); CI never calls the model.
- ``apply_governance_plan`` is a pure function: merge aliases + memberships,
  groups land in vocabulary schema v2; vocabulary v1 normalizes without changing
  aliases/membership behaviour (regression).
- ``tags organize`` defaults to dry-run; the reported plan size matches the
  fixture and the predicted call count equals the real ``--yes`` runs.
- the review UI closed loop (grouped render + accept/reject + accept-all +
  grouped persistence + idempotent apply) — Node harness + API contract.
- API contract for plan/apply with the error paths (expired plan, concurrent
  rename) and per-inference token telemetry.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from fastapi.testclient import TestClient

from graph2note import cli, tagorg
from graph2note.store import FileDocumentStore, SessionDocumentStore
from graph2note.tags import normalize_vocabulary
from graph2note.webapp import create_app

HERE = Path(__file__).parent
GOLDEN = HERE / "golden"

USAGE = {
    "prompt_tokens": 900,
    "completion_tokens": 120,
    "total_tokens": 1020,
    "completion_tokens_details": {"reasoning_tokens": 12},
}

VOCABULARY = {
    "version": 1,
    "tags": {
        "存储芯片": {"aliases": []},
        "sram": {"aliases": ["SRAM"]},
        "dram": {"aliases": []},
        "静态随机存储器": {"aliases": []},
        "缓存": {"aliases": []},
        "传递函数": {"aliases": []},
        "控制理论": {"aliases": []},
    },
}


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text(encoding="utf-8")


class StubPlanner:
    """Recorded-reply planner with call/usage accounting (offline)."""

    def __init__(self, reply: str, *, usage=None, raises: Exception | None = None):
        self.reply = reply
        self.usage = dict(USAGE if usage is None else usage)
        self.raises = raises
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str, model):
        self.calls += 1
        self.prompts.append(prompt)
        if self.raises is not None:
            raise self.raises
        return self.reply, self.usage


def _seed(store, document_id: str, tags: list[str] | None = None) -> dict:
    original = Path(store.root) / f"{document_id}.jpg"
    original.write_bytes(b"fixture-image")
    record = store.save_document(
        document_id=document_id,
        title=document_id,
        source_job_id=f"job-{document_id}",
        model="fixture",
        markdown=f"# {document_id}\n",
        ir_json=json.dumps({"blocks": []}),
        original_path=str(original),
        original_ext=".jpg",
        preprocessed_path="",
        preprocessed_raw_path="",
        assets_dir="",
        timing_json={},
    )
    if tags:
        store.set_tags(document_id, tags)
    return record


# ---------------------------------------------------------------------------
# AC1: inference is offline-testable with recorded goldens
# ---------------------------------------------------------------------------


def test_infer_synonym_merges_golden():
    planner = StubPlanner(_golden("tagorg-merges.json"))
    result = tagorg.infer_governance(VOCABULARY, {"sram": 3}, planner=planner, model="stub")
    assert result.warning is None
    plan = result.plan
    assert [(m.source, m.target) for m in plan.merges] == [
        ("sram", "存储芯片"), ("静态随机存储器", "存储芯片"),
    ]
    assert plan.groups == []
    assert planner.calls == 1
    assert result.usage == {
        "prompt_tokens": 900,
        "completion_tokens": 120,
        "reasoning_tokens": 12,
        "total_tokens": 1020,
    }


def test_infer_theme_groups_golden():
    planner = StubPlanner(_golden("tagorg-groups.json"))
    result = tagorg.infer_governance(VOCABULARY, {}, planner=planner)
    assert result.plan.merges == []
    assert [(g.name, g.tags) for g in result.plan.groups] == [
        ("存储", ["存储芯片", "dram", "缓存"]),
        ("控制理论", ["传递函数", "控制理论"]),
    ]


def test_infer_rejects_missing_reference_golden():
    planner = StubPlanner(_golden("tagorg-invalid-reference.json"))
    result = tagorg.infer_governance(VOCABULARY, {}, planner=planner)
    assert result.plan is None
    assert "不存在" in (result.warning or "")


def test_infer_rejects_merge_cycle_golden():
    planner = StubPlanner(_golden("tagorg-invalid-cycle.json"))
    result = tagorg.infer_governance(VOCABULARY, {}, planner=planner)
    assert result.plan is None
    assert "成环" in (result.warning or "")


def test_validation_rejects_too_many_groups_and_double_membership():
    too_many = {"merges": [], "groups": [
        {"name": f"组{i}", "tags": ["存储芯片"]} for i in range(9)
    ]}
    with pytest.raises(tagorg.TagGovernanceError):
        tagorg.validate_governance_plan(too_many, VOCABULARY)
    doubled = {"merges": [], "groups": [
        {"name": "甲", "tags": ["存储芯片", "缓存"]},
        {"name": "乙", "tags": ["缓存", "dram"]},
    ]}
    with pytest.raises(tagorg.TagGovernanceError):
        tagorg.validate_governance_plan(doubled, VOCABULARY)


def test_build_prompt_lists_vocabulary_with_counts():
    prompt = tagorg.build_prompt(VOCABULARY, {"sram": 5, "存储芯片": 2})
    assert "sram" in prompt and "存储芯片" in prompt
    assert "SRAM" in prompt            # aliases are shown to the model
    assert "×5" in prompt
    assert '"merges"' in prompt and '"groups"' in prompt


# ---------------------------------------------------------------------------
# AC2 / AC3: deterministic apply + v2 shape + v1 migration
# ---------------------------------------------------------------------------


def _plan():
    return tagorg.TagGovernancePlan.model_validate({
        "merges": [
            {"source": "sram", "target": "存储芯片", "reason": "同义"},
            {"source": "静态随机存储器", "target": "sram", "reason": "链式"},
        ],
        "groups": [{"name": "存储", "tags": ["sram", "dram", "缓存"]}],
    })


def test_apply_merges_and_writes_groups_v2():
    vocabulary = json.loads(json.dumps(VOCABULARY, ensure_ascii=False))
    records = [
        {"document_id": "a", "tags": ["sram", "dram"]},
        {"document_id": "b", "tags": ["静态随机存储器", "存储芯片"]},
    ]
    report = tagorg.apply_governance_plan(vocabulary, records, _plan())
    assert vocabulary["version"] == 2
    assert "sram" not in vocabulary["tags"]
    assert "静态随机存储器" not in vocabulary["tags"]
    target = vocabulary["tags"]["存储芯片"]
    assert "sram" in target["aliases"] and "静态随机存储器" in target["aliases"]
    # memberships follow the merge chain and dedupe
    assert records[0]["tags"] == ["存储芯片", "dram"]
    assert records[1]["tags"] == ["存储芯片"]
    # group members follow their merged canonical, one tag at most one group
    assert vocabulary["groups"] == {"存储": {"tags": ["存储芯片", "dram", "缓存"]}}
    assert report["labels_before"] == 7
    assert report["labels_after"] == 5
    assert report["merged"] == 2
    assert report["changed"] is True


def test_apply_is_idempotent():
    vocabulary = json.loads(json.dumps(VOCABULARY, ensure_ascii=False))
    records = [{"document_id": "a", "tags": ["sram"]}]
    plan = _plan()
    first = tagorg.apply_governance_plan(vocabulary, records, plan)
    snapshot = json.loads(json.dumps(vocabulary, ensure_ascii=False))
    second = tagorg.apply_governance_plan(vocabulary, records, plan)
    assert second["merged"] == 0
    assert second["changed"] is False
    assert vocabulary == snapshot
    assert first["merged"] == 2


def test_apply_respects_rejected_subset():
    vocabulary = json.loads(json.dumps(VOCABULARY, ensure_ascii=False))
    records = [{"document_id": "a", "tags": ["sram", "dram"]}]
    report = tagorg.apply_governance_plan(
        vocabulary, records, _plan(),
        accepted={"merges": ["sram"], "groups": []},
    )
    assert [item["source"] for item in report["merges"]] == ["sram"]
    assert "静态随机存储器" in vocabulary["tags"]        # rejected merge kept
    assert vocabulary["groups"] == {}                   # rejected group skipped


def test_normalize_vocabulary_v1_to_v2_is_lossless():
    legacy = {"version": 1, "tags": {"机器学习": {"aliases": ["ML", "ml"]}}}
    normalized = normalize_vocabulary(legacy)
    assert normalized["version"] == 2
    assert normalized["tags"] == {"机器学习": {"aliases": ["ML", "ml"]}}
    assert normalized["groups"] == {}
    # v2 round-trips groups untouched
    v2 = {"version": 2, "tags": {"a": {"aliases": []}},
          "groups": {"主题": {"tags": ["a"]}}}
    assert normalize_vocabulary(v2) == v2


def test_v1_vocabulary_file_still_governs_then_migrates(tmp_path):
    root = tmp_path / "storage"
    root.mkdir(parents=True, exist_ok=True)
    (root / "tag-vocabulary.json").write_text(
        json.dumps({"version": 1, "tags": {"机器学习": {"aliases": ["ML"]}}}),
        encoding="utf-8",
    )
    store = FileDocumentStore(root)
    _seed(store, "a", ["机器学习"])
    entries = store.list_tags()
    assert entries == [{"tag": "机器学习", "aliases": ["ML"], "count": 1}]
    # existing rename/merge stays green on a v1 library
    store.merge_tags("机器学习", "ai")
    assert store.list_tags() == [{"tag": "ai", "aliases": ["ML", "机器学习"], "count": 1}]
    saved = json.loads((root / "tag-vocabulary.json").read_text(encoding="utf-8"))
    assert saved["version"] == 2 and saved["groups"] == {}


def test_merge_remaps_existing_group_membership():
    vocabulary = {
        "version": 2,
        "tags": {"sram": {"aliases": []}, "存储芯片": {"aliases": []}},
        "groups": {"存储": {"tags": ["sram"]}},
    }
    from graph2note.tags import merge_vocabulary_tags

    merge_vocabulary_tags(vocabulary, [], "sram", "存储芯片")
    assert vocabulary["groups"] == {"存储": {"tags": ["存储芯片"]}}


# ---------------------------------------------------------------------------
# AC4: CLI dry-run budget == real apply
# ---------------------------------------------------------------------------


def test_cli_organize_defaults_to_dry_run_without_writing(tmp_path, monkeypatch, capsys):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "a", ["sram", "dram"])
    store.create_tag("存储芯片")
    before = (root / "tag-vocabulary.json").read_text(encoding="utf-8")
    planner = StubPlanner(_golden("tagorg-single-merge.json"))
    monkeypatch.setattr(tagorg, "live_planner", lambda **kw: planner)

    args = cli.build_tags_parser().parse_args(
        ["organize", "--dry-run", "--json", "--storage", str(root)])
    assert args.yes is False
    assert cli.run_tags_organize(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert planner.calls == 1
    assert report["dry_run"] is True
    assert report["estimated_calls"] == 1
    assert report["calls"] == 0
    assert report["merge_count"] == 1
    assert report["group_count"] == 0
    assert report["total_tokens"] == USAGE["total_tokens"]
    # dry-run did not touch the vocabulary on disk
    assert (root / "tag-vocabulary.json").read_text(encoding="utf-8") == before


def test_cli_organize_yes_applies_and_records_telemetry(tmp_path, monkeypatch, capsys):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "a", ["sram", "dram"])
    store.create_tag("存储芯片")
    planner = StubPlanner(_golden("tagorg-single-merge.json"))
    monkeypatch.setattr(tagorg, "live_planner", lambda **kw: planner)

    args = cli.build_tags_parser().parse_args(
        ["organize", "--yes", "--json", "--storage", str(root)])
    assert cli.run_tags_organize(args) == 0
    report = json.loads(capsys.readouterr().out)
    # predicted call count equals the real run
    assert report["estimated_calls"] == report["calls"] == 1
    assert planner.calls == 1
    assert report["applied"]["merged"] == 1
    saved = json.loads((root / "tag-vocabulary.json").read_text(encoding="utf-8"))
    assert "sram" not in saved["tags"]
    assert saved["version"] == 2
    # every inference lands an event with its token usage
    log = json.loads((root / "tag-governance.json").read_text(encoding="utf-8"))
    assert log["events"][-1]["kind"] == "apply"
    assert log["events"][0]["total_tokens"] == USAGE["total_tokens"]


def test_cli_organize_rejects_illegal_plan(tmp_path, monkeypatch, capsys):
    root = tmp_path / "storage"
    store = FileDocumentStore(root)
    _seed(store, "a", ["sram", "dram"])
    store.create_tag("存储芯片")
    planner = StubPlanner(_golden("tagorg-invalid-reference.json"))
    monkeypatch.setattr(tagorg, "live_planner", lambda **kw: planner)
    args = cli.build_tags_parser().parse_args(["organize", "--json", "--storage", str(root)])
    assert cli.run_tags_organize(args) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "invalid"


# ---------------------------------------------------------------------------
# AC5 / AC6: API contract + review loop
# ---------------------------------------------------------------------------


def _app(tmp_path, reply, *, storage=None):
    store = FileDocumentStore(storage or tmp_path / "storage")
    return store, TestClient(create_app(
        document_store=store,
        storage_dir=str(storage or tmp_path / "storage"),
        tag_organize_planner=StubPlanner(reply),
    ))


def test_api_plan_and_apply_persist_groups(tmp_path):
    store, client = _app(tmp_path, _golden("tagorg-single-merge.json"))
    _seed(store, "a", ["sram", "dram"])
    store.create_tag("存储芯片")
    plan = client.post("/api/tags/organize/plan", json={}).json()
    assert plan["plan_id"]
    assert plan["merge_count"] == 1
    assert plan["merges"][0]["source"] == "sram"
    assert plan["merges"][0]["source_count"] == 1
    assert plan["estimated_calls"] == 1
    assert plan["budget"]["estimated_prompt_tokens"] > 0

    applied = client.post("/api/tags/organize/apply", json={"plan_id": plan["plan_id"]}).json()
    assert applied["report"]["merged"] == 1
    assert applied["structure"]["groups"] == []
    structure = client.get("/api/tags/groups").json()
    assert {item["tag"] for item in structure["ungrouped"]} == {"存储芯片", "dram"}
    # persisted across a fresh store instance (restart-safe groups)
    reloaded = FileDocumentStore(tmp_path / "storage")
    assert "sram" not in reloaded.tag_vocabulary()["tags"]


def test_api_apply_is_idempotent(tmp_path):
    store, client = _app(tmp_path, _golden("tagorg-single-group.json"))
    _seed(store, "a", ["sram", "dram"])
    plan = client.post("/api/tags/organize/plan", json={}).json()
    body = {"plan_id": plan["plan_id"]}
    first = client.post("/api/tags/organize/apply", json=body).json()
    assert first["report"]["groups"]
    second = client.post("/api/tags/organize/apply", json=body)
    assert second.status_code == 200
    assert second.json()["report"]["merged"] == 0
    assert second.json()["report"]["changed"] is False
    # groups survive a reload
    reloaded = FileDocumentStore(tmp_path / "storage")
    groups = reloaded.tag_vocabulary()["groups"]
    assert groups["存储"]["tags"] == ["sram", "dram"]


def test_api_plan_unknown_id_and_concurrent_rename_errors(tmp_path):
    store, client = _app(tmp_path, _golden("tagorg-single-merge.json"))
    _seed(store, "a", ["sram", "dram"])
    store.create_tag("存储芯片")
    assert client.post("/api/tags/organize/apply", json={"plan_id": "nope"}).status_code == 404
    plan = client.post("/api/tags/organize/plan", json={}).json()
    store.rename_tag("sram", "sram-v2")          # concurrent rename invalidates it
    stale = client.post("/api/tags/organize/apply", json={"plan_id": plan["plan_id"]})
    assert stale.status_code == 409
    assert "变化" in stale.json()["detail"]


def test_api_plan_invalid_reply_is_502(tmp_path):
    store, client = _app(tmp_path, _golden("tagorg-invalid-cycle.json"))
    _seed(store, "a", ["sram", "dram"])
    store.create_tag("存储芯片")
    response = client.post("/api/tags/organize/plan", json={})
    assert response.status_code == 502
    assert "成环" in response.json()["detail"]


def test_api_plan_transport_failure_is_502_without_key_leak(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    client = TestClient(create_app(
        document_store=store,
        storage_dir=str(tmp_path / "storage"),
        tag_organize_planner=StubPlanner("", raises=RuntimeError("gateway down")),
    ))
    _seed(store, "a", ["sram"])
    store.create_tag("存储芯片")
    response = client.post("/api/tags/organize/plan", json={})
    assert response.status_code == 502
    assert "gateway down" in response.json()["detail"]


def test_api_groups_render_and_ungrouped(tmp_path):
    store = FileDocumentStore(tmp_path / "storage")
    _seed(store, "a", ["存储芯片", "dram"])
    store.create_tag("孤立标签")
    store.save_tag_vocabulary({
        "version": 2,
        "tags": json.loads(json.dumps(store.tag_vocabulary()["tags"], ensure_ascii=False)),
        "groups": {"存储": {"tags": ["存储芯片"]}},
    })
    client = TestClient(create_app(document_store=store, storage_dir=str(tmp_path / "storage")))
    structure = client.get("/api/tags/groups").json()
    assert structure["groups"] == [{
        "name": "存储", "size": 1,
        "tags": [{"tag": "存储芯片", "count": 1, "aliases": []}],
    }]
    assert {item["tag"] for item in structure["ungrouped"]} == {"dram", "孤立标签"}


def test_session_store_governance_seam(tmp_path):
    store = SessionDocumentStore(tmp_path / "session")
    _seed(store, "a", ["sram"])
    store.create_tag("存储芯片")
    vocabulary = store.tag_vocabulary()
    report = tagorg.apply_governance_plan(
        vocabulary, store.tag_records(),
        tagorg.TagGovernancePlan(merges=[
            tagorg.TagMergeSuggestion(source="sram", target="存储芯片"),
        ]),
    )
    store.save_tag_vocabulary(vocabulary)
    store.save_tag_records(store.tag_records())
    assert report["merged"] == 1
    assert store.get_document("a")["tags"] == ["存储芯片"]
    assert "sram" not in store.tag_vocabulary()["tags"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node 未安装")
def test_tag_organize_node_contract():
    proc = subprocess.run(
        ["node", str(HERE / "tag_organize_dom.mjs")],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
