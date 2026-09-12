"""CLI entry for the IR block-level diff (issue S1).

``graph2note diff <doc_id> [--versions A B] [--storage DIR] [--json] [--list]``

The command is *read-only*: it reads the already-persisted ``ir.json`` of two
versions from the document library and prints the :class:`DiffReport`.  It
never re-parses, never calls a model, and never writes to the store.  Until S3
ships a comparison UI this CLI is the main consumption surface for human
acceptance.

Version selectors accepted by ``--versions`` (and resolvable individually):

* a full ``version_id`` (e.g. ``v1789151088677-2``),
* a unique ``version_id`` prefix (e.g. ``v178915``),
* a 0-based integer index into the time-ordered version list,
* the aliases ``latest`` and ``prev``.

With ``--versions`` omitted the diff is ``latest`` vs ``prev``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..ir import IRValidationError, DocumentIR, loads_ir
from .diff import DiffReport, diff_ir

# The engine is pure; IO lives only here so the diff core stays snapshot-testable.


class VersionResolutionError(ValueError):
    """Raised when a ``--versions`` selector does not resolve to one version."""


def build_diff_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="graph2note diff",
        description=(
            "Diff two versions of a document at Document-IR block level "
            "(pure, offline, deterministic).  Read-only."
        ),
    )
    p.add_argument("doc_id", help="document id (see `graph2note diff --list`)")
    p.add_argument(
        "--versions",
        nargs=2,
        metavar=("A", "B"),
        default=None,
        help=(
            "two version selectors: full id, unique id prefix, 0-based index, "
            "or 'latest'/'prev' (default: latest vs prev)"
        ),
    )
    p.add_argument(
        "--storage",
        default=None,
        help="document library storage dir (default: GRAPH2NOTE_STORAGE or "
        "<support>/storage)",
    )
    p.add_argument(
        "--all",
        action="store_true",
        help="include unchanged blocks in the human-readable listing",
    )
    p.add_argument("--json", action="store_true", help="emit the DiffReport as JSON")
    p.add_argument(
        "--list",
        action="store_true",
        dest="list_versions",
        help="list the document's versions and exit",
    )
    return p


# ---------------------------------------------------------------------------
# Version resolution / IO (the only IO in the semantic package)
# ---------------------------------------------------------------------------


def resolve_version(spec: str, version_ids: list[str]) -> str:
    """Resolve one selector to a concrete ``version_id`` (see module doc)."""
    if not version_ids:
        raise VersionResolutionError("document has no versions")
    if spec == "latest":
        return version_ids[-1]
    if spec in ("prev", "previous"):
        if len(version_ids) < 2:
            raise VersionResolutionError(
                "'prev' needs at least two versions"
            )
        return version_ids[-2]
    if spec in version_ids:
        return spec
    matches = [vid for vid in version_ids if vid.startswith(spec)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise VersionResolutionError(
            f"ambiguous version prefix {spec!r}: {', '.join(matches)}"
        )
    if spec.isdigit():
        index = int(spec)
        if 0 <= index < len(version_ids):
            return version_ids[index]
        raise VersionResolutionError(
            f"version index {index} out of range (0..{len(version_ids) - 1})"
        )
    raise VersionResolutionError(f"unknown version selector {spec!r}")


def version_ir_path(store, document_id: str, version_id: str) -> Path | None:
    """Path of a version's persisted ``ir.json`` (no read, no validation).

    The version directory layout is documented in :mod:`graph2note.store`
    (``<root>/documents/<doc_id>/versions/<version_id>/ir.json``).  Kept here,
    rather than as a new ``store`` method, so the semantic track does not edit
    shared store code.
    """
    root = getattr(store, "root", None)
    if root is None:
        return None
    safe_id = version_id.replace("/", "-")
    return Path(root) / "documents" / document_id / "versions" / safe_id / "ir.json"


def load_version_ir(store, document_id: str, version_id: str) -> DocumentIR:
    """Load and validate one version's ``ir.json`` (read-only)."""
    path = version_ir_path(store, document_id, version_id)
    if path is None or not path.is_file():
        raise FileNotFoundError(
            f"IR not found for {document_id} / {version_id} (looked at {path})"
        )
    return loads_ir(path.read_bytes())


def _version_meta(versions: list[dict], version_id: str) -> dict:
    for version in versions:
        if version.get("version_id") == version_id:
            return version
    return {}


# ---------------------------------------------------------------------------
# Human-readable rendering
# ---------------------------------------------------------------------------


