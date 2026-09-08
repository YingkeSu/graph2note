"""经 opencode go 网关调用视觉 LLM（见 docs/llm/opencode-go.md）。

- 端点：https://opencode.ai/zen/go/v1/chat/completions（OpenAI 兼容）
- 认证：Authorization: Bearer $OPENCODE_API_KEY（运行时从环境读取，绝不入库）
- 必须携带 x-opencode-session 头
- max_tokens 统一 10000（思考 token 计入预算，200 会被截断）
- 图片以 base64 data URL 传入
- 最终答案在 message.content（reasoning_content 是思考过程，不取）
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request

GATEWAY_BASE = "https://opencode.ai/zen/go/v1"
CHAT_COMPLETIONS = GATEWAY_BASE + "/chat/completions"

DEFAULT_MAX_TOKENS = 10000
DEFAULT_SESSION = "graph2note-spike-01"
USER_AGENT = "graph2note-eval-harness/0.1"


class GatewayError(RuntimeError):
    """网关调用失败（网络、认证、HTTP 错误、响应异常）。"""


def load_api_key() -> str:
    """从环境变量 OPENCODE_API_KEY 读取；若为空尝试读取仓库根 .env。"""
    key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if key:
        return key
    # 兼容：运行时从仓库根 .env 读取（.env 已 gitignore）
    for candidate in (".env", os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")):
        if os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("OPENCODE_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("\"'")
    raise GatewayError("未找到 OPENCODE_API_KEY（环境变量或仓库根 .env）")


def image_to_data_url(image_path: str) -> str:
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


DEFAULT_SYSTEM = (
    "你是手稿数字化引擎。把这一页手稿/文档的图片转录为 Markdown，只输出 Markdown 正文，"
    "不要额外解释。语义化删除：被删除线/涂抹明确废弃的内容不要输出，判断模糊时保守保留。"
)

DEFAULT_USER_TEMPLATE = (
    "把这一页手稿转成 Markdown：\n"
    "- 完整保留正文、标题层级（用 # ATX 标题）、列表（用 - 无序 / 1. 有序）、段落顺序。\n"
    "- 数学公式用 LaTeX（行内 $…$、独立 $$…$$）。\n"
    "- 流程图/架构图：提取节点与箭头关系，用 Markdown 列表或简短文字描述连线方向；"
    "无法可靠提取时直接抄写图中文字，严禁编造。\n"
    "- 中文标点与全角字符原样保留。\n"
    "只输出最终 Markdown："
)


RETRY_MAX_TOKENS = 2000
RETRY_USER_TEMPLATE = (
    "请把这一页手稿转成 Markdown，直接给出结果，不要思考铺垫，不要分析。\n"
    "- 完整保留正文、标题层级（# ATK 标题）、列表（- / 1.）、段落顺序。\n"
    "- 数学公式用 LaTeX（$…$ / $$…$$）。\n"
    "- 流程图/架构图：提取节点与箭头关系，用 Markdown 列表或简短文字描述连线方向；\n"
    "  无法可靠提取时直接抄写图中文字，严禁编造。\n"
    "- 语义化删除：被删除线/涂抹明确废弃的内容不要输出，模糊时保守保留。\n"
    "只输出最终 Markdown 正文："
)

# 模型在复杂图直转场景可能长时间思考而在 max_tokens 内未产出正文；
# 用递减 max_tokens + 精简提示逐级回退，直到产出正文。
FALLBACKS = [
    (RETRY_MAX_TOKENS, RETRY_USER_TEMPLATE),
    (1200, "直接用 Markdown 列出图内所有文字与结构关系，简洁，不要思考："),
]


def transcribe_image(
    image_path: str,
    model: str,
    *,
    api_key: str | None = None,
    session: str = DEFAULT_SESSION,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    prompt_text: str | None = None,
    timeout: int = 600,
) -> tuple[str, dict]:
    """调用视觉模型把图片转成 Markdown。

    返回 (content, meta)，meta 含 status/cost/latency_seconds/tokens 等，
    供报告记录调用成本与耗时。
    """
    key = api_key or load_api_key()
    data_url = image_to_data_url(image_path)

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": DEFAULT_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt_text or DEFAULT_USER_TEMPLATE},
                ],
            },
        ],
    }

    req = urllib.request.Request(
        CHAT_COMPLETIONS,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "x-opencode-session": session,
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )

    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - error path
        detail = exc.read().decode("utf-8", errors="replace")
        raise GatewayError(f"网关 HTTP {exc.code}: {detail}") from exc
    except Exception as exc:  # pragma: no cover - network path, never hit in CI
        raise GatewayError(f"网关调用失败: {exc}") from exc
    finally:
        latency = time.monotonic() - start

    try:
        choice = body["choices"][0]
        content = choice["message"].get("content", "") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise GatewayError(f"网关响应结构异常: {body}") from exc

    usage = body.get("usage", {}) or {}
    meta = {
        "model": model,
        "status": "ok",
        "cost": body.get("cost", "0"),
        "latency_seconds": round(latency, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "finish_reason": choice.get("finish_reason"),
    }
    return content, meta
