"""End-to-end full-chain tests on the committed real manuscript images.

CI is never live: each test seeds a ``VlmCache`` with the *recorded real*
VLM reply (committed golden) keyed on the deterministic preprocessed image
bytes, so ``parse_document`` runs the complete chain (preprocess -> router ->
IR -> render -> assets -> timing) with zero network.

The golden for ``02-digitize-pipeline.jpg`` was recorded from a real
``glm-5.3-flash`` call (issue-03 Spike 3 evidence).  The 01 (requirements /
architecture board) page has two goldens (issue 12, two-stage fix): a **non-empty**
``real-img01.golden.json`` (real stage-1 transcription + deterministic markdown->IR)
asserting the page now renders structured non-empty Markdown, plus the historical
``real-img01-empty.golden.json`` (empty reply) kept to assert the router's clean
degrade seam is intact (never crashes, never goes live).
``"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytest.importorskip("PIL")
from graph2note import pipeline, preprocess  # noqa: E402
from graph2note.vlm import VlmCache  # noqa: E402

IMG02 = ROOT / "test-images" / "02-digitize-pipeline.jpg"
GOLDEN02 = Path(__file__).parent / "golden" / "real-img02-digitize.golden.json"
IMG01 = ROOT / "test-images" / "01-requirements-arch.jpg"
GOLDEN01_EMPTY = Path(__file__).parent / "golden" / "real-img01-empty.golden.json"
GOLDEN01 = Path(__file__).parent / "golden" / "real-img01.golden.json"


def _seed_cache(cache_dir, img_path, content, model="glm-5.3-flash"):
    """Seed cache keyed on the *deterministic* preprocessed image bytes."""
    seed_out = Path(cache_dir).parent / "seed_pre"
    seed_out.mkdir(parents=True, exist_ok=True)
    prep = preprocess.preprocess_image(str(img_path), str(seed_out), save_stages=False)
    cache = VlmCache(str(cache_dir))
    cache.put(prep["final"], model, content, {"model": model})
    return cache


@pytest.mark.skipif(not (IMG02.exists() and GOLDEN02.exists()),
                    reason="real test image + golden present")
def test_real_image_02_renders_structure(tmp_path):
    cache = _seed_cache(tmp_path / "cache", IMG02, GOLDEN02.read_text("utf-8"))
    result = pipeline.parse_document(
        str(IMG02), str(tmp_path / "out"), model="glm-5.3-flash", cache=cache,
    )
    # the router consumed the cached recorded reply (never live)
    assert result.route.attempts[0]["meta"]["cached"] is True

    md = Path(result.markdown_path).read_text(encoding="utf-8")
    assert md.startswith("# 需求")          # structure-correct Markdown
    assert "> 解析" in md or "解析" in md
    assert "assets/" in md                  # diagram reference embedded

    # full layered pipeline timing present
    timing = json.loads(Path(result.timing_path).read_text(encoding="utf-8"))
    assert {"preprocess", "llm", "render"} <= set(timing["stage_names"])
    assert timing["llm"]["model"] == "glm-5.3-flash"

    # every image reference has a written asset file
    from graph2note.attachments import missing_attachments

    assert missing_attachments(result.markdown, result.assets_dir) == []


@pytest.mark.skipif(not (IMG01.exists() and GOLDEN01.exists()),
                    reason="real test image + non-empty golden present")
def test_real_image_01_renders_nonempty_via_golden(tmp_path):
    """issue 12: 01 (architecture board) now renders non-empty structured Markdown.

    Root-cause regression — the product Route A pipeline produced empty IR / empty
    ``.md`` on real scanned boards.  With the two-stage fix (validated VLM
    Markdown stage + deterministic markdown->IR), the cached non-empty golden
    renders structured non-empty Markdown.
    """
    cache = _seed_cache(tmp_path / "cache", IMG01, GOLDEN01.read_text("utf-8"))
    result = pipeline.parse_document(
        str(IMG01), str(tmp_path / "out"), model="glm-5.3-flash", cache=cache,
    )
    assert result.route.attempts[0]["meta"]["cached"] is True
    assert result.ir.blocks
    md = Path(result.markdown_path).read_text(encoding="utf-8")
    assert md.strip() != ""                     # key: no longer empty
    assert not any("empty" in w for w in result.route.warnings)
    from graph2note.attachments import missing_attachments
    assert missing_attachments(result.markdown, result.assets_dir) == []


@pytest.mark.skipif(not (IMG01.exists() and GOLDEN01_EMPTY.exists()),
                    reason="real test image + empty golden present")
def test_real_image_01_empty_reply_degrades_cleanly(tmp_path):
    cache = _seed_cache(tmp_path / "cache", IMG01, GOLDEN01_EMPTY.read_text("utf-8"))
    # model replies empty -> router must degrade, never crash, never go live
    result = pipeline.parse_document(
        str(IMG01), str(tmp_path / "out"), model="glm-5.3-flash", cache=cache,
    )
    assert result.route.attempts[0]["meta"]["cached"] is True
    assert any("empty" in w for w in result.route.warnings)
    assert result.ir.blocks == []
    # still wrote an (empty) markdown + timing without raising
    assert Path(result.markdown_path).exists()
    assert Path(result.timing_path).exists()