"""AI 辅助 gold Markdown 草拟工具（HITL 前的近似参考，须标注「未经人工校对」）。

用法（工作区根目录）：
    python -m eval.gold_draft --model glm-5.3-flash A02 A09 A10 ...
    # 或默认对 metadata.json 全部样本
    python -m eval.gold_draft                                # 对全部分样本

产出：eval/fixtures/gold/<id>.gold.md + <id>.meta.json（调用代价/耗时）。

要点：
- gold 由 AI 逐字忠实转写，含语义化删除标注（划掉/涂改保留并打标），供后续人工校对。
- 转写调用沿用稳健网关配置（1024 降采样、稳定 x-opencode-session、max_tokens 适中、
  空正文/断连重试、硬超时），避免 glm 新 session 思考狂暴导致的空正文。
- gold 绝不提交密钥；gold 文件必须与 gold_proofed=false 一并交付（人工校对待维护者）。
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request

from PIL import Image

from .dataset import FIXTURES_DIR, GOLD_DIR, load_dataset
from .gateway import DEFAULT_SESSION, USER_AGENT, image_to_data_url, load_api_key, post_gateway

GOLD_PROMPT = (
    "你是手稿转录校对员。请把这一页手稿**逐字忠实**转写为 Markdown，保留所有可见文字、"
    "标题层级、列表、段落；数学公式用 LaTeX；流程/结构图用 Markdown 列表或文字描述节点与箭头；"
    "被划线/涂改的部分在对应位置标注 <<划掉>> / <<涂改>>（不要删除，保留以记录语义化删除表现）；"
    "看不清的字用 [?] 占位。宁可保守保留也不要漏抄。只输出 Markdown，不要解释。"
)

RETRY_MAX_TOKENS = 4000
DOWNSAMPLE_MAX_DIM = 1024


def _downsample_data_url(path: str, max_dim: int = DOWNSAMPLE_MAX_DIM) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, max_dim / max(w, h))
        if scale < 1.0:
            im = im.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _call(image_path: str, model: str, api_key: str, max_tokens: int, prompt: str) -> tuple[str, dict]:
    data_url = _downsample_data_url(image_path)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "image_url", "image_url": {"url": data_url}}, {"type": "text", "text": prompt}],
            }
        ],
    }
    start = time.monotonic()
    # 走统一 choke point：端点/认证/session 头/模型名映射随 GRAPH2NOTE_GATEWAY 切换。
    body = post_gateway(payload, api_key=api_key, session=DEFAULT_SESSION,
                        timeout=600, user_agent=USER_AGENT)
    latency = time.monotonic() - start
    choice = body["choices"][0]
    content = choice["message"].get("content", "") or ""
    usage = body.get("usage", {}) or {}
    meta = {
        "latency_seconds": round(latency, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"),
        "finish_reason": choice.get("finish_reason"),
        "downsample_max_dim": DOWNSAMPLE_MAX_DIM,
    }
    return content, meta


def draft(sample_id: str, model: str, api_key: str) -> dict:
    os.makedirs(GOLD_DIR, exist_ok=True)
    gold_path = os.path.join(GOLD_DIR, f"{sample_id}.gold.md")
    meta_path = os.path.join(GOLD_DIR, f"{sample_id}.meta.json")
    if os.path.exists(gold_path):
        with open(meta_path, encoding="utf-8") as fh:
            return json.load(fh)

    dataset = {s.id: s for s in load_dataset()}
    sample = dataset.get(sample_id)
    if sample is None:
        raise SystemExit(f"样本 {sample_id} 不在 metadata.json")

    def call(max_tokens: int, prompt: str):
        last = None
        for attempt in range(4):
            try:
                return _call(sample.image_path, model, api_key, max_tokens, prompt)
            except (urllib.error.URLError, TimeoutError, ConnectionError, urllib.error.HTTPError) as exc:
                last = exc
                time.sleep(3)
        raise last

    content, meta = call(10000, GOLD_PROMPT)
    if not content.strip():
        # 思考狂暴截断：降 max_tokens 直出重试
        content, meta2 = call(RETRY_MAX_TOKENS, "转写这一页手稿为 Markdown，直接输出，不要思考。")
        meta2["retried"] = True
        meta = meta2
    meta["gold_drafter"] = model
    meta["gold_proofed"] = False

    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    with open(gold_path, "w", encoding="utf-8") as fh:
        fh.write(content.strip() + "\n")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 辅助 gold Markdown 草拟")
    parser.add_argument("ids", nargs="*", help="样本 id；缺省=metadata.json 全部")
    parser.add_argument("--model", default="glm-5.3-flash")
    args = parser.parse_args()

    api_key = load_api_key()
    ids = args.ids or [s.id for s in load_dataset()]
    for sid in ids:
        try:
            meta = draft(sid, args.model, api_key)
            status = "cached" if "gold_drafter" not in meta else "drafted"
            print(f"{sid}: {status} latency={meta.get('latency_seconds')} "
                  f"rt={meta.get('reasoning_tokens')} ct={meta.get('completion_tokens')} "
                  f"fr={meta.get('finish_reason')}", flush=True)
        except urllib.error.HTTPError as exc:
            print(f"{sid}: HTTP {exc.code} {exc.read().decode('utf-8', errors='replace')[:120]}", flush=True)
        except Exception as exc:
            print(f"{sid}: ERR {exc}", flush=True)


if __name__ == "__main__":
    main()