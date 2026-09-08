# BOARD：manuscript-compiler-mvp

> 由调度 agent 维护；依赖关系以各 issue 的 Blocked by 为准，本表只是快照。
> Updated: 2026-09-08（Wave 1 派工：01-harness / 02 / 04 三路并行，AO worker 上限 4）
> Worktree 位置：AO 管理的 worktree（`~/.ao/data/worktrees/graph2note/<session>`），分支按协议命名 `dev/<NN>-<slug>`；主检出目录不建 `.worktrees/`。

| issue | track | agent | worktree | branch | status | updated |
|---|---|---|---|---|---|---|
| 01 spike1 视觉质量评估 | C | graph2note-3（01 spike1 harness） | ~/.ao/data/worktrees/graph2note/graph2note-3 | dev/01-spike1-harness | claimed（harness+冒烟派 agent；评估集供图与 gold 校对 = HITL，已汇总维护者） | 2026-09-08 |
| 02 IR schema+渲染器 | A | graph2note-2（02 IR+renderer） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/02-ir-schema-renderer | claimed | 2026-09-08 |
| 03 解析链路 CLI | A（拟接力） | — | — | — | ready-for-agent（阻塞于 01,02；Wave 2 候选，Track A 接力） | 2026-09-08 |
| 04 Spike3 流程图重建 | B | graph2note-4（04 spike3 diagram） | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/04-spike3-diagram-rebuild | claimed | 2026-09-08 |
| 05 Diagram 渲染+附件 | B（拟接力） | — | — | — | ready-for-agent（阻塞于 02,04；Wave 2 候选，Track B 接力） | 2026-09-08 |
| 06 Web App 三栏 | — | — | — | — | ready-for-agent（阻塞于 03,05；Wave 3） | 2026-09-08 |
| 07 本机文档库 | — | — | — | — | ready-for-agent（阻塞于 06；Wave 3） | 2026-09-08 |
| 08 Spike2 / Route B | — | — | — | — | ready-for-agent（P1 时机，MVP 主链路稳定后；阻塞于 01） | 2026-09-08 |

## HITL 汇总（已向维护者提出，见调度会话）

1. 评估集图片：30–50 张真实手稿，覆盖手写/印刷/公式/中英混排/流程图/涂改六类（issue 01 AC）
2. 流程图手稿样本 ≥10 张（issue 04 真实样本；合成样本先行）
3. gold Markdown 人工校对（harness 冒烟产出后进行）
