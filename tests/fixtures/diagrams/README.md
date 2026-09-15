# Structure-diagram extract fixtures

Real DeepSeek-vision extractions of the `structure-paper-weekly` D-track source
notes, captured during the live audit (session `spw-taudit-live-20260914`). They
are the ground truth for the dense-diagram render tests (`X6` default-view
legibility) and the D-track golden/anchor work.

- `01-requirements-arch.json` — 21 nodes, 6 groups, 10 columns (live 01)
- `02-digitize-pipeline.json` — 10 nodes, 4 groups (live 02)
- `02-digitize-pipeline-increment.json` — 32 nodes, 6 groups, 8 rows (live 02inc)

Each file keeps only `caption` / `nodes` / `edges` / `groups` from the extractor
payload; the provider latency/attempt metadata (`meta`) and the `ok`/`verdict`
envelope are dropped because they do not affect rendering. The node/edge/group
content is byte-for-byte the validated extractor output
(`graph2note.diagram.validate_diagram_json`), only re-serialised with
``indent=2`` and ``ensure_ascii=False``.

Provenance (read-only audit artifacts, not committed):

    /tmp/spw-taudit-artifacts/recheck-live/raw/*-deepseek__extract.json

The render measurements are asserted by
`tests/test_diagram_render_groups.py::test_real_dense_diagram_default_view_is_legible_at_720`.
