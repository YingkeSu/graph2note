"""科研周报 (research weekly report) — issue 01 of the research-weekly-template round.

This module is the *research* template layered on top of the existing weekly
digest primitives (:mod:`graph2note.digest`).  It deliberately does **not**
change the legacy four-section digest: the legacy path keeps its own schema,
cache and ``/api/digests`` endpoints, while a research report is a distinct,
independently versioned artifact.

Design guarantees (issue 01 acceptance criteria):

- **Stable template identity.**  ``TEMPLATE_ID`` / ``TEMPLATE_VERSION`` identify
  the research template; ``SCHEMA_VERSION`` / ``PROMPT_VERSION`` version the
  report schema and the model prompt separately.  ``templates_payload`` exposes
  both the research template and the legacy ``weekly_summary`` template.
- **Core sections + optional 专题.**  Every research report renders 本周概览 /
  本周进展 / 问题与求助 in a fixed order, then the *enabled* optional modules in
  the user's configured order, then a deterministic 附录.  The default module
  catalog (实验结果 / 过程记录 / 方法备忘) is **disabled by default**, so an
  evidence-free week never shows a fabricated 实验结果 section.  An enabled
  module whose model body is empty is omitted too; 问题与求助 keeps its heading
  even when empty ("空求助仅标题").
- **Deterministic statistics + material budget.**  Counts, sources and the
  material budget come from :func:`graph2note.digest.assemble_material`; the
  model never produces numbers.
- **Cache key covers every generation input.**  The report fingerprint hashes
  the template id/version, schema/prompt version, the normalized module config
  (keys, titles, enabled flag, order) and the material fingerprint.  A pure
  layout/reporter/date change therefore reuses the cache with **zero** model
  calls, while a template or module change can never reuse a stale result.  The
  legacy digest cache lives in a different directory with a different
  fingerprint and is never consulted here.
- **Empty material never calls the model.**
- **Persisted history.**  Reports are stored as ``<storage>/reports/<id>.md`` +
  ``<id>.meta.json`` and survive a process restart.

Nothing here talks to the network unless the default (live) planner is used;
tests inject a recorded golden planner.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from . import digest

# ---------------------------------------------------------------------------
# Versioned template identity
# ---------------------------------------------------------------------------

TEMPLATE_ID = "research_weekly"
TEMPLATE_VERSION = "1"
SCHEMA_VERSION = 1
GENERATOR_VERSION = "research-report-1"
# Bumped whenever the research prompt / output schema changes so a cached
# section is never reused with a different instruction set.
PROMPT_VERSION = "research-report-sections-1"

REPORT_TITLE = "# 科研周报"

# The legacy four-section weekly summary stays available as a template.  Its
# version is the digest schema version; the reading UI just links to the digest
# endpoints, this module only advertises it.
LEGACY_TEMPLATE_ID = "weekly_summary"
LEGACY_TEMPLATE_LABEL = "旧版四节小结"

EMPTY_MESSAGE = "该范围内没有材料"

# ---------------------------------------------------------------------------
# Section skeleton
# ---------------------------------------------------------------------------

SECTION_OVERVIEW = "overview"
SECTION_PROGRESS = "progress"
SECTION_ISSUES = "issues"
SECTION_APPENDIX = "appendix"

# Fixed-order core sections.  概览 / 进展 / 问题与求助 always render.
CORE_SECTIONS: tuple[tuple[str, str], ...] = (
    (SECTION_OVERVIEW, "本周概览"),
    (SECTION_PROGRESS, "本周进展"),
    (SECTION_ISSUES, "问题与求助"),
)
CORE_TITLES = dict(CORE_SECTIONS)
CORE_NARRATIVE_SECTIONS: tuple[str, ...] = (SECTION_OVERVIEW, SECTION_PROGRESS, SECTION_ISSUES)
APPENDIX_TITLE = "附录：来源材料"

# 每条事实都要能被归类；未知的不要写成已完成。
EVIDENCE_LABELS: tuple[str, ...] = ("已知", "推论", "猜想", "待验证", "计划")

# Optional 专题 catalog.  Disabled by default — an evidence-free week must not
# show a fabricated 实验结果 section.  Users may enable/disable/reorder these
# and add custom titled modules through the API/UI.
MODULE_CATALOG: tuple[dict[str, str], ...] = (
    {
        "key": "experiments",
        "title": "实验结果",
        "hint": "只在本周材料含实验证据时填写；没有证据就留空，不要补造实验结论。",
    },
    {
        "key": "process",
        "title": "过程记录",
        "hint": "记录过程、踩坑与代价；不虚构结果。",
    },
    {
        "key": "method",
        "title": "方法备忘",
        "hint": "可复用的方法、公式或代码要点。",
    },
)
_CATALOG_BY_KEY: dict[str, dict[str, str]] = {m["key"]: m for m in MODULE_CATALOG}
DEFAULT_MODULES: tuple[dict[str, Any], ...] = tuple(
    {"key": m["key"], "title": m["title"], "enabled": False} for m in MODULE_CATALOG
)


class ReportError(ValueError):
    """Raised for an invalid report request (range / module config)."""


class ModuleError(ReportError):
    """Raised when the 专题 module configuration is malformed."""


# ---------------------------------------------------------------------------
# Template / module registry (pure)
# ---------------------------------------------------------------------------


def templates_payload() -> dict[str, Any]:
    """Both templates + the optional module catalog (for the UI + API)."""
    return {
        "templates": [
            {
                "id": TEMPLATE_ID,
                "version": TEMPLATE_VERSION,
                "label": "科研周报",
                "schema_version": SCHEMA_VERSION,
                "prompt_version": PROMPT_VERSION,
                "supports_modules": True,
                "sections": [
                    {"key": key, "title": title, "optional": False}
                    for key, title in CORE_SECTIONS
                ]
                + [
                    {"key": "appendix", "title": APPENDIX_TITLE, "optional": False},
                ],
                "modules": [dict(m) for m in MODULE_CATALOG],
            },
            {
                "id": LEGACY_TEMPLATE_ID,
                "version": str(digest.SCHEMA_VERSION),
                "label": LEGACY_TEMPLATE_LABEL,
                "schema_version": digest.SCHEMA_VERSION,
                "prompt_version": digest.SECTION_PROMPT_VERSION,
                "supports_modules": False,
                "legacy": True,
                "endpoint": "/api/digests",
                "sections": [
                    {"key": key, "title": title, "optional": False}
                    for key, title in digest.SECTION_DEFS
                ],
                "modules": [],
            },
        ],
        "modules": [dict(m) for m in MODULE_CATALOG],
        "core_sections": [
            {"key": key, "title": title} for key, title in CORE_SECTIONS
        ],
        "evidence_labels": list(EVIDENCE_LABELS),
    }


_MODULE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _clean_module(item: Any) -> dict[str, Any] | None:
    if isinstance(item, str):
        key, title, enabled = item.strip(), None, True
    elif isinstance(item, dict):
        key = str(item.get("key") or item.get("id") or "").strip()
        title = item.get("title")
        enabled = bool(item.get("enabled", True))
    else:
        raise ModuleError(f"专题配置项必须是字符串或对象：{item!r}")
    if not key:
        raise ModuleError("专题配置缺少 key。")
    if not _MODULE_KEY_RE.match(key):
        raise ModuleError(f"专题 key 不合法：{key!r}")
    if key in CORE_TITLES or key == SECTION_APPENDIX:
        raise ModuleError(f"专题 key 不能与固定章节冲突：{key!r}")
    known = _CATALOG_BY_KEY.get(key)
    resolved_title = str(title).strip() if title is not None else ""
    if not resolved_title:
        resolved_title = known["title"] if known else key
    return {"key": key, "title": resolved_title, "enabled": enabled}


def normalize_modules(raw: Any = None) -> list[dict[str, Any]]:
    """Validate + normalize a 专题 config, preserving the caller's order.

    ``None`` (or no config) yields the catalog modules **disabled**, so the
    default research report never contains a fabricated 实验结果 section.
    """
    if raw is None:
        return [dict(m) for m in DEFAULT_MODULES]
    if not isinstance(raw, (list, tuple)):
        raise ModuleError("专题配置必须是列表。")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        module = _clean_module(item)
        if module is None or module["key"] in seen:
            continue
        seen.add(module["key"])
        out.append(module)
    return out


def enabled_modules(modules: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(m) for m in (modules or []) if m.get("enabled")]


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Fingerprint (pure) — every generation input is covered
# ---------------------------------------------------------------------------


def compute_report_fingerprint(
    range_spec: dict[str, Any],
    material: dict[str, Any],
    modules: list[dict[str, Any]],
) -> str:
    """SHA-256 over template/schema/prompt versions, module config and material.

    Reporter / report date are intentionally **not** part of the payload: they
    are presentational and must not trigger a new model call.
    """
    payload = {
        "schema": SCHEMA_VERSION,
        "generator": GENERATOR_VERSION,
        "template": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "from": str(range_spec.get("from") or ""),
        "to": str(range_spec.get("to") or ""),
        "modules": [
            {
                "key": m.get("key"),
                "title": m.get("title"),
                "enabled": bool(m.get("enabled")),
            }
            for m in (modules or [])
        ],
        "documents": [
            {
                "document_id": d.get("document_id"),
                "version_id": d.get("version_id") or "",
                "content_hash": d.get("content_hash") or "",
            }
            for d in material.get("documents") or []
        ],
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Prompt (pure)
# ---------------------------------------------------------------------------


def _document_block(doc: dict[str, Any]) -> list[str]:
    lines = [f'<document id="{doc["document_id"]}" date="{doc["date"]}">']
    lines.append(f'标题：{doc["title"]}')
    if doc.get("tags"):
        lines.append("标签：" + "、".join(str(t) for t in doc["tags"]))
    if doc.get("topics"):
        lines.append("主题：" + "、".join(str(t) for t in doc["topics"]))
    lines.append("内容：")
    lines.append(doc.get("content") or "（无内容）")
    lines.append("</document>")
    return lines


def _material_block(documents: list[dict[str, Any]]) -> list[str]:
    if not documents:
        return ["（没有材料）"]
    lines: list[str] = []
    for doc in documents:
        lines.extend(_document_block(doc))
    return lines


def requested_sections(modules: list[dict[str, Any]]) -> list[str]:
    """Core narrative sections + enabled module keys, in render order."""
    return list(CORE_NARRATIVE_SECTIONS) + [
        str(m["key"]) for m in enabled_modules(modules)
    ]


def build_report_prompt(
    range_spec: dict[str, Any],
    documents: list[dict[str, Any]],
    *,
    stats: dict[str, Any] | None = None,
    modules: list[dict[str, Any]] | None = None,
    sections: Iterable[str] | None = None,
) -> str:
    """Sectioned JSON prompt for the research template (schema-validated reply)."""
    modules = normalize_modules(modules)
    enabled = enabled_modules(modules)
    module_by_key = {str(m["key"]): m for m in modules}
    requested = list(sections) if sections is not None else requested_sections(modules)

    example = ", ".join(
        f'"{key}": {{"markdown": "…", "source_document_ids": ["doc-id"]}}'
        for key in requested
    )
    lines = [
        "你是科研周报助手。请为本期科研周报填写下面指定的分节，只输出 JSON。",
        "JSON 格式：",
        '{"sections": {' + example + "}}",
        "要求：",
        "1. 只依据材料内容，不编造材料中没有的信息；无法核实的不要写成已完成。",
        "2. 每条事实都要能区分：已知 / 推论 / 猜想 / 待验证 / 计划；",
        "   没有证据支持的实验结果不要写，对应分节留空字符串即可。",
        "3. 本周进展按主题或项目分组，写清「做了什么 → 证据/结果 → 判断 → 下一步」。",
        "4. 不要输出数字统计（材料数量、预算等由系统确定性给出）。",
        "5. 问题与求助可以留空字符串，标题由系统保留。",
        "6. 不要输出周报标题、不要输出「来源」清单；Markdown 标题从三级（###）开始。",
        "7. source_document_ids 只能取自材料的 document id，逐条列出本节实际依据的文档；",
        "   没有把握时给空列表。",
        "8. 只输出上面 JSON 里出现的分节，不要新增分节。",
        "",
        f"时间范围：{range_spec.get('label') or range_spec.get('from')}",
        "",
    ]
    if stats is not None:
        lines.append("本期确定性统计（仅作背景，不要复述数字）：")
        lines.extend(digest.render_overview_body(stats).splitlines())
        lines.append("")
    lines.append("材料：")
    lines.extend(_material_block(documents))
    lines.append("")
    if enabled:
        lines.append("可选专题要求：")
        for module in enabled:
            hint = module_by_key.get(str(module["key"]), {}).get("hint")
            if not hint:
                hint = _CATALOG_BY_KEY.get(str(module["key"]), {}).get("hint", "")
            lines.append(f"- {module['key']}（{module['title']}）：{hint or '按材料如实填写。'}")
        lines.append("")
    lines.append(f"请只输出 JSON，其中只包含：{'、'.join(requested) or '（无）'}。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section assembly (pure)
# ---------------------------------------------------------------------------


def _demote_headings(text: str) -> str:
    lines = []
    for line in (text or "").splitlines():
        match = re.match(r"^(#{1,5})(\s+)(.*)$", line)
        lines.append(f"#{match.group(1)}{match.group(2)}{match.group(3)}" if match else line)
    return "\n".join(lines).strip()


def _section(key: str, title: str, body: str, ids: list[str], generated_by: str) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "markdown": body,
        "source_document_ids": ids,
        "generated_by": generated_by,
    }


def render_appendix_body(documents: list[dict[str, Any]]) -> tuple[str, list[str]]:
    from urllib.parse import quote

    if not documents:
        return "（本期没有材料）", []
    lines: list[str] = []
    ids: list[str] = []
    for doc in documents:
        document_id = str(doc["document_id"])
        ids.append(document_id)
        title = doc.get("title") or document_id
        link = f"#doc/{quote(document_id, safe='')}"
        lines.append(f'- [{title}]({link})（`{document_id}`，{doc.get("date") or "日期未知"}）')
    return "\n".join(lines), ids


def build_report_sections(
    material: dict[str, Any],
    bodies: dict[str, dict[str, Any]],
    modes: dict[str, str],
    modules: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Assemble the ordered research sections from bodies + deterministic parts."""
    sections: list[dict[str, Any]] = []

    overview = bodies.get(SECTION_OVERVIEW) or {}
    overview_body = (overview.get("markdown") or "").strip() or "（本期没有可归纳的内容）"
    sections.append(_section(
        SECTION_OVERVIEW, CORE_TITLES[SECTION_OVERVIEW], overview_body,
        list(overview.get("source_document_ids") or []),
        modes.get(SECTION_OVERVIEW, "empty"),
    ))

    progress = bodies.get(SECTION_PROGRESS) or {}
    progress_body = (progress.get("markdown") or "").strip() or "（本期没有可归纳的进展）"
    sections.append(_section(
        SECTION_PROGRESS, CORE_TITLES[SECTION_PROGRESS], progress_body,
        list(progress.get("source_document_ids") or []),
        modes.get(SECTION_PROGRESS, "empty"),
    ))

    # 问题与求助 may be title-only: keep the section even when the model body is empty.
    issues = bodies.get(SECTION_ISSUES) or {}
    sections.append(_section(
        SECTION_ISSUES, CORE_TITLES[SECTION_ISSUES], (issues.get("markdown") or "").strip(),
        list(issues.get("source_document_ids") or []),
        modes.get(SECTION_ISSUES, "empty"),
    ))

    # Optional 专题: only enabled modules, and only when they carry a body
    # (无依据实验不出现 — an empty module is omitted, never padded).
    for module in enabled_modules(modules):
        key = str(module["key"])
        body = bodies.get(key) or {}
        body_text = (body.get("markdown") or "").strip()
        if not body_text:
            continue
        sections.append(_section(
            key, str(module["title"]), body_text,
            list(body.get("source_document_ids") or []),
            modes.get(key, "model"),
        ))

    appendix_body, appendix_ids = render_appendix_body(material.get("documents") or [])
    sections.append(_section(
        SECTION_APPENDIX, APPENDIX_TITLE, appendix_body, appendix_ids, "deterministic",
    ))
    return sections


