"""Cross-validation engine: two-model independent parse -> diff (issue 10).

The *diff* itself lives in ``diffing.py`` (pure function).  This module only
orchestrates the two independent model calls and degrades gracefully when one
(或 both) fails or times out: the result is still produced, marked 未验证, and
never blocks an export (SPEC FR-024 / any Edge Case).

Model calls reuse the fixed gateway strategy (``vlm.call_ir``): stable session,
direct-output prompt, 1024-longest-edge downsampling, hard timeout.  ``runner``
is injectable so tests/goldens replay recorded replies with zero network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from ..ir import DocumentIR, load_dict_as_ir
from .. import vlm as _vlm  # local, network-isolated
from .diffing import diff_documents, CONFIDENCE
from .duplicates import detect_near_dup_blocks
from .model import (
    BlockDiff,
    CrossValidationReport,
    DiffBlock,
    CONSISTENT,
    ONE_SIDE,
    CONFLICT,
)

DEFAULT_MODEL_A = "glm-5.3-flash"
DEFAULT_MODEL_B = "deepseek-v4-flash-vision-exp"

STABLE_SESSION = "graph2note-crossval"


def _parse_reply(content) -> Optional[DocumentIR]:
    """Parse + validate a raw model reply into a DocumentIR, or None."""
    obj = _vlm.parse_ir_json(content or "")
    if obj is None:
        return None
    try:
        return load_dict_as_ir(obj)
    except Exception:
        return None


def run_model(
    image_path: str,
    model: str,
    *,
    runner: Optional[Callable] = None,
    session: Optional[str] = None,
    cache=None,
    max_retries: int = 2,
    max_tokens: int = 10000,
) -> tuple[Optional[DocumentIR], dict, list[str]]:
    """One independent model parse of ``image_path``.

    ``runner(image_path, model, recover=) -> (content, meta)`` is injectable
    for offline tests.  Default wires the fixed ``vlm.call_ir`` gateway
    strategy.  Retries are a strategy switch (recover) per the R4 policy.
    Returns ``(doc, meta, warnings)``; ``doc`` is None on total failure.
    """
    session = session or f"{STABLE_SESSION}-{model.replace('/', '_')}"
    warnings: list[str] = []
    last_err = None
    for attempt in range(max_retries + 1):
        recover = attempt > 0
        try:
            if runner is not None:
                try:
                    content, meta = runner(image_path, model, recover=recover)
                except TypeError:  # 2-arg stub
                    content, meta = runner(image_path, model)
            else:
                content, meta = _vlm.call_ir(
                    image_path, model, session=session, cache=cache,
                    recover=recover, max_tokens=max_tokens,
                )
        except Exception as exc:
            warnings.append(f"{model} call failed on attempt {attempt}: {exc}")
            last_err = exc
            if attempt < max_retries:
                continue
            return None, {}, warnings
        doc = _parse_reply(content)
        if doc is not None:
            meta = dict(meta or {})
            meta["model"] = model
            meta["retries"] = attempt
            return doc, meta, warnings
        warnings.append(f"{model} reply did not parse into IR JSON (attempt {attempt})")
        last_err = RuntimeError("model did not return valid Document IR JSON")
    warnings.append(f"{model}: {last_err}")
    return None, {}, warnings


def _only_side_as_diff(a_doc, b_doc) -> BlockDiff:
    """Synthetic diff for the degraded case (one model failed): every block of
    the surviving doc is surfaced as a one-sided note, report flagged 未验证."""
    present = a_doc or b_doc
    if present is None:
        return BlockDiff(note="两模型均失败，无识别结果可对比。")
    side = "a" if a_doc is not None else "b"
    from . import text as _t
    one = [DiffBlock(tag=ONE_SIDE, block_type=b.type,
                     text_a=(_t.block_text(b) if side == "a" else None),
                     text_b=None if side == "a" else _t.block_text(b),
                     index_a=(i if side == "a" else None),
                     index_b=None if side == "a" else i,
                     side=side, block=b)
           for i, b in enumerate(present.blocks)]
    return BlockDiff(one_side=one, note="未验证：仅单模型结果，全部块标注为单侧。",
                     order_changed=False)


def cross_validate(
    image_path: str,
    *,
    model_a: str = DEFAULT_MODEL_A,
    model_b: str = DEFAULT_MODEL_B,
    runner: Optional[Callable] = None,
    cache=None,
    max_retries: int = 2,
    max_tokens: int = 10000,
    run_duplicates: bool = True,
) -> CrossValidationReport:
    """Two models parse ``image_path`` independently; diff; degrade if needed."""
    from . import text as _t

    sources = [str(image_path)] if not isinstance(image_path, (list, tuple)) \
        else [str(p) for p in image_path]
    src = " + ".join(sources)
    doc_a, meta_a, warn_a = run_model(
        sources[0], model_a, runner=runner, cache=cache, max_retries=max_retries,
        max_tokens=max_tokens)
    doc_b, meta_b, warn_b = run_model(
        sources[0], model_b, runner=runner, cache=cache, max_retries=max_retries,
        max_tokens=max_tokens)

    warnings = warn_a + warn_b
    verified = doc_a is not None and doc_b is not None
    try:
        if verified:
            diff = diff_documents(doc_a, doc_b)
        else:
            diff = _only_side_as_diff(doc_a, doc_b)
    except Exception as exc:  # defensive: diff must never crash the report
        warnings.append(f"diff failed: {exc}")
        diff = BlockDiff(note=f"diff 失败：{exc}")

    dups_a = detect_near_dup_blocks(doc_a) if (run_duplicates and doc_a) else []
    dups_b = detect_near_dup_blocks(doc_b) if (run_duplicates and doc_b) else []

    note = ""
    if not verified:
        if doc_a is None and doc_b is None:
            note = "未验证：双模型均失败，无识别结果。"
        else:
            failed = [m for m, d in [(model_a, doc_a), (model_b, doc_b)] if d is None]
            note = f"未验证:{', '.join(failed)}失败/超时，降级为单模型结果，不阻塞出稿。"

    report = CrossValidationReport(
        source=src,
        model_a=model_a,
        model_b=model_b,
        diff=diff,
        duplicates_a=dups_a,
        duplicates_b=dups_b,
        verified=verified,
        note=note,
        meta_a=meta_a,
        meta_b=meta_b,
        warnings=warnings,
    )
    return report


def verify_primary_against_second(
    primary_doc: DocumentIR,
    image_path: str,
    *,
    primary_model: str,
    second_model: str,
    runner: Optional[Callable] = None,
    cache=None,
    max_retries: int = 2,
    run_duplicates: bool = True,
) -> CrossValidationReport:
    """Diff an already-recognized primary doc against a *fresh* second-model
    parse of the same image — the body of the router ``verify_second_model``
    seam (issue 10).  ``primary_model`` labels which model produced the doc.
    """
    from . import text as _t
    doc_b, meta_b, warn_b = run_model(
        image_path, second_model, runner=runner, cache=cache, max_retries=max_retries)
    warnings = list(warn_b)
    verified = primary_doc is not None and doc_b is not None
    if verified:
        diff = diff_documents(primary_doc, doc_b)
    else:
        diff = _only_side_as_diff(primary_doc, doc_b)
        warnings.append("second model unavailable; downgraded to single model")
    note = ""
    if not verified:
        note = f"未验证:{second_model} 失败/超时，降级为单模型结果，不阻塞出稿。"
    dups_b = detect_near_dup_blocks(doc_b) if (run_duplicates and doc_b) else []
    return CrossValidationReport(
        source=str(image_path),
        model_a=primary_model,
        model_b=second_model,
        diff=diff,
        duplicates_a=detect_near_dup_blocks(primary_doc) if run_duplicates else [],
        duplicates_b=dups_b,
        verified=verified,
        note=note,
        meta_b=meta_b,
        warnings=warnings,
    )


__all__ = [
    "cross_validate",
    "verify_primary_against_second",
    "run_model",
    "diff_documents",
    "detect_near_dup_blocks",
    "DEFAULT_MODEL_A",
    "DEFAULT_MODEL_B",
]