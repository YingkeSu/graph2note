"""Productized image -> strict-diagram extraction (issue 15, Spike 3 $\u00a74-7).

Ports Spike 3's visual nodes/edges generator into ``graph2note/``.  An image is
sent to the vision model with a *strict* ``{"nodes":[{id,label}],"edges":
[{from,to,label}],"caption":""}`` (or ``{"error":"no_flow_extractable"}``)
contract, and the reply is validated into a schema-legal diagram.

Model strategy (Spike 3 $\u00a77, verbatim):

* primary ``glm-5.3-flash`` - the *only* model in the 12-sample evidence that
  extracts structure from real large pages (R01/R02, ~800KB).
* token-budget upgrade on reasoning exhaustion (aligned with issues 10/12's
  10000 cap) - NOT a same-parameters retry (R4 strategy switch).
* empty content / parse failure -> degrade (no same-params retry): ~17% of
  Spike 3 calls returned empty; those funnel to the crop&embed degrade path
  which cannot produce mojibake.

The production path calls this only after stage-1 transcription detects arrow
signals.  The Markdown parser remains the deterministic fallback, while this
specialist pass owns the page-level topology and replaces fragmented text-side
flow blocks when it succeeds.  A dedicated ``diagram`` purpose session keeps
the graph call isolated from parse retries.
"""

from __future__ import annotations

import json
import os
import re
import time

# ---- purpose-session isolation (issue 14) ------------------------------
STABLE_SESSION = os.environ.get("GRAPH2NOTE_DIAGRAM_SESSION", "graph2note-diagram-01")
DEFAULT_MODEL = os.environ.get("GRAPH2NOTE_DIAGRAM_MODEL", "glm-5.3-flash")
DIAGRAM_MAX_TOKENS = int(os.environ.get("GRAPH2NOTE_DIAGRAM_MAX_TOKENS", "8000"))
DIAGRAM_RETRY_TOKENS = int(os.environ.get("GRAPH2NOTE_DIAGRAM_RETRY_TOKENS", "10000"))
# Client timeout for the diagram vision call.  The legacy 120s default truncated
# the token-budget upgrade (T-audit F-H: kimi-k2.6 spent ~117s on the empty
# 3500-token attempt and ~212s on the 10000-token retry, ~= 330s).  The first
# attempt now starts at 8000 tokens, which at the measured ~30 tok/s could add
# ~267s before the retry, so the client budget must clear the whole two-attempt
# worst case (~480s); 600s leaves a margin.  Overridable for other gateways.
DEFAULT_TIMEOUT = int(os.environ.get("GRAPH2NOTE_DIAGRAM_TIMEOUT", "600"))
USER_AGENT = "graph2note-diagram/0.1"


def resolve_session() -> str:
    """Diagram-purpose session id: GRAPH2NOTE_DIAGRAM_SESSION > GRAPH2NOTE_SESSION_DIAGRAM
    > GRAPH2NOTE_OPENCODE_SESSION/OPENCODE_SESSION > graph2note-diagram-01."""
    for env in ("GRAPH2NOTE_SESSION_DIAGRAM", "GRAPH2NOTE_OPENCODE_SESSION",
                "OPENCODE_SESSION"):
        v = os.environ.get(env, "").strip()
        if v:
            return v
    return STABLE_SESSION


def strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def try_parse_json(raw: str):
    """Robust JSON extraction from a raw model answer."""
    if not raw or not raw.strip():
        return None
    text = strip_fences(raw)
    try:
        return json.loads(text)
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            return None
    return None


GROUP_KINDS = ("layer", "lane", "cluster")


