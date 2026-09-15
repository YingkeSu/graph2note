# Y6 — W1 周报遗留 R1–R5 汇总

Status: ready-for-review

来源：`/tmp/spw-W1-done-report.md` 遗留节；`handoffs/W1-digest-content-structure.md` §6；BOARD W1 行残留 R7/R8。属 I 轨遗留（Y 轨，聚合项）。

## What to build

聚合 W1 reviewer/作者记录的 5 条遗留（每条独立验收，可分批实现）：

- **R1 连续体「待确认对」在生产路径基本为 0**：digest 收到的 records 不带 IR；库 >200 篇时按设计只算显著层。修它需动 `webapp.py`/`store.py`（越 W1 领地）。
- **R2 `stats.inbox_*` 与材料分区口径不同**：`stats.inbox_*` 是 Inbox 原样投影（含「仅缺标签」），材料分区以「无标签才算待整理」；W2 并排展示时需知。
- **R3 meta 变大（KB 级/条）**：无上限/裁剪策略说明。
- **R4 长材料下模型 JSON 稳定性未压测**（有 fallback 兜底）。
- **R5 `llm_calls=0` 时 `elapsed=0.0`**：语义与 A2 的「1 次调用总耗时」不同。

（同一批还有 W1 verdict 残留 **R7** `GENERATOR_VERSION` 进整报指纹无回归测试（功能正确、mutation C 仍绿）与 **R8** 裁剪时 `stats.document_count`（范围内总数）与 `meta.document_count`（选入数）同名异义、概览 source ids 含被裁剪文档——若认为属同一批，在 Comments 追加并补验收。）

## Acceptance criteria

按条拆分，每条独立关闭：

- [x] R1：明确「连续体待确认对」在生产路径的期望口径（0 是否可接受，还是须注入 IR 摘要），并落地其一：要么在 `webapp.py`/`store.py` 侧向 digest 提供 IR 摘要，要么在报告/文档中标注该统计在生产环境不适用；附测试或明确说明无法测的原因。
- [x] R2：统一或显式区分两口径：meta/stats 字段命名区分（如 `inbox_backlog` vs `pending_untagged`）并加断言锁定；W2 前端展示不歧义。
- [x] R3：给出 meta 体积上限/裁剪策略或量化说明（记录实测体积与阈值决策）。
- [x] R4：对长材料（≥ `MAX_DOCS`）做模型 JSON 稳定性压测或离线回退测试，记录坏 JSON/纯散文回退仍产出四节的证据。
- [x] R5：`llm_calls=0`（缓存命中）时 `elapsed` 语义澄清：改字段名/加 `cached` 标注/文档说明，二者取一并加断言。
- [x] R7（可选并入）：`GENERATOR_VERSION` 进整报指纹补回归测试（mutation：删除版本入指纹应红）。
- [x] R8（可选并入）：`stats.document_count` 与 `meta.document_count` 同名异义，改名或加断言区分。
- [x] 每条的落地/未落地逐条记录（不必一次全做；本 issue 可分批，每条独立关闭）。
- [x] 不改 W2 前端行为契约：若 R2/R8 改字段名，需同步 W2 消费端与 node 套件。
- [x] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（R1 需跨 `webapp.py`/`store.py` 领地，排期时先确认）。

## 领地

- 独占：`graph2note/digest.py`、`tests/test_digest_structure.py`、`tests/test_digest_budget.py`、`tests/test_weekly_digest.py`。
- 只追加：`graph2note/store.py`/`graph2note/webapp.py`（仅 R1 需要，追加只读/聚合接口）、`graph2note/webstatic/js/views/dashboard.js`（仅 R2/R8 字段名同步，最小追加）。
- 禁止：破坏 W1 已合并的四节契约（SPEC §3）、`papers/*`、抽取/渲染代码。

## Comments

- W1 done-report 遗留原文见上「What to build」；W1 verdict 残留 R7/R8 记为「功能正确、mutation C 仍绿」与「同名异义、概览 source ids 含被裁剪文档」。
- W2 已合并并消费 `meta.sections`/`stats`；改字段名须回归 `tests/digest_view_dom.mjs`（node 套件）与 `tests/test_digest_view.py`。

## Comments（Y6 交付记录，2026-09-16，分支 `dev/Y6-digest-leftovers`）

基线：`main f0dd99e`（派发记录写 `5f5a70c`；worktree 建在 `origin/main 2fd1f98`，已 `checkout -b` 到本地 main 最新 `f0dd99e`，无历史改写）。未 push。全量 `pytest -p no:warnings` = **1239 passed**（本地 main 基线 1224，+15 新用例）。

逐条落地（每条独立关闭）：

