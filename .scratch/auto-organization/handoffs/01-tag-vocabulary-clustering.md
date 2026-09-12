# Handoff 01 — 标签语义聚类与批量治理（词表瘦身 + 主题分组）

Branch: `dev/01-tag-vocab-clustering` · Issue: `.scratch/auto-organization/issues/01-tag-vocabulary-clustering.md` · Status: ready-for-review

## 1. 一句话结论

标签治理已从「逐个 `prompt()` 手工合并」升级为 **LLM 审计 → schema/引用完整性校验 →
批量复核 → 确定性应用** 的闭环：`tagorg.TagGovernancePlan`（merges + groups）整案校验
（引用不存在标签 / 成环 / >8 组 / 一标签多组 → 整案拒绝），`apply_governance_plan` 纯函数
逐对复用 `merge_vocabulary_tags` 并把主题分组写入词表 **schema v2**（v1 无损迁移）；
`graph2note tags organize` 默认 dry-run（预算报告、不落词表），`--yes` 应用并落遥测；
`views/tags.js` 新增「整理建议」复核模式（逐对接受/拒绝 + 整组 + 一键全接受 + 分组持久化渲染）。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/tagorg.py`（新） | `TagGovernancePlan`/`TagMergeSuggestion`/`TagGroupSuggestion`（pydantic）；`validate_governance_plan`（引用完整性 + 无环 + ≤8 组 + 一标签至多一组，任一违反整案拒绝）；`build_prompt`（全量词表 + 计数 + 别名）；`infer_governance`（planner 缝，复用 autotag 的 JSON 提取/usage 归一范式的录制校验）；`live_planner`（唯一 live choke point，classify 渠道）；`estimate_budget`；`plan_summary`；`vocabulary_fingerprint`；`ensure_accepted_resolvable`；`apply_governance_plan`（纯函数）；`record_governance_event`/`load_governance_log`（token 遥测） |
| `graph2note/tags.py` | 词表 **schema v2**：`new_vocabulary` 增 `groups`；`normalize_vocabulary` 兼容 v1（无 `groups` → 空表，别名/计数不变）；`_remap_group_tags` 让既有 merge/rename 同步修正分组归属 |
| `graph2note/store.py`（只追加） | 治理应用缝：`tag_records` / `save_tag_vocabulary` / `save_tag_records`（Session + File 两实现；写入时 `ensure_tag_provenance`） |
| `graph2note/webapp.py`（只追加） | `create_app(tag_organize_planner=)` 注入缝 + 内存方案缓存；新增 `GET /api/tags/groups`、`POST /api/tags/organize/plan`、`POST /api/tags/organize/apply`（既有 `/api/tags*` 契约零改动） |
| `graph2note/cli.py` | `graph2note tags organize [--dry-run\|--yes] [--storage\|--model\|--provider\|--json]`，默认 dry-run；沿用 A1 预算纪律与遥测 |
| `graph2note/webstatic/js/views/tags.js`（独占） | 词表按 v2 分组渲染（组头 + 成员 + 「未分组」）；「整理建议」模式：合并对逐条接受/拒绝、主题组整组、一键全接受、应用端点幂等；纯渲染函数导出供离线 Node 测试 |
| `tests/test_tagorg.py`（新，23 项）+ `tests/golden/tagorg-{merges,groups,single-merge,single-group,invalid-reference,invalid-cycle}.json` | 录制 golden 三类（同义合并 / 主题分组 / 非法输出被拒，含引用不存在与成环）；纯函数快照；v1 回归；CLI dry-run=--yes；API 契约（过期/并发改名/幂等）；遥测 |
| `tests/tag_organize_dom.mjs`（新） | 离线 DOM 契约：分组渲染 → 方案复核 → 拒绝某合并 → 应用（accepted 子集）→ 分组重渲染 |
| `tests/taxonomy.py` | 登记 `test_tagorg → workspace`（integration） |

## 3. 关键决策

- **整案拒绝，绝不部分应用**：任何引用不存在标签、merge 成环（含自环）、重复 source、
  >8 个主题组、组名非法/重复、组内标签不存在、一标签属多组 —— `validate_governance_plan`
  抛 `TagGovernanceError`，`infer_governance` 把它变成 `plan=None + warning`，调用方（CLI/API）
  一律不落地。模型输出先过 JSON 提取 + pydantic，再对照当前词表做引用校验。
- **merge 顺序 sink-first**：`A→B` 且 `B→C` 的链按「目标不再是 source」优先执行，
  否则链式合并会因中间标签消失而失败；`merge_vocabulary_tags` 的别名解析保证两种合法顺序
  收敛到同一终态。
- **幂等**：第二次应用同一方案时 source 已并成 alias，`source==target`/`changed=False` 记为
  skipped，报告 `merged=0`、词表字节级不变（`test_apply_is_idempotent`）。API 侧首次应用后
  把缓存方案的词表指纹更新为应用后的值，因此重复提交返回 200 而非 409。
- **apply 重写整张分组表**：治理方案即「期望的完整分组」，应用时以方案的 groups 覆盖
  `vocabulary["groups"]`（未接受的分组落为未分组）。首版取舍：一个标签至多属一个主题组；
  merge 后组内成员跟随其规范标签（`resolve_tag` 再解析）。
- **v1→v2 无损**：`new_vocabulary` 输出 v2；`normalize_vocabulary` 对 v1 补空 `groups`，
  别名/计数/成员行为不变；既有 rename/merge/导出/图谱等消费方零改动。旧库首次写入时自然升 v2。
- **dry-run 语义**：默认 dry-run 会做 1 次方案推断（否则无法给出方案摘要），只输出摘要 +
  预算，**不写词表**；仅追加一条 token 遥测事件（满足「每次推断 token 入 telemetry」）。
  `--yes` 再推断 1 次并应用。预估调用数（1）与 `--yes` 实际调用数一致（fixture 断言）。
- **无 embedding**：语义聚类完全走 LLM 提议 + 确定性应用，沿仓库既有决定。
- **API 只追加**：`GET /api/tags`、rename/merge 契约原样；新增三个端点。前端经
  `/api/tags/groups` 读分组（含未分组别名+计数），不解析 `tag-vocabulary.json`。

## 4. AC 逐条证据（离线）

| AC | 证据 |
|---|---|
| 1 推断函数离线可测：同义合并 / 主题分组 / 非法输出被拒（引用不存在 + 成环）四类 golden，CI 无真实调用 | `test_infer_synonym_merges_golden`（`tagorg-merges.json`，`planner.calls==1`，usage 归一）、`test_infer_theme_groups_golden`、`test_infer_rejects_missing_reference_golden`（warning 含「不存在」）、`test_infer_rejects_merge_cycle_golden`（warning 含「成环」）；另有 `test_validation_rejects_too_many_groups_and_double_membership`、`test_build_prompt_lists_vocabulary_with_counts` |
| 2 应用层纯函数：merge 后别名/成员正确、groups 落 v2；v1 normalize 回归 | `test_apply_merges_and_writes_groups_v2`（链式 merge + 成员 dedupe + `groups` v2 + labels 7→5）、`test_apply_respects_rejected_subset`、`test_apply_is_idempotent`、`test_normalize_vocabulary_v1_to_v2_is_lossless` |
| 3 词表 v1→v2 迁移无损；既有 tags/store 测试全绿 | `test_v1_vocabulary_file_still_governs_then_migrates`（v1 文件加载 → list_tags 计数/别名不变 → merge 后落 v2 + 空 groups）、`test_merge_remaps_existing_group_membership`；全量 `uv run pytest` **800 passed**（基线 777 + 新增 23） |
| 4 `tags organize` 默认 dry-run：报告数=方案、预估调用=实际；`--yes` 收敛并落遥测 | `test_cli_organize_defaults_to_dry_run_without_writing`（`merge_count/group_count` 与 golden 一致，`estimated_calls=1`、`calls=0`、词表文件字节不变）、`test_cli_organize_yes_applies_and_records_telemetry`（`estimated_calls==calls==1`、`merged=1`、`tag-governance.json` 事件含 `total_tokens`）、`test_cli_organize_rejects_illegal_plan` |
| 5 UI 复核闭环：分组展示 / 逐条接受拒绝 / 一键全接受 / 应用后分组持久化 / 重复提交幂等 | Node `tests/tag_organize_dom.mjs`（`test_tag_organize_node_contract`）：分组渲染 + 未分组、方案复核、拒绝 sram 合并后 apply body `accepted.merges==[]`、应用后按组重渲染；API `test_api_apply_is_idempotent`（二次 apply 200 且 `merged==0`，新 store 重载 `groups` 仍在）、`test_api_plan_and_apply_persist_groups` |
| 6 API 契约（stub store）：方案生成/应用两端点请求响应 + 错误路径（方案过期、并发改名） | `test_api_plan_and_apply_persist_groups`（plan 字段 + apply 报告 + `GET /api/tags/groups`）、`test_api_plan_unknown_id_and_concurrent_rename_errors`（未知 plan_id→404；rename 后指纹变化→409「词表已变化」）、`test_api_plan_invalid_reply_is_502`、`test_api_plan_transport_failure_is_502_without_key_leak`、`test_api_groups_render_and_ungrouped`、`test_session_store_governance_seam` |
| 7 遥测记录每次推断 token；handoff 记真实库结果 | CLI/API 每次 plan 推断写 `tag-governance.json` 事件（`usage`/`total_tokens`/model/provider）；真实库记录见 §6 |

## 5. 如何运行

```bash
uv run pytest tests/test_tagorg.py            # 23 passed
node tests/tag_organize_dom.mjs               # DOM 契约
scripts/run_tests.sh workspace                # 模块级
uv run pytest                                 # 800 passed（全量离线，零真实网络）

