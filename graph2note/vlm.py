"""VLM gateway producing a Document IR JSON string via the configured LLM gateway.

Contract (docs/llm/opencode-go.md; DeepSeek fallback: docs/llm/deepseek.md):
  * endpoint https://opencode.ai/zen/go/v1/chat/completions (OpenAI-compatible)
  * Authorization: Bearer $OPENCODE_API_KEY  (env var, or repo-root .env — never
    committed)
  * must carry ``x-opencode-session`` (kept stable for retries / prompt cache)
  * ``max_tokens`` 10000 (reasoning consumes the budget; 200 truncates to empty)
  * image sent as a base64 ``data:`` URL; final text is ``message.content``

Gateway selection (2026-09-10): ``GRAPH2NOTE_GATEWAY=opencode|deepseek`` —
eval.gateway.post_gateway is the single choke point for endpoint/auth/session
header/model-name mapping (glm-5.3-flash → deepseek-v4-flash-vision-exp,
deepseek-v4-flash → deepseek-flash), so callers keep opencode-era model ids.

The parse prompt demands strict Document IR JSON (schema in ``graph2note/ir.py``)
plus semantic deletion.  The gateway never fails open: HTTP/status/JSON errors
and unknown models surface as ``GatewayError``.  All network is isolated here so
calling code (router/pipeline/CLI) and tests stay offline.
"""

from __future__ import annotations

import base64
import json
import hashlib
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

# O1（issue 11）：收敛到 eval/gateway 的单一网关策略实现（上传/认证/会话/超时/reasoning 提取），
# 消除 eval/harness 与产品管线两套网关的双维护。
from eval.gateway import (  # type: ignore
    GatewayError as _GatewayError,
    GatewayTimeout as _GatewayTimeout,
    maybe_validate_direct as _maybe_validate_direct,
    post_gateway,
    reasoning_tokens_of,
    resolve_session_for as _resolve_session_for,
    warnings_for as _warnings_for,
)

# 端点/认证/session 头由 eval.gateway 按 GRAPH2NOTE_GATEWAY 选择（单一 choke point，
# 见模块 docstring）；本模块不再持有端点常量。
# session 按用途隔离：parse 用独立已验证直出 session，避免与 eval/verify 并发争用同一会话
# （issue 12 风控；见 docs/llm/opencode-go.md §会话隔离）。可由 GRAPH2NOTE_SESSION_PARSE 覆盖；
# 历史 GRAPH2NOTE_OPENCODE_SESSION / OPENCODE_SESSION（含 spike-01、parse-route-a）经 env 还原。
STABLE_SESSION = "graph2note-parse-01"
VALIDATED_SESSION = STABLE_SESSION
USER_AGENT = "graph2note-parse/0.1"


def resolve_session(model: str) -> str:
    """返回本产品管线（parse 用途）的会话 id：GRAPH2NOTE_SESSION_PARSE >
    GRAPH2NOTE_OPENCODE_SESSION / OPENCODE_SESSION > 默认 graph2note-parse-01。
    GRAPH2NOTE_VALIDATE_SESSIONS=1 时对首个解析的 session 做一次直出验证（进程级缓存）。"""
    sess = _resolve_session_for("parse", model)
    _maybe_validate_direct("parse", model)
    return sess


# Latency strategy (aligned to the 2026-09-08 diagnosis, main e0bd5dc):
#  * R2: first call is *direct-output* (strong "no reasoning" instruction) with
#    a medium max_tokens (not 10000, which let the model ramble in reasoning).
#  * R3: the image is downsampled to ~1024 longest edge, q85 JPEG, before being
#    sent, so the model gets a small, fast image.
#  * R4: a hard request timeout; on timeout the caller switches strategy for the
#    retry instead of repeating the same slow parameters.
DEFAULT_MAX_TOKENS = int(os.environ.get("GRAPH2NOTE_MAX_TOKENS", "3500"))
DEFAULT_SEND_MAX_SIDE = 1024
DEFAULT_JPEG_QUALITY = 85
DEFAULT_TIMEOUT = 120

