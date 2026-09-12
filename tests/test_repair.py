"""Offline tests for the R1 black-image detect → repair → verify loop.

Every parse path injects a stub router that returns recorded golden IR, so the
suite never touches the network.  The fixture library covers the four scan
categories (black / normal / missing raw / suspected blank).
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PIL")

from fastapi.testclient import TestClient  # noqa: E402

from graph2note import cli  # noqa: E402
from graph2note import repair  # noqa: E402
from graph2note import webapp  # noqa: E402
from graph2note.router import RouteARouter  # noqa: E402
from graph2note.store import FileDocumentStore  # noqa: E402

HERE = Path(__file__).parent
GOLDEN = (HERE / "golden" / "valid-ir.golden.json").read_text(encoding="utf-8")
BLANK_MARKDOWN = "# 此页无内容\n\n（图片为纯黑，无任何可读文字、公式、图表或结构。）"


# ---------------------------------------------------------------------------
# fixture library
# ---------------------------------------------------------------------------


def _healthy_image(seed: int = 1, w: int = 600, h: int = 800) -> Image.Image:
    arr = np.full((h, w, 3), 250, np.uint8)
    rng = np.random.default_rng(seed)
    for i in range(9):
        y = 70 + i * 80
        arr[y:y + 6, 40:40 + int(rng.integers(300, 480))] = 10
    return Image.fromarray(arr)


def _black_image(w: int = 600, h: int = 800) -> Image.Image:
    return Image.fromarray(np.zeros((h, w, 3), np.uint8))


def _write(tmp: Path, name: str, img: Image.Image) -> Path:
    p = tmp / name
    img.save(p, "PNG")
    return p


class FixtureLibrary:
    """A file-backed library with one document per scan category."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "storage"
        self.store = FileDocumentStore(str(self.root))
        self.paths: dict[str, Path] = {}
        self._build(tmp_path)

    def _add(self, document_id: str, pp: Image.Image, raw: Image.Image,
             markdown: str, raw_missing: bool = False) -> None:
        pp_path = _write(self.root, f"{document_id}-pp.png", pp)
        raw_path = _write(self.root, f"{document_id}-raw.png", raw)
        self.paths[document_id] = raw_path
        self.store.save_document(
            document_id=document_id,
            title=document_id,
            source_job_id="fixture",
            model="fixture-model",
            markdown=markdown,
            ir_json=GOLDEN,
            original_path=str(raw_path),
            original_ext=".png",
            preprocessed_path=str(pp_path),
            preprocessed_raw_path="" if raw_missing else str(raw_path),
            assets_dir="",
            timing_json={},
        )

    def _build(self, tmp_path: Path) -> None:
        self._add("doc-black", _black_image(), _healthy_image(2),
                  "图片为纯黑，无可识别的文字或图形内容，无法转录。")
        self._add("doc-normal", _healthy_image(3), _healthy_image(3),
                  "# 手稿标题\n\n这一页记录了状态空间模型的核心方程与推导要点。")
        self._add("doc-missing", _black_image(), _healthy_image(4),
                  "图片为纯黑，无法转录。", raw_missing=True)
        self._add("doc-suspected", _healthy_image(5), _healthy_image(5),
                  BLANK_MARKDOWN)

    def version_count(self, document_id: str) -> int:
        rec = self.store.get_document(document_id)
        return len(rec["versions"])


@pytest.fixture()
def library(tmp_path) -> FixtureLibrary:
    return FixtureLibrary(tmp_path)


def _stub_factory(content: str = GOLDEN, calls: list | None = None):
    def factory(image_path, model):
        def caller(image_path, model, recover=False):
            if calls is not None:
                calls.append(image_path)
            return content, {}
        return RouteARouter(model, caller=caller)
    return factory


def _no_llm(monkeypatch):
    """Fail loudly if anything reaches the real VLM gateway."""
    def _boom(*a, **k):  # pragma: no cover - only runs on a regression
        raise AssertionError("scan must not call the model")
    monkeypatch.setattr("graph2note.vlm.call_ir", _boom)


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------


