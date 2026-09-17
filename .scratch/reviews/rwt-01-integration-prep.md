# Pre-merge integration handoff — research-weekly-template issue 01 (approved `83270eb`)

- **Author**: AO worker `graph2note-138` (integration prep only — not the merge owner)
- **Base**: local `main` = `f771b9d` (verified, untouched)
- **Candidate branch**: `dev/prr-02-integration-rwt-01`
- **Candidate worktree**: `/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138-integration`
- **Candidate merge commit**: `d1914671abbfc347afe44bfe2fa67faa980db50d`
- **Approved source**: `83270eb` (weekly report; implementation `3e17c5b`)
- **Status**: PAUSED at a reproducible point (awaiting 136's re-review of the metadata fix). No main/WIP/push/merge changes.
- **Date**: 2026-09-17

## 1. Candidate

Built with an exact `merge --no-ff` of the approved SHA (no feature-commit replay):

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138
git worktree add /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138-integration \
  -b dev/prr-02-integration-rwt-01 f771b9d
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138-integration
git merge --no-ff 83270eb -m "merge: research-weekly-template issue 01 (approved 83270eb)"
# candidate tree must be byte-identical to the approved SHA:
git diff --stat 83270eb HEAD        # → empty
```

- `git diff 83270eb HEAD` is empty ⇒ the candidate tree equals the approved `83270eb` tree; the merge commit only adds history.
- The audited ancestry is preserved (`f771b9d → bcfe1a6 → b27c4df → aeb2c05 → 3e17c5b → 83270eb`).
- **Note**: this necessarily includes `.scratch/reviews/prr-02-metadata.md` from `aeb2c05` (a review document, no code). It is part of the approved SHA's ancestry; if the dispatcher wants a strict code-only tree, that single doc would have to be dropped separately — I did **not** replay feature commits via cherry-pick, to avoid new drift.

### Candidate regression (reproducible)

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138-integration
PY=/Users/suyingke/Programs/OHO/graph2note/.venv/bin/python
OPENCODE_API_KEY=dummy PYTHONPATH="$PWD" $PY -m pytest -o addopts="" -p no:warnings -q \
  tests/test_research_report.py tests/test_report_view.py \
  tests/test_weekly_digest.py tests/test_digest_structure.py tests/test_digest_budget.py tests/test_digest_view.py
# → 127 passed
node tests/report_view_dom.mjs && node tests/digest_view_dom.mjs   # both pass
OPENCODE_API_KEY=dummy PYTHONPATH="$PWD" $PY -m pytest -o addopts="" -p no:warnings -q \
  --junitxml=/tmp/prr02-integration/candidate.xml
# → 1396 passed / 0 failed / 0 error / 0 skipped  (candidate.xml sha256 30b8f658375ac54e39dd0df07fbe9830baf2ce50b6c68530b2ea110c3d1b2ea9)
```

## 2. Main-checkout WIP rehearsal (isolated; user WIP preserved)

The main checkout has uncommitted WIP that overlaps the weekly branch's files. To find the real conflicts I replayed the WIP into a throwaway copy — **without copying storage, credentials, `.venv` or large artifacts, and without touching the main checkout**.

Evidence dir: `/tmp/prr02-integration/`

```bash
# tracked WIP patch + per-file hashes (originals in main, read-only)
cd /Users/suyingke/Programs/OHO/graph2note
git diff --binary > /tmp/prr02-integration/wip.patch        # sha256 ee35d7d98b9c8fe6ac88b8efd5bc2435391bb327235e616e5b1e6a3f475c1f7e
git diff --name-only | while read -r f; do shasum -a 256 "$f"; done \
  > /tmp/prr02-integration/wip-tracked.sha256               # sha256 067b81f9734e516f23b0f37f1018eac196867de94b9eafdfe0b7b92936806212

# isolated rehearsal worktree (throwaway; removed afterwards)
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-138
git worktree add /tmp/rwt01-integration-rehearsal -b rehearsal/wip-copy f771b9d
cd /tmp/rwt01-integration-rehearsal
git reset -q && git apply /tmp/prr02-integration/wip.patch   # mirror main WIP (unstaged)
# copy ONLY the untracked files needed (no references/ binaries, no storage/.venv)
MAIN=/Users/suyingke/Programs/OHO/graph2note
rsync -a --exclude 'references/' "$MAIN/.scratch/research-weekly-template/" ./.scratch/research-weekly-template/
cp "$MAIN/graph2note/papers/view.py" graph2note/papers/view.py
cp "$MAIN/graph2note/webstatic/js/workspace.js" graph2note/webstatic/js/workspace.js
cp "$MAIN/graph2note/webstatic/workspace.css" graph2note/webstatic/workspace.css
```

Per-file WIP hashes (also in `wip-tracked.sha256`):

```
61dc5122…  .scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md
acfec726…  graph2note/webapp.py
75c34977…  graph2note/webstatic/index.html
a97710ca…  graph2note/webstatic/js/ui.js
bd03d761…  graph2note/webstatic/js/views/graph-layout.js
8e4ada76…  graph2note/webstatic/js/views/graph.js
25c05dd9…  graph2note/webstatic/reading.css
5534fceb…  pyproject.toml
f8423eee…  tests/graph_interaction.mjs
9554bde3…  tests/graph_layout.mjs
7328616c…  tests/test_papers_view.py
```

### Actual rehearsal conflicts

1. **Direct merge into the WIP working tree is refused** (reproduced verbatim):

```text
error: Your local changes to the following files would be overwritten by merge:
        graph2note/webapp.py
        graph2note/webstatic/index.html
Please commit your changes or stash them before you merge.
error: The following untracked working tree files would be overwritten by merge:
        .scratch/research-weekly-template/BREAKDOWN.md
        … (16 files) …
        .scratch/research-weekly-template/issues/01-research-report.md
Please move or remove them before you merge.
Aborting
```

2. **After the WIP is preserved (committed in the throwaway copy), the merge is clean**:

```bash
# throwaway only (never applied to main):
cp .scratch/research-weekly-template/issues/01-research-report.md \
   /tmp/prr02-integration/01-research-report.main-untracked.md   # sha256 d3ffdc69a64b733aca018edc097a13de3d50a38c90f258280bbeb88d3250b03d
git show d191467:.scratch/research-weekly-template/issues/01-research-report.md \
   > .scratch/research-weekly-template/issues/01-research-report.md
git add -A && git commit -m "rehearsal: copy of main WIP (throwaway, never applied to main)"   # 2d700d2
git merge --no-ff d191467 -m "rehearsal merge of approved weekly report"                     # 067a172
git diff --name-only --diff-filter=U     # → empty  (no conflicts)
```

Combined-tree verification (candidate + WIP):

```bash
OPENCODE_API_KEY=dummy PYTHONPATH="$PWD" $PY -m pytest -o addopts="" -p no:warnings -q \
  tests/test_research_report.py tests/test_report_view.py tests/test_digest_view.py \
  tests/test_weekly_digest.py tests/test_digest_structure.py tests/test_digest_budget.py tests/test_papers_view.py
# → 145 passed;  node report_view_dom + digest_view_dom pass
OPENCODE_API_KEY=dummy PYTHONPATH="$PWD" $PY -m pytest -o addopts="" -p no:warnings -q \
  --junitxml=/tmp/prr02-integration/rehearsal.xml
# → 1399 passed / 0 failed / 0 error / 0 skipped  (rehearsal.xml sha256 f2beb52bc95670c443e278108bb3fd1f6fd8d429ab599cf0866ddf4498004231)
```

The rehearsal worktree/branch (`rehearsal/wip-copy`) were removed after capturing evidence; the candidate worktree was kept.

### Untracked same-path docs: differences and safe retention

16 untracked `.scratch/research-weekly-template/**` files collide with the merge. **15/16 are byte-identical** to `83270eb`; only:

- `issues/01-research-report.md` **differs**: main's untracked copy is the stale pre-implementation version (`Status: ready-for-agent`, unchecked ACs, no delivery comments); the branch version is authoritative (`Status: in-review`, checked ACs, delivery + Rework records).
- Untracked `references/page-{1,5}.png` exist but are **not** added by the merge (no collision; intentionally not copied into the rehearsal).
- Backup of the differing untracked original kept at `/tmp/prr02-integration/01-research-report.main-untracked.md` (sha256 `d3ffdc69…`).

**Safe path** (for the human/dispatcher; not auto-applied): back up `issues/01-research-report.md`, then let the merge take the branch version; the other 15 docs are identical so committing or deleting them changes no content. Do not auto-commit user WIP.

## 3. Shell mis-expansion impact check (conclusion)

An earlier `ao send` message passed a backtick-quoted command inside double quotes, so the shell executed:

```text
git worktree add -b dev/prr-02-metadata/integration-rwt-01
```

with no `<path>` argument. **Actual impact: a usage error on stderr only — no repository or file changes.** Read-only verification:

- no branch `dev/prr-02-metadata/integration-rwt-01` exists;
- `git worktree list` shows only the intended worktrees (`graph2note-138`, `graph2note-138-integration`); no stray `integration-rwt-01` directory;
- no `*.lock` files in the shared git dir;
- main checkout still `f771b9d` with the same 25 WIP/untracked entries;
- no credentials/environment values were printed or leaked.

Outbound messages are now passed via files (`ao send --message "$(cat …)"`), never inline double quotes with backticks/`$()`.

## 4. b27c4df dev `storage/reports/` compatibility

Read-only check of the real library `/Users/suyingke/Library/Application Support/Graph2Note/storage/`: **there is no `reports/` directory** (only `digests/`, which is empty). So the b27c4df dev build left **no real user research-report data**; only `/tmp` test artifacts exist. No migration or deletion is needed; no blocker. (If a real `reports/` store is ever found, files must be kept in place and reported, not migrated.)

Sidecar note (from the R1 review): a missing/corrupt `<id>.report.json` falls back to one real regeneration on a display-only change — a known recovery behavior, not a blanket zero-call guarantee.

## 5. Safe integration path / resume point

1. Owner preserves the main WIP (commit or otherwise); I will not commit it.
2. Reconcile the 16 untracked docs per §2 (15 identical; back up + keep the branch version for `issues/01-research-report.md`).
3. `git merge --no-ff d191467` (or merge `83270eb` directly) — rehearsed clean, no code conflicts; the weekly branch regions (`webapp.py` ~66/891-980, `index.html` ~44/409) differ from the WIP regions (`webapp.py` ~1022+).
4. Run the full offline suite (candidate already 1396 passed; combined rehearsal 1399 passed).

**Resume state**: candidate `d191467` retained at the path above; no main/WIP/push/merge changes; awaiting 136's re-review of the metadata SHA `fd083c2`. No new features, no issue set to `merged`.
