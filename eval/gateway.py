"""经 opencode go 网关调用视觉 LLM（见 docs/llm/opencode-go.md）。

按诊断报告（reports/latency-diagnosis.md）落地提速修复：
- R1(P0) 每模型固定已验证直出 session；记录 reasoning_tokens，超阈值告警，支持换 session。
- R2(P0) 首调直出 prompt + 小 max_tokens；空内容/length 截断时换参/换 session，而非 10k 空转后才回退。
- R4(P1) 客户端硬超时（默认 120s）；超时/空内容标记失败原因，不隐性双倍调用。
- R3(P1) 送模型前图片降采样（最长边 ~1024px，JPEG q85）。

最终答案在 message.content；reasoning_content 是思考过程，不取。
"""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import socket
import tempfile
import time
import urllib.error
import urllib.request

GATEWAY_BASE = "https://opencode.ai/zen/go/v1"
CHAT_COMPLETIONS = GATEWAY_BASE + "/chat/completions"

# ---------- 配置（运行时可被环境变量覆盖） ----------
DEFAULT_SESSION = "graph2note-spike-01"  # R1：已验证直出模式（glm 0 reasoning、~18s）
DEFAULT_SESSIONS = {
    "glm-5.3-flash": "graph2note-spike-01",
    "deepseek-v4-flash-vision-exp": "graph2note-spike-01",
}
ALT_SESSIONS: list[str] = []  # R1：备选 session（可经 OPENCODE_SESSIONS 注入）

FIRST_CALL_MAX_TOKENS = 3500    # R2：首调直出预算
MAX_TOKENS_ESCALATE = 10000     # R2：换参/换 session 后的兜底预算
DEFAULT_MAX_TOKENS = MAX_TOKENS_ESCALATE

CALL_TIMEOUT_SECONDS = 120.0    # R4
DOWNSCALE_ENABLED = True        # R3
DEFAULT_MAX_IMAGE_DIM = 1024
DEFAULT_IMAGE_QUALITY = 85
RUNWAY_REASONING_TOKENS = 800   # R1：reasoning_tokens 阈值

USER_AGENT = "graph2note-eval-harness/0.2"


class GatewayError(RuntimeError):
    """网关调用失败（网络、认证、HTTP 错误、响应异常）。"""


# ================= 基础工具 =================

def load_api_key() -> str:
    key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if key:
        return key
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

# R2：默认 prompt——显式「直接输出，不要思考」，抑制 reasoning_content 抢占预算。
DIRECT_USER_TEMPLATE = (
    "把这一页手稿转成 Markdown。直接输出最终 Markdown 正文，不要输出任何思考过程、推理、"
    "分析或铺垫，不要解释。\n"
    "- 完整保留正文、标题层级（用 # ATX 标题）、列表（用 - 无序 / 1. 有序）、段落顺序。\n"
    "- 数学公式用 LaTeX（行内 $…$、独立 $$…$$）。\n"
    "- 流程图/架构图：提取节点与箭头关系，用 Markdown 列表或简短文字描述连线方向；"
    "无法可靠提取时直接抄写图中文字，严禁编造。\n"
    "- 中文标点与全角字符原样保留。\n"
    "只输出最终 Markdown："
)

# 旧 prompt 保留（历史/对比）；新默认用 DIRECT_USER_TEMPLATE。
DEFAULT_USER_TEMPLATE = (
    "把这一页手稿转成 Markdown：\n"
    "- 完整保留正文、标题层级（用 # ATX 标题）、列表（用 - 无序 / 1. 有序）、段落顺序。\n"
    "- 数学公式用 LaTeX（行内 $…$、独立 $$…$$）。\n"
    "- 流程图/架构图：提取节点与箭头关系，用 Markdown 列表或简短文字描述连线方向；"
    "无法可靠提取时直接抄写图中文字，严禁编造。\n"
    "- 中文标点与全角字符原样保留。\n"
    "只输出最终 Markdown："
)
RETRY_USER_TEMPLATE = (
    "请把这一页手稿转成 Markdown，直接给出结果，不要思考铺垫，不要分析。\n"
    "- 完整保留正文、标题层级（# ATK 标题）、列表（- / 1.）、段落顺序。\n"
    "- 数学公式用 LaTeX（$…$ / $$…$$）。\n"
    "- 流程图/架构图：提取节点与箭头关系，用 Markdown 列表或简短文字描述连线方向；\n"
    "  无法可靠提取时直接抄写图中文字，严禁编造。\n"
    "- 语义化删除：被删除线/涂抹明确废弃的内容不要输出，模糊时保守保留。\n"
    "只输出最终 Markdown 正文："
)
FALLBACKS = [
    (RETRY_USER_TEMPLATE, 2000),
    ("直接用 Markdown 列出图内所有文字与结构关系，简洁，不要思考：", 1200),
]


