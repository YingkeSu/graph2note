# BOARD：notes-organizer

> 由调度 agent 维护；依赖关系以各 issue 的 Blocked by 为准，本表只是快照。
> Updated: 2026-09-08（manuscript 07/09 已合并，01 已派 graph2note-2）

| issue | track | agent | worktree | branch | status | updated |
|---|---|---|---|---|---|---|
| 01 vault 导出器（溯源） | A | graph2note-2（跨 feature 接力） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/no01-vault-exporter | merged（168+2 离线；幂等+死链校验+双路去重） | 2026-09-08 |
| 02 分类归纳 + MOC | A | graph2note-2（接力） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/no02-classification-moc | merged（207+2 离线；规则分类器+可注入 LLM 分类器+MOC 死链校验） | 2026-09-08 |
| 03 增量导出闭环 | — | — | — | — | ready-for-agent（阻塞于本 feature 01、02） | 2026-09-08 |