# ================= 解析链路（文字转录 → 图结构 → IR） =========================
# 根因（issue 11 基线 §7）：产品 IR-JSON 直出 prompt 在密集扫描板书上常返回**合法但 blocks
# 为空**的 IR（completion 很短），导致渲染空 Markdown，EditRate 恒 1.0。eval harness 已证明
# 「VLM Markdown 直出」策略对同批页面稳定非空。当前链路分为三步：
#   stage1 = 已校验的 VLM Markdown 直出（非空、完整转录）；
#   stage2 = 轻量**文本** LLM/确定性 parser 把 Markdown 收敛为 Document IR JSON；
#   stage3 = 专用图 VLM 从原图抽取 nodes/edges，成功时替换碎片化的文字侧 flow。
# 文本模型仅用 chat/completions 清单（docs/llm/opencode-go.md §4）；muse 系列（responses 端点、
# 用输入训练）一律禁用。prompt 策略集中在 vlm 层，Router 缝（caller 返回 IR JSON 字符串）不变。
IR_MODEL = os.environ.get("GRAPH2NOTE_IR_MODEL", "deepseek-v4-flash")  # 廉价文本模型，muse 禁用
DEFAULT_IR_MAX_TOKENS = int(os.environ.get("GRAPH2NOTE_IR_MAX_TOKENS", "6000"))
# stage-1 推理耗尽时的升级预算（对齐 worker4 verify/run_model 的 10000）
MARKDOWN_STAGE_RETRY_TOKENS = int(os.environ.get("GRAPH2NOTE_MARKDOWN_RETRY_TOKENS", "10000"))
# Optional specialist model.  If unset, the same vision model is called with a
# different strict topology prompt; deployments can point this at a cheaper or
# more capable graph/VLM without changing the document route.
DIAGRAM_MODEL = os.environ.get("GRAPH2NOTE_DIAGRAM_MODEL", "")

# stage-1：VLM 视觉转录 -> Markdown（对齐 eval harness 已验证的 DIRECT_USER_TEMPLATE + 非空约束）
MARKDOWN_SYSTEM_PROMPT = (
    "你是手稿数字化引擎。把这一页手稿/文档的图片转录为 Markdown，只输出 Markdown 正文，"
    "不输出任何思考、分析、解释或前后缀文字。语义化删除：被删除线/涂抹明确废弃的内容不要输出，"
    "判断模糊时保守保留。"
)
MARKDOWN_USER_PROMPT = (
    "把这一页手稿转成 Markdown。直接输出最终 Markdown 正文，完整转录这一页上的全部可读文字与结构，"
    "不要思考、不要铺垫、不要省略、严禁返回空内容。\n"
    "- 完整保留正文、标题层级（用 # ATX 标题）、列表（用 - 无序 / 1. 有序）、段落阅读顺序。\n"
    "- 数学公式用 LaTeX（行内 $…$、独立 $$…$$）。\n"
    "- 流程图/架构图：提取节点与箭头关系，用 Markdown 列表或简短文字描述连线方向"
    "（如 '节点A → 节点B'）；无法可靠提取时直接抄写图中文字，严禁编造。\n"
    "- 中文标点与全角字符原样保留。\n"
    "只输出最终 Markdown："
)


class GatewayError(RuntimeError):
    """Gateway call failed (network, auth, HTTP, bad response shape)."""


def load_api_key() -> str:
    """Gateway-aware API key (OPENCODE_API_KEY or DEEPSEEK_API_KEY by
    GRAPH2NOTE_GATEWAY), delegated to the shared loader in eval.gateway.
    Re-raised as this module's GatewayError to keep the Router seam stable."""
    from eval.gateway import GatewayError as _GatewayError
    from eval.gateway import load_api_key as _gateway_load_api_key
    try:
        return _gateway_load_api_key()
    except _GatewayError as exc:
        raise GatewayError(str(exc)) from exc


