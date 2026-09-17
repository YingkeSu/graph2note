# Real paper regression fixtures (SPW Y4)

The P1/P2 suites (`tests/test_papers_ingest.py`, `tests/test_papers_meta.py`)
were built entirely from synthetic PDFs and hand-written front pages. These
fixtures lift the regression to **real born-digital papers**: the raw PyMuPDF
text layer of six arXiv papers, a curated `expected.json` per paper, and two
offline test files (`tests/test_papers_ingest_real.py`,
`tests/test_papers_meta_real.py`).

They are **frozen text**, never generated at test time. The tests need no
network, no model and no PDF: `lines.jsonl` carries the per-line font size /
bold flag, `front.txt` is the first page, and `references.txt` is the located
reference section.

## Samples

| key | paper | arXiv | license | pages | layout |
| --- | --- | --- | --- | --- | --- |
| `scaling-laws` | Scaling Laws for Neural Language Models (OpenAI) | [2001.08361](https://arxiv.org/abs/2001.08361) | arXiv.org perpetual, non-exclusive 1.0 | 30 | single-column preprint |
| `constitutional-ai` | Constitutional AI: Harmlessness from AI Feedback (Anthropic) | [2212.08073](https://arxiv.org/abs/2212.08073) | arXiv.org perpetual, non-exclusive 1.0 | 34 | single-column preprint, 51-author byline |
| `deepseek-moe` | DeepSeekMoE (DeepSeek) | [2401.06066](https://arxiv.org/abs/2401.06066) | arXiv.org perpetual, non-exclusive 1.0 | 33 | single-column technical report, multi-affiliation byline |
| `bert` | BERT (Google) | [1810.04805](https://arxiv.org/abs/1810.04805) | arXiv.org perpetual, non-exclusive 1.0 | 16 | **two-column conference** (NAACL) |
| `gpt4-tech-report` | GPT-4 Technical Report (OpenAI) | [2303.08774](https://arxiv.org/abs/2303.08774) | arXiv.org perpetual, non-exclusive 1.0 | 100 | single-column technical report, one-line org byline |
| `gpt3-few-shot` | Language Models are Few-Shot Learners (OpenAI) | [2005.14165](https://arxiv.org/abs/2005.14165) | arXiv.org perpetual, non-exclusive 1.0 | 75 | single-column preprint, 31-author one-per-line byline |

`manifest.json` is the machine-readable version of this table (including each
PDF's `sha256_16`). Only short extracted text is stored — no PDF is committed.

## Fixture files

```
real/<key>/
  front.txt        # page 0 plain text, exactly as extracted from the PDF
  lines.jsonl      # full text-layer export: {p: page, s: size, b: bold, t: text}
  references.txt   # the located "References" section body
  expected.json    # source/license, layout, P1/P2 expectations, known failures
```

`expected.json` records, per paper: the P1 text-layer decision and section
snapshot, the full P2 `PaperMeta` snapshot + notes + provenance confidence, an
explicit `gold` block (human-checked title / author prefix / abstract opening;
accuracy is asserted against gold, not a non-empty count), a
`field_status` map (`ok` / `degraded` / `wrong` / `missing`), the
`known_failures` list, the reference-section count/style/provenance and a
`differences_from_synthetic` note.

Tests split `lines.jsonl` on `"\n"` (not `str.splitlines()`): text can contain
Unicode line separators such as U+2028 that are preserved by `json.dumps`.

## Regenerating the raw fixtures

`_generate.py` rebuilds `front.txt` / `lines.jsonl` / `references.txt` from a
local PDF (read-only input):

```bash
python tests/fixtures/papers/real/_generate.py bert /path/to/1810.04805.pdf
```

`expected.json` is curated by hand from the observed output and is deliberately
**not** overwritten: the fixtures exist to freeze current real-layout behaviour,
including the failures below.

## Known real-layout failures

Y4 originally recorded where synthetic fixtures were too kind.  **PRR/02**
(`paper-reading-reliability/02`) fixed the front-matter boundary and the byline
parser and added the two GPT samples, so the table below is split into
*addressed* and *open*.  Per-paper detail lives in each `expected.json`; the
"Regenerating" note above no longer means the parser is frozen — a parser fix
recalibrates the snapshot on purpose (and asserts gold in `test_real_gold_*`).

| # | finding | where | status |
| --- | --- | --- | --- |
| 1 | `structure.split_sections` promotes figure/table/axis text (`Layers`, `+ 16`, `1010`, `1024`, `91.2`) to headings — 42–76 sections on real papers | `structure` | **open** — issue 03 (spurious-heading guard) |
| 2 | the byline melted into `title` when the text layer merges title/byline/abstract into one block (`scaling-laws`, `bert`, both GPT samples) | `metadata._title_lines` | **fixed (PRR/02)** — abstract label is a hard front-matter boundary; wrapped-title and one-name-per-line bylines are split out |
| 3 | affiliation/URL/email fragments landed in `authors` | `metadata._parse_authors` | **fixed (PRR/02 R2)** — line-aware parsing + fixed `_AFFIL_RE` + affiliation/org pruning + PDF-ligature folding; `bert` now yields exactly the four people (gold `author_count: 4`) |
| 4 | `doi` falls back to `full_text` and picks a DOI out of the reference list (`scaling-laws`, `deepseek-moe`) | `metadata._extract_doi` | **fixed (PRR/02 R2/R3)** — DOI only from a front-page metadata line (label + copyright/identifier marker, or a line that is only the DOI/URL); citation/reference/body-prose DOIs rejected; a DOI wrapped across a line break is re-joined (no minimum-length or digit heuristic — short/alpha-only DOIs such as the DOI Handbook's `10.1000/182` are legitimate); no evidence ⇒ empty + `doi-not-found` |
| 5 | real unnumbered / alphabetic-key reference lists under-split into 3–9 multi-page entries (`[ACDE12]`, `[Askell et al., 2021]`) | `references.split_reference_entries` | **open** |
| 6 | `venue`/`keywords` are `missing` on every sample (arXiv preprints carry neither) | `metadata` | expected for this source; not a defect |
| 7 | the two-column `bert` reflow put the swallowed `'Abstract'` line in `title_keys`, so the real summary was lost (`abstract-not-found`) | `metadata._extract_abstract` | **fixed (PRR/02)** — `bert` recovers the abstract; a label whose body is in the next paragraph is now collected too (R3) |

The under-split in #5 is **conservative**: the entries keep `merged-continuation`
/ `merged-incomplete` / `dehyphenated` / `authors-unparsed` provenance and never
invent an entry (asserted in
`test_real_reference_failures_are_conservative_and_traceable`).

## Not included

- No scanned sample: all 17 papers in the source library are born-digital and
  report a full text layer. The image-only fallback path stays covered by the
  injected-router synthetic tests in `tests/test_papers_ingest.py`.
- The P2 baseline is the **merged Y5 final** on `main` (`560fe59`, R1–R5). The
  fixtures were recalibrated against it; the only snapshot change vs the
  pre-final baseline is the `bert` abstract (finding #7 above).

## Offline guarantee

`tests/test_papers_ingest_real.py` and `tests/test_papers_meta_real.py` monkeypatch
`socket.socket` / `socket.create_connection` to raise and re-run the P1/P2 parse,
so a network access would fail the suite. The one pipeline test rebuilds a tiny
in-memory PDF from the frozen lines and injects a router factory that raises if
a model call is ever attempted — the real text-layer path is asserted to be
zero-LLM.
