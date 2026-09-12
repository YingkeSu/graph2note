# 03：显著连续笔记的检测与合并（PDF 连续页 / 首尾衔接手稿）

Status: merged
Labels: track-organization

## What to build

覆盖 auto-organization PRD 能力 3。PDF 逐页入库把一本讲义拆成共享 `source_job_id` 的 N 份独立文档；重拍/补拍的手稿与原件内容首尾衔接——这些**显著连续的笔记应合并成一篇**，而不是并列堆积。本 issue 捡起 S2 明确 defer 的两块：内容级跨文档关联、（受控的）合并执行。

现状盘点（写 issue 时核实）：S1 `DiffReport`（IR 块级 diff 纯函数）与 S2 演进锚定（版本链 + `versions_for_original_phash` 跨文档候选）均已 merged；S2 纪律「只建议、确认后才关联」延续到本 issue；R1 的版本来源标注字段约定（repair）为 merge 来源标注提供范式；Inbox 已有「待整理」只读投影与 reason 标签体系（`inbox.py` REASON_LABELS）。

- **连续对检测器（确定性为主）**：`detect_continuity(records) -> [{doc_a, doc_b, order, evidence, tier}]` 纯函数，两档置信：
  - **显著档（significant）**：同 `source_job_id` 且页序相邻（页码自 record/job 元数据读取，字段位置实现时核实）——同一 PDF 的连续页；
  - **疑似档（suggested）**：pHash 跨文档候选（复用 S2）**且**尾首块重叠——doc A 末尾 N 块与 doc B 开头 N 块的 S1 块级匹配（N 与匹配率阈值显式可配），判定衔接方向（order = A→B）。
  - 已归档（`merged_into`）文档不参与检测；已确认/已拒绝的对不重复建议（拒绝记忆持久化，沿 S2「拒绝后不再重复提示同一对」口径）。
- **合并执行器（确定性）**：`merge_documents(store, doc_a, doc_b) -> merge_report`——IR 块拼接 + 重叠区去重（消费 S1 DiffReport 定位尾首重叠块，重叠块只保留一份）；产物作为**新文档**入库：标题取首文档、正文为拼接结果、版本链首版标注来源 `merge`（含两个源 document_id，沿 R1 repair 字段约定）；标签取并集（provenance 逐标签保留）、集合取并集（auto/manual 来源不变）。**原两文档软归档**：标记 `merged_into: <new_id>` 不删除——Library 默认列表排除归档稿、直达路由仍可达、恢复 = 清除标记。
- **执行策略（绝不静默合并）**：显著档支持批量——CLI `graph2note docs merge-continuous [--dry-run|--yes]`，dry-run 报告连续对数/证据/预估零 LLM 调用（检测与合并全程确定性，无预算问题）；疑似档只进确认队列逐条确认。两档都在 UI 留确认动作，CLI 批量仅限显著档。
- **确认队列 UI**：Inbox 新增 reason「可合并」（`REASON_LABELS` 追加）或独立区块（实现时择一，倾向复用 Inbox 投影）——每条展示证据（「同 PDF 第 m–n 页」/「尾首重叠 N 块」+ 双方标题/缩略图）、确认合并/拒绝；合并后编辑器版本链可见 merge 事件与两个源文档链接（消费 S3 版本切换器既有 UI）。

## Acceptance criteria

- [ ] 检测器表驱动测试：同 job 连续页 → 显著档；pHash 候选 + 尾首重叠 → 疑似档且方向正确；无关对不报；已归档/已拒绝对不重复出现；阈值上下边界各一例。
- [ ] 合并执行器纯函数/集成快照：fixture 两篇重叠文档 → 拼接后重叠块仅一份、无内容丢失（块计数守恒断言：|A| + |B| − |重叠| = |合并|）；标签/集合并集与 provenance 正确；merge 来源字段沿 R1 约定写入。
- [ ] 软归档闭环：归档稿从 Library 默认列表排除、直达路由可达、清除 `merged_into` 后恢复列表可见；归档稿不再参与连续检测与自动打标回填。
- [ ] CLI 默认 dry-run 计数与检测器一致；`--yes` 仅执行显著档；疑似档永远需要逐条确认（API 层拒绝批量）。
- [ ] UI 队列闭环：证据展示、确认/拒绝持久化（重启后不重复提示）、合并后版本链 merge 事件可见；无可合并项的安全空态。
- [ ] API 契约测试（stub store）+ 全程零 LLM 调用断言；handoff 记录真实库 43 篇的连续对检测结果与合并执行清单。

## Blocked by

None - can start immediately（S1/S2 均已 merged，本 issue 直接消费）
（领地提示：新增检测/合并模块 + `inbox.py`/`views/inbox.js` 追加 reason；`store.py` 仅追加软归档字段与查询；与 issue 01（tags 视图）、issue 02（Library 集合区）文件领地不相交；与 usable-product-iteration 残余 P3 无交集）