- **R1（已关闭 / 选“标注不适用”路线）**：确认生产路径 `webapp._all_records()`/CLI 都用 `store.get_document`，其 `versions[]` 不含 `ir_json`；
  连续体 suggested 层需 IR（`continuity.document_ir`）故必为 0。**决策：0 属预期，选择在报告中显式标注“不适用”而非注入 IR**——向
  webapp/store 注入需改既有调用点（越“只追加”领地）并为每次周报加载全库 IR。实现：`compute_stats` 增纯函数字段
  `continuity_suggested_applicable`（库内是否有任何可解析 IR）；`render_pending_stats_body` 在不可用时输出
  「（未提供 IR 材料，待确认对不适用）」。测试：`test_continuity_suggested_is_marked_inapplicable_without_ir`（无 IR→False+
  文案）、`test_continuity_suggested_counts_when_records_carry_ir`（带 IR 的两篇尾首重叠→suggested=1 且不标注）。
- **R2（已关闭）**：`stats` 字段显式区分两口径——Inbox 投影：`inbox_pending`（历史别名）+ `inbox_backlog`；材料分区：
  `pending_material_count` / `organized_material_count`（由 `assemble_material` 填充）。`render_pending_stats_body` 增加「待整理材料」
  行并注明“与 Inbox 投影口径不同，不可相加”。前端 `dashboard.js` 最小追加「待整理材料」chip；node 套件 fixture/断言同步。
  测试：`test_inbox_projection_and_material_partition_are_distinct_fields`，node `digest_view_dom.mjs` 两条新断言。
  附带：因 prompt 文案变化，`SECTION_PROMPT_VERSION` 1→2（旧节缓存一次性失效，四节契约不变）。
- **R3（已关闭）**：量化 + 裁剪策略。新增常量 `META_STATS_LIST_LIMIT=50`、`MAX_META_BYTES=262144`（256 KiB/条）；
  `save_digest` 持久化前用 `_meta_stats_view` / `_meta_budget_view` 截断 `stats.topics/tags`、`budget.topics/per_topic_kept`
  （真值仍存 `topic_count`/`tag_count`，内存 stats 不裁剪、渲染不受影响）。**实测**：60 篇、每篇各 1 个互异主题/标签的
  最坏 meta = **17040 B**（约 17 KB）≪ 256 KiB。测试：`test_meta_size_is_bounded_and_verbose_lists_are_capped`。
- **R4（已关闭）**：离线长材料压测。`tests/test_digest_structure.py` 构造 =`MAX_DOCS`(60)、每篇正文 2500 字（触发 2000 字截断）的库，
  覆盖合法分节 JSON（四节 + prompt 含 60 篇 + 截断标记）与 6 种坏回包（截断 JSON / 半截 fence / 纯散文 / JSON 数组 /
  非字符串 markdown / 空 body）——全部 `status=ok`、四节齐全、`## 来源` 在。测试：`test_long_material_json_reply_keeps_the_four_sections`、
  `test_long_material_malformed_replies_still_yield_four_sections`（6 参数）。
- **R5（已关闭 / 选“加字段标注”路线）**：`save_digest` meta 增 `elapsed_scope`：有模型调用=`"model"`，纯缓存（`llm_calls=0`）
  =`"none"` 且 `elapsed=0.0`；docstring 说明 `elapsed` 仅计模型墙钟时间。测试：`test_elapsed_scope_separates_model_time_from_cache_only`。
- **R7（已并入关闭）**：补 `GENERATOR_VERSION` 进整报指纹的回归测试。`test_generator_version_is_part_of_the_report_fingerprint`
  （mutation：删 payload 里 `generator`→该用例红，已实测）+ `test_generator_version_bump_invalidates_the_whole_report_cache`
  （bump 后整报缓存不命中、旧指纹仍可精确命中）。
- **R8（已并入关闭）**：`assemble_material` 增 `material_document_count`/`organized_material_count`/`pending_material_count`，
  与 `stats.document_count`（范围内总数）显式区分；`meta.document_count`（选入数）语义不变。概览 source ids 含被裁剪文档为**有意**（概览按范围），
  用测试锁定。测试：`test_range_total_and_material_count_are_distinct_and_labelled`；`dashboard.js` 选入材料 chip 回退读
  `stats.material_document_count`，node 断言同步。

领地：独占 `graph2note/digest.py` + `tests/test_digest_structure.py`/`test_digest_budget.py`；
`dashboard.js` 仅 R2/R8 最小追加；`tests/digest_view_dom.mjs` 为同步 W2 消费端（AC 要求）。
**未动** `webapp.py`/`store.py`（R1 走标注路线）、`tests/test_weekly_digest.py`（无需改，原断言全绿）、`papers/*`、抽取/渲染代码；
未碰脏文件 `.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`；未 push；密钥未进产物。
