# BOARD：auto-organization

发布日期：2026-09-12
上游：[PRD](PRD.md)（标签聚类治理 / 相似笔记归夹 / 连续笔记合并）；触发 = 维护者反馈「A1 自动打标完成后标签过多过杂，要求自动聚类整理；相似笔记自动归入一个文件夹；显著连续的笔记合并」。
实测证据（2026-09-12 真实库）：43 篇文档 / 词表 243 标签 / 平均每文档 6.7 个 / **212 个（87%）仅一篇文档使用**；Top 标签仅覆盖 2–6 篇（`传递函数`6、`控制理论`5）。

## 发布与执行状态

- 已发布：3（01、02、03）。已认领：0。已完成：3（01、02、03）。已合并：3（01 merge `6baa5dd`、02 merge `da19bdc`、03 merge `edae1e7`）。
- 全部 issue `ready-for-agent` = 需求已就绪；三 issue **互相无阻塞，可全量并行派发**。
- 共同纪律（各 issue 均内嵌）：LLM 只提议 + schema 校验 + 确定性应用 + 人确认后执行；无 embedding；dry-run 预算纪律（03 全程零 LLM）；provenance auto/manual 分流；合并可逆（软归档）。
- 领地隔离：01 独占 `views/tags.js` + 新增 `tagorg.py`；02 独占 `views/library.js` 集合区 + 新增相似度/归类模块；03 独占 `inbox.py`/`views/inbox.js` + 新增检测/合并模块。三者共享文件仅 `store.py`（各自只追加函数）与 `webapp.py` 路由登记（各自只追加端点）——并行领取时调度按并集整合，冲突面小。
- 与 usable-product-iteration 关系：其 A1（自动打标，merge `6fe379e`）是本包上游；S1/S2（Semantic Diff/锚定）是 03 的上游，均已 merged；残余 P3（⌘K 统一搜索）与本包三 issue 无文件交集，可同期在跑。

## Issue 清单

| Issue | 类别 | Blocked by | Status |
|---|---|---|---|
| [01 标签语义聚类与批量治理](issues/01-tag-vocabulary-clustering.md) | 整理 | 无 | merged (6baa5dd) |
| [02 相似笔记自动归类到集合（文件夹）](issues/02-auto-collection-assignment.md) | 整理 | 无 | merged (da19bdc) |
| [03 显著连续笔记的检测与合并](issues/03-continuity-merge.md) | 整理 | 无 | merged (edae1e7) |

## 背景速览

- 标签失控根因：A1 闭环只拦字面变体（`normalize_tag`），语义近义（`sram`/`dram`、`随机存储器`/`只读存储器`）各自成词；治理 UI 仅逐条 `prompt()`，243 词手工不可行。
- 笔记平铺根因：`notes/classify.py` 的归类能力只在导出 Obsidian 时运行、从不回写库内集合；PDF 逐页入库（共享 `source_job_id`）天然碎片化，S2  defer 了内容级关联与合并——本包 03 捡起。
- 集合即文件夹：`collections.py` slug 确定性且是 Obsidian 导出文件夹键，归夹确认后导出自动变现，无需新导出逻辑。
