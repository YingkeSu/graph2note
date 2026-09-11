"""LLM 网关传输层：Kimi 官方 API / DeepSeek 官方 API 可选，opencode go 网关存档。

Kimi 接入见 docs/llm/kimi.md（如缺省可参照 deepseek.md 结构补充）；
DeepSeek 备援见 docs/llm/deepseek.md；opencode 历史接入见 docs/llm/opencode-go.md。
2026-09-10 起支持 ``GRAPH2NOTE_GATEWAY=opencode|deepseek`` 切换；2026-09-11 opencode key
退役，新增 kimi 通道，base URL / 认证 key / session 头 / 模型名映射收敛在 post_gateway 单点处理。

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

# ---------- 网关选择（2026-09-11：opencode 退役，Kimi 官方 API + DeepSeek 官方 API 双通道） ----------
# GRAPH2NOTE_GATEWAY=opencode（历史主通道，key 已删除，仅存档）| deepseek | kimi。
# 所有调用方（parse/IR/diagram/eval/verify/gold_draft）沿用 opencode 时代模型名，
# post_gateway 负责端点、认证、session 头与模型名翻译——单一 choke point。
GATEWAYS = {
    "opencode": {
        "label": "OpenCode Go",
        "base": "https://opencode.ai/zen/go/v1",
        "key_env": "OPENCODE_API_KEY",
        "session_header": "x-opencode-session",
        "models": {
            "parse_visual": ["glm-5.3-flash", "deepseek-v4-flash-vision-exp"],
            "ir_text": ["deepseek-v4-flash", "kimi-k3", "glm-5.3"],
            "diagram": ["glm-5.3-flash", "deepseek-v4-flash-vision-exp"],
            "classify": ["kimi-k3", "deepseek-v4-flash", "glm-5.3"],
        },
        "defaults": {
            "parse_visual": "glm-5.3-flash",
            "ir_text": "deepseek-v4-flash",
            "diagram": "glm-5.3-flash",
            "classify": "kimi-k3",
        },
    },
    "deepseek": {
        "label": "DeepSeek API",
        "base": "https://api.deepseek.com",
        "key_env": "DEEPSEEK_API_KEY",
        "session_header": None,  # 无会话语义；重试策略中的「换 session」退化为仅换参
        "models": {
            "parse_visual": ["deepseek-v4-flash-vision-exp", "glm-5.3-flash"],
            "ir_text": ["deepseek-v4-flash", "deepseek-flash", "deepseek-v4-pro"],
            "diagram": ["deepseek-v4-flash-vision-exp", "glm-5.3-flash"],
            "classify": ["deepseek-v4-flash", "deepseek-flash", "deepseek-v4-pro"],
        },
        "defaults": {
            "parse_visual": "glm-5.3-flash",
            "ir_text": "deepseek-v4-flash",
            "diagram": "glm-5.3-flash",
            "classify": "deepseek-v4-flash",
        },
    },
    # 2026-09-11 实测 /models（新 key）：kimi-k2.6 / kimi-k2.7-code / kimi-k2.7-code-highspeed /
    # kimi-k3，全部 supports_image_in=true；kimi-k3 另有 1M 上下文且 thinking-only（默认 effort=max，
    # 实测直出正常但 reasoning 开销高于 k2.6，故视觉直出热路径默认 k2.6）。
    # k2.7-code 系列为代码特化，与手稿数字化用途不符，不入列。
    "kimi": {
        "label": "Kimi API",
        "base": "https://api.moonshot.cn/v1",
        "key_env": "KIMI_API_KEY",
        "session_header": None,  # 无会话语义；重试策略中的「换 session」退化为仅换参
        "models": {
            "parse_visual": ["kimi-k2.6", "kimi-k3"],
            "ir_text": ["kimi-k3", "kimi-k2.6"],
            "diagram": ["kimi-k2.6", "kimi-k3"],
            "classify": ["kimi-k3", "kimi-k2.6"],
        },
        "defaults": {
            "parse_visual": "kimi-k2.6",
            "ir_text": "kimi-k3",
            "diagram": "kimi-k2.6",
            "classify": "kimi-k3",
        },
    },
}
# deepseek 网关模型名翻译（实测 2026-09-11 复核：/models 仍仅 deepseek-flash 与 deepseek-v4-pro；
# deepseek-v4-flash-vision-exp 是官方文档化视觉别名，响应 model 字段回显为 deepseek-flash，
# 两个名字等价，映射到显式别名便于对账文档）。
DEEPSEEK_MODEL_MAP = {
    "glm-5.3-flash": "deepseek-v4-flash-vision-exp",  # parse 默认视觉模型
    "deepseek-v4-flash": "deepseek-flash",            # IR/文本侧廉价模型
}


def _dotenv_get(key: str) -> str:
    """从 cwd/.env 或仓库根 .env 读取一个键值（与 load_api_key 同一候选序）。

    让 GRAPH2NOTE_GATEWAY 与 API key 一样「改 .env 即生效」，进程无需 export。
    """
    for candidate in (".env", os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")):
        if os.path.exists(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if line.startswith(key + "="):
                            return line.split("=", 1)[1].strip().strip("\"'")
            except OSError:
                continue
    return ""


def active_gateway_name() -> str:
    raw = os.environ.get("GRAPH2NOTE_GATEWAY", "").strip() or _dotenv_get("GRAPH2NOTE_GATEWAY")
    name = raw.strip().lower() or "opencode"
    if name not in GATEWAYS:
        raise GatewayError(
            f"未知 GRAPH2NOTE_GATEWAY={name!r}（可选：{' / '.join(GATEWAYS)}）"
        )
    return name


def gateway_config(provider: str | None = None) -> dict:
    """Return a registered gateway, optionally overriding the env default."""

    name = (provider or active_gateway_name()).strip().lower() if isinstance(provider, str) else active_gateway_name()
    if name not in GATEWAYS:
        raise GatewayError(
            f"未知 provider={name!r}（可选：{' / '.join(GATEWAYS)}）"
        )
    return GATEWAYS[name]


def chat_completions_url(provider: str | None = None) -> str:
    return gateway_config(provider)["base"] + "/chat/completions"


def map_model(model: str, provider: str | None = None) -> str:
    """deepseek 网关下把 opencode 时代模型名翻译为官方 API 名；其余网关原样返回。"""
    name = (provider or active_gateway_name()).strip().lower() if isinstance(provider, str) else active_gateway_name()
    if name != "deepseek":
        return model
    return DEEPSEEK_MODEL_MAP.get(model, model)


# 旧常量保留（opencode 默认端点；历史引用与 gold_draft 兼容），运行时端点以 chat_completions_url() 为准。
GATEWAY_BASE = "https://opencode.ai/zen/go/v1"
CHAT_COMPLETIONS = GATEWAY_BASE + "/chat/completions"

# ---------- 配置（运行时可被环境变量覆盖） ----------
# 按用途隔离的稳定「已验证直出模式」x-opencode-session（R1 扩展，见 docs/llm/opencode-go.md §会话隔离）。
# parse / eval / verify 各自持有独立 session id，避免评估批次、产品解析、交叉验证并发争用同一会话
# —— 同用 graph2note-spike-01 时，一方批量会令共享会话退化、返回极短「全黑页」/空 IR（issue 12 风控）。
# 覆盖优先级：GRAPH2NOTE_SESSION_<PURPOSE> > GRAPH2NOTE_OPENCODE_SESSION / OPENCODE_SESSION > 用途默认。
PURPOSES = ("parse", "eval", "verify", "routeb", "diagram")
DEFAULT_PURPOSE_SESSIONS = {
    "parse":  "graph2note-parse-01",
    "eval":   "graph2note-eval-01",
    "verify": "graph2note-verify-01",
    "routeb": "graph2note-routeb-01",   # issue 08：Route B（OCR->文本 LLM 结构化），独立会话避免与 parse/eval 争用
    "diagram": "graph2note-diagram-01", # issue 15：图像->nodes/edges 提取（spike3 产品化），独立会话避免争用
}
# 历史统一覆盖（兼容旧 env）：GRAPH2NOTE_OPENCODE_SESSION（产品级）、OPENCODE_SESSION（通用）。
GRAPH2NOTE_OPENCODE_SESSION = "GRAPH2NOTE_OPENCODE_SESSION"
OPENCODE_SESSION = "OPENCODE_SESSION"
# 历史默认：spike-01 曾是 parse/eval 共享的已验证直出会话（issue 12 已证其被并发争用）；
# 仅作未知用途兜底/文档说明，勿再分配给具体用途。graph2note-parse-route-a 可用
# GRAPH2NOTE_SESSION_PARSE=graph2note-parse-route-a 经 env 还原（历史产品默认）。
DEFAULT_SESSION = "graph2note-spike-01"
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


class GatewayTimeout(GatewayError):
    """网关调用超时（客户端硬超时，R4）。"""


# ================= 可复用传输层（eval/gateway 与 graph2note/vlm 共用，消除双维护） =================

def reasoning_tokens_of(usage: dict) -> int | None:
    """从 usage 里提取 reasoning_tokens（opencode 放在 completion_tokens_details 下）。"""
    if not usage:
        return None
    return (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")


def post_gateway(
    payload: dict,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    session: str,
    timeout: float,
    user_agent: str = USER_AGENT,
) -> dict:
    """POST 一个 chat/completions payload，返回解析后的 body。

    网络/HTTP 错误抛 :class:`GatewayError`；超时抛 :class:`GatewayTimeout`。
    这是 eval/gateway 与 graph2note/vlm 收敛后的单一上传/认证/会话实现，
    也是网关选择的唯一 choke point（端点/认证 key/session 头/模型名映射）。
    """
    key = api_key or load_api_key(provider)
    cfg = gateway_config(provider)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": user_agent,
    }
    if cfg["session_header"]:
        headers[cfg["session_header"]] = session
    body = dict(payload)
    if body.get("model"):
        body["model"] = map_model(body["model"], provider)
    req = urllib.request.Request(
        chat_completions_url(provider),
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GatewayError(f"gateway HTTP {exc.code}: {detail[:300]}") from exc
    except socket.timeout as exc:
        raise GatewayTimeout(f"gateway timeout after {timeout}s") from exc
    except urllib.error.URLError as exc:
        if "timed out" in str(exc.reason).lower():
            raise GatewayTimeout(f"gateway timeout: {exc.reason}") from exc
        raise GatewayError(f"gateway connection error: {exc.reason}") from exc
    except (ConnectionError, OSError) as exc:
        raise GatewayError(f"gateway connection error: {exc}") from exc


def load_api_key(provider: str | None = None) -> str:
    key_env = gateway_config(provider)["key_env"]
    key = os.environ.get(key_env, "").strip() or _dotenv_get(key_env)
    if key:
        return key
    raise GatewayError(f"未找到 {key_env}（环境变量或仓库根 .env）")


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


def purpose_session_env(purpose: str) -> str:
    """用途专属会话环境变量名：GRAPH2NOTE_SESSION_<PARSE|EVAL|VERIFY>。"""
    return f"GRAPH2NOTE_SESSION_{purpose.upper()}"


def resolve_session_for(purpose: str, model: str | None = None) -> str:
    """按用途解析稳定直出 session。

    优先级：GRAPH2NOTE_SESSION_<PURPOSE> > GRAPH2NOTE_OPENCODE_SESSION / OPENCODE_SESSION
    > DEFAULT_PURPOSE_SESSIONS[purpose]。model 保留给未来每模型覆盖用；未知用途抛 ValueError。
    """
    purpose = purpose.lower()
    if purpose not in DEFAULT_PURPOSE_SESSIONS:
        raise ValueError(f"unknown purpose {purpose!r}; expected one of {PURPOSES}")
    for env in (purpose_session_env(purpose), GRAPH2NOTE_OPENCODE_SESSION, OPENCODE_SESSION):
        v = os.environ.get(env, "").strip()
        if v:
            return v
    return DEFAULT_PURPOSE_SESSIONS[purpose]


def resolve_sessions(model: str) -> list[str]:
    """有序 session 列表（主 session 在前，去重）；主 session 走 eval 用途隔离解析。
    OPENCODE_SESSIONS 注入备选（兼容旧行为）。"""
    primary = resolve_session_for("eval", model)
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

    start = time.monotonic()
    try:
        body = post_gateway(payload, api_key=key, session=session, timeout=timeout, user_agent=USER_AGENT)
    except GatewayTimeout as exc:
        latency = time.monotonic() - start
        return "", _meta_fail("timeout", str(exc), model=model, session=session,
                              max_tokens=max_tokens, latency=latency, prep=prep, cost=None)
    except GatewayError as exc:
        latency = time.monotonic() - start
        return "", _meta_fail("error", str(exc), model=model, session=session,
                              max_tokens=max_tokens, latency=latency, prep=prep, cost=None)
    latency = time.monotonic() - start

    try:
        choice = body["choices"][0]
        msg = choice["message"]
    except (KeyError, IndexError, TypeError):
        return "", _meta_fail("error", f"响应结构异常: {body}", model=model, session=session,
                              max_tokens=max_tokens, latency=latency, prep=prep, cost=None)

    content = msg.get("content", "") or ""
    usage = body.get("usage", {}) or {}
    reasoning_tokens = reasoning_tokens_of(usage)
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


# ================= 会话直出验证（启动/首次调用；reasoning_tokens 检查） =================
# 用途隔离后，每用途 session 都应被验证是「直出模式」（reasoning 占用低、content 非空），
# 避免再次落入 issue 12 的空 IR（推理路由烧 token）场景。探针调用极轻量（2x2 PNG + 64 token）。
DIRECT_SESSION_PROBE_PROMPT = "直接输出一个字或空白即可，不要思考。"
PROBE_MAX_TOKENS = 64
PROBE_TIMEOUT_SECONDS = 30.0
PROBE_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAADklEQVR4nGNoAAMGCAUAKg4GARWeQtcAAAAASUVORK5CYII="
)
_PROBE_MODEL = "glm-5.3-flash"
_direct_validation_cache: dict = {}


def probe_image_path() -> str:
    """生成/复用 2x2 灰 PNG 探针图片（PIL-free，base64 内嵌），用于渠道通/直出验证。"""
    path = os.path.join(tempfile.gettempdir(), "graph2note_session_probe.png")
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(base64.b64decode(PROBE_IMAGE_B64))
    return path


def reset_direct_validation_cache() -> None:
    """清空进程级直出验证缓存（测试/重验用）。"""
    _direct_validation_cache.clear()


def validate_session_direct(
    purpose: str,
    model: str | None = None,
    *,
    api_key: str | None = None,
    timeout: float = PROBE_TIMEOUT_SECONDS,
    max_tokens: int = PROBE_MAX_TOKENS,
    threshold: int = RUNWAY_REASONING_TOKENS,
    session: str | None = None,
) -> dict:
    """启动/首次调用时验证某用途 session 为「直出模式」。

    发一次极小的探针调用，检查 content 非空且 reasoning_tokens <= threshold。结果按
    (purpose, session, model) 缓存到进程级 ``_direct_validation_cache``，避免每次调用重复探测。

    返回 record：{purpose, session, model, direct, reasoning_tokens, content_len, status, latency_seconds}。
    ``direct`` 为 True 表示该 session 直出可用；网络/超时/响应异常时按 not-direct 计。
    """
    sess = session or resolve_session_for(purpose, model)
    model = model or _PROBE_MODEL
    key = (purpose, sess, model)
    if key in _direct_validation_cache:
        return _direct_validation_cache[key]
    content, meta = _raw_call(
        probe_image_path(), model, api_key=api_key, session=sess,
        max_tokens=max_tokens, prompt_text=DIRECT_SESSION_PROBE_PROMPT, timeout=timeout,
    )
    rt = meta.get("reasoning_tokens")
    status_ok = meta.get("status") == "ok"
    # 直出判据针对 issue-12 的「推理吃满预算致空」签名：reasoning 填满整个 max_tokens 且无内容。
    # 探针 max_tokens 很小（64），低推理（<<阈值）但内容字节为 0 不算失败——那是预算太紧没留出内容位，
    # 真实调用（3500+）会正常产出。只有「无内容 且 reasoning >= max_tokens」才是 reasoning 独占预算的退化。
    runaway = (not content) and rt is not None and max_tokens > 0 and rt >= max_tokens
    direct = status_ok and not runaway and (rt is None or rt <= threshold)
    record = {
        "purpose": purpose, "session": sess, "model": model,
        "direct": direct, "reasoning_tokens": rt,
        "content_len": len(content or ""), "status": meta.get("status"),
        "latency_seconds": meta.get("latency_seconds"),
    }
    _direct_validation_cache[key] = record
    return record


def session_validation_enabled() -> bool:
    """是否开启启动/首次解析时的直出验证（env GRAPH2NOTE_VALIDATE_SESSIONS；默认关）。"""
    return _env_bool("GRAPH2NOTE_VALIDATE_SESSIONS", False)


def maybe_validate_direct(purpose: str, model: str | None = None) -> dict | None:
    """首解析时按 env 开关做一次直出验证（进程级缓存，仅首调触网）；未开启时返回 None。

    会话直出验证是 opencode 专属风控（服务端按 session 路由/缓存）；无会话语义的
    网关（如 deepseek）直接跳过，不浪费探针调用。
    """
    if not session_validation_enabled():
        return None
    if gateway_config()["session_header"] is None:
        return None
    return validate_session_direct(purpose, model)


def session_health(records: list[dict]) -> tuple[bool, list[str]]:
    """聚合直出验证记录：返回 (all_direct, degraded_purposes)。供健康巡检/跑批前自检。"""
    bad = [r for r in records if not r.get("direct")]
    return (len(bad) == 0), [r["purpose"] for r in bad]


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


# ================= Route B：文本 LLM（非视觉）调用 =================

# Route B 结构化 prompt（OCR 文本 -> Markdown 中间表示）。复用 issue 12 的两阶段经验：
# 文本 LLM 先把 OCR 噪声整理成 Markdown，再由确定性 markdown-parser 转 IR。文本端
# 选稳定直出的 glm-5.3-flash（issue 12 已证 deepseek-v4-flash 推理吃满预算返空，故不用）。
ROUTE_B_SYSTEM = (
    "你是文档数字化引擎。下面文本来自 OCR（可能含噪声、错字、乱序）。\n"
    "请把它整理成结构清晰的 Markdown 正文：恢复标题层级（# ATX）、段落、列表（- / 1.）、\n"
    "行内与独立公式用 LaTeX（$…$ / $$…$$）。\n"
    "重要：绝对不要拒绝、不要只输出一句「说明无法整理」、不要输出任何解释/前言/代码块。\n"
    "即使 OCR 有噪声，也把你能辨识的内容逐字照实转写出来、保留可辨识的结构；只有完全\n"
    "无法辨认的碎片才跳过，严禁凭空编造或凭空发挥。只输出最终 Markdown 正文。"
)
ROUTE_B_USER_TEMPLATE = "把下面 OCR 文本整理为结构化 Markdown 正文（噪声也照常转写，不要拒绝），直接输出结果："
ROUTE_B_TEXT_MODEL = "glm-5.3-flash"  # 稳定直出文本模型（chat/completions，非视觉）


def transcribe_text(
    text: str,
    model: str = ROUTE_B_TEXT_MODEL,
    *,
    provider: str | None = None,
    api_key: str | None = None,
    session: str | None = None,
    purpose: str = "routeb",
    main_text: str | None = None,
    max_tokens: int = 10000,
    timeout: float | None = None,
) -> tuple[str, dict]:
    """文本-only chat/completions（无图片）—— Route B 的 OCR 文本结构化调用。

    覆盖 ``purpose`` 默认 routeb（独立 session，见 GRAPH2NOTE_SESSION_ROUTEB）。
    ``main_text`` 覆盖传给用户的消息正文（默认 ROUTE_B_USER_TEMPLATE）。
    返回 (content, meta)；网络/超时/响应异常以 meta.status 标记，不抛业务异常。
    """
    key = api_key or load_api_key(provider)
    sess = session or resolve_session_for(purpose, model)
    timeout = timeout if timeout is not None else call_timeout()
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": ROUTE_B_SYSTEM},
            {"role": "user", "content": (main_text or ROUTE_B_USER_TEMPLATE) + "\n\n" + text},
        ],
    }
    start = time.monotonic()
    try:
        body = post_gateway(
            payload,
            provider=provider,
            api_key=key,
            session=sess,
            timeout=timeout,
            user_agent=USER_AGENT,
        )
    except GatewayTimeout as exc:
        meta = _meta_fail("timeout", str(exc), model=model, session=sess,
                          max_tokens=max_tokens, latency=time.monotonic() - start, prep={})
        if provider is not None:
            meta["provider"] = provider
        return "", meta
    except GatewayError as exc:
        meta = _meta_fail("error", str(exc), model=model, session=sess,
                          max_tokens=max_tokens, latency=time.monotonic() - start, prep={})
        if provider is not None:
            meta["provider"] = provider
        return "", meta
    latency = time.monotonic() - start
    try:
        choice = body["choices"][0]
        content = choice["message"].get("content", "") or ""
    except (KeyError, IndexError, TypeError):
        meta = _meta_fail("error", f"响应结构异常: {body}", model=model, session=sess,
                          max_tokens=max_tokens, latency=latency, prep={})
        if provider is not None:
            meta["provider"] = provider
        return "", meta
    usage = body.get("usage", {}) or {}
    rt = reasoning_tokens_of(usage)
    meta = {
        "status": "ok",
        "error": None,
        "model": model,
        "session": sess,
        "max_tokens": max_tokens,
        "latency_seconds": round(latency, 2),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": rt,
        "finish_reason": choice.get("finish_reason"),
        "cost": body.get("cost", "0"),
        "prep": {},
        "warnings": warnings_for(rt, max_tokens),
        "provider": provider,
    }
    return content, meta