# 治理（默认 dry-run，核对后加 --yes）
uv run graph2note tags organize --dry-run
uv run graph2note tags organize --yes
```

## 6. 真实库 dry-run 记录（43 篇 / 243 标签）

**数据**：`~/Library/Application Support/Graph2Note/storage`（为不改动真实库，先 `cp -R` 到
`/tmp/g2n-real-storage` 再跑；源库零写入）。确定性审计：

| 指标 | 值 |
|---|---|
| 文档数 | 43 |
| 词表标签数 | 243 |
| 仅一篇文档使用的标签 | 212（87.2%） |
| 别名总数 | 0 |
| Top 标签 | 传递函数 6、控制理论 5、系统极点 4、信号与系统 3、傅里叶变换 3… |
| 词表版本 | v1 → normalize 后 v2（groups 为空） |

**预算消耗（真实 243 标签 prompt）**：prompt 3130 字符 ≈ **2087 prompt tokens**，
输出上限 4096 tokens，预估总消耗 ≈ **6183 tokens / 1 次调用**。

**零预算说明（重要）**：本机未配置任何 LLM key（`env` 无 `*_API_KEY`，仓库根无 `.env`），
真实调用直接命中预算闸门：

```
$ uv run graph2note tags organize --dry-run --storage /tmp/g2n-real-storage
storage=/tmp/g2n-real-storage
治理方案生成失败：未找到 OPENCODE_API_KEY（环境变量或仓库根 .env）
rc=1
```

因此**未做真实 LLM 推断**，只做了 **dry-run 结构验证**：用离线确定性 planner（对真实词表构造
≤8 组、成员全部命中真实标签的合法方案）跑完整 `infer_governance → 校验 → 摘要 → 预算` 链路，
证明 43/243 规模下方案能被接受且预算可测：

| 结构验证项 | 值 |
|---|---|
| planner 调用 | 1（离线） |
| 方案被接受 | 是（无 warning） |
| 合并对数 | 0（离线结构方案不含合并；真实合对数需 LLM 推断） |
| 分组分布 | 8 组 × 3 标签（传递函数 / 信号与系统 / 平面连杆机构 / llm / ocr识别 / 信息论 / 周期信号 / 开集与闭集） |
| 若应用后标签数 | 243（0 合并） |
| token | prompt 3130 chars ≈ 2087 tokens + 4096 输出上限（离线 usage 记 3130） |

> 真实 LLM 治理（合并对数、收敛后标签数、主题分布）需在配置 key 后执行
> `tags organize --dry-run` 核对预算、再 `--yes`。零预算下不作任何真实推断，符合 issue
> 的 dry-run 预算纪律。

## 7. 未尽事项 / 建议

1. **一标签多主题组**：首版硬约束「一个标签至多属一个组」，方案校验阶段即拒绝；多归属
   留 follow-up（PRD 明确记录）。
2. **apply 覆盖整张分组表**：治理方案视为完整期望；若未来需要「增量追加分组」语义，
   改为 upsert + 冲突仲裁即可（不改纯函数签名）。
3. **方案缓存为进程内存**：`app.state.tag_organize_cache` 重启即失效（plan_id 404 提示重新生成）；
   分组本身已持久化在词表，重启后渲染不受影响。
4. **dry-run 写遥测**：dry-run 只追加 `tag-governance.json` 的 token 事件，不写词表；
   若希望 dry-run 完全零写盘，可给 `record_governance_event` 加开关。
5. **真实 LLM 复核**：零预算未做，需维护者配置 key 后按 §6 复核真实合并质量。

## 8. Suggested skills

- `/code-review`：审查 `tagorg.apply_governance_plan` 的链式顺序与幂等语义、webapp 端点错误路径。
- 真实数据验收：`scripts/run_tests.sh --all` + 配置 key 后 `graph2note tags organize`。

## 9. 相关文件

- 实现：`graph2note/tagorg.py`、`graph2note/tags.py`、`graph2note/store.py`、`graph2note/webapp.py`、`graph2note/cli.py`
- 前端：`graph2note/webstatic/js/views/tags.js`
- 测试：`tests/test_tagorg.py`、`tests/tag_organize_dom.mjs`、`tests/golden/tagorg-*.json`、`tests/taxonomy.py`
- 上游：`../auto-organization/PRD.md`、`../auto-organization/issues/01-tag-vocabulary-clustering.md`
