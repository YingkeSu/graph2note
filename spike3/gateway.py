"""OPenCode Go gateway for Spike 3 (Spike-time manual calls only).

This module makes ONE network call per (image, model) and caches the raw model
answer to cache/<image>__<model>.json so reruns never re-invoke the LLM (quota
is limited; same image + same model must not repeat).  The pytest suite never
touches this network path - it only exercises the deterministic parser against
recorded fixture responses.

Reference: docs/llm/opencode-go.md (endpoint, auth header, x-opencode-session,
max_tokens=10000, reasoning_content eats the token budget).
"""
from __future__ import annotations

import base64
import json
import os

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)

API_BASE = "https://opencode.ai/zen/go/v1"
VISION_MODELS = ["glm-5.3-flash", "deepseek-v4-flash-vision-exp"]
SESSION = "graph2note-spike3"


def _api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY")
    if key:
        return key
    # fall back to ../.env  (gitignored; copied into worktree root, never committed)
    env_path = os.path.abspath(os.path.join(HERE, os.pardir, ".env"))
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("OPENCODE_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("OPENCODE_API_KEY not found in env or ../.env")


def _b64_data_url(path: str) -> str:
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode()
    mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
    return f"data:{mime};base64,{b64}"


EXTRACT_INSTRUCTION = (
    "这是一张手写流程图。请把其中的流程结构提取为严格的 JSON，只输出 JSON，不要任何其他文字、"
    "不要 Markdown 代码块围栏。不要推测图上没有画出来的节点或连线。\n"
    "JSON 格式（严格遵守）：\n"
    '{"nodes":[{"id":"n1","label":"节点文字"},...],"edges":[{"from":"n1","to":"n2","label":"箭头标注(可空字符串)"}]}\n'
    "要求：\n"
    "1) 每个节点给一个唯一 id；label 是节点框内的文字（中文原样保留）。\n"
    "2) edges 用 from/to 指向节点 id；方向必须忠实于箭头方向；箭头旁/线上的标注放 label，无标注用空串。\n"
    "3) 回流线、分支、汇合都要表达。\n"
    "4) 如果图中没有清晰可辨的流程结构，只输出：{\"error\":\"no_flow_extractable\"}\n"
)


def call(image_path: str, model: str, force: bool = False, retries: int = 3) -> dict:
    """Return cached-or-fetched raw record for (image, model); retries on timeout.

    Record schema: {"image","model","raw":<content>, "ok":bool, "http":int}
    On fatal network failure after retries returns an ok:False record so the
    caller can keep going.
    """
    name = os.path.splitext(os.path.basename(image_path))[0]
    key = f"{name}__{model}.json"
    cpath = os.path.join(CACHE, key)
    if os.path.exists(cpath) and not force:
        with open(cpath, encoding="utf-8") as fh:
            return json.load(fh)
    payload = {
        "model": model,
        "max_tokens": 10000,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url",
                 "image_url": {"url": _b64_data_url(image_path)}},
                {"type": "text", "text": EXTRACT_INSTRUCTION},
            ],
        }],
    }
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
        "x-opencode-session": SESSION,
        "User-Agent": "graph2note-spike3/0.1",
    }
    last = None
    for attempt in range(retries):
        try:
            resp = requests.post(f"{API_BASE}/chat/completions",
                                 headers=headers, json=payload, timeout=420)
            raw = ""
            ok = resp.status_code == 200
            if ok:
                data = resp.json()
                try:
                    raw = data["choices"][0]["message"]["content"] or ""
                except Exception:
                    raw = json.dumps(data, ensure_ascii=False)
            record = {"image": os.path.basename(image_path), "model": model,
                      "raw": raw, "ok": ok, "http": resp.status_code}
            with open(cpath, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False, indent=2)
            if ok:
                return record
            last = f"http {resp.status_code}"
        except requests.exceptions.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"
            import time
            time.sleep(3 * (attempt + 1))
    return {"image": os.path.basename(image_path), "model": model,
            "raw": "", "ok": False, "http": 0, "err": last}


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--models", nargs="+", default=VISION_MODELS)
    p.add_argument("--force", action="store_true")
    args = p.parse_args()
    import prepare_samples
    reg = load_registry()
    for model in args.models:
        for name, info in reg.items():
            record = call(info["image"], model, force=args.force)
            print(f"[{model}] {name}: http={record['http']} ok={record['ok']} "
                  f"len={len(record['raw'])}", flush=True)


def load_registry():
    import json
    with open(os.path.join(HERE, "sample_registry.json"), encoding="utf-8") as fh:
        return json.load(fh)


if __name__ == "__main__":
    main()