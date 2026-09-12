# Handoff — auto-organization Issue 02：相似笔记自动归类到集合（文件夹）

**Status: ready-for-review** · AO worker：graph2note-51（修复轮：graph2note-55，评审打回后） · Branch：`dev/02-auto-collection`（基线 `8d3b5f2`）
**提交**：`2002907` `b850e40` `21f3e87` `965fc26` `2295b3c` `3cd2261` + 修复轮（见 §7 修复记录）
**验证**：全量 `uv run pytest` 绿（808 + 新增回归）/ `node tests/collection_suggestions.mjs` 绿；全套零网络调用。

---

## 1. 交付物清单

| 文件 | 角色 |
|---|---|
| `graph2note/similarity.py`（新） | 确定性候选：Markdown 归一化 → ASCII/CJK token → shingle Jaccard。`pairwise_similarity` / `pairwise_scores` / `jaccard_similarity` / `shingles` / `tokenize_markdown`，纯函数、零 LLM、零 I/O；独立可导入供 issue 03 复用。 |
| `graph2note/collection_organize.py`（新） | 库级归类：prompt 构建 → planner 缝 → `parse_scheme_json` → `validate_scheme`（复用 `notes/classify.py`，`DEFAULT_MAX_TOPICS=8`）→ 方案缓存 → provenance 分流应用 → 遥测。含 `project_assignments`（纯函数投影，可快照）与 `apply_assignments`（落盘、幂等）。 |
| `graph2note/cli.py`（增） | `graph2note collections organize [--dry-run\|--yes]`（`--offline/--force/--no-cache/--include-manual/--json` + 相似度参数），默认 dry-run。 |
| `graph2note/webapp.py`（增） | `GET/POST /api/collections/suggestions`、`POST /api/collections/suggestions/apply`；`create_app(organize_planner=...)` 注入缝。 |
| `graph2note/collections.py`（增） | `apply_topic_defaults` 认识新 `record['auto_collections']` 桶：`collections = manual + auto + topic-derived`，并对失效 auto 归属做 registry 清理（删除/改名不复活）。 |
| `graph2note/store.py`（增） | `add_auto_collections`（Session + File），`rename_collection` 同步重映射 `auto_collections`；既有字段语义未改。 |
| `graph2note/graph.py`（增） | 图谱集合节点/边/筛选计入 `auto_collections`（`_collection_memberships`），topic 派生集合仍不进图谱。 |
| `graph2note/webstatic/js/collection_suggestions.js`（新） | 纯渲染/接线模块：`normalizeSuggestions` / `suggestionsHtml` / `suggestionDocMap` / `suggestionChipHtml` / `wireSuggestionActions` / `wireSuggestionChips`。 |
| `graph2note/webstatic/js/views/library.js`、`index.html`、`state.js`、`style.css` | Library 集合区「归类建议」：主题分组、逐文档/整组接受拒绝、卡片「建议集合」chip、空态；接受后刷新网格 + 集合树。 |
| `tests/test_collection_organize.py`、`tests/collection_suggestions.mjs`、`tests/golden/organize-*.json` | 离线契约（31 条）；`tests/taxonomy.py`、`docs/testing.md` 登记。 |

## 2. AC 逐条证据（issue 全文 6 条）

1. **相似度纯函数表驱动 + 边界** — `tests/test_collection_organize.py::test_pairwise_similarity_table`（高重叠 1.0、无关 0.0、阈值 0.333333 命中、0.333334 排除、空库 `[]`、单文档 `[]`）；`test_shingles_and_jaccard_are_pure_building_blocks`；`test_pairwise_scores_deterministic_and_all_pairs`；`test_similarity_ignores_markdown_scaffolding_and_truncates`（代码块/URL 剔除、`max_chars` 截断）。
2. **归类推断离线可测（三类 golden）** — `organize-new.json`（新建主题，`test_plan_collections_golden_new_topic`）、`organize-merge.json`（并入既有集合，`test_plan_collections_golden_merges_into_existing_collection`，断言 `new_collections` 不含既有集合）、`organize-invalid-unknown-doc.json`（`test_plan_rejects_unknown_document_golden`）、`organize-invalid-too-many.json`（`test_plan_rejects_too_many_topics_golden`）；`test_build_prompt_injects_collections_candidates_and_truncates` 验证「优先并入既有集合」注入与 top-N/文档上限截断。注入 planner，CI 零 live。
3. **应用层纯函数快照 + manual 永不自动变更 + 幂等** — `test_project_assignments_is_pure_and_snapshot_stable`（两次输出相同、输入未被改写）；`test_apply_assignments_subset_and_manual_protection`（子集确认、手工文档默认不动、显式确认后仅追加 auto）；`test_apply_assignments_is_idempotent`（第二次 `applied == []` 且集合不变）；`test_auto_membership_survives_topic_recompute`、`test_deleting_collection_drops_auto_membership`。
4. **CLI dry-run 数字 = `--yes`，归属在既有消费路径可见** — `test_cli_collections_organize_dry_run_then_yes`：dry-run `pending_count == 3`，`--yes` `calls_made == 0`（复用缓存）、`applied_count == 3`、`topics` 一致；随后 `list_collections()` 有归属，`/api/graph` 出现 collection 节点与集合边。`test_cli_collections_organize_rejects_illegal_scheme` 验证非法输出被拒且不落缓存。
5. **UI 复核闭环 + 持久化 + 空态** — `tests/collection_suggestions.mjs`（31 条中的 1 条 Python 用例运行）：分组渲染、逐文档 accept/reject、整组 acceptGroup/rejectGroup、`confirmation_required` 标记、chip、空态/完成态、转义、点击与 Enter 派发、重复接线不重复触发；`test_collection_suggestions_frontend_is_wired` 断言 `index.html` 挂载与 `library.js`/`collection_suggestions.js` 接线；`test_suggestions_api_generate_apply_persist_and_telemetry` 用新 `FileDocumentStore` 重载断言归属仍在；`test_suggestions_api_manual_document_requires_confirmation` 覆盖手工文档需显式确认。
6. **API 契约（stub store）+ 遥测 token** — `test_api_contract_against_in_memory_stub_store`（`SessionDocumentStore`）、`test_suggestions_api_*`（`TestClient` + 注入 golden planner）；`collection-organize.json` 记录 `usage.total_tokens=362`（`test_suggestions_api_generate_apply_persist_and_telemetry` 断言），并断言遥测文本不含 key 字样。