def test_scan_classifies_fixture_library_offline(library, monkeypatch):
    _no_llm(monkeypatch)
    report = repair.scan_library(library.store)

    summary = report["summary"]
    assert summary == {
        "total": 4, "black": 1, "suspected": 1, "needs_reupload": 1,
        "healthy": 1, "repairable": 2, "pages": 2, "estimated_vlm_calls": 2,
    }
    by_id = {d["document_id"]: d for d in report["documents"]}
    assert by_id["doc-black"]["status"] == "black"
    assert by_id["doc-black"]["mean"] < repair.BLACK_MEAN_THRESHOLD
    assert by_id["doc-black"]["reasons"] == ["preprocessed_black"]
    assert by_id["doc-normal"]["status"] == "healthy"
    assert by_id["doc-missing"]["status"] == "needs_reupload"
    assert by_id["doc-missing"]["reasons"] == ["preprocessed_raw_missing"]
    assert by_id["doc-suspected"]["status"] == "suspected"
    assert by_id["doc-suspected"]["mean"] > repair.HEALTHY_MEAN_TARGET

    # page / call accounting is explicit per document and in the summary
    for finding in report["documents"]:
        assert finding["pages"] == 1
    assert by_id["doc-black"]["estimated_vlm_calls"] == 1
    assert by_id["doc-normal"]["estimated_vlm_calls"] == 0
    assert set(report["black"]) == {"doc-black"}
    assert set(report["suspected"]) == {"doc-suspected"}
    assert set(report["needs_reupload"]) == {"doc-missing"}
    assert set(report["repairable"]) == {"doc-black", "doc-suspected"}


def test_scan_subset_filter(library):
    report = repair.scan_library(library.store, ["doc-black", "doc-normal"])
    assert {d["document_id"] for d in report["documents"]} == {"doc-black", "doc-normal"}
    assert report["summary"]["total"] == 2
    assert report["summary"]["estimated_vlm_calls"] == 1


def test_plan_excludes_missing_raw_and_keeps_it_visible(library):
    plan = repair.plan_repair(library.store)
    assert plan["document_ids"] == ["doc-black", "doc-suspected"]
    assert plan["estimated_vlm_calls"] == 2
    assert plan["skipped"] == []

    forced = repair.plan_repair(library.store, ["doc-missing"])
    assert forced["document_ids"] == []
    assert forced["estimated_vlm_calls"] == 0
    assert forced["skipped"] == [{"document_id": "doc-missing",
                                  "reason": "needs_reupload"}]

    unknown = repair.plan_repair(library.store, ["doc-ghost"])
    assert unknown["document_ids"] == []
    assert unknown["skipped"] == [{"document_id": "doc-ghost", "reason": "not_found"}]


def test_blank_placeholder_detector():
    assert repair.looks_blank_placeholder("")
    assert repair.looks_blank_placeholder("图片为纯黑，无法转录。")
    assert repair.looks_blank_placeholder("# 此页无内容\n\n（图片为纯黑色）")
    assert not repair.looks_blank_placeholder("# 状态空间模型\n\n$$\\dot{x}=Ax+Bu$$")


# ---------------------------------------------------------------------------
# run — dry-run default, explicit confirmation, new version semantics
# ---------------------------------------------------------------------------


def test_run_without_confirmation_is_dry_run(library):
    before = {d: library.version_count(d) for d in ("doc-black", "doc-suspected")}
    plan = repair.plan_repair(library.store)  # dry-run reports only
    assert plan["estimated_vlm_calls"] == 2
    after = {d: library.version_count(d) for d in before}
    assert before == after


def test_run_appends_new_version_and_preserves_old_and_raw(library):
    black = library.store.get_document("doc-black")
    old_version_id = black["latest_version_id"]
    old_pp = Path(black["latest"]["preprocessed_path"])
    raw = Path(black["latest"]["preprocessed_raw_path"])
    old_pp_bytes = old_pp.read_bytes()
    raw_bytes = raw.read_bytes()

    calls: list[str] = []
    job = repair.run_repair(library.store, ["doc-black"], model="stub",
                            router_factory=_stub_factory(calls=calls))
    assert job.status == "done"
    item = job.items["doc-black"]
    assert item.status == "success" and item.verified is True
    assert item.new_version_id and item.new_version_id != old_version_id
    assert item.post_mean > repair.HEALTHY_MEAN_TARGET
    assert item.post_ink > repair.HEALTHY_INK_TARGET
    assert item.blank_placeholder is False

    rec = library.store.get_document("doc-black")
    assert len(rec["versions"]) == 2               # old version kept, new appended
    assert rec["latest_version_id"] == item.new_version_id
    vids = [v["version_id"] for v in rec["versions"]]
    assert old_version_id in vids

    # old version + raw are neither overwritten nor deleted
    assert old_pp.is_file() and old_pp.read_bytes() == old_pp_bytes
    assert raw.is_file() and raw.read_bytes() == raw_bytes

    # new version's preprocessed image matches the acceptance bar
    new_pp = Path(rec["latest"]["preprocessed_path"])
    mean, ink = repair.gray_stats(new_pp)
    assert mean > repair.HEALTHY_MEAN_TARGET
    assert ink > repair.HEALTHY_INK_TARGET
    assert not repair.looks_blank_placeholder(rec["current_markdown"])


