# BOARD：manuscript-compiler-mvp

> 由调度 agent 维护；依赖关系以各 issue 的 Blocked by 为准，本表只是快照。
> Updated: 2026-09-08（P1 增补：新增 09–11 去重/交叉验证/提速，均阻塞于 03；Wave 2 中期：02/04/05 已合并；01 全量评估进行中；03/06 待解锁）
> Worktree 位置：AO 管理的 worktree（`~/.ao/data/worktrees/graph2note/<session>`），分支按协议命名 `dev/<NN>-<slug>`；主检出目录不建 `.worktrees/`。

| issue | track | agent | worktree | branch | status | updated |
|---|---|---|---|---|---|---|
| 01 spike1 视觉质量评估 | C | graph2note-3（01 spike1 harness） | ~/.ao/data/worktrees/graph2note/graph2note-3 | dev/01-spike1-harness | in-review（harness+冒烟已合并 f50a414；评估集≥30张与 gold 校对、选型结论待数据集 HITL） | 2026-09-08 |
| 02 IR schema+渲染器 | A | graph2note-2（02 IR+renderer） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/02-ir-schema-renderer | merged（2a06952，验收：31 测试绿+AC 全证据+审查+无密钥） | 2026-09-08 |
| 03 解析链路 CLI | A | graph2note-2（接力） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/03-parse-pipeline-cli | claimed（提前启动：临时选型 glm-5.3-flash 可配置化，正式结论到达后仅切配置） | 2026-09-08 |
| 04 Spike3 流程图重建 | B | graph2note-4（04 spike3 diagram） | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/04-spike3-diagram-rebuild | merged（bb28a01；结论 graphviz 主/matplotlib 回退已回写 PRD；真实样本复跑随数据集补） | 2026-09-08 |
| 05 Diagram 渲染+附件 | B | graph2note-4（接力） | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/05-diagram-render-attachments | merged（9593366；验收：69 测试绿+2 干净 skip+AC 证据+审查） | 2026-09-08 |
| 06 Web App 三栏 | — | — | — | — | ready-for-agent（阻塞于 03,05✅；03 完成后即启动） | 2026-09-08 |
| 07 本机文档库 | — | — | — | — | ready-for-agent（阻塞于 06；Wave 3） | 2026-09-08 |
| 08 Spike2 / Route B | — | — | — | — | ready-for-agent（P1 时机，MVP 主链路稳定后；阻塞于 01） | 2026-09-08 |
| 09 PDF 拆页+去重+缺页预警 | — | — | — | — | ready-for-agent（P1 增补；阻塞于 03；首批样本：test-images/ 4 个扫描 PDF） | 2026-09-08 |
| 10 交叉验证引擎 | — | — | — | — | ready-for-agent（P1 增补；阻塞于 03） | 2026-09-08 |
| 11 解析提速 | — | — | — | — | ready-for-agent（P1 增补；阻塞于 03；先基线后优化） | 2026-09-08 |

> 侧任务（非 issue）：graph2note-5「latency diagnose」分支 dev/diag-eval-latency —— 排查评估/解析单次调用 19–65s 偏慢问题，报告将喂 issue 11 基线。2026-09-08 派。

## HITL 汇总（已向维护者提出，见调度会话）

1. 评估集图片：30–50 张真实手稿，覆盖手写/印刷/公式/中英混排/流程图/涂改六类（issue 01 AC）
2. 流程图手稿样本 ≥10 张（issue 04 真实样本；合成样本先行）
3. gold Markdown 人工校对（harness 冒烟产出后进行）