def _clean_note(value):
    """Normalize an optional note: blank/None -> None, else stripped text."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_groups(raw, order):
    """Validate/normalize the optional ``groups`` payload.

    Returns ``(groups, ok)``.  Rules (SPEC §1): group ids are unique, ``kind``
    is one of ``layer``/``lane``/``cluster``, and every member id must exist in
    ``nodes[]`` (dangling references are rejected).  Membership is a *set*, so
    duplicate members are dropped and the list is written in node-appearance
    order (the layout canonicalizer can re-sort later; this keeps the
    extractor's output deterministic for the same semantic content).
    ``order`` maps node id -> index in the normalized ``nodes`` list.
    """
    if raw is None:
        return [], True
    if not isinstance(raw, list):
        return [], False
    seen: set[str] = set()
    groups: list[dict] = []
    for item in raw:
        if not isinstance(item, dict) or "id" not in item:
            return [], False
        gid = str(item["id"])
        if not gid or gid in seen:
            return [], False
        seen.add(gid)
        kind = str(item.get("kind", "cluster"))
        if kind not in GROUP_KINDS:
            return [], False
        members_raw = item.get("nodes", [])
        if not isinstance(members_raw, list):
            return [], False
        members: list[str] = []
        for member in members_raw:
            mid = str(member)
            if mid not in order:
                return [], False
            if mid not in members:
                members.append(mid)
        members.sort(key=lambda mid: order[mid])
        groups.append({
            "id": gid,
            "label": str(item.get("label", "")),
            "kind": kind,
            "nodes": members,
        })
    return groups, True


def _cached_result(cached: str) -> tuple[dict, dict]:
    """Decode a ``VlmCache`` record into ``(result, meta)``.

    ``VlmCache.get`` returns the whole on-disk record ``{"content": <str>,
    "meta": {...}}`` and the diagram writer stores the full result (plus its
    meta) as that content JSON string.  A historic reader looked for a
    ``result`` key that was never written, so cache hits returned ``meta`` only
    and silently dropped the graph (T-audit F-G).  Also tolerate a legacy flat
    record (result fields stored beside ``meta``).
    """
    try:
        rec = json.loads(cached)
    except (TypeError, json.JSONDecodeError):
        return {}, {}
    if not isinstance(rec, dict):
        return {}, {}
    meta = dict(rec.get("meta") or {})
    payload = rec.get("content")
    data = None
    if isinstance(payload, str):
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = None
    if isinstance(data, dict) and data:
        meta = {**dict(data.get("meta") or {}), **meta}
        return {k: v for k, v in data.items() if k != "meta"}, meta
    return {k: v for k, v in rec.items() if k not in ("meta", "content")}, meta


def validate_diagram_json(data):
    """Validate a candidate dict into ``({"nodes","edges","caption","groups"}, verdict)``.

    Strict contract: ``nodes``+``edges`` lists, unique node ids, every edge
    references existing ids, no self-loops, at least one node.  Optional
    ``note`` on nodes and ``style`` on edges are preserved; optional ``groups``
    must reference existing node ids and use a known ``kind``.  A dict with an
    ``error`` key is treated as "no_flow" (None + verdict no_flow); any
    contract violation is ``malformed``.
    """
    if not isinstance(data, dict):
        return None, "malformed"
    if data.get("error"):
        return None, "no_flow"
    nodes, edges = data.get("nodes"), data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return None, "malformed"
    ids = {}
    ns = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict) or "id" not in n:
            return None, "malformed"
        nid = str(n["id"])
        if nid in ids:
            return None, "malformed"
        ids[nid] = nid
        node = {"id": nid, "label": str(n.get("label", ""))}
        note = _clean_note(n.get("note"))
        if note is not None:
            node["note"] = note
        ns.append(node)
    es = []
    for e in edges:
        if not isinstance(e, dict):
            return None, "malformed"
        src, tgt = str(e.get("from", "")), str(e.get("to", ""))
        if src not in ids or tgt not in ids:
            return None, "malformed"
        if src == tgt:
            return None, "malformed"
        style = str(e.get("style", "solid"))
        if style not in ("solid", "dashed"):
            return None, "malformed"
        edge = {"from": src, "to": tgt, "label": str(e.get("label", ""))}
        if style == "dashed":
            edge["style"] = style
        es.append(edge)
    if not ns:
        return None, "malformed"
    order = {nid: i for i, nid in enumerate(ids)}
    groups, ok = _normalize_groups(data.get("groups"), order)
    if not ok:
        return None, "malformed"
    caption = str(data.get("caption", ""))
    return ({"nodes": ns, "edges": es, "caption": caption, "groups": groups}, "ok")


SYSTEM_PROMPT = (
    "你是手稿图表结构化引擎。根据这张图片（手绘流程/架构图或相关区域），"
    "先识别页面中的分层/泳道/分组结构，再填写节点与边，"
    "输出严格 JSON 对象，只输出该 JSON，不要 Markdown 围栏、不要任何解释文字。\n"
    '格式：{"caption":"<可选说明>",'
    '"groups":[{"id":"g1","label":"通信层","kind":"layer",'
    '"nodes":["n1","n2"]}...],'
    '"nodes":[{"id":"n1","label":"节点文本","note":"可选旁注"}...],'
    '"edges":[{"from":"n1","to":"n2","label":"可选边说明",'
    '"style":"solid|dashed"}...]}\n'
    "要求：\n"
    "1. 先判层次：若图中存在水平层带、垂直泳道或明显局部簇，用 groups 表达；"
    "kind 取 layer（水平分层带）/ lane（垂直泳道）/ cluster（局部簇），"
    "nodes 列出该组成员节点 id，顺序按图中自上而下、自左而右的阅读顺序。\n"
    "2. 节点只放实体/步骤/组件/选项本身；label 原样保留中文与标点，id 自增编号互不重复。\n"
    "3. 评价性短句不建节点、只作相关节点的 note：警告、坑、不支持、注意、风险、限制、"
    "亮点、优化、优点、缺点、建议、备注等。找到语义上最相关的那一个节点，把整句写进它的 note；"
    "note 不要重复节点自己的主标签。"
    "例：手稿「坑：Tiger VNC 不支持」是对某个远程桌面/通信节点的注记，应写成该节点的 "
    '"note":"坑：Tiger VNC 不支持"，不要为它新建节点；「亮点：Critical Path 优化 ☆」是通信/'
    "调度方案的注记，同样写进相关节点的 note，不另建节点。\n"
    "4. 每条边 from/to 必须引用已定义的节点 id；不要自环；方向跟着图中箭头。"
    "style 缺省为 solid。手稿中若把两节点的关联画得松散/说明性，或文字写明「参考」「可选」"
    "「备选」「弱引用」「跨组引用」，则该边用 style:\"dashed\"，label 保留原文。"
    '例：「调研 → 预处理」上标「参考」→ {"from":"<调研id>","to":"<预处理id>",'
    '"label":"参考","style":"dashed"}；跨组/跨层指向的弱引用同样建 dashed 边。\n'
    "5. 弱关联不得整条丢弃：图中出现的 参考/虚线/跨组弱引用 类关系，即使不确定也要用 dashed 边"
    "或相关节点的 note 表达，不得因为「不是主流程」而省略。\n"
    "6. 一页中可能有多个相互独立的区域；仍输出一个 page-level graph，"
    "把每个可见方框/概念作为节点，把每一条明确箭头作为边，不要只挑一条主线。\n"
    "7. 不要把普通说明、项目符号、问题清单、目录或旁注文字臆造为图节点或边；"
    "这类文字若与某节点相关则作为该节点 note（见要求 3 与 5），确实无关联时才可忽略。\n"
    "8. 若图中没有可提取的流程/架构关系，直接输出 {\"error\":\"no_flow_extractable\"}。\n"
    "9. 无法可靠读出的文字不要编造；宁可使用短标签或省略该节点。"
    "若无法识别任何层次/分组，groups 合法为空数组 []，严禁编造层次。\n"
    "只输出 JSON："
)

USER_PROMPT = "把这张图的结构提取为上述 JSON："


def extract_diagram_image(
    image_path: str,
    model: str | None = None,
    *,
    api_key: str | None = None,
    session: str | None = None,
    max_tokens: int = DIAGRAM_MAX_TOKENS,
    retry_tokens: int = DIAGRAM_RETRY_TOKENS,
    timeout: int = DEFAULT_TIMEOUT,
    cache=None,
    provider: str | None = None,
) -> dict:
    """Extract a diagram from an image.  Returns a result dict:

    ``{"ok": bool, "verdict": "ok"|"no_flow"|"parse_fail"|"empty"|"http_error",
        "nodes":[...], "edges":[...], "caption":"", "meta": {...}}``

    Empty content or parse failure -> ``ok=False`` with a ``verdict`` the caller
    can use to funnel to the crop&embed degrade path (renderer source crop).
    No same-parameter retry on empty (Spike 3 rate ~17%); only a
    ``finish_reason=length`` (reasoning exhaustion) triggers one upgraded-budget
    retry (issues 10/12 alignment).
    """
    from . import vlm  # lazy: keeps ingest import free of vlm's banner side effects

    from .llm_settings import resolve_channel

    channel = resolve_channel("diagram")
    model = model or channel["model"]
    provider = provider or channel["provider"]
    if api_key:
        key = api_key
    else:
        try:
            key = vlm.load_api_key(provider)
        except TypeError:
            # Keep compatibility with zero-argument offline fixtures.
            key = vlm.load_api_key()
    sess = session if session is not None else resolve_session()

    if cache is not None:
        cached = cache.get(image_path, model)
        if cached is not None:
            result, meta = _cached_result(cached)
            meta["cached"] = True
            return {**result, "meta": meta}

    data_url, send_size = vlm.image_data_url_downscaled(image_path)
    attempts: list[dict] = []
    last_content = ""
    last_finish = None
    for attempt in range(2):
        mt = max_tokens
        system = SYSTEM_PROMPT
        if attempt > 0:
            system = system + (
                "\n重要：这是预算升级后的重试（推理预算不足）。直接输出严格 JSON，"
                "不要任何思考/解释文字，严禁空内容。"
            )
            mt = max(mt, retry_tokens)
        payload = {
            "model": model,
            "max_tokens": mt,
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
        start = time.monotonic()
        try:
            body = None
            body = _post(payload, key=key, sess=sess, timeout=timeout, provider=provider)
        except Exception as exc:
            return {
                "ok": False, "verdict": "http_error", "nodes": [], "edges": [],
                "caption": "",
                "meta": {"model": model, "provider": provider, "error": str(exc),
                         "attempts": attempts, "session": sess},
            }
        latency = time.monotonic() - start
        try:
            choice = body["choices"][0]
            content = choice["message"].get("content", "") or ""
        except (KeyError, IndexError, TypeError) as exc:
            return {"ok": False, "verdict": "http_error", "nodes": [], "edges": [],
                    "caption": "", "meta": {"model": model, "provider": provider, "error": str(exc),
                                            "attempts": attempts, "session": sess}}
        finish = choice.get("finish_reason")
        last_content = content
        last_finish = finish
        attempts.append({
            "attempt": attempt, "max_tokens": mt, "finish_reason": finish,
            "content_len": len(content or ""),
            "latency_seconds": round(latency, 2),
        })
        if (content or "").strip() and finish != "length":
            break  # got a reply -> parse it below (no more retries)
        if attempt == 0 and finish == "length" and not (content or "").strip():
            continue  # reasoning exhausted with empty content -> one upgraded retry
        break
        # empty content with finish_reason NOT length -> degrade immediately
        # (no same-parameters retry), handled after the loop.

    verdict = "empty"
    nodes, edges, caption, groups = [], [], "", []
    if (last_content or "").strip():
        data = try_parse_json(last_content)
        if data is None:
            verdict = "parse_fail"
        else:
            diag, verdict = validate_diagram_json(data)
            if diag is not None:
                nodes = diag["nodes"]
                edges = diag["edges"]
                caption = diag["caption"]
                groups = diag["groups"]
                verdict = "ok"
    ok = verdict == "ok"
    result = {
        "ok": ok, "verdict": verdict, "nodes": nodes, "edges": edges,
        "caption": caption, "groups": groups,
    }
    meta = {
        "model": model, "provider": provider, "session": sess, "image_size": send_size,
        "retried": len(attempts) > 1, "attempts": attempts,
    }
    if cache is not None:
        cache.put(image_path, model, json.dumps({**result, "meta": meta},
                                                ensure_ascii=False))
    return {**result, "meta": meta}


def _post(payload, *, key, sess, timeout, provider=None):
    # Reuse the product gateway seam so the dedicated graph call shares the
    # same auth/session policy as the text transcription stage and remains
    # straightforward to stub in offline tests.
    from . import vlm

    return vlm.post_gateway(payload, provider=provider, api_key=key, session=sess,
                            timeout=timeout, user_agent=USER_AGENT)


__all__ = [
    "resolve_session",
    "STABLE_SESSION",
    "DEFAULT_MODEL",
    "strip_fences",
    "try_parse_json",
    "validate_diagram_json",
    "GROUP_KINDS",
    "extract_diagram_image",
    "SYSTEM_PROMPT",
    "USER_PROMPT",
]