def test_repaired_version_is_stamped_with_repair_provenance(library):
    job = repair.run_repair(library.store, ["doc-black"], model="stub",
                            router_factory=_stub_factory())
    item = job.items["doc-black"]
    rec = library.store.get_document("doc-black")
    versions = {v["version_id"]: v for v in rec["versions"]}
    new_version = versions[item.new_version_id]
    assert new_version["provenance"] == repair.PROVENANCE_REPAIR
    detail = new_version["provenance_detail"]
    assert detail["source"] == "preprocessed_raw"
    assert detail["repair_id"] == job.repair_id
    assert detail["old_version_id"] == item.old_version_id
    # also exposed on the enriched latest block + per-version API view (S2 seam)
    assert rec["latest"]["provenance"] == repair.PROVENANCE_REPAIR
    assert rec["versions"][-1]["provenance"] == repair.PROVENANCE_REPAIR


def test_run_budget_matches_actual_calls(library):
    plan = repair.plan_repair(library.store)
    calls: list[str] = []
    job = repair.run_repair(library.store, plan["document_ids"], model="stub",
                            router_factory=_stub_factory(calls=calls))
    assert job.status == "done"
    assert job.estimated_vlm_calls == plan["estimated_vlm_calls"]
    assert job.vlm_calls == plan["estimated_vlm_calls"]
    assert len(calls) == plan["estimated_vlm_calls"]
    assert job.counts()["success"] == plan["estimated_vlm_calls"]


def test_missing_raw_document_is_skipped_without_a_call(library):
    calls: list[str] = []
    job = repair.run_repair(library.store, ["doc-missing"], model="stub",
                            router_factory=_stub_factory(calls=calls))
    item = job.items["doc-missing"]
    assert item.status == "skipped"
    assert item.error_kind == "needs_reupload"
    assert job.vlm_calls == 0 and calls == []
    assert library.version_count("doc-missing") == 1


def test_run_persists_per_document_results_for_reload(library):
    job = repair.run_repair(library.store, ["doc-black"], model="stub",
                            router_factory=_stub_factory())
    reloaded = repair.load_job(job.work_dir)
    assert reloaded is not None
    assert reloaded.repair_id == job.repair_id
    item = reloaded.items["doc-black"]
    assert item.status == "success"
    assert reloaded.vlm_calls == 1
    assert json.loads(Path(job.work_dir, "job.json").read_text())["items"][0]["verified"] is True
    assert Path(job.work_dir, "report.json").is_file()


def test_unverified_repair_is_failed_and_retryable(library):
    # a stub that still returns the blank-page placeholder -> verification fails
    job = repair.run_repair(library.store, ["doc-black"], model="stub",
                            router_factory=_stub_factory(content=""))
    item = job.items["doc-black"]
    assert item.status == "failed" and item.verified is False
    assert item.error_kind == "verify"
    assert job.retryable_ids() == ["doc-black"]
    assert job.status == "failed"           # nothing repaired successfully

    # retrying with a good stub succeeds; a third version is appended
    retry = repair.run_job(library.store, job, router_factory=_stub_factory(),
                           only=["doc-black"])
    assert retry.items["doc-black"].status == "success"
    assert library.version_count("doc-black") == 3


