"""Offline unit contracts for paper metadata & references (SPW I 轨 P2).

Everything here is fixture/golden-driven and deterministic: no network, no LLM
(an injected stub planner stands in for the optional enhancement seam).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from graph2note.papers import citegraph, enhance, metadata, references

FIXTURES = Path(__file__).parent / "fixtures" / "papers"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# PaperMeta — three typical front-page layouts
# ---------------------------------------------------------------------------

def test_single_column_journal_front_page():
    result = metadata.parse_paper_meta(_fixture("front_single_column.txt"))
    meta = result.meta
    assert meta.title == "Graph Neural Networks for Document Understanding: A Comprehensive Survey"
    assert meta.authors == ["Wei Zhang", "Li Chen", "Ming Li"]
    assert meta.year == 2023
    assert meta.venue == "IEEE Transactions on Knowledge and Data Engineering"
    assert meta.doi == "10.1109/tkde.2023.1234567"
    assert meta.abstract.startswith("Document understanding has attracted")
    assert meta.keywords == ["graph neural networks", "document understanding", "survey"]
    assert meta.source == "text-layer"
    assert result.provenance["doi"].confidence == "high"


def test_two_column_conference_front_page():
    result = metadata.parse_paper_meta(_fixture("front_two_column.txt"))
    meta = result.meta
    assert meta.title == "Robust Feature Matching under Extreme Viewpoint Changes"
    assert meta.authors == ["Jian Sun", "Alex Kim", "Priya Nair"]
    assert meta.year == 2022
    assert meta.venue.endswith("(CVPR)")
    assert meta.abstract.startswith("We present a robust method")
    assert meta.keywords == ["feature matching", "viewpoint robustness", "geometric verification"]


def test_arxiv_preprint_front_page():
    result = metadata.parse_paper_meta(_fixture("front_arxiv.txt"))
    meta = result.meta
    assert meta.title == "Attention Is Still All You Need: A Revisiting Study"
    assert meta.authors == ["Emily R. Johnson", "Kenji Tanaka", "Sofia Alvarez"]
    assert meta.year == 2024
    assert meta.venue == "arXiv"
    assert meta.keywords == ["attention", "transformer", "sequence modeling"]


def test_title_containing_a_venue_word_is_not_dropped_as_a_header():
    text = (
        "Deep Learning for Journal Recommendation\n"
        "Wei Zhang, Li Chen\n\n"
        "Abstract\nWe study recommendation.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.title == "Deep Learning for Journal Recommendation"
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]


# ---------------------------------------------------------------------------
# Reflowed text-layer front page: abstract glued to the author block (Y5)
# ---------------------------------------------------------------------------

def test_reflowed_author_block_keeps_the_abstract_out_of_authors():
    """P3-r2 live regression: the text layer merges byline + ``Abstract`` head."""

    # Same layout as the synthetic born-digital PDF of the P3-r2 live run: the
    # heading, byline and ``Abstract`` label share one paragraph because the
    # text-layer extraction inserts no blank line between them.
    text = (
        "Graph Neural Networks for Document Understanding:\n"
        "A Comprehensive Survey\n"
        "Wei Zhang, Li Chen, and Ming Li\n"
        "Abstract\n"
        "Document understanding has attracted attention in recent years. "
        "We review graph neural network methods for document understanding.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Wei Zhang", "Li Chen", "Ming Li"]
    assert result.meta.abstract.startswith("Document understanding has attracted")
    assert result.meta.title == (
        "Graph Neural Networks for Document Understanding: A Comprehensive Survey"
    )


def test_inline_abstract_label_glued_to_a_byline_is_not_an_author():
    text = (
        "Robust Feature Matching under Extreme Viewpoint Changes\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "Abstract—We present a robust method for feature matching, which combines "
        "geometric verification with learned descriptors.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.title == "Robust Feature Matching under Extreme Viewpoint Changes"
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]
    assert result.meta.abstract.startswith("We present a robust method")


def test_sentence_like_reflowed_line_is_not_taken_as_an_author():
    text = (
        "Neural Networks for Document Understanding\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "Document Understanding, which has attracted much attention, is surveyed here.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]


def test_separate_paragraph_byline_ending_with_a_period_is_preserved():
    """The sentence heuristic must never drop the line that opened the block."""

    text = (
        "A Paper Title\n"
        "\n"
        "Wei Zhang, Li Chen, Ming Li, and Will Smith.\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Wei Zhang", "Li Chen", "Ming Li", "Will Smith"]
    assert result.meta.abstract == "Body text."


def test_vlm_superscript_byline_ending_with_a_period_is_preserved():
    text = (
        "A Paper Title\n"
        "\n"
        "Wei Zhang1, Li Chen2, Ming Li3, and Will Brown1.\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Wei Zhang", "Li Chen", "Ming Li", "Will Brown"]


def test_wrapped_byline_line_with_a_capitalized_hint_name_is_preserved():
    """``Will`` is a name here, not the prose function word "will"."""

    text = (
        "A Paper Title\n"
        "\n"
        "Wei Zhang, Li Chen, Ming Li, Alice Anderson, Bob Brown,\n"
        "Carol Clark, David Davis, Eve Evans, Frank Foster, and Will Smith.\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == [
        "Wei Zhang", "Li Chen", "Ming Li", "Alice Anderson", "Bob Brown",
        "Carol Clark", "David Davis", "Eve Evans", "Frank Foster", "Will Smith",
    ]


def test_inline_label_after_a_byline_with_capitalized_hint_names_is_preserved():
    """A glued ``Abstract—`` must not make capitalized name parts look prose."""

    text = (
        "A Paper Title\n"
        "Will Smith, Can The Abstract—We present a robust method, then verify it.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Will Smith", "Can The"]
    assert result.meta.abstract.startswith("We present a robust method")


def test_title_with_a_capitalized_function_word_before_abstract_is_not_the_abstract():
    """R3/D2: a capitalized title prefix must not turn the title into the abstract."""

    text = (
        "A Study Of Abstract Meaning Representation, which is used, in NLP\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert "Abstract" not in " ".join(result.meta.authors)


@pytest.mark.parametrize(
    "title",
    [
        "Deep Learning For Abstract Reasoning, which is used, in NLP",
        "Towards Abstract Reasoning, which is used, in NLP",
        "A Survey Of Abstract Meaning Representation, which is used, in NLP",
    ],
)
def test_capitalized_title_prefix_does_not_turn_the_title_into_the_abstract(title):
    text = title + "\n\nWei Zhang, Li Chen\n\nAbstract\nBody text.\n"
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert "Abstract" not in " ".join(result.meta.authors)


def test_wrapped_title_line_starting_with_abstract_is_not_the_abstract():
    """R4/D3: a title's wrapped line must not be read as the abstract label."""

    text = (
        "Graph Neural Networks for\n"
        "Abstract Meaning Representation\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert result.meta.title == "Graph Neural Networks for Abstract Meaning Representation"
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]