## 3. 真实库 43 篇 dry-run 记录（只读实测）

命令（**不读不写 plan 缓存/遥测**，`--offline` 确定性规划器；真实库目录未产生任何新文件、`record.json` mtime 未变）：

```
uv run python -m graph2note.cli collections organize --offline --dry-run \
  --no-cache --json --storage "/Users/suyingke/Library/Application Support/Graph2Note/storage"
```

- 文档 **43** 篇；全对 **903** 对；跨 3-char shingle、阈值 0.08 的相似候选 **4** 对：
  - `0.173` doc-75d37e7d26 ~ doc-ef525ae0a8（两篇「手稿电子化管线」）
  - `0.170` doc-12eacd6e8b ~ doc-2e5b047680（概率论）
  - `0.114` doc-12eacd6e8b ~ doc-803f3425e7（概率论）
  - `0.098` doc-2e5b047680 ~ doc-803f3425e7（概率论）
- 归夹分布（离线规则规划器，`model=rule-classifier`，跨主题去重后 43 篇待变更，0 篇手工需确认）：数学 **33** / 杂项 **6** / 物理 **5** / 笔记 **3** / 计算机 **1**（一篇可属多主题，故分组计数合计 48）。
- 预算：确定性路径 **0 token / 0 网络调用**；换算为 live 归类调用 = **1 次** gateway 请求，prompt 约 4.8k 字符（`estimated_tokens≈1199`）。
- **偏差说明**：本 worktree 无 `.env`、当前运行环境无 `OPENCODE_API_KEY`，故未执行 live LLM 归类（不打印/不落盘任何 key）。主检出 `/Users/suyingke/Programs/OHO/graph2note/.env` **存在**（键名：`KIMI_API_KEY` / `DEEPSEEK_API_KEY` / `GRAPH2NOTE_GATEWAY`）；`.env` 被 gitignore，未跟踪文件不随 worktree 分发，故本 worktree 确实没有。这几个 key 正是 `classify` 通道所用，配置后可在主检出对同命令跑 live 归类。上表分布来自确定性规则规划器；live 路径经同一 prompt/校验/落地回路，测试用录制 golden 覆盖。

## 4. 决策与对 spec 的偏离

- **新增 `record['auto_collections']` 桶**：`apply_topic_defaults` 原本把 `collections` 重算为 `manual + topic-derived`，纯 auto 归属会被读路径抹掉。为满足「auto 可区分、manual 永不自动变更」，新增机器归属桶并做 registry 清理；`collections` 仍是既有消费路径用的有效列表（集合树/图谱/导出文件夹零改动变现）。这是 additive schema 扩展，既有字段语义未变。
- **图谱集合边**：既有图谱只投影 `manual_collections`；AC4 要求 `--yes` 后图谱集合边可见，故 `graph.py` 改为 manual+auto（topic 派生集合仍不入图，保持既有图谱测试不变）。
- **方案缓存**：dry-run 与 `--yes` 共用一次模型调用（`<storage>/collection-plan.json`，按库指纹）；`--no-cache` 供严格只读实测。指纹只含文档内容+参数、不含 registry（否则应用后缓存立即失效）。
- **手工文档确认**：`--yes` 默认只写非手工文档；`--include-manual` 才是对既有手工归类文档的显式确认；API/UI 侧逐文档 accept 即显式确认。**“忽略”只记录 rejected、不写任何归属**（见 §7 BLOCKER 修复）。
- **无 embedding**：沿仓库决定，相似度走 shingle Jaccard，归类走 LLM 提议 + schema 校验 + 确定性应用。

### 领地说明（Minor 4）

