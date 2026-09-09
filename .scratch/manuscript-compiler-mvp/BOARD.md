# BOARD：manuscript-compiler-mvp

> 由调度 agent 维护；依赖关系以各 issue 的 Blocked by 为准，本表只是快照。
> Updated: 2026-09-09（第一阶段收官：两 feature 20/20 issue 全部 merged，分支/worktree 已清理）
> 阶段总结：PHASE-SUMMARY.md（架构、质量证据、决策记录、开放事项）
> 开放候选（未立项）：EditRate 质量迭代、印刷样本+AutoRouter 决策、模板/HTML/PDF、公式表格质量、真实使用反馈驱动
> Worktree 位置：AO 管理的 worktree（`~/.ao/data/worktrees/graph2note/<session>`），分支按协议命名 `dev/<NN>-<slug>`；主检出目录不建 `.worktrees/`。

| issue | track | agent | worktree | branch | status | updated |
|---|---|---|---|---|---|---|
| 01 spike1 视觉质量评估 | C | graph2note-3 | ~/.ao/data/worktrees/graph2note/graph2note-3 | dev/01-spike1-full-eval | merged（维护者临时验收：选型定案 glm-5.3-flash；gold 精修与印刷样本后续增量） | 2026-09-09 |
| 02 IR schema+渲染器 | A | graph2note-2（02 IR+renderer） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/02-ir-schema-renderer | merged（2a06952，验收：31 测试绿+AC 全证据+审查+无密钥） | 2026-09-08 |
| 03 解析链路 CLI | A | graph2note-2（接力） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/03-parse-pipeline-cli | merged（4c0cb1e；92+2 测试绿；img01 golden 待网关修复后重录，AC 留一条未勾） | 2026-09-08 |
| 04 Spike3 流程图重建 | B | graph2note-4（04 spike3 diagram） | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/04-spike3-diagram-rebuild | merged（bb28a01；结论 graphviz 主/matplotlib 回退已回写 PRD；真实样本复跑随数据集补） | 2026-09-08 |
| 05 Diagram 渲染+附件 | B | graph2note-4（接力） | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/05-diagram-render-attachments | merged（9593366；验收：69 测试绿+2 干净 skip+AC 证据+审查） | 2026-09-08 |
| 06 Web App 三栏 | A | graph2note-2（接力） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/06-webapp-three-pane | merged（ddf3dba；142+2 离线测试；浏览器手工路径见 handoff 06 §3） | 2026-09-08 |
| 07 本机文档库 | A | graph2note-2（接力） | ~/.ao/data/worktrees/graph2note/graph2note-2 | dev/07-local-document-library | merged（6ee8cad；153+2 离线；MVP 主链 02–07 收官） | 2026-09-08 |
| 08 Spike2 / Route B | 5 | graph2note-5 | ~/.ao/data/worktrees/graph2note/graph2note-5 | dev/08-spike2-route-b | merged（b46561f；Route A 全面占优，清印刷窄域切 B；AutoRouter 落地待维护者决策） | 2026-09-08 |
| 12 Route A 空IR修复（新立） | 5 | graph2note-5 | ~/.ao/data/worktrees/graph2note/graph2note-5 | dev/12-route-a-empty-ir | merged（2227dd3；两阶段解析：VLM→Markdown→确定性 IR；6/6 页非空；EditRate 绝对值优化随 01/11 跟进） | 2026-09-08 |
| 14 网关会话隔离（worker 立项） | 5 | graph2note-5 | ~/.ao/data/worktrees/graph2note/graph2note-5 | dev/gateway-session-isolation | merged（57187b3；三用途独立已验证 session + 64-token 探针；docs/llm §2.1 规范） | 2026-09-08 |
| 15 图形提取入管线（FR-009 闭环） | B | graph2note-4 | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/15-diagram-extraction | in-review（310 离线通过；文本侧确定性汇聚 + 视觉提取器产品化/独立接入） | 2026-09-08 |
| 13 Ingest↔Store 去重集成（新立） | B | graph2note-4 | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/13-ingest-store-dedup | merged（0043ed8；pHash 同页并入候选版本+可拆分+web 提示） | 2026-09-08 |
| 09 PDF 拆页+去重+缺页预警 | B | graph2note-4（接力） | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/09-pdf-split-dedup | merged（ingest 包 9 模块+可调阈值、recluster 拆分、93 测试绿；真实扫描无内容重复） | 2026-09-08 |
| 10 交叉验证引擎 | B | graph2note-4 | ~/.ao/data/worktrees/graph2note/graph2note-4 | dev/10-cross-validation | in-review（verify 包 9 模块+router 缝实现+CLI；162 测试绿；实测 2 评估图×双模型分歧率数据记 out/10） | 2026-09-08 |
| 11 解析提速 | 5 | graph2note-5 | ~/.ao/data/worktrees/graph2note/graph2note-5 | dev/11-parse-latency | merged（3f57669；P95 6.4s 达标；O1 网关收敛/O2 结果缓存/O3 并发；AC4 EditRate 顺延至 12 修复后联动补验） | 2026-09-08 |

> 侧任务（非 issue）：graph2note-5 延迟诊断已完成并合并（e0bd5dc，reports/latency-diagnosis.md：根因=新 session 路由推理变体思考狂暴+10k 空转）。同 worker 续派网关修复（R1 稳定 session/R2 首调直出/R3 1024 降采样/R4 硬超时），分支 dev/gateway-speed-fix——issue 11 先行落地，03 与全量评估消费。2026-09-08。

## HITL 汇总（已向维护者提出，见调度会话）

1. 评估集图片：30–50 张真实手稿，覆盖手写/印刷/公式/中英混排/流程图/涂改六类（issue 01 AC）
2. 流程图手稿样本 ≥10 张（issue 04 真实样本；合成样本先行）
3. gold Markdown 人工校对（harness 冒烟产出后进行）
