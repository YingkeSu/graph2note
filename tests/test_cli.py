"""CLI demo entry tests (AC: minimal IR JSON -> .md entry point)."""

import json
import subprocess
import sys

from pathlib import Path

# Ensure the package is importable when invoking the module.
ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "graph2note.cli", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


def _write_ir(tmp_path, blocks):
    p = tmp_path / "doc.ir.json"
    p.write_text(json.dumps({"document_type": "note", "blocks": blocks}), encoding="utf-8")
    return p


def test_cli_ir_to_markdown(tmp_path):
    ir = _write_ir(tmp_path, [{"type": "heading", "level": 1, "text": "你好"}])
    out = tmp_path / "out.md"
    res = _run_cli(str(ir), "-o", str(out))
    assert res.returncode == 0, res.stderr
    assert out.read_text(encoding="utf-8") == "# 你好\n"


def test_cli_stdout_matches_file(tmp_path):
    ir = _write_ir(tmp_path, [{"type": "paragraph", "text": "正文"}])
    res = _run_cli(str(ir), "--stdout")
    assert res.returncode == 0
    assert res.stdout == "正文\n"


def test_cli_with_assets_dir(tmp_path):
    ir = _write_ir(tmp_path, [{"type": "diagram", "caption": "c", "nodes": [{"id": "a"}]}])
    out = tmp_path / "out.md"
    assets = tmp_path / "assets_out"
    res = _run_cli(str(ir), "-o", str(out), "--assets-dir", str(assets))
    assert res.returncode == 0, res.stderr
    md = out.read_text(encoding="utf-8")
    assert "![c](assets/doc.ir-diagram-0.png)" in md
    assert (ROOT / assets)
    # Asset relative to the written markdown's location expectation:
    # the writer uses doc_id = ir file stem "doc.ir".
    assert (assets / "assets" / "doc.ir-diagram-0.png").exists()


def test_cli_rejects_invalid_ir(tmp_path):
    bad = tmp_path / "bad.ir.json"
    bad.write_text('{"blocks": [{"type": "nope", "text": "x"}]}', encoding="utf-8")
    res = _run_cli(str(bad), "--stdout")
    assert res.returncode == 1
    assert "failed validation" in res.stderr


def test_cli_missing_file(tmp_path):
    res = _run_cli(str(tmp_path / "nope.json"), "--stdout")
    assert res.returncode == 2