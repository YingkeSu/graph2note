"""Issue 11 optimizations: O2 result-cache zero-call reparse + O3 multi-page
concurrency — offline (seeded VlmCache / stub router), no network."""

import json
import pathlib

import pytest

from graph2note import pipeline
from graph2note.router import RouteARouter
from graph2note.vlm import VlmCache

pytest.importorskip("PIL")


def _valid_reply():
    return (pathlib.Path(__file__).parent / "golden" / "valid-ir.golden.json").read_text(
        encoding="utf-8"
    )


def _make_test_image(tmp_path, name="note", draw_text=True):
    from PIL import Image, ImageDraw, ImageFont

    im = Image.new("RGB", (700, 500), (255, 255, 255))
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=28)
    except TypeError:
        font = ImageFont.load_default()
    if draw_text:
        d.text((40, 60), "标题：状态空间模型", fill=(40, 40, 40), font=font)
    p = tmp_path / f"{name}.png"
    im.save(p)
    return p


def _counting_router():
    calls = {"n": 0}

    def caller(img, model):
        calls["n"] += 1
        return _valid_reply(), {"status": "ok", "latency_seconds": 1.0, "cached": False}

    return RouteARouter("dummy", caller=caller), calls


# ---------------- O2：整页结果缓存（重新解析零调用） ----------------

def test_result_cache_zero_call_reparse(tmp_path):
    img = _make_test_image(tmp_path)
    rc = pipeline.ParseCache(str(tmp_path / "rc"))
    router, calls = _counting_router()
    out = str(tmp_path / "out")
    r1 = pipeline.parse_document(str(img), out, model="dummy", router=router, result_cache=rc)
    assert calls["n"] == 1                       # first parse -> 1 model call
    assert r1.timing_json["cached"] is False

    r2 = pipeline.parse_document(str(img), out, model="dummy", router=router, result_cache=rc)
    assert calls["n"] == 1                       # reparse -> ZERO additional model calls
    assert r2.markdown == r1.markdown
    assert r2.timing_json["cached"] is True
    md_file = (tmp_path / "out" / "note.md").read_text(encoding="utf-8")
    assert md_file == r2.markdown          # md file still written on hit


def test_result_cache_partitioned_by_model(tmp_path):
    img = _make_test_image(tmp_path, "named")
    rc = pipeline.ParseCache(str(tmp_path / "rc"))
    router, _ = _counting_router()
    out = str(tmp_path / "o")
    pipeline.parse_document(str(img), out, model="dummy", router=router, result_cache=rc)
    # different model -> miss
    assert rc.get(str(img), "other-model", True) is None
    assert rc.get(str(img), "dummy", True) is not None


# ---------------- 管线级超时/重试回归（AC：提速不引入新失败路径） ----------------

def test_pipeline_timeout_propagates_explicit_error(tmp_path):
    """A persistent-timeout caller surfaces as RecognitionError (explicit), not a
    silent double-call or a crash — the origin of the old 'waiting for tests' waste."""
    img = _make_test_image(tmp_path)

    def always_timeout(start_time):
        def caller(img2, model):
            raise RuntimeError(f"gateway timeout after 120s")  # timeout-like
        return caller

    router = RouteARouter("dummy", caller=always_timeout(None), max_retries=2)
    from graph2note.router import RecognitionError

    with pytest.raises(RecognitionError):
        pipeline.parse_document(str(img), str(tmp_path / "out"), model="dummy", router=router)
    # no silent .md produced
    assert not (tmp_path / "out" / "note.md").exists()


def test_pipeline_recovers_after_transient_timeout(tmp_path):
    """R4: a transient timeout is followed by a strategy-switch retry that succeeds
    (recover=True on the next attempt) — the pipeline recovers instead of failing."""
    img = _make_test_image(tmp_path)
    calls = {"n": 0}

    def caller(img2, model, recover=False):
        calls["n"] += 1
        if calls["n"] == 1 and not recover:
            raise RuntimeError("gateway timeout after 120s")
        return _valid_reply(), {"status": "ok", "latency_seconds": 1.0, "cached": False}

    router = RouteARouter("dummy", caller=caller, max_retries=2)
    result = pipeline.parse_document(str(img), str(tmp_path / "out"), model="dummy", router=router)
    assert result.markdown
    assert calls["n"] == 2                        # exactly one strategy-switch retry

    from graph2note.router import RecognitionError

    assert result.route is not None


def _seed_vlm_cache(tmp_path, images):
    """Pre-populate a VlmCache so offline route calls are cache hits."""
    cache = VlmCache(str(tmp_path / "vlm"))
    for p in images:
        cache.put(str(p), "dummy", _valid_reply(), {"status": "ok", "cached": False})
    return cache


def test_parse_many_concurrent(tmp_path):
    images = [_make_test_image(tmp_path, f"p{i}") for i in range(3)]
    cache = _seed_vlm_cache(tmp_path, images)
    results, summary = pipeline.parse_many(
        [str(p) for p in images],
        str(tmp_path / "many"),
        model="dummy",
        workers=3,
        cache=cache,
        preprocess=False,
    )
    assert set(results.keys()) == {"p0", "p1", "p2"}
    assert all("状态空间模型" in r.markdown for r in results.values())
    assert summary["pages"] == 3
    assert summary["workers"] == 3
    assert summary["parallel_wall_seconds"] >= 0
    assert summary["sequential_sum_seconds"] >= 0