# ================= 配置解析（运行时读 env） =================

def _env_int(name, default):
    v = os.environ.get(name, "").strip()
    try:
        return int(v) if v else default
    except ValueError:
        return default


def _env_float(name, default):
    v = os.environ.get(name, "").strip()
    try:
        return float(v) if v else default
    except ValueError:
        return default


def _env_bool(name, default):
    v = os.environ.get(name, "").strip().lower()
    if not v:
        return default
    return v not in {"0", "false", "no", "off"}


def resolve_sessions(model: str) -> list[str]:
    """有序 session 列表（主 session 在前，去重）。OPENCODE_SESSION>每模型默认>全局默认；OPENCODE_SESSIONS 注入备选。"""
    primary = os.environ.get("OPENCODE_SESSION", "").strip() or DEFAULT_SESSIONS.get(model) or DEFAULT_SESSION
    extra_env = os.environ.get("OPENCODE_SESSIONS", "").strip()
    extras = [s.strip() for s in extra_env.split(",") if s.strip()] if extra_env else list(ALT_SESSIONS)
    out: list[str] = []
    for s in [primary] + extras:
        if s and s not in out:
            out.append(s)
    return out


def first_max_tokens() -> int:
    return _env_int("OPENCODE_FIRST_MAX_TOKENS", FIRST_CALL_MAX_TOKENS)


def call_timeout() -> float:
    return _env_float("OPENCODE_TIMEOUT", CALL_TIMEOUT_SECONDS)


def downscale_enabled() -> bool:
    return _env_bool("OPENCODE_DOWNSCALE", DOWNSCALE_ENABLED)


def cache_namespace() -> str:
    """缓存指纹：prompt+预算+降采样变化时旧缓存失效（img+model+prompt 指纹）。"""
    raw = "|".join([
        DIRECT_USER_TEMPLATE,
        str(first_max_tokens()),
        str(MAX_TOKENS_ESCALATE),
        f"dim{DEFAULT_MAX_IMAGE_DIM}q{DEFAULT_IMAGE_QUALITY}",
        "down" if downscale_enabled() else "orig",
    ])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


# ================= R3：图片降采样 =================

def prepare_image(image_path, *, max_dim=DEFAULT_MAX_IMAGE_DIM,
                  quality=DEFAULT_IMAGE_QUALITY, enabled=True):
    """最长边超 max_dim 时降采样为 JPEG(q)。返回 (路径, prep 元数据)；超限不满足或 PIL 缺失则原样返回。"""
    prep: dict = {}
    if not enabled:
        try:
            prep["original"] = {"bytes": os.path.getsize(image_path)}
        except OSError:
            pass
        prep["skipped"] = "downscale disabled"
        return image_path, prep
    try:
        from PIL import Image as PILImage
    except Exception as exc:
        prep["skipped"] = f"PIL unavailable: {exc}"
        return image_path, prep
    try:
        im = PILImage.open(image_path)
        im.load()
    except Exception as exc:
        prep["skipped"] = f"open failed: {exc}"
        return image_path, prep
    w, h = im.size
    prep["original"] = {"width": w, "height": h, "bytes": os.path.getsize(image_path)}
    if max(w, h) <= max_dim:
        prep["resized"] = dict(prep["original"], resized=False)
        return image_path, prep
    scale = max_dim / float(max(w, h))
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = im.convert("RGB").resize((nw, nh), PILImage.LANCZOS)
    fd, tmp = tempfile.mkstemp(suffix=".jpg", prefix="g2n-prep-")
    os.close(fd)
    try:
        resized.save(tmp, "JPEG", quality=quality, optimize=True)
    except Exception as exc:  # pragma: no cover - 保存失败回退原图
        try:
            os.remove(tmp)
        except OSError:
            pass
        prep["resized"] = {"skipped": f"save failed: {exc}"}
        return image_path, prep
    prep["resized"] = {
        "width": nw, "height": nh, "bytes": os.path.getsize(tmp), "resized": True,
        "max_dim": max_dim, "quality": quality,
    }
    return tmp, prep