def format_version_list(versions: list[dict]) -> str:
    lines = []
    for index, version in enumerate(versions):
        marker = "current" if version.get("current") else "history"
        lines.append(
            f"{index}: {version.get('version_id')}  "
            f"created={version.get('created_at') or '-'}  "
            f"model={version.get('model') or '-'}  [{marker}]"
        )
    return "\n".join(lines)


def _ref_label(ref) -> str:
    return "—" if ref is None else f"#{ref.index}"


def _change_line(change) -> list[str]:
    line = (
        f"  [{change.op}] {change.block_type}  "
        f"{_ref_label(change.block_ref_a)} -> {_ref_label(change.block_ref_b)}"
    )
    if change.similarity is not None:
        line += f"  sim={change.similarity}"
    lines = [line]
    if change.block_ref_a is not None and change.block_ref_a.preview:
        lines.append(f"      A: {change.block_ref_a.preview}")
    if change.block_ref_b is not None and change.block_ref_b.preview:
        lines.append(f"      B: {change.block_ref_b.preview}")
    return lines


def format_report(
    report: DiffReport,
    *,
    doc_id: str,
    title: str = "",
    versions: list[dict] | None = None,
    include_unchanged: bool = False,
) -> str:
    versions = versions or []
    summary = report.summary
    meta_a = _version_meta(versions, report.label_a or "")
    meta_b = _version_meta(versions, report.label_b or "")

    lines = [f"doc: {doc_id}" + (f'  "{title}"' if title else "")]
    lines.append(
        f"A: {report.label_a or '-'}  created={meta_a.get('created_at') or '-'}  "
        f"blocks={summary.blocks_a}"
    )
    lines.append(
        f"B: {report.label_b or '-'}  created={meta_b.get('created_at') or '-'}  "
        f"blocks={summary.blocks_b}"
    )
    lines.append(
        f"verdict: {summary.verdict}   changed={summary.changed_blocks}/"
        f"{summary.total_blocks}   density={summary.change_density:.4f}"
    )
    lines.append(
        "by op: "
        + " ".join(f"{op}={summary.by_op.get(op, 0)}" for op in (
            "added", "removed", "modified", "moved", "unchanged"))
    )

    interesting = {
        block_type: counts
        for block_type, counts in summary.by_type.items()
        if counts.added or counts.removed or counts.modified or counts.moved
    }
    if interesting:
        lines.append("by type:")
        for block_type in sorted(interesting):
            counts = interesting[block_type]
            parts = [
                f"{op}={getattr(counts, op)}"
                for op in ("added", "removed", "modified", "moved")
                if getattr(counts, op)
            ]
            lines.append(f"  {block_type:<12} {' '.join(parts)}")

    shown = [
        change
        for change in report.changes
        if include_unchanged or change.op != "unchanged"
    ]
    if shown:
        lines.append("changes:")
        for change in shown:
            lines.extend(_change_line(change))
    else:
        lines.append("changes: (none)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def cmd_diff(args) -> int:
    from .. import config
    from ..store import FileDocumentStore

    try:
        storage = config.ensure_storage_dir(config.resolve_storage_dir(args.storage))
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    store = FileDocumentStore(str(storage))
    record = store.get_document(args.doc_id)
    if record is None:
        print(f"error: document not found: {args.doc_id}", file=sys.stderr)
        return 2

    versions = record.get("versions") or []
    version_ids = [v.get("version_id") for v in versions if v.get("version_id")]

    if args.list_versions:
        print(format_version_list(versions))
        return 0

    if not version_ids:
        print(f"error: document has no versions: {args.doc_id}", file=sys.stderr)
        return 1

    if args.versions:
        spec_a, spec_b = args.versions
    else:
        if len(version_ids) < 2:
            print(
                f"error: document has {len(version_ids)} version(s); "
                "need two to diff",
                file=sys.stderr,
            )
            return 1
        spec_a, spec_b = "prev", "latest"

    try:
        version_a = resolve_version(spec_a, version_ids)
        version_b = resolve_version(spec_b, version_ids)
    except VersionResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        ir_a = load_version_ir(store, args.doc_id, version_a)
        ir_b = load_version_ir(store, args.doc_id, version_b)
    except (OSError, IRValidationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    report = diff_ir(ir_a, ir_b, label_a=version_a, label_b=version_b)

    if args.json:
        print(json.dumps(report.model_dump(), ensure_ascii=False, indent=2))
    else:
        print(
            format_report(
                report,
                doc_id=args.doc_id,
                title=record.get("title") or "",
                versions=versions,
                include_unchanged=args.all,
            )
        )
    return 0


__all__ = [
    "build_diff_parser",
    "cmd_diff",
    "resolve_version",
    "format_report",
    "format_version_list",
    "version_ir_path",
    "load_version_ir",
    "VersionResolutionError",
]
