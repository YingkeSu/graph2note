# Handoff 03：显著连续笔记的检测与合并

Status: ready-for-review
Branch: `dev/03-continuity-merge`（基线 `8d3b5f2`，**未 push、未合并 main**）
Author: AO worker (graph2note-52)
Date: 2026-09-12

## 交付物清单

新增：

| 文件 | 内容 |
|---|---|
| `graph2note/continuity.py` | 检测器（纯函数）+ 合并执行器 + 去重/证据 + 受控批量；`ZERO_LLM`/`llm_calls` 契约 |
| `graph2note/webstatic/js/inbox_merge_core.js` | Inbox 合并队列的纯前端 helper（证据标签/行 markup/空态/结果） |
| `tests/test_continuity.py` | 检测器表驱动 + 合并执行器快照/守恒 + 软归档闭环 + 零 LLM（29 个测试函数，48 用例含参数化） |
| `tests/test_continuity_api.py` | API/CLI/静态接线/离线 DOM 契约（18 个测试） |
| `tests/inbox_merge_dom.mjs` | 队列 markdown/证据/转义/版本链跳转的 Node 断言 |

追加（共享文件，见“领地说明”）：

| 文件 | 追加内容 |
|---|---|
| `graph2note/store.py` | `merged_into` 软归档字段 + `archive_document`/`restore_document`/`archived_documents`/`set_tags_with_provenance`；`list_documents(include_archived=False)` 默认排除归档稿；summary 增列 `merged_into` |
| `graph2note/evolution.py` | `PROVENANCE_MERGE="merge"` + `SOURCE_LABELS["merge"]="合并"` + classifier 识别（沿 R1 `repair` 范式，共 9 行） |
| `graph2note/inbox.py` | `REASON_LABELS["merge_candidate"]="可合并"`；`build_inbox(..., merge_reasons=)` 附加 `merge_candidate` 理由 + `merge_evidence` |
| `graph2note/webapp.py` | 新增 `/api/continuity/candidates`、`/api/continuity/merge`、`/api/continuity/reject`、`POST /api/documents/{id}/restore`；`/api/inbox` 注入合并理由 |
| `graph2note/cli.py` | 新增 `graph2note docs merge-continuous [--dry-run\|--yes]` |
| `graph2note/webstatic/js/views/inbox.js` | 合并区块：证据、双方标题、确认/拒绝、安全空态、合并后跳 `#doc/<new>/versions` |
| `tests/taxonomy.py` | 登记 `test_continuity`(workspace) / `test_continuity_api`(webapp+integration) |

提交（conventional commits，均带 `Co-Authored-By: Claude Code <noreply@anthropic.com>`）：

```
3bc3168 test(continuity): detector tables, merge snapshots, API/CLI/UI contracts
76fa8e0 feat(webapp,ui): continuity merge queue in the Inbox
16c4abb feat(continuity): deterministic continuity detection + merge executor
2af7c25 feat(store): soft-archive merged_into + provenance-preserving tag write
```

## 测试统计

- 全量 `uv run pytest`：**825 passed**（基线 777 + 新增 48），0 failed，115–125s。
- 新增单测 `tests/test_continuity.py` 48 用例；`tests/test_continuity_api.py` 18 用例。
- `node tests/inbox_merge_dom.mjs`：all assertions passed。
- 零 LLM：continuity 源码不含 `eval.gateway`/`post_gateway`/`vlm`/`llm_settings`；测试把 `eval.gateway.post_gateway` 打成抛错桩后跑完整检测+批量合并仍通过；所有 report/API payload 均 `llm_calls: 0`、`zero_llm: true`。
- 无任何 key/token 出现在代码、测试、文档或本 handoff。

## AC 逐条证据