# ================= R1：reasoning 告警 =================

def warnings_for(reasoning_tokens, max_tokens) -> list[str]:
    if reasoning_tokens is None:
        return []
    out: list[str] = []
    if reasoning_tokens > RUNWAY_REASONING_TOKENS:
        out.append("reasoning_high")
    if max_tokens and reasoning_tokens >= max_tokens:
        out.append("reasoning_runaway_capped")
    return out


def _meta_fail(status, error, *, model, session, max_tokens, latency, prep, cost=None):
    return {
        "status": status,
        "error": error,
        "model": model,
        "session": session,
        "max_tokens": max_tokens,
        "latency_seconds": round(latency, 2),
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": None,
        "cost": cost,
        "prep": prep,
        "warnings": [],
    }


def _raw_call(image_path, model, *, api_key, session, max_tokens, prompt_text, timeout):
    """单次底层调用。返回 (content, meta)；网络/超时/HTTP 错误以 meta.status 表示，不抛业务异常。"""
    key = api_key or load_api_key()
    down = downscale_enabled()
    prepared, prep = prepare_image(image_path, enabled=down)
    try:
        data_url = image_to_data_url(prepared)
    finally:
        if prepared != image_path:
            try:
                os.remove(prepared)
            except OSError:
                pass

    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": DEFAULT_SYSTEM},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt_text},
            ]},
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
    except urllib.error.HTTPError as exc:  # pragma: no cover - 错误路径
        latency = time.monotonic() - start
        return "", _meta_fail("error", f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}",
                              model=model, session=session, max_tokens=max_tokens, latency=latency,
                              prep=prep, cost=None)
    except urllib.error.URLError as exc:
        latency = time.monotonic() - start
        return "", _meta_fail("timeout" if "timed out" in str(exc.reason) else "error",
                              f"urlopen: {exc.reason}", model=model, session=session,
                              max_tokens=max_tokens, latency=latency, prep=prep, cost=None)
    except socket.timeout:
        latency = time.monotonic() - start
        return "", _meta_fail("timeout", "socket timeout",
                              model=model, session=session, max_tokens=max_tokens,
                              latency=latency, prep=prep, cost=None)
    except Exception as exc:  # pragma: no cover - 网络路径
        latency = time.monotonic() - start
        return "", _meta_fail("error", f"{type(exc).__name__}: {exc}",
                              model=model, session=session, max_tokens=max_tokens,
                              latency=latency, prep=prep, cost=None)
    latency = time.monotonic() - start

    try:
        choice = body["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError):
        return "", _meta_fail("error", f"响应结构异常: {body}", model=model, session=session,
                              max_tokens=max_tokens, latency=latency, prep=prep, cost=None)

    content = msg.get("content", "") or ""
    usage = body.get("usage", {}) or {}
    reasoning_tokens = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    meta = {
        "status": "ok",
        "error": None,
        "model": model,
        "session": session,
        "max_tokens": max_tokens,
        "latency_seconds": round(latency, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": reasoning_tokens,
        "finish_reason": choice.get("finish_reason"),
        "cost": body.get("cost", "0"),
        "prep": prep,
        "warnings": warnings_for(reasoning_tokens, max_tokens),
    }
    return content, meta

# ================= R2/R4：策略化调用（首调直出 + 换参/换 session + 不隐性双倍调用） =================

def transcribe_with_policy(
    image_path: str,
    model: str,
    *,
    api_key: str | None = None,
    sessions: list[str] | None = None,
    first_mt: int | None = None,
    escalate_mt: int = MAX_TOKENS_ESCALATE,
    timeout: float | None = None,
    prompt_text: str | None = None,
    max_attempts: int = 2,
) -> tuple[str, dict]:
    """按策略调用视觉模型，返回 (content, meta)。

    策略（R2/R4）：
    - 首次：主 session + 直出 prompt + 小预算（FIRST_CALL_MAX_TOKENS）。
    - 变空/截断(length)：换 session（有备选）并升预算，最多 max_attempts 次。
    - 超时/网络错误：返回失败 meta，**不**隐性重试（R4）。
    - meta 聚合：顶层为最终一次尝试的字段 + attempts 列表 + retried 标记（供 issue 11 基线）。
    """
    key = api_key or load_api_key()
    timeout = timeout if timeout is not None else call_timeout()
    first_mt = first_mt if first_mt is not None else first_max_tokens()
    prompt_text = prompt_text if prompt_text is not None else DIRECT_USER_TEMPLATE
    order = sessions or resolve_sessions(model)

    plans = [
        (order[0], first_mt, prompt_text, "first_direct"),
        ((order[1] if len(order) > 1 else order[0]), escalate_mt, prompt_text, "escalate_switch"),
    ][:max_attempts]

    attempts: list[dict] = []
    for idx, (sess, mt, pt, kind) in enumerate(plans):
        content, meta = _raw_call(image_path, model, api_key=key, session=sess,
                                  max_tokens=mt, prompt_text=pt, timeout=timeout)
        meta["attempt"] = idx
        meta["attempt_kind"] = kind
        attempts.append(meta)
        if meta["status"] != "ok":
            # 超时/网络错误：不隐性双倍调用，直接失败返回。
            return content, _merge_policy_meta(attempts)
        if (content or "").strip():
            return content, _merge_policy_meta(attempts)
        # 空内容（length 截断/空转）→ 下一档换参/换 session。
    if not attempts:
        return "", _empty_policy_meta(order, first_mt)
    # 所有尝试已执行且均空 → 状态标 empty（不误标为错误，也不背锅 reasoning 具体原因）。
    merged = _merge_policy_meta(attempts)
    merged["status"] = "empty"
    merged["error"] = "all attempts returned empty content"
    return "", merged


def _merge_policy_meta(attempts: list[dict]) -> dict:
    merged = dict(attempts[-1])
    merged["attempts"] = attempts
    merged["retried"] = len(attempts) > 1
    return merged


def _empty_policy_meta(order: list[str], first_mt: int) -> dict:
    return {
        "status": "empty",
        "error": "no attempts executed",
        "model": None,
        "session": order[0] if order else None,
        "max_tokens": first_mt,
        "latency_seconds": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "reasoning_tokens": None,
        "finish_reason": None,
        "cost": None,
        "prep": {},
        "warnings": ["reasoning_high"],
        "attempts": [],
        "retried": False,
    }


# ================= 兼容单次调用（供 CLI/实时验证；错误时抛 GatewayError） =================

def transcribe_image(
    image_path: str,
    model: str,
    *,
    api_key: str | None = None,
    session: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    prompt_text: str | None = None,
    timeout: int = 600,
) -> tuple[str, dict]:
    """单次调用（无策略重试）。与旧签名兼容；主入口建议用 transcribe_with_policy。"""
    key = api_key or load_api_key()
    sess = session or resolve_sessions(model)[0]
    pt = prompt_text if prompt_text is not None else DIRECT_USER_TEMPLATE
    content, meta = _raw_call(image_path, model, api_key=key, session=sess,
                              max_tokens=max_tokens, prompt_text=pt, timeout=timeout)
    if meta["status"] != "ok":
        raise GatewayError(meta["error"] or meta["status"])
    return content, meta
