"""graph2note papers package — born-digital PDF paper pipeline.

SPW I 轨 shared package.  P1 owns the ingest path
(``pipeline.py`` / ``textlayer.py`` / ``structure.py`` / ``model.py``);
P2 owns metadata and reference recognition:

- :mod:`graph2note.papers.metadata`   — deterministic ``PaperMeta`` parsing
- :mod:`graph2note.papers.references` — reference-section location/splitting
- :mod:`graph2note.papers.citegraph`  — in-library reference resolution
- :mod:`graph2note.papers.enhance`    — optional, schema-validated LLM boost

Everything here is offline-safe and deterministic by default; the LLM seam is
opt-in and injectable.
"""