BOARD 约定共享文件 `store.py`「各自只追加函数」；本分支在既有 `rename_collection` 函数体内插入了 `auto_collections` 重映射两行（Session/File 各一处，`store.py:1269`/`618` 附近）。**理由**：重映射必须与重命名同事务（改名与归属改写原子），无法做成纯追加函数；两行保持追加语义（只补 auto 桶重映射、不改既有字段语义），冲突面极小。记录在案。

## 5. 未尽事项 / 后续

- live LLM 归类质量未在本环境实测（无 key）；真实归夹分布需在有 key 环境以同命令 `--dry-run`（或 `--yes`）复跑一次。
- 已接受 auto 归属目前只能通过删除/改名集合回收（未做「撤销单条自动归属」入口）；手工 set_collections 也不会清除 auto（符合「manual 永不自动变更」，但可能需要后续「取消自动归类」动作）。
- ~~重命名集合会丢失该集合上 auto-only 的归属~~ **已解决（表述修正）**：`store.py` 的 `rename_collection`（Session/File）已在同一事务内重映射 `auto_collections`，实测 `auto ['自动'] → ['新名']` 且归属保留（评审实测确认）。此前的 follow-up 描述已过期，删除。
- **图谱 auto 边 provenance（评审 Minor 2，本次未修）**：`graph.py::_collection_memberships` 目前对 manual+auto 统一发 `source="manual"`，图谱图例（`views/graph.js`）把机器归属显示为「手工」；记录级 provenance（`auto_collections` vs `manual_collections`）仍正确，AC4 只要求「可见」。Follow-up：给 auto 独立 edge source + 图例标签，并同步 `EDGE_SOURCES` / `ALL_SOURCES` / 既有图谱断言（`tests/test_graph.py`、`tests/test_graph_layout.py` 的精确 source 集合断言需一并更新）。

## 6. Suggested skills

- 复核 UI：`impeccable`（集合区视觉/交互审查）
- 归类质量评估：`diagnose`（如 live 方案分布异常）

## 7. 修复记录（评审打回轮，graph2note-55）

评审 verdict：changes-requested（`/tmp/review-org02-verdict.md`），1 BLOCKER + 3 minor。修复提交追加在本分支（不 rebase、不合并 main）。

### BLOCKER 1 — 「忽略」静默全量 apply（已修）

- **根因**：「忽略/整组忽略」的请求体未包含 `accept`（`library.js` 旧代码 `if (accept.length) body.accept = accept`），服务端 `accept=None` 落到 `apply_assignments(..., include_manual=True)`，`None` 被解释为「整份方案全量接受」，连 `manual_collections` 文档也被追加 auto 归属。
- **修复（服务端）**：`collection_organize.apply_suggestions()` 对 `accept is None` 的请求只记录 `rejected`、**不写任何归属**（`applied == []`）。接受路径显式传 `accept` 列表，行为不变；CLI `--yes` 仍走 `generate_suggestions` → `apply_assignments(accept=None)` 的全量路径（其 `None` 语义保留）。
- **修复（前端）**：新增纯函数 `collection_suggestions.suggestionApplyBody(accept, reject)`，`accept` **恒出现**（reject-only 时为 `[]`）；`views/library.js::applySuggestion` 改用它，使「忽略」与「接受其余」在请求体上可区分。
- **回归测试**：
  - Python `test_suggestions_api_reject_only_writes_nothing`：reject-only（`{"reject":[...]}` 与 `{"accept":[],"reject":[...]}`）后 `applied == []`，含 `manual_collections` 的文档与其余文档的 `collections`/`auto_collections`/`manual_collections` 全不变，仅 `rejected` 累积；随后显式 `accept` 仍只写确认子集。
  - Python `test_apply_suggestions_none_accept_is_a_noop`：`apply_suggestions(accept=None)` 单元级只记录不写。
  - Node `tests/collection_suggestions.mjs`：断言 reject 点击的请求体为 `{accept: [], reject: [...]}`（`accept` 键存在）、accept 请求含两字段。
  - 独立复现脚本 `/tmp/verify_reject_fix.py`（离线 stub planner）复验：ignore 前后 `doc-a` 保持 `['手工集合']`、`auto=[]`。
- **API 契约兼容**：既有 `accept` 路径行为未变（`test_api_contract_against_in_memory_stub_store`、`test_suggestions_api_manual_document_requires_confirmation`、`test_suggestions_api_generate_apply_persist_and_telemetry` 均绿）。

### Minor 3 — handoff 表述（已修）

- §5「重命名集合丢失 auto 归属」为过期描述 → 改为「已解决」并注明 `rename_collection` 已在同一事务重映射、评审实测保留。
- §3「无 .env」→ 改为「本 worktree 无 `.env`、环境无 `OPENCODE_API_KEY`；主检出存在 `.env`（KIMI/DEEPSEEK key），配置后可跑 live」的准确表述。

### Minor 4 — `store.py` 领地说明（已补充）

- §4 新增「领地说明」：说明重映射必须与重命名同事务、无法纯追加，故在既有函数体内补两行；无需改代码。

### Minor 2 — 图谱 auto 边标签（本次未修，follow-up）

- 见 §5 末条；不阻塞本 issue（AC4 只要求可见），已在 follow-up 明示。
