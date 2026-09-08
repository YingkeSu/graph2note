"""End-to-end parse pipeline: image -> preprocess -> router -> IR -> render.

``parse_document`` is the CLI- and web-facing entry.  It wires the fixed
stages (SPEC/PRD four-layer pipeline) through the Recognition Router and the
IR schema, and records staged timing into a JSON file that issue 11
(speed-up baseline) consumes.

Pipeline layers communicate only through data contracts: preprocessor outputs
an image path; router outputs a validated ``DocumentIR``; renderer outputs
Markdown + asset files.  No stage bypasses the router, and invalid IR never
reaches the renderer (rejected inside the router's validation/retry loop).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .attachments import AttachmentWriter, FileAssetWriter
from .ir import DocumentIR
from .render import render_markdown
from .router import RecognitionRouter, RouteARouter, RouteResult
from .timing import StageTimer


@dataclass
class ParseResult:
    markdown: str
    markdown_path: str | None
    preprocessed_path: str
    preprocessed_raw_path: str
    assets_dir: str
    route: RouteResult
    timing_json: dict
    timing_path: str | None
    ir: DocumentIR


def default_doc_id(image_path: str) -> str:
    return Path(image_path).stem


def make_router(
    model: str,
    *,
    caller=None,
    max_retries: int = 2,
    cache=None,
) -> RouteARouter:
    """Build the MVP Route A router (injectable caller for offline tests)."""
    if caller is None and cache is not None:
        from . import vlm

        def _caller(image_path, mdl, recover=False):
            return vlm.call_ir(image_path, mdl, cache=cache, recover=recover)

        caller = _caller
    return RouteARouter(model, caller=caller, max_retries=max_retries)


def parse_document(
    image_path: str,
    out_dir: str,
    *,
    model: str,
    router: RecognitionRouter | None = None,
    cache=None,
    doc_id: str | None = None,
    timer: StageTimer | None = None,
    preprocess: bool = True,
    save_preprocess_stages: bool = True,
) -> ParseResult:
    """Run the full parse chain and write artifacts under ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pid = doc_id or default_doc_id(image_path)

    router = router or make_router(model, cache=cache)
    timer = timer or StageTimer()

    # --- preprocess (independent fixed stage) -------------------------------
    pre_dir = out_dir / "preprocessed"
    pre_dir.mkdir(parents=True, exist_ok=True)
    preprocessed_path = image_path  # fallback: use raw if no preprocessing
    preprocessed_raw_path = image_path
    preprocess_info = None
    if preprocess:
        with timer.stage("preprocess"):
            from . import preprocess as pp

            prep = pp.preprocess_image(image_path, str(pre_dir), save_stages=save_preprocess_stages)
            preprocessed_path = prep["final"]
            preprocessed_raw_path = prep["stages"]["raw"]
            preprocess_info = prep

    # --- recognition (through the router; never bypassed) --------------------
    with timer.stage("llm"):
        route = router.recognize(
            preprocessed_path, diagram_source=preprocessed_path
        )

    # --- render (deterministic) ----------------------------------------------
    # FileAssetWriter treats its dir as the *root* that hosts an ``assets/``
    # subfolder (matching its ``assets/<doc>-<kind>-<index>.png`` path contract).
    # Passing the out dir as root places files at ``out_dir/assets/<name>`` so
    # the Markdown's relative ``assets/...`` references resolve on disk.
    assets_root = str(out_dir)
    with timer.stage("render"):
        writer = FileAssetWriter(assets_root, doc_id=pid)
        md = render_markdown(route.document, doc_id=pid, attachment_writer=writer)

    # leaf directory that actually holds the attachment files
    # (kept for callers that want the exact folder; refs in the Markdown use
    # ``assets/<name>`` relative to the out dir/root).

    md_path = out_dir / f"{pid}.md"
    md_path.write_text(md, encoding="utf-8")

    timing_path = out_dir / "timing.json"
    timing_json = json.loads(timer.write(str(timing_path)))

    # issue-11 baseline: record LLM meta (reasoning_tokens + latency) per attempt
    llm_attempts = []
    for a in route.attempts:
        meta = a.get("meta") or {}
        llm_attempts.append({
            "attempt": a.get("attempt"),
            "status": meta.get("status"),
            "cached": bool(meta.get("cached")),
            "latency_seconds": meta.get("latency_seconds"),
            "reasoning_tokens": meta.get("reasoning_tokens"),
            "completion_tokens": meta.get("completion_tokens"),
            "prompt_tokens": meta.get("prompt_tokens"),
            "finish_reason": meta.get("finish_reason"),
        })
    timing_json["llm"] = {
        "model": model,
        "retries": route.retries,
        "attempts": llm_attempts,
        "max_reasoning_tokens": max(
            (a.get("reasoning_tokens") or 0) for a in llm_attempts
        ) if llm_attempts else None,
        "sum_llm_latency_seconds": round(
            sum((a.get("latency_seconds") or 0) for a in llm_attempts), 3
        ) if llm_attempts else None,
    }
    # keep the file on disk in sync
    with open(timing_path, "w", encoding="utf-8") as fh:
        json.dump(timing_json, fh, ensure_ascii=False, indent=2)
    return ParseResult(
        markdown=md,
        markdown_path=str(md_path),
        preprocessed_path=preprocessed_path,
        preprocessed_raw_path=preprocessed_raw_path,
        assets_dir=assets_root,
        route=route,
        timing_json=timing_json,
        timing_path=str(timing_path),
        ir=route.document,
    )


__all__ = [
    "parse_document",
    "make_router",
    "default_doc_id",
    "ParseResult",
]