def image_to_data_url(image_path: str) -> str:
    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def downscale_to_max_side(image_path: str, max_side: int = DEFAULT_SEND_MAX_SIDE,
                          quality: int = DEFAULT_JPEG_QUALITY) -> bytes:
    """R3: return a downscaled JPEG (<= max_side longest edge) of the image.

    Vision quality drops fast past ~1024px while token/timing costs grow
    quickly, so we cap the longest edge and re-encode to q85 JPEG before the
    base64 is put in the request body.  Falls back to the raw file bytes when
    Pillow is unavailable.
    """
    try:
        from PIL import Image, ImageOps  # type: ignore
    except Exception:
        with open(image_path, "rb") as fh:
            return fh.read()

    im = Image.open(image_path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    longest = max(w, h)
    if longest > max_side:
        scale = max_side / float(longest)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))),
                       Image.LANCZOS)
    import io

    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def image_data_url_downscaled(image_path: str,
                              max_side: int = DEFAULT_SEND_MAX_SIDE,
                              quality: int = DEFAULT_JPEG_QUALITY) -> tuple[str, list[int]]:
    """Data URL of the downscaled image plus its (w, h) for meta/timing."""
    data = downscale_to_max_side(image_path, max_side, quality)
    b64 = base64.b64encode(data).decode("ascii")
    try:
        from PIL import Image
        with Image.open(image_path) as im:
            size = list(im.size)
    except Exception:
        size = [0, 0]
    return f"data:image/jpeg;base64,{b64}", size


SYSTEM_PROMPT = (
    "你是手稿文档结构化引擎。把下面给出的 Markdown 正文转换为结构化的 Document IR JSON，"
    "只输出该 JSON 对象本身，不要 Markdown 围栏、不要任何多余解释或前后缀文字，不要空 JSON。\n"
    '结构为 {"document_type":"note","blocks":[...]}。\n'
    "block 类型全集（type 取值）：\n"
    '- heading: {"type":"heading","level":1..6,"text":...}\n'
    '- paragraph: {"type":"paragraph","text":...}\n'
    '- list: {"type":"list","ordered":true|false,"items":[{"text":...,"items":[…]?}]}\n'
    '- formula: {"type":"formula","latex":"<LaTeX>","inline":false|true}\n'
    '- table: {"type":"table","headers":[...],"rows":[[...]],"caption":""?}\n'
    '- code: {"type":"code","language":""?,"content":...}\n'
    '- quote: {"type":"quote","text":...}\n'
    '- image: {"type":"image","src":...,"alt":""?}\n'
    '- diagram / flow: {"type":"diagram","caption":""?,"nodes":[{"id","label"}],'
    '"edges":[{"from","to","label"?}],"source":null}\n'
    "要求：\n"
    "1. 完整保留 Markdown 的全部标题层级、段落、列表（- 无序 / 1. 有序）、阅读顺序；公式用上述结构。\n"
    "2. Markdown 中的流程/依赖（如 'A → B' 或 'flow:' 行）转换为 diagram/flow block，"
    "能可靠提取时给出 nodes/edges，不能时保留文字于 caption。\n"
    "3. 语义化删除：被删除线或涂抹明确废弃的内容不要输出；判断模糊时保守保留。\n"
    "4. 中文标点与全角字符原样保留。\n"
    "只输出 JSON："
)

USER_PROMPT = "把下面的 Markdown 正文转换为上述格式的 Document IR JSON，只输出 JSON："


def parse_ir_json(content: str) -> dict | None:
    """Extract a JSON object from a model reply.

    Tolerates an optional ```json ... ``` fence or surrounding prose by
    locating the outermost balanced ``{...}``.  Returns None if none found or
    not valid JSON.  Does NOT validate against the IR schema (router does).
    """
    if not content:
        return None
    text = content.strip()
    # Strip a surrounding ```json ... ``` code fence if present.
    m = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, flags=re.S)
    if m:
        text = m.group(1).strip()

    # find the first '{' and its matching close at depth zero
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _cache_key(image_path: str, model: str, prompt_version: str) -> str:
    with open(image_path, "rb") as fh:
        digest = hashlib.sha1(fh.read()).hexdigest()[:16]
    return f"{model.replace('/', '_')}__{digest}__{prompt_version}"


class VlmCache:
    """On-disk cache of raw VLM replies, keyed by image bytes+model+prompt.

    Lets the CLI and tests reuse recorded real replies without re-hitting the
    network (offline + deterministic).  Cache files are gitignored or stored
    under a caller-supplied dir (tests use tmp dirs / committed golden files
    separately).
    """

    def __init__(self, cache_dir: str, prompt_version: str = "v1") -> None:
        self.cache_dir = Path(cache_dir)
        self.prompt_version = prompt_version

    def _path(self, image_path: str, model: str) -> Path:
        return self.cache_dir / (_cache_key(image_path, model, self.prompt_version) + ".json")

    def get(self, image_path: str, model: str) -> str | None:
        p = self._path(image_path, model)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return None

    def put(self, image_path: str, model: str, content: str, meta: dict | None = None) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        rec = {"content": content, "meta": meta or {}}
        self._path(image_path, model).write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8"
        )


