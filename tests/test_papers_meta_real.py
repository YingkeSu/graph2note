"""Offline regression over **real** paper metadata/references fixtures (Y4).

``tests/test_papers_meta.py`` drives P2 with hand-written front-page fixtures.
This module replays the *same* code over four real born-digital papers (see
``tests/fixtures/papers/real/`` and its ``README.md``) and asserts

- the per-paper metadata snapshot (``expected.json`` -> ``p2.meta``) and notes;
- the recorded ``field_status``/``known_failures`` (real layouts degrade in
  specific, documented ways — e.g. a two-column byline melts into the title);
- the reference section location, entry count and the conservative-merge
  provenance that explains the under-splitting;
- the whole parse is offline (no socket) and deterministic.

Nothing here consults the network or a model; the fixtures are frozen text.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from graph2note.papers import metadata, references

REAL = Path(__file__).parent / "fixtures" / "papers" / "real"

KEYS = sorted(
    path.name for path in REAL.iterdir()
    if path.is_dir() and (path / "expected.json").is_file()
)

FAILURE_TAGS = {
    "title-absorbs-byline",
    "title-absorbs-byline-and-abstract",
    "authors-are-affiliations",
    "authors-are-abstract-fragments",
    "authors-absorb-affiliation",
    "abstract-lost-when-label-swallowed-by-title",
    "doi-from-references",
    "venue-not-found",
    "keywords-not-found",
    "year-is-arxiv-v1",
}


def _expected(key: str) -> dict:
    return json.loads((REAL / key / "expected.json").read_text(encoding="utf-8"))


def _front(key: str) -> str:
    return (REAL / key / "front.txt").read_text(encoding="utf-8")


def _references_text(key: str) -> str:
    return (REAL / key / "references.txt").read_text(encoding="utf-8")


def _full_text(key: str) -> str:
    """Rebuild the whole-document text from the frozen line export.

    Mirrors ``TextLayer.fulltext`` (pages in source order, joined by a blank
    line) so the P2 tests never need the original PDF.
    """
    pages: dict[int, list[str]] = {}
    for raw in (REAL / key / "lines.jsonl").read_text(encoding="utf-8").split("\n"):
        if not raw.strip():
            continue
        entry = json.loads(raw)
        pages.setdefault(entry["p"], []).append(entry["t"])
    return "\n\n".join(
        "\n".join(pages[index]) for index in sorted(pages)
        if "\n".join(pages[index]).strip()
    ).strip()


def _meta(key: str):
    return metadata.parse_paper_meta(
        _front(key), full_text=_full_text(key), source="text-layer"
    )


# ---------------------------------------------------------------------------
# metadata snapshot + documented degradation (AC2, AC3, AC5)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_real_meta_snapshot_matches_fixture(key):
    expected = _expected(key)["p2"]["meta"]
    assert _meta(key).meta.model_dump() == expected


@pytest.mark.parametrize("key", KEYS)
def test_real_meta_notes_and_provenance_match_fixture(key):
    expected = _expected(key)["p2"]
    result = _meta(key)
    assert result.notes == expected["notes"]
    confidence = {field: prov.confidence for field, prov in result.provenance.items()}
    assert confidence == expected["provenance_confidence"]
    assert set(result.provenance) == {
        "title", "authors", "year", "venue", "doi", "abstract", "keywords", "source",
    }


@pytest.mark.parametrize("key", KEYS)
def test_real_meta_degradation_is_explicitly_documented(key):
    p2 = _expected(key)["p2"]
    meta = _meta(key).meta

    # Every paper records at least one real-layout failure with a pointer shape.
    assert p2["known_failures"], key
    for failure in p2["known_failures"]:
        assert set(failure) == {"field", "tag", "detail"}
        assert failure["tag"] in FAILURE_TAGS, failure["tag"]
        assert failure["detail"].strip()
        assert p2["field_status"][failure["field"]] != "ok"

    # "missing" means the field really is empty/None — the parser never invents.
    for field, status in p2["field_status"].items():
        if status != "missing":
            continue
        value = getattr(meta, field)
        assert value in ("", [], None), (key, field, value)

    # "ok" fields are non-empty and self-consistent.
    if p2["field_status"]["title"] == "ok":
        assert meta.title and meta.title == _expected(key)["source"]["title"]
    if p2["field_status"]["year"] == "ok":
        assert isinstance(meta.year, int)


@pytest.mark.parametrize("key", KEYS)
def test_real_meta_is_pure_and_replayable(key):
    first = _meta(key)
    second = _meta(key)
    assert first.model_dump() == second.model_dump()


def test_two_column_byline_absorption_drops_the_real_abstract():
    """Y4 finding on the post-Y5 baseline: the two-column reflow feeds
    ``'Abstract'`` into ``title_keys`` (the title block swallowed the byline and
    the label), and ``_extract_abstract`` skips ``title_keys`` lines, so the
    real summary is lost (``abstract-not-found``).  If a later fix recovers it,
    this test turns red and the ``bert`` fixture must be recalibrated.
    """
    result = _meta("bert")
    assert result.meta.title.startswith("BERT: Pre-training of Deep Bidirectional")
    assert "Google AI Language" in result.meta.title  # byline inside the title block
    assert result.meta.abstract == ""
    assert "abstract-not-found" in result.notes
    assert result.provenance["abstract"].confidence == "low"


# ---------------------------------------------------------------------------
# reference section location + conservative splitting (AC3, AC5)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_real_references_heading_is_located(key):
    expected = _expected(key)["p2"]["references"]
    section = references.locate_references_section(_full_text(key))
    assert section is not None
    assert section.heading == expected["heading"]


@pytest.mark.parametrize("key", KEYS)
def test_real_reference_snapshot_matches_fixture(key):
    expected = _expected(key)["p2"]["references"]
    parsed = references.parse_references(_references_text(key))
    assert len(parsed.references) == expected["count"]
    assert parsed.references[0].raw.startswith(expected["first_raw_startswith"])
    assert all(p.style == expected["style"] for p in parsed.provenance)


@pytest.mark.parametrize("key", KEYS)
def test_real_reference_failures_are_conservative_and_traceable(key):
    """Under-splitting must be an explainable merge, not a silent fabrication."""
    expected = _expected(key)["p2"]["references"]
    section = _references_text(key)
    parsed = references.parse_references(section)

    # one provenance record per entry; raw text is always present
    assert len(parsed.provenance) == len(parsed.references)
    assert all(entry.raw.strip() for entry in parsed.references)

    # a missing year / author list is flagged, never guessed
    for entry, prov in zip(parsed.entries, parsed.provenance):
        if entry.year is None:
            assert "year-not-found" in prov.notes, prov
        if not entry.authors:
            assert "authors-unparsed" in prov.notes, prov

    # the recorded under-split is a conservative merge with provenance
    if expected["under_split"]:
        assert max(p.fragments for p in parsed.provenance) == expected["max_fragments"]
        assert expected["max_fragments"] > 1
        assert "merged-continuation" in {n for p in parsed.provenance for n in p.notes}
    assert set(expected["provenance_notes"]) <= {
        n for p in parsed.provenance for n in p.notes
    }

    # the split conserves the section text (no entry was silently dropped)
    def _squash(text: str) -> str:
        return re.sub(r"[\s\-]+", "", text)

    covered = _squash(" ".join(entry.raw for entry in parsed.references))
    body = _squash(section)
    assert len(covered) >= int(0.9 * len(body)), (key, len(covered), len(body))


@pytest.mark.parametrize("key", KEYS)
def test_real_parse_paper_text_wires_meta_and_references(key):
    document = references.parse_paper_text({
        "full_text": _full_text(key),
        "front_text": _front(key),
    })
    expected = _expected(key)["p2"]
    assert document.meta.model_dump() == expected["meta"]
    assert len(document.references) == expected["references"]["count"]
    assert any(note.startswith("references-section:References") for note in document.notes)


# ---------------------------------------------------------------------------
# AC5: the fixture documents how real layouts differ from the synthetic ones
# ---------------------------------------------------------------------------

def test_real_fixtures_record_differences_from_synthetic():
    for key in KEYS:
        differences = _expected(key)["differences_from_synthetic"]
        assert len(differences) >= 2, key
        assert all(isinstance(item, str) and item.strip() for item in differences)


# ---------------------------------------------------------------------------
# AC4: offline (no socket) — the real fixtures need no network
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("key", KEYS)
def test_real_p2_fixtures_are_offline(key, monkeypatch):
    import socket

    def _no_network(*_args, **_kwargs):
        raise AssertionError("P2 real fixtures must not touch the network")

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(socket, "create_connection", _no_network)
    assert _meta(key).meta.source == "text-layer"
    assert references.parse_references(_references_text(key)).references
