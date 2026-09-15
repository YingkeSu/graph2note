#!/usr/bin/env python3
"""Regenerate the raw real-paper fixtures (Y4).

This script only rebuilds ``front.txt`` / ``lines.jsonl`` / ``references.txt``
from a born-digital PDF.  ``expected.json`` is *curated by hand* from the
observed output (which fields are correct, which are known failures) — never
auto-overwritten here, because the point of Y4 is to record the current real
behaviour on purpose.

Usage (run from the repository root)::

    python tests/fixtures/papers/real/_generate.py <key> <path/to/paper.pdf>

The PDF is read-only input; nothing is copied into the repository other than
the extracted text fixtures.  See ``README.md`` for the provenance/license of
the four committed samples.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pymupdf

REAL = Path(__file__).resolve().parent

# Tests read a fixture line per JSON object; ``ensure_ascii=False`` keeps the
# text readable, so readers must split on "\n" only (json.dumps escapes real
# newlines, but Unicode line separators like U+2028 survive literally).
sys.path.insert(0, str(REAL.parents[3]))
from graph2note.papers import references, textlayer  # noqa: E402


def full_text_from_lines(lines) -> str:
    pages: dict[int, list[str]] = {}
    for line in lines:
        pages.setdefault(line.page_index, []).append(line.text)
    return "\n\n".join(
        "\n".join(pages[index]) for index in sorted(pages)
        if "\n".join(pages[index]).strip()
    ).strip()


def generate(key: str, pdf_path: str) -> None:
    doc = pymupdf.open(pdf_path)
    try:
        layer = textlayer.extract_text_layer(doc)
        lines = layer.lines
        front = layer.pages[0].text if layer.pages else ""
        section = references.locate_references_section(full_text_from_lines(lines))
        refs_text = section.text if section else ""
    finally:
        doc.close()

    target = REAL / key
    target.mkdir(parents=True, exist_ok=True)
    (target / "front.txt").write_text(front, encoding="utf-8")
    (target / "references.txt").write_text(refs_text, encoding="utf-8")
    with (target / "lines.jsonl").open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(
                {"p": line.page_index, "s": line.size, "b": line.bold, "t": line.text},
                ensure_ascii=False,
            ) + "\n")
    print(f"wrote {target}/front.txt lines.jsonl references.txt")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    generate(sys.argv[1], sys.argv[2])
