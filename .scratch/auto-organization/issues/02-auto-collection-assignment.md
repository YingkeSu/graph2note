# 02：相似笔记自动归类到集合（文件夹）

Status: merged
Labels: track-organization

## What to build

覆盖 auto-organization PRD 能力 2。让相似主题的笔记自动聚拢到同一个集合（集合 slug 即 Obsidian 导出文件夹键，归夹结果导出即变现为文件夹）：**确定性相似度生成候选 → LLM 库级归类方案 → 复核确认 → 写入集合归属（auto 来源）**。

现状盘点（写 issue 时核实）：`collections.py` 已有集合注册（slug 确定性、`manual_collections` 为手工归属、图谱 manual 边消费它）；`notes/classify.py` 的 `ClassificationScheme`（topics + assignments + summaries，`validate_scheme` 机器校验，一级类目 ≤ 8）**只在导出 Obsidian 时运行**，从未回写库内集合；record 同时有 `collections`（系统/auto 归属）与 `manual_collections`（手工归属）两个字段，provenance 分流天然成立。真实库 43 篇主题分布目测集中在控制理论/概率论/信号与系统/机械原理/数学分析/计算机组成，适合粗粒度归夹。

- **相似候选生成（确定性，零 LLM）**：`pairwise_similarity(docs) -> [(doc_a, doc_b, score)]` 纯函数——Markdown token 化 + shingle Jaccard（参数显式：shingle 宽、阈值可配）；输入为标题 + 正文（截断上限显式）。43 篇全对仅 903 对，无需索引结构；表驱动快照测试（高相似对/无关对/空库安全）。
- **库级归类推断（LLM）**：输入 = 每文档标题 + 首段摘要 + 标签 + 相似候选对（top-N 截断显式）；输出 = **复用 `ClassificationScheme` 结构**（topics → 集合名，assignments → 文档归属，summaries → 一句话理由），过 `validate_scheme` 后才可落地；一级类目 ≤ 8 沿 `DEFAULT_MAX_TOPICS`。prompt 要求「能并入既有集合就不新建」（注入当前集合注册表）。录制 golden fixture（三类：新建主题归夹、并入既有集合、非法输出被拒）。
- **落地与 provenance 分流**：确认后写入 `record.collections`（auto 来源）；**已手工归类的文档默认不动**——方案可对它们建议追加集合，但必须显式确认才写入，且手工归属（`manual_collections`）永不自动移除。确定性应用函数纯函数化可快照。
- **dry-run CLI**：`graph2note collections organize [--dry-run|--yes]`——dry-run 报告方案（主题数、每主题文档数、待变更文档数、预估调用/token），`--yes` 执行；遥测记录 token（沿 A1 预算纪律）。
- **复核 UI**：Library 集合区（`views/library.js` 领地）加「归类建议」——按主题组展示建议归属（集合名 + 文档清单 + 一句话理由），逐文档接受/拒绝 + 整组接受；文档卡片显示「建议集合」chip 可一键接受。已接受归属立即反映到集合树与 Obsidian 导出（既有行为，无需新导出逻辑）。

## Acceptance criteria

- [ ] 相似度纯函数表驱动测试：高重叠对得分高于阈值、无关对低于阈值、空库/单文档安全空态；阈值上下边界各一例。
- [ ] 归类推断离线可测：录制 golden 覆盖「新建主题」「并入既有集合」「非法输出被拒」（assignments 引用不存在文档、topics 超上限各一例），CI 无真实调用。
- [ ] 应用层纯函数快照：确认子集 → `collections` 写入正确；`manual_collections` 永不自动变更；重复应用幂等。
- [ ] `collections organize` 默认 dry-run 数字与方案一致；`--yes` 执行后集合树/图谱集合边（既有消费路径）可见新归属。
- [ ] UI 复核闭环：建议分组展示、逐文档/整组接受拒绝、chip 快捷接受、持久化（重启后归属仍在）；无建议时的安全空态。
- [ ] API 契约测试（stub store）；遥测 token 记录；handoff 记录真实库 43 篇的归夹分布与预算消耗。

## Blocked by

None - can start immediately
（领地提示：独占 `views/library.js` 集合区与新增相似度/归类模块；`store.py` 仅追加写入函数不改既有字段语义；与 issue 01（tags 视图/词表）和 issue 03（Inbox 队列/合并执行）文件领地不相交；若 03 需要内容相似度可复用本 issue 的 `pairwise_similarity`，但 03 不依赖本 issue 先行）
