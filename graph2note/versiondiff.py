"""Version comparison payload (issue S3) — the read-only backend for the UI.

Consumes two already-shipped contracts and adds **no new diff logic**:

* S1 — :func:`graph2note.semantic.diff_ir` produces the block-level
  :class:`~graph2note.semantic.DiffReport` (``added/removed/modified/moved``
  with :class:`~graph2note.semantic.BlockRef` locations).
* S2 — :func:`graph2note.evolution.build_version_chain` supplies the version
  timeline (source + labels) and :func:`graph2note.evolution.classify_version_source`
  the provenance vocabulary.

What this module adds for the compare view:

* per-version content at **block granularity** (each IR block rendered to its
  own Markdown snippet with S1's deterministic ``block-{index}`` anchor) so the
  UI can highlight and jump without re-inventing a text diff;
* a **templated** natural-language summary (``summarize_diff``) built purely
  from the :class:`~graph2note.semantic.DiffSummary` numbers — string
  concatenation, **zero model calls**, zero network;
* safe payloads for the single-version / empty-diff cases.

Nothing here calls a model: per-block Markdown uses the deterministic
:func:`graph2note.render.render_markdown`, and the working-copy edit head (a
live Markdown that was never committed as a version) is projected to IR with
the existing deterministic ``vlm._markdown_to_ir`` helper — the same path S2
uses (no model involved).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import evolution
from .ir import DocumentIR, IRValidationError, load_dict_as_ir, loads_ir
from .render import render_markdown
from .semantic import DiffSummary, diff_ir
from .semantic.cli import load_version_ir
from .semantic.text import preview as block_preview

# The S2 version-chain contract names the uncommitted edit head ``working-copy``
# (see handoff §5).  Re-declared here (not imported from a private name) because
# it is a public JSON value, not an implementation detail.
EDIT_VERSION_ID = "working-copy"

# Canonical label vocabulary for the UI and the templated summary.
BLOCK_TYPE_LABELS: dict[str, str] = {
    "heading": "标题",
    "paragraph": "段落",
    "list": "列表",
    "formula": "公式",
    "table": "表格",
    "code": "代码",
    "quote": "引用",
    "image": "图片",
    "diagram": "图表",
    "flow": "流程图",
}

OP_LABELS: dict[str, str] = {
    "added": "新增",
    "removed": "删除",
    "modified": "修改",
    "moved": "移动",
    "unchanged": "未变",
}

VERDICT_LABELS: dict[str, str] = {
    "unchanged": "无改动",
    "minor": "小幅改动",
    "major": "较大改动",
}

# Deterministic display order for block types in the summary (unknown types are
# appended sorted after these, so the output is total and stable).
_TYPE_ORDER: tuple[str, ...] = (
    "heading", "paragraph", "list", "formula", "table", "code", "quote",
    "image", "diagram", "flow",
)
_CHANGED_OPS: tuple[str, ...] = ("modified", "added", "removed", "moved")


class VersionDiffError(ValueError):
    """A comparison could not be built (unknown version / unreadable IR)."""


def block_type_label(block_type: str) -> str:
    return BLOCK_TYPE_LABELS.get(block_type, block_type or "块")


def op_label(op: str) -> str:
    return OP_LABELS.get(op, op)


def _ordered_types(by_type: dict[str, Any]) -> list[str]:
    known = [t for t in _TYPE_ORDER if t in by_type]
    extra = sorted(t for t in by_type if t not in _TYPE_ORDER)
    return known + extra


def summarize_diff(summary: DiffSummary | dict[str, Any]) -> list[str]:
    """Template a human summary straight from the DiffSummary numbers.

    Pure string concatenation over ``by_op`` / ``by_type`` — no model call, no
    IO.  Every number in the output is the exact value from the S1 report, so
    the UI can never disagree with the diff engine.
    """
    data = summary.model_dump() if hasattr(summary, "model_dump") else dict(summary or {})
    by_type = data.get("by_type") or {}
    changed = int(data.get("changed_blocks") or 0)
    total = int(data.get("total_blocks") or 0)
    if changed == 0:
        return ["两版内容一致，无块级变更。"]

    density = float(data.get("change_density") or 0.0)
    verdict = str(data.get("verdict") or "minor")
    lines = [
        f"整体判定：{VERDICT_LABELS.get(verdict, verdict)}"
        f"（变更 {changed}/{total} 块，密度 {density:.2f}）"
    ]
    for op in _CHANGED_OPS:
        parts = []
        for block_type in _ordered_types(by_type):
            counts = by_type.get(block_type) or {}
            count = int(counts.get(op, 0) or 0)
            if count:
                parts.append(f"{count} 个{block_type_label(block_type)}")
        if parts:
            lines.append(f"{op_label(op)}：" + "、".join(parts))
    return lines


# ---------------------------------------------------------------------------
# Version content (IR + per-block Markdown)
# ---------------------------------------------------------------------------


def _markdown_ir(markdown: str) -> Optional[DocumentIR]:
    """Deterministic Markdown -> IR for the uncommitted edit head (no model)."""
    if not markdown or not markdown.strip():
        return None
    try:
        from .vlm import _markdown_to_ir

        return load_dict_as_ir(_markdown_to_ir(markdown))
    except Exception:  # a projection failure must never break the whole view
        return None


def _version_ir(store, document_id: str, meta: dict) -> Optional[DocumentIR]:
    """Version IR from the in-memory record, else from the version dir file."""
    raw = meta.get("ir_json")
    if raw:
        try:
            return loads_ir(raw) if isinstance(raw, str) else load_dict_as_ir(raw)
        except (IRValidationError, ValueError, TypeError):
            pass
    try:
        return load_version_ir(store, document_id, str(meta["version_id"]))
    except (OSError, IRValidationError, KeyError, TypeError):
        return None


def _version_dir(store, document_id: str, version_id: str) -> Optional[Path]:
    root = getattr(store, "root", None)
    if root is None:
        return None
    return Path(root) / "documents" / document_id / "versions" / str(version_id)


def _version_markdown(store, document_id: str, meta: dict, version_id: str) -> str:
    """Version Markdown from either the in-memory record or the version dir."""
    inline = meta.get("markdown")
    if inline:
        return inline
    vdir = _version_dir(store, document_id, version_id)
    if vdir is not None:
        path = vdir / "markdown.md"
        if path.is_file():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                pass
    return ""


def version_preprocessed_path(store, document_id: str, version_id: str) -> Optional[str]:
    """Filesystem path of a version's ``preprocessed.png`` (or None)."""
    meta = evolution.versions_for_document(store, document_id)
    for entry in meta:
        if str(entry.get("version_id")) == str(version_id):
            inline = entry.get("preprocessed_path")
            if inline and Path(inline).is_file():
                return str(inline)
            break
    vdir = _version_dir(store, document_id, version_id)
    if vdir is not None:
        path = vdir / "preprocessed.png"
        if path.is_file():
            return str(path)
    return None


