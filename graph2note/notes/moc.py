"""MOC (Map of Content) index-note generation — deterministic.

For a validated :class:`ClassificationScheme`, one MOC index note is produced
per topic listing every note in that topic with its one-line summary.  MOC
links are **relative markdown links** to the document notes
(``../notes/<safe_id>/note.md``), which the exporter's link validator resolves
against the vault — matching how the note bodies and source-image embeds already
reference their targets.  Same input -> same MOC bytes (deterministic).
"""

from __future__ import annotations

from typing import Iterable

from .classify import ClassificationScheme
from .exporter import ExportEntry


def build_moc(
    topic: str,
    scheme: ClassificationScheme,
    entries_by_id: dict[str, ExportEntry],
) -> str:
    """Render one MOC index note for ``topic`` as a markdown string."""
    docs = [d for d in scheme.assignments.get(topic, []) if d in entries_by_id]
    lines = [
        "---",
        f'title: "{topic}（MOC）"',
        "type: moc",
        "topics:",
        f"  - {topic}",
        "---",
        "",
        f"# {topic}",
        "",
        f"收录 {len(docs)} 篇笔记：",
        "",
    ]
    for d in sorted(docs):
        e = entries_by_id[d]
        summary = (scheme.summaries.get(d) or "").strip()
        # relative markdown link (Obsidian-compatible; resolved by the exporter's
        # link validator against the vault tree — see module docstring).
        lines.append(f"- [{e.title or d}](../notes/{e.safe_id}/note.md) — {summary}")
    lines.append("")
    return "\n".join(lines)


def build_mocs(
    scheme: ClassificationScheme,
    entries: Iterable[ExportEntry],
) -> dict[str, str]:
    """Return ``{topic: moc_markdown}`` for every topic in the scheme."""
    by_id = {e.document_id: e for e in entries}
    out: dict[str, str] = {}
    for topic in scheme.topics:
        out[topic] = build_moc(topic, scheme, by_id)
    return out