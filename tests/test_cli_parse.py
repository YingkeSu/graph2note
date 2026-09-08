"""CLI `parse` subcommand tests (offline via seeded cache + fake model)."""

import json
import subprocess
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "graph2note.cli", *args],
        cwd=ROOT, capture_output=True, text=True,
    )


def _valid_reply():
    return (Path(__file__).parent / "golden" / "valid-ir.golden.json").read_text("utf-8")


def _make_image(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (600, 400), (255, 255, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=26)
    except TypeError:
        font = ImageFont.load_default()
    d.text((40, 60), "CLI 端到端测试标题", fill=(30, 30, 30), font=font)
    p = tmp_path / "cli-img.png"
    im.save(p)
    return p


def test_parse_subcommand_offline_via_cache(tmp_path):
    pytest = __import__("pytest")
    pytest.importorskip("PIL")
    img = _make_image(tmp_path)
    # seed cache so the CLI never needs the network
    from graph2note.vlm import VlmCache

    cache = VlmCache(str(tmp_path / "cache"))
    cache.put(str(img), "glm-5.3-flash", _valid_reply(), {"model": "glm-5.3-flash"})

    out = tmp_path / "out"
    res = _run_cli(
        "parse", str(img), "--model", "glm-5.3-flash",
        "--cache-dir", str(tmp_path / "cache"),
        "--out-dir", str(out), "--no-preprocess",
    )
    assert res.returncode == 0, res.stderr
    md = (out / "cli-img.md").read_text(encoding="utf-8")
    assert "状态空间模型" in md
    assert (out / "assets").is_dir()


def test_parse_subcommand_with_output_path(tmp_path):
    img = _make_image(tmp_path)
    from graph2note.vlm import VlmCache

    cache = VlmCache(str(tmp_path / "cache"))
    cache.put(str(img), "glm-5.3-flash", _valid_reply(), {"model": "glm-5.3-flash"})
    outmd = tmp_path / "custom.md"

    res = _run_cli(
        "parse", str(img), "--model", "glm-5.3-flash",
        "--cache-dir", str(tmp_path / "cache"),
        "--no-preprocess", "-o", str(outmd),
    )
    assert res.returncode == 0, res.stderr
    assert outmd.read_text(encoding="utf-8").startswith("# 状态空间模型笔记")


def test_parse_subcommand_missing_image(tmp_path):
    res = _run_cli("parse", str(tmp_path / "nope.png"))
    assert res.returncode == 2


def test_parse_reports_recognition_error(tmp_path):
    # Seed the cache with a reply that never becomes valid IR; the router must
    # exhaust retries (offline) and the CLI exits 1 with a clean message.
    img = _make_image(tmp_path)
    from graph2note.vlm import VlmCache

    illegal = (Path(__file__).parent / "golden" / "illegal-ir.golden.json").read_text("utf-8")
    cache = VlmCache(str(tmp_path / "cache"))
    cache.put(str(img), "glm-5.3-flash", illegal, {"model": "glm-5.3-flash"})

    res = _run_cli(
        "parse", str(img), "--model", "glm-5.3-flash",
        "--cache-dir", str(tmp_path / "cache"), "--no-preprocess",
    )
    assert res.returncode == 1
    assert "Traceback" not in res.stderr


def test_legacy_compile_still_works(tmp_path):
    # issue-02 demo entry preserved.
    ir = tmp_path / "d.ir.json"
    ir.write_text(json.dumps({"blocks": [{"type": "paragraph", "text": "hi"}]}), encoding="utf-8")
    out = tmp_path / "out.md"
    res = _run_cli(str(ir), "-o", str(out))
    assert res.returncode == 0
    assert out.read_text(encoding="utf-8") == "hi\n"