def _render_block(ir: DocumentIR, block) -> str:
    """Render one IR block to a standalone Markdown snippet (deterministic)."""
    single = DocumentIR(document_type=ir.document_type, blocks=[block])
    return render_markdown(single).strip()


def _blocks_payload(ir: Optional[DocumentIR]) -> list[dict[str, Any]]:
    if ir is None:
        return []
    return [
        {
            "index": index,
            "type": block.type,
            "type_label": block_type_label(block.type),
            "anchor": f"block-{index}",
            "markdown": _render_block(ir, block),
            "preview": block_preview(block),
        }
        for index, block in enumerate(ir.blocks)
    ]


def _entry_map(chain: dict[str, Any]) -> dict[str, dict]:
    return {
        str(entry["version_id"]): entry
        for entry in chain.get("versions") or []
        if entry.get("version_id")
    }


def record_version(record: dict, version_id: str) -> Optional[dict]:
    for version in record.get("versions") or []:
        if isinstance(version, dict) and str(version.get("version_id")) == str(version_id):
            return version
    return None


def resolve_selector(chain: dict[str, Any], selector: Optional[str]) -> Optional[str]:
    """Resolve ``latest`` / ``prev`` / a version id / a 0-based index.

    Returns ``None`` when the selector is unknown.  An empty selector means the
    newest entry (matching the UI default).
    """
    entries = [entry for entry in chain.get("versions") or [] if entry.get("version_id")]
    if not entries:
        return None
    if selector in (None, "", "latest"):
        return str(entries[-1]["version_id"])
    if selector in ("prev", "previous"):
        return str(entries[-2]["version_id"]) if len(entries) >= 2 else str(entries[0]["version_id"])
    selector = str(selector)
    for entry in entries:
        if str(entry["version_id"]) == selector:
            return str(entry["version_id"])
    if selector.isdigit():
        index = int(selector)
        if 0 <= index < len(entries):
            return str(entries[index]["version_id"])
    return None