@pytest.mark.parametrize(
    ("title_first", "title_second"),
    [
        ("Code Models for", "Abstract Syntax Trees"),
        ("Attention Is Still All You Need:", "Abstract Representations in Transformers"),
        ("Neural Networks for", "Abstract Reasoning"),
    ],
)
def test_wrapped_title_starting_with_abstract_does_not_shadow_the_abstract(
    title_first, title_second
):
    text = (
        f"{title_first}\n{title_second}\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert result.meta.title == f"{title_first} {title_second}"


def test_wrapped_cjk_title_starting_with_the_abstract_label_is_not_the_abstract():
    text = (
        "一种基于图神经网络的\n"
        "摘要：方法研究\n"
        "\n"
        "张三、李四\n"
        "\n"
        "摘要\n"
        "本文综述了图神经网络。\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "本文综述了图神经网络。"
    assert result.meta.title == "一种基于图神经网络的 摘要：方法研究"
    assert result.meta.authors == ["张三", "李四"]


def test_wrapped_title_after_an_authorlike_title_line_is_not_the_abstract():
    """R5/D4: the wrapped title line is not in title_block, tiering must save it."""

    text = (
        "Neural Networks, Deep Learning for\n"
        "Abstract Reasoning\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."


def test_authorlike_title_line_does_not_shadow_a_later_abstract_paragraph():
    text = (
        "Graph Neural Networks, A Survey of\n"
        "Abstract Meaning Representation\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."


@pytest.mark.parametrize(
    "title",
    [
        "Graph Neural Networks for\nNeural Networks, Deep Learning\nAbstract Reasoning",
        "Representation Learning, Advances in\nAbstract Meaning Representation",
    ],
)
def test_authorlike_title_wrap_does_not_shadow_the_abstract(title):
    text = title + "\n\nWei Zhang, Li Chen\n\nAbstract\nBody text.\n"
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."


def test_byline_line_starting_with_abstract_does_not_shadow_the_abstract():
    """A byline's second line is mid-paragraph, so a later paragraph-head wins."""

    text = (
        "A Paper Title\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "Abstract reasoning is a hard problem.\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]


def test_title_and_abstract_in_one_reflowed_paragraph_still_finds_the_abstract():
    """Both labels are mid-paragraph; the title block line must not win."""

    text = (
        "Graph Neural Networks for\n"
        "Abstract Reasoning\n"
        "Wei Zhang, Li Chen\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert result.meta.title == "Graph Neural Networks for Abstract Reasoning"
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("Abstract", "Body text."),
        ("摘要", "本文综述了图神经网络。"),
    ],
)
def test_a_title_that_is_only_the_abstract_label_still_finds_the_abstract(title, body):
    """R4 kept the word ``Abstract`` title out; the paragraph-head real label wins."""

    authors = "Wei Zhang, Li Chen" if title == "Abstract" else "张三、李四"
    text = f"{title}\n\n{authors}\n\n{title}\n{body}\n"
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == body


def test_authorlike_title_prefix_does_not_shadow_the_real_abstract():
    """A canonical ``Abstract`` line beats an inline label inside a title."""

    text = (
        "Neural Networks, Abstract Reasoning, and Compositionality\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."


def test_inline_abstract_inside_a_title_is_not_invented_without_a_real_abstract():
    """With no real summary present, a title must not be mined for one."""

    text = (
        "A Study Of Abstract Meaning Representation, which is used, in NLP\n"
        "\n"
        "Wei Zhang, Li Chen\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == ""
    assert "Abstract" not in " ".join(result.meta.authors)


def test_first_byline_line_is_not_dropped_by_the_sentence_heuristic():
    """The sentence boundary only guards extra lines, never the first byline line."""

    text = (
        "A Paper Title\n"
        "\n"
        "Wei Zhang, Li Chen, and the Ming Li Group.\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Wei Zhang", "Li Chen", "the Ming Li Group"]


def test_cjk_author_list_is_unchanged_by_the_abstract_boundary():
    text = (
        "图神经网络文档理解综述\n"
        "\n"
        "张三、李四、王五\n"
        "\n"
        "摘要\n"
        "本文综述了图神经网络在文档理解中的应用。\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["张三", "李四", "王五"]
    assert result.meta.abstract.startswith("本文综述了")


def test_affiliation_paragraph_is_still_not_part_of_the_author_list():
    text = (
        "Robust Feature Matching under Extreme Viewpoint Changes\n"
        "\n"
        "Jian Sun1, Alex Kim2, and Priya Nair1\n"
        "\n"
        "1University of Example  2Institute of Vision\n"
        "\n"
        "Abstract\n"
        "We present a robust method.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.authors == ["Jian Sun", "Alex Kim", "Priya Nair"]


def test_author_and_abstract_in_separate_paragraphs_is_unchanged():
    text = (
        "A Paper Title\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text here.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.title == "A Paper Title"
    assert result.meta.authors == ["Wei Zhang", "Li Chen"]
    assert result.meta.abstract == "Body text here."


def test_a_title_containing_the_word_abstract_does_not_become_the_abstract():
    text = (
        "A Survey of Abstract Meaning Representation, which is used, in NLP\n"
        "\n"
        "Wei Zhang, Li Chen\n"
        "\n"
        "Abstract\n"
        "Body text.\n"
    )
    result = metadata.parse_paper_meta(text)
    assert result.meta.abstract == "Body text."
    assert "Abstract" not in " ".join(result.meta.authors)


def test_empty_front_text_is_none_sourced_and_never_invents():
    result = metadata.parse_paper_meta("")
    assert result.meta.source == "none"
    assert result.meta.title == ""
    assert result.meta.authors == []
    assert result.notes == ["front-text-empty"]
    assert all(p.source == "none" for p in result.provenance.values())


def test_meta_parse_is_pure_and_replayable():
    text = _fixture("front_single_column.txt")
    first = metadata.parse_paper_meta(text)
    second = metadata.parse_paper_meta(text)
    assert first.model_dump() == second.model_dump()
    assert json.loads(first.model_dump_json()) == first.model_dump()


def test_parse_paper_text_combines_meta_and_references():
    full = (
        _fixture("front_single_column.txt")
        + "\n\n1 Introduction\nBody text.\n\n"
        + _fixture("references_numbered.txt")
    )
    document = references.parse_paper_text({"full_text": full})
    assert document.meta.title.startswith("Graph Neural Networks")
    assert len(document.references) == 3
    assert document.references[0].resolved_document_id is None
    assert "references-section:References" in document.notes


# ---------------------------------------------------------------------------
# Reference section location
# ---------------------------------------------------------------------------

def test_locate_references_prefers_the_last_heading():
    text = "Contents\nReferences\n1 Introduction\nbody\nReferences\n[1] A. Author. T. 2020.\n"
    section = references.locate_references_section(text)
    assert section is not None
    assert section.text.strip().startswith("[1]")


def test_locate_references_chinese_heading():
    text = "摘要\n本文……\n参考文献\n[1] 张三. 论文标题. 2021.\n"
    section = references.locate_references_section(text)
    assert section is not None
    assert section.heading == "参考文献"
    assert "[1]" in section.text


def test_locate_references_stops_at_appendix():
    text = "References\n[1] A. Author. Title. 2020.\nAppendix A\nProof.\n"
    section = references.locate_references_section(text)
    assert section is not None
    assert "Appendix" not in section.text


def test_locator_returns_none_without_heading():
    assert references.locate_references_section("Just a body paragraph.") is None


# ---------------------------------------------------------------------------
# Entry splitting and field extraction
# ---------------------------------------------------------------------------

def test_numbered_reference_entries():
    parsed = references.parse_references(_fixture("references_numbered.txt"))
    assert len(parsed.references) == 3
    assert all(p.style == "numbered" for p in parsed.provenance)
    first = parsed.references[0]
    assert first.doi == "10.1109/tkde.2023.1234567"
    assert first.title == "Graph neural networks for document understanding"
    assert first.authors == ["W. Zhang", "L. Chen", "M. Li"]
    assert first.year == 2023
    assert parsed.references[1].year == 2022
    assert parsed.references[2].title.startswith("Representation learning")


def test_cross_column_breaks_are_rejoined_and_dehyphenated():
    parsed = references.parse_references(_fixture("references_cross_column.txt"))
    assert len(parsed.references) == 2
    first = parsed.references[0]
    assert "under-\n" not in first.raw
    assert "understanding" in first.raw
    assert "dehyphenated" in parsed.provenance[0].notes
    assert parsed.provenance[0].fragments == 2


def test_author_year_entries_split_on_blank_lines():
    parsed = references.parse_references(_fixture("references_author_year.txt"))
    assert len(parsed.references) == 2
    assert all(p.style == "author-year" for p in parsed.provenance)
    assert parsed.references[0].year == 2023
    assert parsed.references[0].title == "Graph neural networks for document understanding"
    assert parsed.references[1].year == 2022


def test_missing_numbering_splits_on_leading_initials():
    parsed = references.parse_references(_fixture("references_missing_numbers.txt"))
    assert len(parsed.references) == 3
    assert [r.year for r in parsed.references] == [2023, 2022, 2013]
    assert parsed.references[0].authors == ["W. Zhang", "L. Chen", "M. Li"]


def test_yearless_fragment_is_merged_conservatively_with_provenance():
    text = (
        "References\n"
        "Zhang, W. (2023). Title one. Journal A.\n"
        "Sun, J. Title two without any year. Conference B.\n"
    )
    parsed = references.parse_references(text)
    assert len(parsed.references) == 1  # never fabricates a year-less second entry
    assert "merged-incomplete" in parsed.provenance[0].notes
    assert "Sun, J." in parsed.references[0].raw


def test_unparseable_entry_gets_explicit_note_not_fake_fields():
    entry = references.parse_reference_entry("Some untitled fragment", index=0)
    assert entry.title == "Some untitled fragment"
    assert entry.authors == []
    assert "authors-unparsed" in entry.notes
    assert "year-not-found" in entry.notes


# ---------------------------------------------------------------------------
# Library linkage / citation graph
# ---------------------------------------------------------------------------

def test_normalize_title_and_doi():
    assert metadata.normalize_title("Graph  Neural, Networks!") == "graph neural networks"
    assert metadata.normalize_title("图神经网络：综述") == "图神经网络 综述"
    assert metadata.normalize_doi("https://doi.org/10.1109/TKDE.2023.1") == "10.1109/tkde.2023.1"
    assert metadata.normalize_doi("doi:10.1/ABC.") == "10.1/abc"


def _library():
    return [
        citegraph.LibraryEntry("doc-a", "Graph Neural Networks for Document Understanding",
                               "10.1109/TKDE.2023.1234567"),
        citegraph.LibraryEntry("doc-b", "Robust Feature Matching under Extreme Viewpoint Changes", ""),
    ]


def test_resolve_by_doi_takes_priority_over_title():
    ref = references.PaperReference(
        raw="r", title="Robust Feature Matching under Extreme Viewpoint Changes",
        doi="10.1109/tkde.2023.1234567",
    )
    result = citegraph.resolve_references([ref], _library())
    assert result.references[0].resolved_document_id == "doc-a"
    assert result.resolutions[0].matched_by == "doi"


def test_resolve_by_normalized_title():
    ref = references.PaperReference(
        raw="r", title="robust feature  matching, under extreme viewpoint changes!")
    result = citegraph.resolve_references([ref], _library())
    assert result.references[0].resolved_document_id == "doc-b"
    assert result.resolutions[0].matched_by == "title"


def test_ambiguous_keys_never_produce_a_false_match():
    entries = [
        citegraph.LibraryEntry("doc-1", "Same Title", ""),
        citegraph.LibraryEntry("doc-2", "Same Title", ""),
    ]
    ref = references.PaperReference(raw="r", title="Same Title")
    result = citegraph.resolve_references([ref], entries)
    assert result.references[0].resolved_document_id is None
    assert result.unresolved == 1
    assert "ambiguous-title-keys:1" in result.notes


def test_unresolved_reference_stays_none():
    ref = references.PaperReference(raw="r", title="Nothing In The Library")
    result = citegraph.resolve_references([ref], _library())
    assert result.references[0].resolved_document_id is None
    assert result.unresolved == 1


def test_build_citation_graph_is_deduplicated_and_sorted():
    sources = [
        citegraph.CitationSource("doc-a", (
            references.PaperReference(raw="r1", title="Robust Feature Matching under Extreme Viewpoint Changes"),
            references.PaperReference(raw="r2", title="Robust Feature Matching under Extreme Viewpoint Changes"),
        )),
    ]
    graph = citegraph.build_citation_graph(sources, _library())
    assert graph.nodes == ["doc-a", "doc-b"]
    assert len(graph.edges) == 1
    assert graph.edges[0].source == "doc-a" and graph.edges[0].target == "doc-b"


def test_library_entries_are_read_from_store_records():
    records = [{
        "document_id": "doc-x",
        "title": "Fallback Title",
        "paper": {"meta": {"title": "Paper Title", "doi": "10.1/x"}},
    }]
    entries = citegraph.library_entries_from_documents(records)
    assert entries[0] == citegraph.LibraryEntry("doc-x", "Paper Title", "10.1/x")


# ---------------------------------------------------------------------------
# Optional LLM enhancement (offline stub seam)
# ---------------------------------------------------------------------------

def _baseline() -> metadata.PaperMetaResult:
    return metadata.parse_paper_meta(_fixture("front_arxiv.txt"))


def test_enhance_without_planner_keeps_deterministic_result():
    baseline = _baseline()
    result = enhance.enhance_meta(baseline, planner=None)
    assert result.meta.model_dump() == baseline.meta.model_dump()
    assert "llm-planner-absent" in result.notes


def test_enhance_survives_transport_failure_without_key():
    def boom(prompt, model):
        raise RuntimeError("no api key")

    result = enhance.enhance_meta(_baseline(), planner=boom)
    assert result.meta.title == _baseline().meta.title
    assert any(note.startswith("llm-enhance-failed") for note in result.notes)


def test_invalid_proposal_is_rejected():
    def bad_json(prompt, model):
        return "not json at all", {}

    result = enhance.enhance_meta(_baseline(), planner=bad_json)
    assert "llm-proposal-invalid" in result.notes

    assert enhance.validate_meta_proposal({"unknown": 1}) is None
    assert enhance.validate_meta_proposal({"year": 1200}) is None
    assert enhance.validate_meta_proposal({"title": 5, "authors": "x"}) is None


def test_proposal_never_overrides_deterministic_and_fills_empty_fields():
    baseline = metadata.parse_paper_meta(_fixture("front_two_column.txt"))
    assert baseline.meta.doi == ""  # nothing deterministic to keep

    def planner(prompt, model):
        return json.dumps({
            "title": "Hijacked",
            "doi": "https://doi.org/10.1145/1234567",
            "venue": "Hijacked Venue",
        }), {}

    result = enhance.enhance_meta(baseline, planner=planner)
    assert result.meta.title == baseline.meta.title  # deterministic wins
    assert result.meta.venue == baseline.meta.venue
    assert result.meta.doi == "10.1145/1234567"  # empty field filled
    assert result.provenance["doi"].source == "vlm"
    assert "llm-fields:doi" in result.notes


def test_proposal_sets_vlm_source_only_when_baseline_is_empty():
    baseline = metadata.parse_paper_meta("")
    assert baseline.meta.source == "none"

    def planner(prompt, model):
        return '{"title": "Recovered Title"}', {}

    result = enhance.enhance_meta(baseline, planner=planner, source="vlm")
    assert result.meta.title == "Recovered Title"
    assert result.meta.source == "vlm"


def test_extra_proposal_keys_are_forbidden():
    assert enhance.validate_meta_proposal({"title": "ok", "extra": 1}) is None
