"""VLM gateway producing a Document IR JSON string via the opencode go gateway.

Contract (docs/llm/opencode-go.md):
  * endpoint https://opencode.ai/zen/go/v1/chat/completions (OpenAI-compatible)
  * Authorization: Bearer $OPENCODE_API_KEY  (env var, or repo-root .env — never
    committed)
  * must carry ``x-opencode-session`` (kept stable for retries / prompt cache)
  * ``max_tokens`` 10000 (reasoning consumes the budget; 200 truncates to empty)
  * image sent as a base64 ``data:`` URL; final text is ``message.content``

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

GATEWAY_BASE = "https://opencode.ai/zen/go/v1"
CHAT_COMPLETIONS = GATEWAY_BASE + "/chat/completions"
# Stable, reused session id -> known-good routing & prompt cache (R1).  Kept
# identical across retries so the gateway reuses warm routing.
STABLE_SESSION = "graph2note-parse-route-a"
USER_AGENT = "graph2note-parse/0.1"

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


class GatewayError(RuntimeError):
    """Gateway call failed (network, auth, HTTP, bad response shape)."""


def load_api_key() -> str:
    """OPENCODE_API_KEY from env, else from the repo-root `.env`."""

    key = os.environ.get("OPENCODE_API_KEY", "").strip()
    if key:
        return key
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "..", ".env"),
        # main checkout .env (this worktree has none)
        "/Users/suyingke/Programs/OHO/graph2note/.env",
    ]
    seen = set()
    for cand in candidates:
        cand = os.path.abspath(cand)
        if cand in seen or not os.path.exists(cand):
            continue
        seen.add(cand)
        try:
            with open(cand, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line.startswith("OPENCODE_API_KEY="):
                        return line.split("=", 1)[1].strip().strip("\"'")
        except OSError:
            continue
    raise GatewayError(
        "OPENCODE_API_KEY not found (set env var or put it in repo-root .env)"
    )


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
    "你是手稿数字化引擎。把这一页手稿/文档图片解析为结构化的 Document IR JSON，"
    "只输出该 JSON 对象本身，不要 Markdown 围栏、不要任何多余解释或前后缀文字。\n"
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
    "1. 完整保留正文、标题层级、列表（- 无序 / 1. 有序）、段落阅读顺序；表格与公式用上述结构表达。\n"
    "2. 语义化删除：被删除线或涂抹明确废弃的内容不要输出；判断模糊时保守保留。\n"
    "3. 图表（diagram/flow）：能可靠提取节点与有向连线语义时给出 nodes/edges；"
    "无法可靠提取时输出该类型 block 且 nodes 与 edges 均为空数组（保持结构化语义契约）。\n"
    "4. 中文标点与全角字符原样保留。\n"
    "只输出 JSON："
)

USER_PROMPT = "把这张手稿图片解析为上述格式的 Document IR JSON。"


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


def call_ir(
    image_path: str,
    model: str,
    *,
    api_key: str | None = None,
    session: str = STABLE_SESSION,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
    cache: VlmCache | None = None,
    recover: bool = False,
) -> tuple[str, dict]:
    """Call the vision model, returning ``(content, meta)``.

    ``content`` is the raw model reply text (still to be parsed into IR).
    If ``cache`` is given, a hit returns the recorded reply (offline).
    ``recover`` selects the tight retry prompt (R4 strategy switch).
    """
    key = api_key or load_api_key()

    if cache is not None:
        cached = cache.get(image_path, model)
        if cached is not None:
            rec = json.loads(cached)
            meta = dict(rec.get("meta") or {})
            meta["cached"] = True
            return rec.get("content", ""), meta

    data_url, send_size = image_data_url_downscaled(image_path)
    system = SYSTEM_PROMPT
    if recover:
        system = system + (
            "\n重要：这是重试。请直接输出合法 JSON，\n"
            "绝对不要任何推理过程、解释、思考链或前后缀文字，"
            "也绝不要输出空的 JSON。"
        )
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": USER_PROMPT},
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
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GatewayError(f"gateway HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise GatewayError(f"gateway call failed: {exc}") from exc
    finally:
        latency = time.monotonic() - start

    try:
        choice = body["choices"][0]
        content = choice["message"].get("content", "") or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise GatewayError(f"gateway response shape unexpected: {body}") from exc

    usage = body.get("usage", {}) or {}
    meta = {
        "model": model,
        "status": "ok",
        "cost": body.get("cost", "0"),
        "latency_seconds": round(latency, 2),
        "image_size": send_size,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reasoning_tokens": usage.get("reasoning_tokens"),
        "finish_reason": choice.get("finish_reason"),
        "cached": False,
    }
    if cache is not None:
        cache.put(image_path, model, content, meta)
    return content, meta


__all__ = [
    "GatewayError",
    "load_api_key",
    "image_to_data_url",
    "downscale_to_max_side",
    "image_data_url_downscaled",
    "SYSTEM_PROMPT",
    "USER_PROMPT",
    "parse_ir_json",
    "VlmCache",
    "call_ir",
]