def _version_content(store, document_id: str, record: dict, chain: dict,
                     version_id: str) -> Optional[dict[str, Any]]:
    entries = _entry_map(chain)
    entry = entries.get(version_id)
    latest_version_id = chain.get("latest_version_id")

    if version_id == EDIT_VERSION_ID or (entry is not None and entry.get("is_edit")):
        markdown = record.get("current_markdown") or ""
        ir = _markdown_ir(markdown)
        return {
            "version_id": EDIT_VERSION_ID,
            "index": entry.get("index") if entry else None,
            "created_at": record.get("updated_at"),
            "model": None,
            "source": evolution.PROVENANCE_EDIT,
            "source_label": evolution.SOURCE_LABELS.get(evolution.PROVENANCE_EDIT, "编辑保存"),
            "is_edit": True,
            "is_history": False,
            "is_current": True,
            "markdown": markdown,
            "ir": ir,
            "blocks": _blocks_payload(ir),
            "block_count": len(ir.blocks) if ir is not None else 0,
            "preprocessed_version_id": latest_version_id,
        }

    raw = record_version(record, version_id)
    if entry is None and raw is None:
        return None
    meta = raw or {}
    ir = _version_ir(store, document_id, meta) if meta else None
    markdown = _version_markdown(store, document_id, meta, version_id)
    source = (entry or {}).get("source") or evolution.classify_version_source(meta, index=0)
    is_history = bool(latest_version_id) and str(version_id) != str(latest_version_id)
    return {
        "version_id": str(version_id),
        "index": (entry or {}).get("index", meta.get("index")),
        "created_at": (entry or {}).get("created_at") or meta.get("created_at"),
        "model": (entry or {}).get("model") or meta.get("model"),
        "source": source,
        "source_label": (entry or {}).get("source_label")
        or evolution.SOURCE_LABELS.get(source, source),
        "is_edit": False,
        "is_history": is_history,
        "is_current": not is_history,
        "markdown": markdown or "",
        "ir": ir,
        "blocks": _blocks_payload(ir),
        "block_count": len(ir.blocks) if ir is not None else 0,
        "preprocessed_version_id": version_id,
    }


def _public_version(content: dict[str, Any]) -> dict[str, Any]:
    """Drop the private IR object before serializing."""
    return {key: value for key, value in content.items() if key != "ir"}


def build_compare(
    store,
    document_id: str,
    *,
    version_a: Optional[str] = None,
    version_b: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Read-only comparison payload for two versions of one document.

    Returns ``None`` for an unknown document.  Raises :class:`VersionDiffError`
    when a selector cannot be resolved or a version's IR is unreadable.
    """
    record = store.get_document(document_id)
    if record is None:
        return None
    chain = evolution.build_version_chain(store, document_id) or {}
    entries = chain.get("versions") or []

    if not entries:
        return {
            "document_id": document_id,
            "title": record.get("title"),
            "latest_version_id": None,
            "count": 0,
            "single_version": True,
            "empty": True,
            "same_version": True,
            "a": None,
            "b": None,
            "report": None,
            "summary_lines": ["暂无版本记录，无法对比。"],
        }

    # Default: newest vs the one before it (issue default "最新 vs 前一版").
    resolved_a = resolve_selector(chain, version_a if version_a is not None else "prev")
    resolved_b = resolve_selector(chain, version_b if version_b is not None else "latest")
    if resolved_a is None or resolved_b is None:
        raise VersionDiffError(
            f"未知版本：a={version_a!r} b={version_b!r}（可用 id 或 0-based 序号）"
        )

    content_a = _version_content(store, document_id, record, chain, resolved_a)
    content_b = _version_content(store, document_id, record, chain, resolved_b)
    if content_a is None or content_b is None:
        raise VersionDiffError(f"版本不存在或缺少内容：a={resolved_a!r} b={resolved_b!r}")
    ir_a, ir_b = content_a.get("ir"), content_b.get("ir")
    if ir_a is None or ir_b is None:
        raise VersionDiffError(
            f"版本缺少可用的 IR，无法比较：a={resolved_a!r} b={resolved_b!r}"
        )

    report = diff_ir(ir_a, ir_b, label_a=resolved_a, label_b=resolved_b)
    payload = {
        "document_id": document_id,
        "title": record.get("title"),
        "latest_version_id": chain.get("latest_version_id"),
        "count": len(entries),
        "single_version": len(entries) <= 1,
        "empty": report.summary.changed_blocks == 0,
        "same_version": resolved_a == resolved_b,
        "a": _public_version(content_a),
        "b": _public_version(content_b),
        "report": report.model_dump(),
        "summary_lines": summarize_diff(report.summary),
    }
    return payload


__all__ = [
    "EDIT_VERSION_ID",
    "BLOCK_TYPE_LABELS",
    "OP_LABELS",
    "VERDICT_LABELS",
    "VersionDiffError",
    "block_type_label",
    "op_label",
    "summarize_diff",
    "resolve_selector",
    "record_version",
    "version_preprocessed_path",
    "build_compare",
]