def test_after_commit_hook_is_the_a1_seam(library):
    seen: list[tuple] = []

    def hook(store, document_id, result, rec):
        seen.append((document_id, len(result.markdown or ""), rec["latest_version_id"]))

    repair.run_repair(library.store, ["doc-black"], model="stub",
                      router_factory=_stub_factory(), after_commit=hook)
    assert len(seen) == 1
    assert seen[0][0] == "doc-black"
    assert seen[0][1] > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_scan_json_is_offline(library, capsys, monkeypatch):
    _no_llm(monkeypatch)
    rc = cli.main(["repair", "scan", "--storage", str(library.root), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["black"] == 1
    assert payload["summary"]["estimated_vlm_calls"] == 2


def test_cli_run_defaults_to_dry_run(library, capsys):
    before = library.version_count("doc-black")
    rc = cli.main(["repair", "run", "--storage", str(library.root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "dry-run" in out
    assert library.version_count("doc-black") == before


def test_cli_run_yes_executes_with_a_budget_report(library, capsys, monkeypatch):
    # the CLI builds the real router; substitute the offline stub factory
    monkeypatch.setattr("graph2note.repair._build_router",
                        lambda factory, raw, model, provider: _stub_factory()(raw, model))
    rc = cli.main(["repair", "run", "--yes", "--doc", "doc-black",
                   "--model", "stub", "--storage", str(library.root)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "预估 VLM 调用数 1" in out
    assert "实际 1" in out
    assert library.version_count("doc-black") == 2


# ---------------------------------------------------------------------------
# API + Web entry
# ---------------------------------------------------------------------------


def _client(library, **kw):
    return TestClient(webapp.create_app(
        model="stub-model", storage_dir=str(library.root),
        router_factory=_stub_factory(), **kw))


def _wait_repair(client, repair_id, timeout=30):
    import time

    for _ in range(int(timeout / 0.1)):
        r = client.get(f"/api/repair/{repair_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["status"] not in ("queued", "processing"):
            return body
        time.sleep(0.1)
    raise AssertionError("repair job did not finish in time")


def test_api_scan_reports_the_fixture_categories(library):
    client = _client(library)
    r = client.post("/api/repair/scan", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["black"] == 1
    assert body["summary"]["suspected"] == 1
    assert body["summary"]["needs_reupload"] == 1
    assert body["summary"]["estimated_vlm_calls"] == 2


def test_api_run_requires_explicit_ids_and_confirmation(library):
    client = _client(library)
    # no ids -> 422 (no implicit whole-library run)
    r = client.post("/api/repair/run", json={"confirm": True})
    assert r.status_code == 422
    # ids but no confirmation -> 4xx
    r = client.post("/api/repair/run", json={"document_ids": ["doc-black"]})
    assert r.status_code == 400
    # explicit ids + confirmation -> job starts
    r = client.post("/api/repair/run",
                    json={"document_ids": ["doc-black"], "confirm": True})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["estimated_vlm_calls"] == 1
    done = _wait_repair(client, job["repair_id"])
    assert done["status"] == "done"
    assert done["counts"]["success"] == 1
    assert done["vlm_calls"] == job["estimated_vlm_calls"]
    # explicit id list is validated
    assert client.post("/api/repair/run",
                       json={"document_ids": ["doc-ghost"], "confirm": True}).status_code == 404


def test_api_repair_retry_endpoint(library):
    client = TestClient(webapp.create_app(
        model="stub-model", storage_dir=str(library.root),
        router_factory=_stub_factory(content="")))
    r = client.post("/api/repair/run",
                    json={"document_ids": ["doc-black"], "confirm": True})
    done = _wait_repair(client, r.json()["repair_id"])
    assert done["counts"]["failed"] == 1
    assert done["retryable"] == ["doc-black"]

    # swap in a good stub and retry only the failed document
    client.app.state.router_factory = _stub_factory()
    r = client.post(f"/api/repair/{done['repair_id']}/retry")
    assert r.status_code == 200 and r.json()["triggered"] is True
    final = _wait_repair(client, done["repair_id"])
    assert final["counts"]["success"] == 1
    assert library.version_count("doc-black") == 3


def test_web_entry_and_static_module_are_served(library):
    client = _client(library)
    index = client.get("/")
    assert index.status_code == 200
    assert "/static/repair.js" in index.text
    js = client.get("/static/repair.js")
    assert js.status_code == 200
    assert "api/repair/scan" in js.text
