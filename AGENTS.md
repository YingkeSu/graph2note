## Agent skills

### Issue tracker

Issues live as local markdown under `.scratch/<feature>/` in this repo; there is no external PR triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles using their default strings: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.

### Parallel development

Multi-agent worktree protocol: dispatcher classifies issues by dependency graph, each worker gets its own worktree, handoffs via `/handoff` documents, automated acceptance, dispatcher-only merges to main. See `docs/agents/parallel-dev.md`.
