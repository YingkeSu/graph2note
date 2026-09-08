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

import concurrent.futures
import hashlib
import json
import os
import time
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
    result_cache: "ParseCache | None" = None,
) -> ParseResult:
    """Run the full parse chain and write artifacts under ``out_dir``.

    O2 (issue 11): when ``result_cache`` is given and holds this image+model+config,
    re-parsing returns immediately (zero LLM calls) and ``timing_json['cached']``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pid = doc_id or default_doc_id(image_path)

    router = router or make_router(model, cache=cache)
    timer = timer or StageTimer()

    # O2: result-cache fast path (同文档重新解析零调用).
    if result_cache is not None:
        hit = result_cache.get(image_path, model, preprocess)
        if hit is not None:
            tj = dict(hit.get("timing", {}))
            tj["cached"] = True              # 缓存命中标记
            _write_parse_result_files(out_dir, pid, hit.get("markdown", ""), tj)
            return ParseResult(
                markdown=hit.get("markdown", ""),
                markdown_path=str(out_dir / f"{pid}.md"),
                preprocessed_path=image_path,
                preprocessed_raw_path=image_path,
                assets_dir=str(out_dir / "assets"),
                route=RouteResult(
                    document=DocumentIR(blocks=[]),
                    degraded_block_indices=[],
                    retries=0,
                    strategy="route_a",
                    raw_content=hit.get("markdown", ""),
                    attempts=[],
                    warnings=[],
                ),
                timing_json=tj,
                timing_path=str(out_dir / "timing.json"),
                ir=DocumentIR(blocks=[]),
            )


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

    # O2: persist full parse result for zero-call reparse.
    timing_json["cached"] = False
    if result_cache is not None:
        result_cache.put(image_path, model, preprocess, {
            "markdown": md,
            "timing": timing_json,
        })
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

# ================= O2：整页解析结果缓存（同文档重新解析零调用） =================

def _config_fingerprint(*, model: str, preprocess: bool) -> str:
    """提示/配置指纹：prompt、会话、降采样或预处理开关变化时旧结果缓存失效。"""
    try:
        from .vlm import SYSTEM_PROMPT, USER_PROMPT

        raw = SYSTEM_PROMPT + USER_PROMPT
    except Exception:
        raw = ""
    raw = raw + f"|model={model}|preprocess={int(preprocess)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


class ParseCache:
    """整页解析结果缓存：key = image 字节 + model + 配置指纹。

    O2：命中时重新解析无需任何 LLM 调用（重新解析零调用），返回上一次的
    markdown 与计时 JSON。
    """

    def __init__(self, cache_dir: str) -> None:
        self.cache_dir = Path(cache_dir)

    @staticmethod
    def _sha1(source: str | bytes) -> str:
        if isinstance(source, bytes):
            return hashlib.sha1(source).hexdigest()[:16]
        with open(source, "rb") as fh:
            return hashlib.sha1(fh.read()).hexdigest()[:16]

    def path_for(self, image_path: str, model: str, preprocess: bool) -> Path:
        fp = _config_fingerprint(model=model, preprocess=preprocess)
        digest = self._sha1(image_path)
        return self.cache_dir / f"{model.replace('/', '_')}__{digest}__{fp}.json"

    def get(self, image_path: str, model: str, preprocess: bool) -> dict | None:
        p = self.path_for(image_path, model, preprocess)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def put(self, image_path: str, model: str, preprocess: bool, record: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.path_for(image_path, model, preprocess).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )


def _write_parse_result_files(out_dir: Path, pid: str, markdown: str, timing: dict) -> None:
    """Re-write the .md + timing.json for a result-cache hit."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{pid}.md").write_text(markdown, encoding="utf-8")
    (out_dir / "timing.json").write_text(json.dumps(timing, ensure_ascii=False, indent=2), encoding="utf-8")


# ================= O3：多页并发解析（预处理+LLM 并行，吞吐） =================

def parse_many(
    image_paths,
    out_dir: str,
    *,
    model: str,
    workers: int = 2,
    cache=None,
    result_cache: "ParseCache | None" = None,
    preprocess: bool = True,
    doc_ids=None,
) -> tuple[dict, dict]:
    """并发解析多页。

    O3（issue 11）：多页/多文档并行 2-4 worker 摊薄 LLM 等待，吞吐提升。每页写到
    独立子目录 ``out_dir/<doc_id>/`` 避免资源碰撞。返回 (pid -> ParseResult, summary)。
    ``summary`` 含顺序合计 latency 与并行 wall_seconds 供前后对比。
    """
    ids = list(doc_ids) if doc_ids is not None else [default_doc_id(p) for p in image_paths]
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    def _one(path, pid):
        return parse_document(
            path,
            str(out_root / pid),
            model=model,
            cache=cache,
            result_cache=result_cache,
            preprocess=preprocess,
        )

    t0 = time.monotonic()
    results: dict = {}
    seq_total = 0.0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futures = {ex.submit(_one, p, pid): pid for p, pid in zip(image_paths, ids)}
        for fut in concurrent.futures.as_completed(futures):
            pid = futures[fut]
            results[pid] = fut.result()
            seq_total += float(results[pid].timing_json.get("total_seconds", 0.0))
    wall = time.monotonic() - t0

    summary = {
        "pages": len(image_paths),
        "workers": max(1, workers),
        "sequential_sum_seconds": round(seq_total, 3),
        "parallel_wall_seconds": round(wall, 3),
        "implied_speedup": round(seq_total / wall, 2) if wall > 0 else None,
    }
    return results, summary


__all__ = [
    "parse_document",
    "parse_many",
    "make_router",
    "default_doc_id",
    "ParseResult",
    "ParseCache",
    "_config_fingerprint",
]