**AC1 检测器表驱动**（`tests/test_continuity.py`）
- 显著档：`test_significant_same_source_adjacent_pages`（同 `pdf_id`/`source_pdf`/`source_job_id` 组 + 页序差 1，`order` 早→晚，证据 `同 PDF 第 3–4 页`）。
- 疑似档方向：`test_suggested_phash_plus_tail_head_overlap`（A→B）、`test_suggested_direction_is_reversed_when_only_b_tail_matches_a_head`（order 反转为 `["b","a"]`）。
- 无关对不报：`test_significant_same_source_non_adjacent_not_reported`、`test_significant_requires_a_page_order`、`test_different_sources_never_significant`、`test_suggested_requires_both_hash_and_overlap`。
- 已归档/已拒绝不复现：`test_archived_documents_never_participate`、`test_rejected_and_confirmed_pairs_are_not_repeated`、`test_reject_pair_persists_and_suppresses`（重载 store 后仍抑制）。
- 阈值边界：`test_phash_distance_threshold_boundary`（距离 0/1 与 64）、`test_suggested_overlap_ratio_threshold_boundary`（0.66 过 / 0.67 拒）、`test_tail_blocks_boundary_limits_the_search_window`（N=2 过、N=1/N=0 拒）。
- 字段位置已核实：真实 record 的页码来源为 `pdf_id`/`source_pdf`/`page_index`/`page_number`（`pdflib._run_attempts` 写入 `source_job_id=pdf-<pdf_id>` + `pdf_id` + `page_index`，见 `graph2note/pdflib.py`）；检测按 `pdf_id > source_pdf > source_job_id` 取源、`page_index`（0 基）优先、`page_number` 兜底。

**AC2 合并执行器快照/守恒**（`tests/test_continuity.py`）
- `test_merge_documents_snapshot`：`|A|4 + |B|3 − overlap 2 = merged 5`（`conservation_ok`），markdown 中重叠块各仅 1 次。
- `test_tail_head_overlap_is_lossless_and_deterministic`：S1 `DiffReport` 定位重叠（`unchanged==2`），仅接受精确块身份；空 IR 返回 `(0, None)`。
- `test_merge_documents_union_tags_and_collections`：标签并集 `[控制,重点,新词]` 且 provenance `{控制:manual, 重点:manual, 新词:auto}`（manual 优先、纯 auto 保持 auto）；集合并集 + `manual_collections` 保留。
- `test_merge_documents_version_provenance_and_chain`：新文档首版 `provenance=="merge"`、`provenance_detail.sources==[doc-a,doc-b]`；版本链 `source_label=="合并"`。

**AC3 软归档闭环**（`tests/test_continuity.py` + `test_continuity_api.py`）
- 默认列表排除：`test_soft_archive_closed_loop`、API `test_merge_endpoint_merges_and_archives`（`GET /api/documents` 只剩新文档）。
- 直达可达：`GET /api/documents/doc-a` 仍 200 且带 `merged_into`。
- 恢复：`store.restore_document` / `POST /api/documents/{id}/restore` 后列表重新包含（`test_restore_endpoint_reverses_soft_archive`）。
- 归档稿不参与检测与自动打标回填：`test_archived_document_not_in_detection_again`、`test_archived_documents_do_not_get_auto_tag_backfill`（`autotag.pending_documents` 不含归档稿）。

**AC4 CLI 默认 dry-run / 仅显著档**
- `test_cli_defaults_to_dry_run`：无 `--yes` 时输出“显著连续对 1 对 / 预估 LLM 调用 0”，且 store 无写入。
- `test_cli_yes_executes_significant_only`：`--yes` 执行显著档（1 对），源稿软归档。
- `test_cli_never_batches_suggested`：疑似档在 dry-run 列表标注“疑似（仅入确认队列）”，`--yes` 仍“已合并 0 对”。
- API 层拒绝批量：`test_merge_endpoint_rejects_batch_payloads`（`pairs`/`candidates`/`items` 任一数组 → 422“逐条”）。
- 多页链式合并：`test_merge_continuous_chains_multiple_pages_into_one`（3 页 → 1 篇，中间产物也软归档，重叠块各留 1 份）。