def _looks_like_nonempty_ir(content: str) -> bool:
    """Cheap check: content parses into an IR object with at least one block."""
    obj = parse_ir_json(content)
    if not obj:
        return False
    blocks = obj.get("blocks") or []
    return len(blocks) > 0


def _transcribe_markdown(
    image_path: str,
    model: str,
    *,
    key: str,
    sess: str,
    max_tokens: int,
    timeout: int,
    recover: bool = False,
) -> tuple[str, dict]:
    """stage-1：VLM 视觉转录——图片 -> 非空 Markdown（eval 已验证策略）。

    采纳 worker4(issue10) 线索：推理路由下 3500 的 token 预算常被 reasoning 吃满
    （finish_reason=length）进而 content 为空。因此首次空渲染/长度截断时**内部重试一次**，
    把预算提升到 MARKDOWN_STAGE_RETRY_TOKENS（默认 10000，对齐 verify 的 run_model），
    并配合非空/直出约束 + 硬超时（timeout）兜底，避免回到 300s runaway 时代。
    只在真正耗尽时升级预算，正常页仍是单次调用。
    """
    data_url, send_size = image_data_url_downscaled(image_path)
    attempts: list[dict] = []
    last_content = ""
    for attempt in range(2):
        system = MARKDOWN_SYSTEM_PROMPT
        mt = max_tokens
        if attempt > 0 or recover:
            system = system + (
                "\n重要：这是重试。请直接完整输出这一页的 Markdown 正文，"
                "绝对不要任何思考/解释/前后缀文字，严禁输出空内容。"
            )
            mt = max(mt, MARKDOWN_STAGE_RETRY_TOKENS)
        payload = {
            "model": model,
            "max_tokens": mt,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": MARKDOWN_USER_PROMPT},
                    ],
                },
            ],
        }
        start = time.monotonic()
        try:
            body = post_gateway(payload, api_key=key, session=sess, timeout=timeout, user_agent=USER_AGENT)
        except _GatewayTimeout as exc:
            raise GatewayError(f"gateway timeout after {timeout}s: {exc}") from exc
        except _GatewayError as exc:
            raise GatewayError(str(exc)) from exc
        latency = time.monotonic() - start

        try:
            choice = body["choices"][0]
            content = choice["message"].get("content", "") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(f"gateway response shape unexpected: {body}") from exc

        usage = body.get("usage", {}) or {}
        reasoning_tokens = reasoning_tokens_of(usage)
        attempts.append({
            "attempt": attempt,
            "status": "ok",
            "max_tokens": mt,
            "latency_seconds": round(latency, 2),
            "reasoning_tokens": reasoning_tokens,
            "completion_tokens": usage.get("completion_tokens"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "finish_reason": choice.get("finish_reason"),
            "cached": False,
        })
        last_content = content
        # 内容可用即返回；空渲染或长度截断（推理耗尽）则升级预算重试一次
        exhausted = (content or "").strip() == "" or choice.get("finish_reason") == "length"
        if not exhausted:
            break
    content = last_content
    meta = {
        "stage": "markdown",
        "model": model,
        "status": "ok",
        "cost": body.get("cost", "0"),
        "image_size": send_size,
        "session": sess,
        "reasoning_tokens": attempts[-1]["reasoning_tokens"],
        "finish_reason": attempts[-1]["finish_reason"],
        "latency_seconds": round(sum(a["latency_seconds"] or 0 for a in attempts), 2),
        "retried_stage1": len(attempts) > 1,
        "retries_stage1": max(len(attempts) - 1, 0),
        "attempts": attempts,
        "warnings": _warnings_for(attempts[-1].get("reasoning_tokens"), attempts[-1].get("max_tokens", max_tokens)),
    }
    return content, meta
IR_MODE = os.environ.get("GRAPH2NOTE_IR_MODE", "parser")  # "parser" (default) | "llm"


def _markdown_to_ir(markdown: str) -> dict:
    """确定性 Markdown -> Document IR（保序、保证非空）。

    issue 12 售后回归：可用的 chat/completions **文本** 模型（deepseek-v4-flash 等）
    是强推理型（reasoning 吃满 max_tokens、返回空），无法稳定重构 IR。本解析器把
    stage-1 已验证明的、内容丰富的 Markdown 直接映射为合法 IR JSON（保序 -> 渲染
    后 EditRate 高），且对任意非空输入**永不返回空**，彻底消除「空 IR」根因。
    """
    import re as _re

    blocks: list[dict] = []
    lines = markdown.split("\n")
    n = len(lines)
    i = 0
    while i < n:
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        # 围栏代码
        if stripped.startswith("```"):
            code: list[str] = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # 跳过闭合围栏
            blocks.append({"type": "code", "language": "", "content": "\n".join(code)})
            continue
        # 标题
        m = _re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if m:
            blocks.append({"type": "heading", "level": len(m.group(1)), "text": m.group(2).strip()})
            i += 1
            continue
        # 引用
        if stripped.startswith(">"):
            blocks.append({"type": "quote", "text": stripped.lstrip(">").lstrip()})
            i += 1
            continue
        # 行内公式（markdown-parser 层不拆分行内公式，按段保留）
        if stripped.startswith("$$"):
            latex = stripped[2:].strip()
            if latex.endswith("$$"):
                latex = latex[:-2].strip()
                blocks.append({"type": "formula", "latex": latex, "inline": False})
                i += 1
                continue
            acc = [stripped[2:]]
            i += 1
            while i < n:
                l2 = lines[i]
                if "$$" in l2:
                    acc.append(l2.split("$$", 1)[0])
                    i += 1
                    break
                acc.append(l2)
                i += 1
            blocks.append({"type": "formula", "latex": "\n".join(acc).strip(), "inline": False})
            continue
        # 列表（有序 / 无序）
        mu = _re.match(r"^[-*+]\s+(.*)$", stripped)
        mo = _re.match(r"^(\d+)[.)]\s+(.*)$", stripped)
        if mu or mo:
            ordered = bool(mo)
            items: list[dict] = []
            while i < n:
                l2 = lines[i].strip()
                mm = _re.match(r"^(\d+)[.)]\s+(.*)$", l2) if ordered else _re.match(r"^[-*+]\s+(.*)$", l2)
                if not mm:
                    break
                items.append({"text": (mm.group(2) if ordered else mm.group(1)).strip()})
                i += 1
            blocks.append({"type": "list", "ordered": ordered, "items": items})
            continue
        # 其余为段落（保留原文本，行内 $…$ 公式随段回读）
        blocks.append({"type": "paragraph", "text": line})
        i += 1
    # issue 15：流程/架构关系行（段落或列表项里的 `A → B`）确定性汇聚为
    # flow/diagram block 追加到文末（保留既有文字块；仅 diagram 页触发）。
    # 结构化可解析 -> flow nodes/edges；否则 caption 只保留原文字不丢失。
    from .diagrams import infer as _infer

    if _infer.detect_diagram_markdown(markdown):
        # A page-level graph should not be split merely because the VLM put a
        # bullet, heading, or explanatory line between two visual rows.
        # Collect all arrow-bearing rows into one deterministic fallback graph;
        # the dedicated image extractor below can replace it with richer
        # topology when available.
        relation_rows = _infer.relation_lines(markdown.split("\n"))
        if relation_rows:
            fb = _infer.arrow_flow_block(relation_rows, 0)
            if fb is not None:
                blocks.append(fb)
    if not blocks:
        blocks.append({"type": "paragraph", "text": markdown.strip()})
    return {"document_type": "note", "blocks": blocks}
def _ir_from_markdown(
    markdown: str,
    ir_model: str,
    *,
    key: str,
    sess: str,
    max_tokens: int,
    timeout: int,
    recover: bool = False,
    use_llm: bool = False,
) -> tuple[str, dict]:
    """stage-2：Markdown -> Document IR JSON。

    默认（use_llm=False）走**确定性 markdown-parser**：合法、保序、非空、零网络。
    可选 `GRAPH2NOTE_IR_MODE=llm` 时先尝试轻量文本 LLM 重构，失败后同样回退到
    parser —— 保证任何情况下都返回非空 IR（不再产生空 IR / 空 .md）。
    """
    if not use_llm:
        ir = _markdown_to_ir(markdown)
        meta = {
            "stage": "ir",
            "model": "markdown-parser",
            "retried": False,
            "reasoning_tokens": None,
            "finish_reason": None,
            "mode": "markdown-parser",
            "attempts": [
                {"attempt": 0, "status": "ok", "mode": "markdown-parser", "blocks": len(ir["blocks"])}
            ],
        }
        return json.dumps(ir, ensure_ascii=False), meta

    meta = {"stage": "ir", "model": ir_model, "retried": False, "attempts": []}
    for attempt in range(2):
        system = SYSTEM_PROMPT
        if attempt > 0 or recover:
            system = system + (
                "\n重要：这是重试。请直接输出合法且非空的 JSON，"
                "绝对不要空 JSON、不要空 blocks、不要任何解释或前后缀文字。"
            )
        payload = {
            "model": ir_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": USER_PROMPT + "\n\n" + markdown},
            ],
        }
        start = time.monotonic()
        try:
            body = post_gateway(payload, api_key=key, session=sess, timeout=timeout, user_agent=USER_AGENT)
        except _GatewayTimeout as exc:
            raise GatewayError(f"gateway timeout after {timeout}s: {exc}") from exc
        except _GatewayError as exc:
            raise GatewayError(str(exc)) from exc
        latency = time.monotonic() - start
        try:
            choice = body["choices"][0]
            content = choice["message"].get("content", "") or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise GatewayError(f"gateway response shape unexpected: {body}") from exc
        usage = body.get("usage", {}) or {}
        reasoning_tokens = reasoning_tokens_of(usage)
        attempt_meta = {
            "attempt": attempt,
            "latency_seconds": round(latency, 2),
            "completion_tokens": usage.get("completion_tokens"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "reasoning_tokens": reasoning_tokens,
            "finish_reason": choice.get("finish_reason"),
            "status": "ok",
        }
        meta["attempts"].append(attempt_meta)
        if attempt == 0 and _looks_like_nonempty_ir(content):
            meta.update(attempt_meta)
            return content, meta
    # LLM 两次都失败 -> 确定性回退（永不返回空）
    ir = _markdown_to_ir(markdown)
    meta["fallback"] = "markdown-parser"
    meta["retried"] = True
    meta["reasoning_tokens"] = None
    rs = [a.get("reasoning_tokens") for a in meta["attempts"]]
    rs = [r for r in rs if r is not None]
    if rs:
        meta["reasoning_tokens"] = rs[-1]
    return json.dumps(ir, ensure_ascii=False), meta


def _merge_visual_graph(
    ir_str: str,
    markdown: str,
    image_path: str,
    *,
    model: str,
    api_key: str,
    session: str,
    timeout: int,
) -> tuple[str, dict | None]:
    """Replace text-inferred graph blocks with a strict image graph when possible.

    Text transcription remains the source of paragraphs and lists.  A second,
    purpose-built VLM call owns only topology, so prose recognition can never
    accidentally turn a bullet or an edge label into a node.  Any extraction
    failure is intentionally non-fatal: the deterministic Markdown inference
    already present in ``ir_str`` remains the fallback.
    """
    from . import diagram
    from .diagrams import infer

    if not infer.detect_diagram_markdown(markdown):
        return ir_str, None
    try:
        graph_model = DIAGRAM_MODEL or model
        result = diagram.extract_diagram_image(
            image_path,
            model=graph_model,
            api_key=api_key,
            session=session,
            timeout=timeout,
        )
    except Exception as exc:  # defensive boundary: graph extraction is optional
        return ir_str, {"verdict": "exception", "error": str(exc)}

    if not result.get("ok") or not result.get("nodes"):
        meta = dict(result.get("meta") or {})
        meta["verdict"] = result.get("verdict", "unknown")
        return ir_str, meta

    obj = parse_ir_json(ir_str)
    if not isinstance(obj, dict) or not isinstance(obj.get("blocks"), list):
        return ir_str, {"verdict": "ir_parse_fail"}

    # The parser's flow/diagram blocks are a fallback representation of the
    # same visual region.  Keep all textual blocks, then add exactly one graph
    # block produced from the image-level structured output.
    kept = [b for b in obj["blocks"] if b.get("type") not in {"flow", "diagram"}]
    kept.append({
        "type": "flow",
        "orientation": "TB",
        "nodes": result["nodes"],
        "edges": result.get("edges", []),
        "caption": result.get("caption", ""),
        "source": None,
    })
    obj["blocks"] = kept
    meta = dict(result.get("meta") or {})
    meta["verdict"] = "ok"
    meta["specialist_model"] = DIAGRAM_MODEL or model
    meta["node_count"] = len(result["nodes"])
    meta["edge_count"] = len(result.get("edges", []))
    return json.dumps(obj, ensure_ascii=False), meta


def call_ir(
    image_path: str,
    model: str,
    *,
    api_key: str | None = None,
    session: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
    cache: VlmCache | None = None,
    recover: bool = False,
    ir_model: str | None = None,
    ir_max_tokens: int | None = None,
) -> tuple[str, dict]:
    """Parse an image into text IR plus an optional specialist graph IR block.

    ``content`` 仍是 IR JSON 字符串（Router 缝不变）；``meta`` 含文字转录、
    IR 和专用图结构阶段的信息。``recover`` 令各阶段都用更紧的重试约束
    （R4 策略切换，绝不同参重复）。muse 系列一律禁用（见 IR_MODEL 注释）。
    """
    key = api_key or load_api_key()
    sess = session if session is not None else resolve_session(model)
    ir_model = ir_model or IR_MODEL
    ir_mt = ir_max_tokens or DEFAULT_IR_MAX_TOKENS

    if cache is not None:
        cached = cache.get(image_path, model)
        if cached is not None:
            rec = json.loads(cached)
            meta = dict(rec.get("meta") or {})
            meta["cached"] = True
            return rec.get("content", ""), meta

    # stage-1：VLM -> 非空 Markdown（eval 已验证对真实扫描页稳定非空）
    markdown, m1 = _transcribe_markdown(
        image_path, model, key=key, sess=sess,
        max_tokens=max_tokens, timeout=timeout, recover=recover,
    )
    if not (markdown or "").strip():
        m1w = list(m1.get("warnings") or [])
        meta = {
            **m1,
            "stage": "markdown",
            "status": "ok",
            "empty": True,
            "empty_stage": "markdown",
            "warnings": m1w + ["VLM markdown stage returned empty content"],
            "retried": recover,
        }
        if cache is not None:
            cache.put(image_path, model, "", meta)
        return "", meta

    # stage-2：轻量文本 LLM -> IR JSON
    use_llm = os.environ.get("GRAPH2NOTE_IR_MODE", "parser") == "llm"
    ir_str, m2 = _ir_from_markdown(
        markdown, ir_model, key=key, sess=sess,
        max_tokens=ir_mt, timeout=timeout, recover=recover, use_llm=use_llm,
    )
    # Dedicated image-level topology extraction is deliberately after the
    # normal text pass: text remains useful even when the graph VLM times out.
    # It is activated only for pages whose transcription contains relation
    # signals, avoiding a second vision call for ordinary notes.
    ir_str, m3 = _merge_visual_graph(
        ir_str,
        markdown,
        image_path,
        model=model,
        api_key=key,
        session=sess,
        timeout=timeout,
    )
    meta = {
        "stage": "ir",
        "status": "ok",
        "model": model,
        "session": sess,
        "recover": recover,
        "markdown_stage": m1,
        "ir_stage": m2,
        "diagram_stage": m3,
        "reasoning_tokens": m2.get("reasoning_tokens"),
        "finish_reason": m2.get("finish_reason"),
        "markdown_len": len(markdown),
        "empty": not bool(ir_str.strip()),
    }
    if not ir_str.strip():
        meta["empty_stage"] = "ir"
        meta["warnings"] = (m1.get("warnings") or []) + [
            "IR stage produced no parseable non-empty JSON"
        ]
    if cache is not None:
        cache.put(image_path, model, ir_str, meta)
    return ir_str, meta
__all__ = [
    "GatewayError",
    "load_api_key",
    "image_to_data_url",
    "downscale_to_max_side",
    "image_data_url_downscaled",
    "SYSTEM_PROMPT",
    "USER_PROMPT",
    "MARKDOWN_SYSTEM_PROMPT",
    "MARKDOWN_USER_PROMPT",
    "DIAGRAM_MODEL",
    "IR_MODEL",
    "parse_ir_json",
    "VlmCache",
    "resolve_session",
    "call_ir",
]
