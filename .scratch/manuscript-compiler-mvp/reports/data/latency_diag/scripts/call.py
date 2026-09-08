"""诊断用 LLM 调用客户端（仅诊断，不改共享代码）。

- prompt 文本与 eval/gateway.py 保持 byte 级一致（只读 import 常量）。
- streaming 模式下逐 chunk 计时：区分 prefill→首个 delta / reasoning 阶段 /
  content 生成阶段的耗时，用于定位单次调用慢的主项。
- 每次调用写一条证据 JSON 到 calls/<tag>.json（小文件，可提交）。
- 不做重试/回退（避免隐性双倍调用干扰测量）。
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from datetime import datetime, timezone

# 仓库根
# scripts -> latency_diag -> data -> reports -> manuscript-compiler-mvp -> .scratch -> repo root
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), *([".."] * 6)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import requests  # noqa: E402

from eval.gateway import (  # noqa: E402  # 只读复用生产 prompt，保证实验与生产同文本
    DEFAULT_SYSTEM,
    DEFAULT_USER_TEMPLATE,
    FALLBACKS,
    RETRY_USER_TEMPLATE,
)

API = "https://opencode.ai/zen/go/v1/chat/completions"
UA = "graph2note-latency-diag/0.1"

PROMPT_STYLES = {
    "main": (DEFAULT_USER_TEMPLATE, 10000),
    "retry": (RETRY_USER_TEMPLATE, 2000),
    "fallback2": (FALLBACKS[1][1], 1200),  # "直接用 Markdown 列出图内所有文字…"
}


def _data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/jpeg"
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _payload(model, image_path, max_tokens, prompt_text, session):
    return {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "messages": [
            {"role": "system", "content": DEFAULT_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": _data_url(image_path)}},
                    {"type": "text", "text": prompt_text},
                ],
            },
        ],
    }


def _sse_chunks(resp):
    """逐行解析 SSE（data: {...} 或纯 JSON 行）。"""
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if line == "[DONE]":
            break
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def run_call(tag, model, image_path, *, session, style="main", max_tokens=None,
             stream=True, api_key=None, out_dir=None, http_timeout=420, max_wait=None):
    user_text, default_mt = PROMPT_STYLES[style]
    max_tokens = max_tokens or default_mt
    t0 = time.monotonic()
    payload = _payload(model, image_path, max_tokens, user_text, session)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-opencode-session": session,
        "User-Agent": UA,
    }
    rec = {
        "tag": tag,
        "ts_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "session": session,
        "image": os.path.basename(image_path),
        "style": style,
        "max_tokens": max_tokens,
        "stream": bool(stream),
        "http": None,
        "error": None,
    }
    reasoning_chars = 0
    content_chars = 0
    t_first_delta = t_first_reason = t_first_content = t_last_chunk = None
    n_chunks = 0
    finish_reason = None
    usage = None
    status_text = None
    aborted = False
    try:
        with requests.post(API, headers=headers, json=payload,
                           stream=bool(stream), timeout=(30, http_timeout)) as resp:
            rec["http"] = resp.status_code
            ctype = resp.headers.get("Content-Type", "")
            if resp.status_code != 200:
                rec["error"] = resp.text[:500]
            else:
                if "text/event-stream" in ctype or "application/x-ndjson" in ctype:
                    for chunk in _sse_chunks(resp):
                        n_chunks += 1
                        now = time.monotonic()
                        if t_first_delta is None:
                            t_first_delta = now
                        ch = (chunk.get("choices") or [{}])[0]
                        delta = ch.get("delta") or {}
                        rc = delta.get("reasoning_content")
                        if rc:
                            if t_first_reason is None:
                                t_first_reason = now
                            reasoning_chars += len(rc)
                        cc = delta.get("content")
                        if cc:
                            if t_first_content is None:
                                t_first_content = now
                            content_chars += len(cc)
                            t_last_chunk = now
                        if delta.get("reasoning_content") or delta.get("content"):
                            t_last_chunk = now
                        if ch.get("finish_reason"):
                            finish_reason = ch["finish_reason"]
                        if chunk.get("usage"):
                            usage = chunk["usage"]
                        if max_wait and (time.monotonic() - t0) > max_wait:
                            aborted = True
                            break
                else:
                    # 非 SSE：一次性 JSON
                    body = resp.json()
                    status_text = None
                    choice = (body.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    content = msg.get("content") or ""
                    reasoning = msg.get("reasoning_content") or ""
                    content_chars = len(content)
                    reasoning_chars = len(reasoning)
                    finish_reason = choice.get("finish_reason")
                    usage = body.get("usage")
                    now = time.monotonic()
                    if content or reasoning:
                        if reasoning and not content:
                            t_first_reason = now
                        elif content:
                            t_first_content = now
                    t_first_delta = now
                    t_last_chunk = now
    except requests.RequestException as exc:
        rec["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        total = time.monotonic() - t0

    def s(x):
        return round(x - t0, 3) if x else None

    rec["aborted"] = aborted
    rec.update({
        "timeline_s": {
            "t_first_delta": s(t_first_delta),
            "t_first_reasoning": s(t_first_reason),
            "t_first_content": s(t_first_content),
            "t_last_chunk": s(t_last_chunk),
            "total": round(total, 3),
        },
        "phase_s": {
            # 从请求发出到首个 delta（prefill/排队/图片上传处理）
            "prefill_to_first_delta": round(t_first_delta - t0, 3) if t_first_delta else None,
            # reasoning 阶段（首个 reasoning delta → 首个 content delta）
            "reasoning": round(t_first_content - t_first_reason, 3)
            if (t_first_reason is not None and t_first_content is not None) else None,
            # content 生成（首个 content delta → 末 chunk）
            "content_gen": round(t_last_chunk - t_first_content, 3)
            if (t_first_content is not None and t_last_chunk is not None) else None,
        },
        "chars": {"reasoning": reasoning_chars, "content": content_chars},
        "chunk_count": n_chunks,
        "finish_reason": finish_reason,
        "usage": usage,
    })
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, f"{tag}.json"), "w", encoding="utf-8") as fh:
            json.dump(rec, fh, ensure_ascii=False, indent=2)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--session", default="diag-latency")
    ap.add_argument("--style", default="main", choices=list(PROMPT_STYLES))
    ap.add_argument("--max-tokens", type=int, default=None)
    ap.add_argument("--nostream", action="store_true")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--max-wait", type=float, default=None, help="秒；超过即中止流并记录 partial")
    ap.add_argument("--http-timeout", type=float, default=420)
    args = ap.parse_args()
    api_key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if not api_key:
        sys.exit("OPENCODE_API_KEY 未设置")
    rec = run_call(args.tag, args.model, args.image, session=args.session,
                   style=args.style, max_tokens=args.max_tokens,
                   stream=not args.nostream, api_key=api_key, out_dir=args.outdir,
                   max_wait=args.max_wait, http_timeout=args.http_timeout)
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    if rec.get("http") != 200:
        sys.exit(f"call failed http={rec.get('http')} err={rec.get('error')}")


if __name__ == "__main__":
    main()
