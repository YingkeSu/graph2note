# 01：标签语义聚类与批量治理（词表瘦身 + 主题分组）

Status: ready-for-agent
Labels: track-organization

## What to build

覆盖 auto-organization PRD 能力 1。把标签治理从「逐个 `prompt()` 手工合并」升级为「LLM 审计 → 方案校验 → 批量复核 → 确定性应用」闭环，词表持久化主题分组。

现状盘点（2026-09-12 对真实库实测）：43 篇文档、词表 243 个标签、平均每文档 6.7 个、**212 个（87%）仅一篇文档使用**；语义近义并存（如 `sram`/`dram`、`随机存储器`/`只读存储器` 各自独立），`normalize_tag` 只规范字面变体管不了语义。`tags.py` 已有 `merge_vocabulary_tags`/`rename_vocabulary_tag`/`resolve_tag` 全套确定性治理函数；`autotag.py` 已有 LLM 推断 + 录制校验 + 遥测的完整范式可复刻；`views/tags.js` 只有逐条 rename/merge。

- **治理方案推断函数**（新，建议放 `tags.py` 旁新模块如 `tagorg.py`）：输入 = 词表（规范名 + 别名 + 每标签文档计数，计数由 store 注入）；输出 = `TagGovernancePlan`（pydantic）：`merges: [{source, target, reason}]`（同义/近义合并对）、`groups: [{name, tags: [...]}]`（主题分组，一级类目 ≤ 8、宜粗不宜细）。校验规则沿 `validate_tag_inference` 口径并加引用完整性：source/target 必须能 `resolve_tag` 命中词表、merge 不得成环（A→B 且 B→A）、group 内标签必须存在于词表、group 名过 `normalize_tag`；任一违反整案拒绝。prompt 要求「能合并就不新建、组名复用既有高频标签优先」。零网络测试用录制 golden（三类：同义合并、主题分组、非法输出被拒——含引用不存在标签与成环各一）。
- **确定性应用层**：`apply_governance_plan(vocabulary, records, plan, accepted) -> report` 纯函数——merge 逐对走 `merge_vocabulary_tags`（自动带别名与文档成员更新）；groups 写入词表 **schema v2**：顶层新增 `groups: {name: {tags: [canonical...]}}`；`normalize_vocabulary` 兼容 v1（无 `groups` 字段 → 空表），v1→v2 迁移无损（别名/计数视图不变）。首版取舍：**一个标签至多属于一个主题组**，重复归属时方案校验阶段即拒绝。
- **dry-run CLI**：`graph2note tags organize [--dry-run|--yes]`——默认 dry-run 输出方案摘要（合并对数、分组数、每组规模、预估 LLM 调用/token）不落盘；`--yes` 执行并输出应用报告。沿 A1 `tags backfill` 预算纪律与遥测（每次推断 token 入 telemetry）。
- **复核 UI**（`views/tags.js` 升级 + 所需 API）：「整理建议」模式——请求方案后端缓存后分组展示：合并对逐条（`source → target` + 理由 + 各挡文档计数，接受/拒绝），主题组整组展示（组名 + 成员标签 + 规模）；支持一键全接受。确认集合（accepted 子集）提交应用端点，执行后词表视图按组渲染（组头 + 组内标签，未分组标签归入「未分组」）。应用端点幂等：重复提交同一方案不产生二次 merge 副作用。

## Acceptance criteria

- [ ] 推断函数离线可测：录制 golden fixture 覆盖「同义合并」「主题分组」「非法输出被拒」（引用不存在标签 / merge 成环各至少一例），CI 无真实调用。
- [ ] 应用层纯函数快照测试：fixture 词表 + 文档记录 → merge 后别名/成员正确、groups 落 v2 结构；v1 词表 normalize 后行为不变（回归测试）。
- [ ] 词表 v1→v2 迁移无损：旧库打开后别名、重命名/合并既有功能全绿（既有 tags/store 测试不红）。
- [ ] `tags organize` 默认 dry-run：报告的合并对数/分组数与方案一致、预估调用数与实际一致（fixture 断言）；`--yes` 执行后词表收敛且报告落遥测。
- [ ] UI 复核闭环：方案分组展示、逐条接受/拒绝、一键全接受、应用后分组渲染持久化（重启后分组仍在）；重复提交幂等。
- [ ] API 契约测试（stub store）：方案生成/应用两端点的请求响应与错误路径（方案过期、标签已被并发改名）。
- [ ] 遥测记录每次推断 token；handoff 记录真实库（43 篇/243 标签）治理结果：合并对数、最终标签数、分组分布与预算消耗。

## Blocked by

None - can start immediately
（领地提示：独占 `views/tags.js` 与新增 `tagorg.py`；`/api/tags/*` 仅追加端点不改既有契约；与 usable-product-iteration 残余 P3（⌘K 搜索）无文件交集）