def render_report_markdown(
    range_spec: dict[str, Any],
    sections: list[dict[str, Any]],
    *,
    reporter: str | None = None,
    report_date: str | None = None,
) -> str:
    label = (range_spec or {}).get("label") or (range_spec or {}).get("from") or ""
    lines = [REPORT_TITLE, ""]
    if label:
        lines.append(f"时间范围：{label}")
    meta_bits = []
    if reporter:
        meta_bits.append(f"汇报人：{reporter}")
    if report_date:
        meta_bits.append(str(report_date))
    if meta_bits:
        lines.append("　　".join(meta_bits))
    lines.append("")
    for section in sections:
        lines.extend([f"## {section['title']}", ""])
        body = (section.get("markdown") or "").strip()
        lines.append(body if body else "_（本节暂无内容）_")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def public_sections(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reading/UI contract: key / title / source ids / generator + size."""
    return [
        {
            "key": section["key"],
            "title": section["title"],
            "source_document_ids": list(section.get("source_document_ids") or []),
            "generated_by": section.get("generated_by"),
            "chars": len(section.get("markdown") or ""),
        }
        for section in sections
    ]


# ---------------------------------------------------------------------------
# Persistence (the only IO in this module)
# ---------------------------------------------------------------------------


def reports_dir(storage_dir: str | Path) -> Path:
    return Path(storage_dir) / "reports"


def _meta_path(storage_dir: str | Path, report_id: str) -> Path:
    return reports_dir(storage_dir) / f"{report_id}.meta.json"


def _markdown_path(storage_dir: str | Path, report_id: str) -> Path:
    return reports_dir(storage_dir) / f"{report_id}.md"


def list_reports(storage_dir: str | Path) -> list[dict[str, Any]]:
    """All persisted research report metas, newest first (restart-safe)."""
    directory = reports_dir(storage_dir)
    if not directory.is_dir():
        return []
    metas: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.meta.json")):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(meta, dict) and meta.get("report_id"):
            metas.append(meta)
    metas.sort(
        key=lambda meta: (str(meta.get("created_at") or ""), meta["report_id"]),
        reverse=True,
    )
    return metas


def load_report(storage_dir: str | Path, report_id: str) -> dict[str, Any] | None:
    """Return ``{meta, markdown, sections}`` for one report, or ``None``."""
    meta_path = _meta_path(storage_dir, report_id)
    if not meta_path.is_file():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(meta, dict):
        return None
    markdown_path = _markdown_path(storage_dir, report_id)
    markdown = markdown_path.read_text(encoding="utf-8") if markdown_path.is_file() else ""
    return {"meta": meta, "markdown": markdown, "sections": meta.get("sections") or []}


def find_cached_report(storage_dir: str | Path, fingerprint: str) -> dict[str, Any] | None:
    """Newest persisted report with the same fingerprint (budget cache)."""
    if not fingerprint:
        return None
    for meta in list_reports(storage_dir):
        if meta.get("fingerprint") == fingerprint:
            return meta
    return None


def _new_report_id(storage_dir: str | Path, created_at: str, fingerprint: str) -> str:
    base = "rp-" + (re.sub(r"[^0-9]", "", created_at) or "0")
    report_id = f"{base}-{fingerprint[:8]}"
    suffix = 1
    while _meta_path(storage_dir, report_id).exists():
        suffix += 1
        report_id = f"{base}-{fingerprint[:8]}-{suffix}"
    return report_id


def save_report(
    storage_dir: str | Path,
    *,
    range_spec: dict[str, Any],
    material: dict[str, Any],
    markdown: str,
    sections: list[dict[str, Any]],
    modules: list[dict[str, Any]],
    fingerprint: str,
    reporter: str | None,
    report_date: str | None,
    model: str | None,
    provider: str | None,
    session: str | None,
    usage: dict[str, Any] | None,
    elapsed: float,
    llm_mode: str,
    llm_calls: int,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Write ``<id>.md`` + ``<id>.meta.json`` and return the meta."""
    directory = reports_dir(storage_dir)
    directory.mkdir(parents=True, exist_ok=True)
    created_at = created_at or datetime.now().isoformat(timespec="seconds")
    report_id = _new_report_id(storage_dir, created_at, fingerprint)
    documents = material.get("documents") or []
    meta = {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR_VERSION,
        "template_id": TEMPLATE_ID,
        "template_version": TEMPLATE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "report_id": report_id,
        "created_at": created_at,
        "range": range_spec,
        "fingerprint": fingerprint,
        "reporter": reporter,
        "report_date": report_date,
        "modules": [dict(m) for m in modules],
        "document_ids": [d["document_id"] for d in documents],
        "documents": [
            {
                "document_id": d["document_id"],
                "title": d["title"],
                "date": d["date"],
                "effective_time": d.get("effective_time"),
                "truncated": bool(d.get("truncated")),
            }
            for d in documents
        ],
        "document_count": len(documents),
        "omitted_documents": material.get("omitted", 0),
        "sections": public_sections(sections),
        "stats": digest._meta_stats_view(material.get("stats") or {}),
        "budget": digest._meta_budget_view(material.get("budget") or {}),
        "llm_mode": llm_mode,
        "model": model,
        "provider": provider,
        "session": session,
        "usage": usage or {},
        "llm_calls": int(llm_calls),
        "elapsed": round(float(elapsed or 0.0), 3),
        "elapsed_scope": "model" if int(llm_calls) else "none",
        "content_chars": len(markdown or ""),
    }
    _markdown_path(storage_dir, report_id).write_text(markdown or "", encoding="utf-8")
    _meta_path(storage_dir, report_id).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _normalize_reply(reply: Any) -> tuple[str, dict, str | None, str | None]:
    return digest._normalize_reply(reply)


def generate_report(
    records: Iterable[dict[str, Any]],
    range_spec: dict[str, Any],
    *,
    storage_dir: str | Path,
    planner: Optional[Callable[[str, str], Any]] = None,
    force: bool = False,
    modules: Any = None,
    reporter: str | None = None,
    report_date: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    session: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Generate (or fingerprint-cache reuse) one research weekly report.

    Returns ``{status, generated, cached, llm_calls, range, fingerprint,
    documents, sections, modules, message, report, meta, markdown}``.
    ``status`` is one of ``ok`` / ``empty`` / ``error``.
    """
    modules_norm = normalize_modules(modules)
    material = digest.assemble_material(records, range_spec)
    public = digest.public_documents(material["documents"])
    if not material["documents"]:
        return {
            "status": "empty",
            "generated": False,
            "cached": False,
            "llm_calls": 0,
            "range": range_spec,
            "fingerprint": material["fingerprint"],
            "documents": [],
            "sections": [],
            "modules": modules_norm,
            "message": EMPTY_MESSAGE,
            "report": None,
            "meta": None,
            "markdown": "",
        }

    fingerprint = compute_report_fingerprint(range_spec, material, modules_norm)
    reporter = (str(reporter).strip() or None) if reporter else None
    report_date = (str(report_date).strip() or None) if report_date else None

    if not force:
        cached = find_cached_report(storage_dir, fingerprint)
        if cached is not None:
            stored = load_report(storage_dir, cached["report_id"]) or {
                "meta": cached, "markdown": "", "sections": [],
            }
            return {
                "status": "ok",
                "generated": False,
                "cached": True,
                "llm_calls": 0,
                "range": cached.get("range") or range_spec,
                "fingerprint": fingerprint,
                "documents": public,
                "sections": stored.get("sections") or [],
                "modules": modules_norm,
                "message": "命中指纹缓存，未重新调用模型。",
                "report": cached,
                "meta": cached,
                "markdown": stored.get("markdown") or "",
            }

    requested = requested_sections(modules_norm)
    channel = digest.resolve_digest_channel()
    model = model or channel.get("model")
    provider = provider if provider is not None else channel.get("provider")
    session = session or digest.digest_session()

    prompt = build_report_prompt(
        range_spec,
        material["documents"],
        stats=material["stats"],
        modules=modules_norm,
        sections=requested,
    )

    def _live(prompt_text: str, selected_model: str) -> dict[str, Any]:
        from .notes.llm import _gateway_text_usage

        return _gateway_text_usage(
            prompt_text,
            selected_model,
            provider=channel.get("provider"),
            session=session,
            temperature=None,
            max_tokens=digest.MAX_SUMMARY_TOKENS,
        )

    call = planner or _live
    llm_calls = 0
    usage: dict[str, Any] = {}
    reply_model: str | None = None
    reply_provider: str | None = None
    llm_mode = "json"
    started = datetime.now()
    try:
        raw = call(prompt, model or "")
    except Exception as exc:  # noqa: BLE001 - surfaced as a status, never a crash
        return {
            "status": "error",
            "generated": False,
            "cached": False,
            "llm_calls": 0,
            "range": range_spec,
            "fingerprint": fingerprint,
            "documents": public,
            "sections": [],
            "modules": modules_norm,
            "message": f"模型生成失败：{exc}",
            "report": None,
            "meta": None,
            "markdown": "",
        }
    llm_calls = 1
    text, usage, reply_model, reply_provider = _normalize_reply(raw)
    if not (text or "").strip():
        return {
            "status": "error",
            "generated": False,
            "cached": False,
            "llm_calls": 1,
            "range": range_spec,
            "fingerprint": fingerprint,
            "documents": public,
            "sections": [],
            "modules": modules_norm,
            "message": "模型返回了空周报。",
            "report": None,
            "meta": None,
            "markdown": "",
        }

    allowed = [str(d["document_id"]) for d in material["documents"]]
    parsed, reply_mode = digest.parse_section_reply(
        text, allowed_ids=allowed, sections=requested
    )
    bodies: dict[str, dict[str, Any]] = {}
    modes: dict[str, str] = {}
    if reply_mode == "json":
        llm_mode = "json"
        for key, value in parsed.items():
            bodies[key] = value
            modes[key] = "model"
    else:
        # Unstructured reply: keep the prose (demoted) in 本周进展 and attribute
        # it to the material it was shown.  Never spread it over every section.
        llm_mode = "text-fallback"
        bodies[SECTION_PROGRESS] = {
            "markdown": _demote_headings(text),
            "source_document_ids": list(allowed),
        }
        modes[SECTION_PROGRESS] = "text-fallback"

    sections = build_report_sections(material, bodies, modes, modules_norm)
    markdown = render_report_markdown(
        range_spec, sections, reporter=reporter, report_date=report_date
    )
    elapsed = (datetime.now() - started).total_seconds()
    meta = save_report(
        storage_dir,
        range_spec=range_spec,
        material=material,
        markdown=markdown,
        sections=sections,
        modules=modules_norm,
        fingerprint=fingerprint,
        reporter=reporter,
        report_date=report_date,
        model=reply_model or model,
        provider=reply_provider or provider,
        session=session,
        usage=digest.normalize_usage(usage),
        elapsed=elapsed if llm_calls else 0.0,
        llm_mode=llm_mode,
        llm_calls=llm_calls,
        created_at=created_at,
    )
    return {
        "status": "ok",
        "generated": True,
        "cached": False,
        "llm_calls": llm_calls,
        "range": range_spec,
        "fingerprint": fingerprint,
        "documents": public,
        "sections": meta["sections"],
        "modules": modules_norm,
        "message": "",
        "report": meta,
        "meta": meta,
        "markdown": markdown,
    }


__all__ = [
    "TEMPLATE_ID",
    "TEMPLATE_VERSION",
    "SCHEMA_VERSION",
    "GENERATOR_VERSION",
    "PROMPT_VERSION",
    "REPORT_TITLE",
    "LEGACY_TEMPLATE_ID",
    "EMPTY_MESSAGE",
    "SECTION_OVERVIEW",
    "SECTION_PROGRESS",
    "SECTION_ISSUES",
    "SECTION_APPENDIX",
    "CORE_SECTIONS",
    "CORE_TITLES",
    "APPENDIX_TITLE",
    "EVIDENCE_LABELS",
    "MODULE_CATALOG",
    "DEFAULT_MODULES",
    "ReportError",
    "ModuleError",
    "templates_payload",
    "normalize_modules",
    "enabled_modules",
    "compute_report_fingerprint",
    "requested_sections",
    "build_report_prompt",
    "build_report_sections",
    "render_appendix_body",
    "render_report_markdown",
    "public_sections",
    "reports_dir",
    "list_reports",
    "load_report",
    "find_cached_report",
    "save_report",
    "generate_report",
]
