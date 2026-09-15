"""Paper PDF import pipeline (SPW I-track).

Public surface for P1:

- :mod:`graph2note.papers.pipeline` — job orchestration (text-layer first, VLM
  fallback for scans) + durable job state + read-only result payload;
- :mod:`graph2note.papers.textlayer` — deterministic text-layer extraction and
  the offline text-layer / scan decision;
- :mod:`graph2note.papers.structure` — deterministic heading detection and
  ``PaperSection`` splitting;
- :mod:`graph2note.papers.model` — the SPEC §2 paper contract (including the
  P2 ``PaperMeta`` / ``PaperReference`` slots).

P2 appends its own modules (``metadata.py`` / ``references.py`` / ``citegraph.py``)
to this package; nothing here imports them, so P2 stays contract-decoupled.
"""

from .model import (
    PAPER_DOC_KIND,
    PAPER_SCHEMA_VERSION,
    PaperMeta,
    PaperPage,
    PaperPayload,
    PaperProvenance,
    PaperReference,
    PaperSection,
)
from .pipeline import (
    MAX_PAPER_ATTEMPTS,
    PAPERS_DIRNAME,
    PAPER_DOC_SUFFIX,
    PAPER_JOB_TIMEOUT,
    TEXT_LAYER_MODEL,
    PaperJob,
    build_page_map,
    load_job,
    load_jobs,
    paper_dir,
    paper_document_id,
    paper_id_for_pdf,
    process_paper,
    render_paper_markdown,
    result_payload,
    save_job,
    stable_paper_id,
    start_job,
    validate_paper,
)
from .structure import Heading, body_size, detect_headings, split_sections
from .textlayer import (
    MIN_PAGE_CHARS,
    MIN_TEXT_PAGE_RATIO,
    MIN_TOTAL_CHARS,
    PageText,
    TextLayer,
    TextLayerDecision,
    TextLine,
    decide_text_layer,
    read_text_layer,
)

__all__ = [
    "MAX_PAPER_ATTEMPTS",
    "MIN_PAGE_CHARS",
    "MIN_TEXT_PAGE_RATIO",
    "MIN_TOTAL_CHARS",
    "PAPERS_DIRNAME",
    "PAPER_DOC_KIND",
    "PAPER_DOC_SUFFIX",
    "PAPER_JOB_TIMEOUT",
    "PAPER_SCHEMA_VERSION",
    "TEXT_LAYER_MODEL",
    "Heading",
    "PageText",
    "PaperJob",
    "PaperMeta",
    "PaperPage",
    "PaperPayload",
    "PaperProvenance",
    "PaperReference",
    "PaperSection",
    "TextLayer",
    "TextLayerDecision",
    "TextLine",
    "body_size",
    "build_page_map",
    "decide_text_layer",
    "detect_headings",
    "load_job",
    "load_jobs",
    "paper_dir",
    "paper_document_id",
    "paper_id_for_pdf",
    "process_paper",
    "read_text_layer",
    "render_paper_markdown",
    "result_payload",
    "save_job",
    "split_sections",
    "stable_paper_id",
    "start_job",
    "validate_paper",
]