**AC5 UI 队列闭环**
- 证据展示：后端 `evidence_label`（`同 PDF 第 m–n 页` / `尾首重叠 N 块`，含 pHash 距离与块预览）；前端 `inbox_merge_core.js`。
- 确认/拒绝持久化：`test_reject_endpoint_persists_and_suppresses`（重启后仍不提示）；`test_inbox_exposes_merge_reason`（`inbox_reasons` 含 `merge_candidate`，`inbox_reason_labels` 含“可合并”，`merge_evidence` 为证据行）。
- 合并后版本链 merge 事件可见：`test_version_chain_shows_merge_event`（`source=="merge"`, `source_label=="合并"`）；UI 合并成功即跳转 `#doc/<new>/versions`（消费 S3 版本切换器既有 UI）。
- 安全空态：`test_candidates_endpoint_empty_state` + `mergeEmptyHtml()` + `tests/inbox_merge_dom.mjs`。

**AC6 API 契约 + 零 LLM 断言 + 真实库记录**
- API 契约：`tests/test_continuity_api.py`（candidates 字段、merge/reject/restore、inbox、version chain、静态接线，共 18 用例）。
- 零 LLM：`test_continuity_module_is_zero_llm`、`test_zero_llm_assertion_via_gateway_patch`。
- 真实库 43 篇实测见下节。

## 真实库 43 篇实测（只读，dry-run 不落盘）

命令：`graph2note docs merge-continuous --storage "~/Library/Application Support/Graph2Note/storage" --json`（当前代码）。

- 检测结果：`significant 0 对`、`suggested 0 对`、`total 0`、`llm_calls 0`；`merged_count 0`（无写入）。
- 原因（实测数据）：
  - 43 篇全部无页码溯源：`pdf_id`/`source_pdf`/`page_index`/`page_number` 均为 null，`source_job_id` 为单图上传的随机 id（或 `import-*`），**同源多文档组 0 个** → 显著档 0。
  - pHash 最近对距离为 **14**（`doc-71b1803c98` ↔ `doc-a9483ffb2b`），大于 S2 建议阈值 12；距离 ≤20 的对有 45 对，但 **尾首块重叠全部为 0** → 疑似档 0。
  - 43 篇 IR 均可解析，块数 6–778（合计 2402），内容互不衔接。
- 只读验证：dry-run 前后整库 1198 个文件内容 sha256 完全一致（`03979f1a…6c3d3f`），确认 `--dry-run` 未落盘。
- 结论：真实库是彼此的独立手稿/整页，不存在应合并的连续笔记；能力对 PDF 逐页入库的库有实际效果（`pdflib` 会写入共享 `source_job_id`/`pdf_id` + 相邻 `page_index`）。

## 领地说明（请 reviewer 关注）

- `views/tags.js`、`views/library.js` 集合区未改动。
- `store.py` 除“追加字段/查询函数”外，`list_documents` 增加了 `include_archived` 形参并默认排除 `merged_into` 文档（并在 summary 中追加 `merged_into`）。这是满足 AC3“Library 默认列表排除 / 归档稿不再参与检测与自动打标回填”的唯一单点改法：Library、检测、`autotag.pending_documents` 都读 `list_documents`。归档稿仍可 `get_document` 直达。
- `evolution.py` 追加 9 行把 `merge` 纳入 provenance 词表（与 R1 `repair` 完全同构），否则版本链只能把 merge 显示为“未知”，无法满足 AC5“merge 事件可见”。issue 01/02 不涉及该文件。
- `webapp.py` 为路由/理由注入追加，未改动既有端点语义。

## 已知风险 / Follow-up

1. 链式合并的中间产物也会被软归档（最终文档的 `provenance_detail.sources` 指向直接来源，不是全量传递闭包）。如需完整溯源，可后续在 provenance_detail 里累积 `lineage`。
2. 合并文档继承“较后页”的 `pdf_id`/`page_index` 以便连续链式合并；跨 PDF 的疑似档合并不会伪造页码溯源（`same_source` 为假时不写）。
3. 图片资源：合并时把两源最新版本的 `assets/` 复制进新版本；同名文件后者覆盖（内容通常一致）。
4. 真实库无 PDF 页码溯源，显著档实测为 0；建议后续补一个 PDF 逐页入库的 fixture 快照，覆盖显著档端到端回归。
5. 未 push origin、未合并 main；BOARD.md 与 issues/*.md 状态未改动（留待 reviewer）。
