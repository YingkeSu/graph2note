"""CLI acceptance tests for the IR block diff (issue S1, AC6).

Exercises the real ``graph2note diff`` entry point against a temporary
``FileDocumentStore`` library.  Everything is offline and read-only: the tests
assert the command never changes a byte in the library.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from graph2note.semantic.cli import (
    VersionResolutionError,
    format_report,
    resolve_version,
)
from graph2note.semantic import diff_ir
from graph2note.store import FileDocumentStore

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _ir_json(blocks: list[dict]) -> str:
    return json.dumps({"document_type": "note", "blocks": blocks}, ensure_ascii=False)


def _save_version(store: FileDocumentStore, document_id: str, blocks: list[dict],
                  tag: str) -> dict:
    return store.save_document(
        document_id=document_id,
        title="示范文档",
        source_job_id=f"job-{tag}",
        model="glm-5.3-flash",
        markdown="",
        ir_json=_ir_json(blocks),
        original_path=None,
        original_ext=".jpg",
        preprocessed_path=None,
        preprocessed_raw_path=None,
        assets_dir=None,
        timing_json={},
    )


@pytest.fixture()
def library(tmp_path):
    """A 2-version document with a heading edit, an add and a move."""
    storage = tmp_path / "store"
    store = FileDocumentStore(str(storage))
    _save_version(
        store,
        "doc-semantic-1",
        [
            {"type": "heading", "level": 1, "text": "1 绪论"},
            {"type": "paragraph", "text": "背景背景背景 alpha beta"},
            {"type": "paragraph", "text": "第二段内容 stable body"},
        ],
        "v0",
    )
    _save_version(
        store,
        "doc-semantic-1",
        [
            {"type": "heading", "level": 1, "text": "1 绪论与方法"},
            {"type": "paragraph", "text": "第二段内容 stable body"},
            {"type": "formula", "latex": "E = m c^2", "inline": False},
            {"type": "paragraph", "text": "背景背景背景 alpha beta"},
        ],
        "v1",
    )
    return storage


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "graph2note.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# version selection (pure)
# ---------------------------------------------------------------------------


def test_resolve_version_variants():
    ids = ["v100-0", "v200-1", "v300-2"]
    assert resolve_version("latest", ids) == "v300-2"
    assert resolve_version("prev", ids) == "v200-1"
    assert resolve_version("v300-2", ids) == "v300-2"
    assert resolve_version("v300", ids) == "v300-2"  # unique prefix
    assert resolve_version("0", ids) == "v100-0"  # 0-based index
    assert resolve_version("2", ids) == "v300-2"


def test_resolve_version_errors():
    with pytest.raises(VersionResolutionError):
        resolve_version("latest", [])
    with pytest.raises(VersionResolutionError):
        resolve_version("prev", ["v1-0"])
    with pytest.raises(VersionResolutionError):
        resolve_version("5", ["v1-0", "v2-1"])
    with pytest.raises(VersionResolutionError):
        resolve_version("nope", ["v1-0", "v2-1"])


# ---------------------------------------------------------------------------
# CLI behaviour
# ---------------------------------------------------------------------------


def test_cli_diff_latest_vs_prev_human_readable(library):
    result = _run("diff", "doc-semantic-1", "--storage", str(library))
    assert result.returncode == 0, result.stderr
    out = result.stdout
    assert "doc: doc-semantic-1" in out
    assert "verdict:" in out
    assert "by op:" in out
    assert "[modified] heading" in out
    assert "[added] formula" in out
    assert "[moved] paragraph" in out
    assert "sim=" in out


def test_cli_diff_json_is_a_structured_report(library):
    result = _run("diff", "doc-semantic-1", "--storage", str(library), "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert set(report) >= {"label_a", "label_b", "changes", "summary"}
    assert report["label_a"].endswith("-0") and report["label_b"].endswith("-1")
    summary = report["summary"]
    assert summary["blocks_a"] == 3 and summary["blocks_b"] == 4
    assert summary["verdict"] in {"unchanged", "minor", "major"}

    # block locations are traceable in both versions
    modified = next(c for c in report["changes"] if c["op"] == "modified")
    assert modified["block_type"] == "heading"
    assert modified["block_ref_a"]["index"] == 0
    assert modified["block_ref_b"]["index"] == 0
    assert modified["block_ref_a"]["anchor"] == "block-0"
    assert "绪论" in modified["block_ref_a"]["preview"]

    added = next(c for c in report["changes"] if c["op"] == "added")
    assert added["block_ref_a"] is None
    assert added["block_ref_b"]["block_type"] == "formula"


def test_cli_diff_version_selectors(library):
    default = _run("diff", "doc-semantic-1", "--storage", str(library))
    assert default.returncode == 0, default.stderr

    by_index = _run(
        "diff", "doc-semantic-1", "--versions", "0", "1", "--storage", str(library)
    )
    assert by_index.returncode == 0, by_index.stderr
    assert by_index.stdout == default.stdout

    by_alias = _run(
        "diff", "doc-semantic-1", "--versions", "prev", "latest",
        "--storage", str(library),
    )
    assert by_alias.returncode == 0, by_alias.stderr
    assert by_alias.stdout == default.stdout

    # reversed order swaps A/B in the report (not a failure).
    reversed_run = _run(
        "diff", "doc-semantic-1", "--versions", "1", "0", "--storage", str(library)
    )
    assert reversed_run.returncode == 0, reversed_run.stderr
    assert reversed_run.stdout != default.stdout


def test_cli_diff_rejects_bad_selector(library):
    result = _run(
        "diff", "doc-semantic-1", "--versions", "0", "9", "--storage", str(library)
    )
    assert result.returncode == 2
    assert "out of range" in result.stderr


def test_cli_diff_unknown_document(library):
    result = _run("diff", "doc-missing", "--storage", str(library))
    assert result.returncode == 2
    assert "not found" in result.stderr


def test_cli_diff_single_version_is_safe(tmp_path):
    storage = tmp_path / "store"
    store = FileDocumentStore(str(storage))
    _save_version(store, "doc-one", [{"type": "paragraph", "text": "only"}], "v0")
    result = _run("diff", "doc-one", "--storage", str(storage))
    assert result.returncode == 1
    assert "need two" in result.stderr
    # explicit --list still works
    listed = _run("diff", "doc-one", "--list", "--storage", str(storage))
    assert listed.returncode == 0
    assert "0:" in listed.stdout


def test_cli_diff_list_versions(library):
    result = _run("diff", "doc-semantic-1", "--list", "--storage", str(library))
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("0: ")
    assert lines[1].startswith("1: ")
    assert "[current]" in lines[-1]


def test_cli_diff_is_read_only(library):
    before = _snapshot(library)
    result = _run("diff", "doc-semantic-1", "--storage", str(library), "--json")
    assert result.returncode == 0, result.stderr
    _run("diff", "doc-semantic-1", "--list", "--storage", str(library))
    assert _snapshot(library) == before


def test_cli_diff_all_flag_includes_unchanged(library):
    result = _run("diff", "doc-semantic-1", "--storage", str(library), "--all")
    assert result.returncode == 0, result.stderr
    assert "[unchanged]" in result.stdout


def test_format_report_matches_engine_summary(library):
    from graph2note.semantic.cli import load_version_ir

    store = FileDocumentStore(str(library))
    versions = store.get_document("doc-semantic-1")["versions"]
    ids = [v["version_id"] for v in versions]
    report = diff_ir(
        load_version_ir(store, "doc-semantic-1", ids[0]),
        load_version_ir(store, "doc-semantic-1", ids[1]),
        label_a=ids[0],
        label_b=ids[1],
    )
    text = format_report(
        report, doc_id="doc-semantic-1", title="示范文档", versions=versions
    )
    assert f"changed={report.summary.changed_blocks}/{report.summary.total_blocks}" in text
    assert "verdict: " + report.summary.verdict in text
