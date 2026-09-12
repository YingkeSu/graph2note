# Handoff S2 — 演进锚定：版本链 + pHash 跨文档候选

Branch: `dev/s2-evolution-anchoring`（基于本地 main `97361a5`，已含 S1 merge `582aa61`；未 push、未开 PR）
Commits: `a20d4ae`（feat）、`a9d6de0`（test）· Issue: `.scratch/usable-product-iteration/issues/S2-evolution-anchoring.md`
Status → in-review

## 1. 一句话结论

S2 已交付两条严格分离的锚定线：**同 doc_id 版本链**（确定性主锚——时间排序、来源标注、逐版消费 S1
的 `DiffReport` 摘要与块定位）与 **pHash 跨文档候选**（建议性辅锚——只读建议、显式可配置阈值、用户确认
后才写入既有 `manual` 边、拒绝持久化不再提示）。新增 4 个 API、1 个自包含编辑器侧板、40 个离线测试；
全量 `uv run pytest` **556 passed**，真实用户库（43 篇）只读跑通、文件字节不变。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/evolution.py`（新，核心） | 纯规则 `classify_version_source`/`similarity_from_distance`/`within_suggestion_threshold`/`canonical_pair`；版本链 `versions_for_document`/`build_version_chain`；pHash `versions_for_original_phash`/`find_phash_candidates`；确认 `confirm_relation` + 拒绝持久化 `reject_candidate`/`load_rejections` |
| `graph2note/store.py` | **仅新增** `DocumentStore.set_manual_relations` 抽象方法 + `SessionDocumentStore`/`FileDocumentStore` 实现（manual 边落盘 `record.json`）。未改任何既有方法/签名，避免与 R1 的 `store.py` 改动争用 |
| `graph2note/webapp.py` | 4 个 API：`GET /api/documents/{id}/versions`、`GET .../candidates`、`POST .../relations`、`POST .../candidates/reject` |
| `graph2note/webstatic/evolution.js`（新） | 自包含编辑器侧板：版本链 + 相似手稿建议（确认/忽略按钮），只读 `#doc/<id>` 路由，不改 `app.js`（U 系重构可整体搬走） |
| `graph2note/webstatic/index.html` | 新增 `<section id="evolution-panel">` 挂载点 + `<script src="/static/evolution.js">`（各 1 处） |
| `tests/test_evolution.py`（新，30 项） | 表驱动来源/阈值规则 + StubStore 版本链/pHash/空态 + 真实 `FileDocumentStore` 拒绝持久化 |
| `tests/test_evolution_api.py`（新，10 项） | API 契约（temp `FileDocumentStore` + `SessionDocumentStore` stub）；R1 provenance 写入/不写入两路；确认→图 manual 边→重启仍在；拒绝→重启仍不提示；阈值边界与错误码；静态面板接线 |
| `tests/taxonomy.py` | 登记 `test_evolution → workspace`、`test_evolution_api → webapp`（后加入 integration 集） |

## 3. 关键决策

- **来源判定规则（表驱动、可测、无猜测）**：版本元数据显式 `provenance` 优先（R1 写 `repair`）；
  无字段时按位置——第 1 版 = `parse`，其后 = `reparse`；显式但无法识别的值 = `unknown`（README 口径：
  「无法判定的来源显式归 unknown」）。规则见 `classify_version_source`，测试 `test_classify_version_source_rule_table`
  （11 行）钉死。
- **「编辑保存」= 未提交 edit 头**：`store.save_edits` 不产生新版本（只更新 `markdown.md`），因此把
  「live markdown ≠ 最新版本 markdown」建模为时间线末尾的 `working-copy`（`source=edit`/`is_edit=true`）
  条目，并用 `_markdown_to_ir`（确定性、零模型）转 IR 后与最新版本做 `diff_ir`。这样四种来源全部可见；
  第 1 版无前版时 `diff=null`，单版/空链安全。
- **R1 字段约定按已定契约消费，不引入 R1 代码**：从 `record.json` 原始版本元数据读 `provenance`/
  `provenance_detail`（`_raw_version_meta`），并对 R1 合并后 `get_document` enriched `versions[]`/`latest`
  透出的同名字段同样生效（enriched 优先、raw 兜底）。缺字段 = 普通 parse；显式 `"repair"` 常量对齐
  `graph2note.repair.PROVENANCE_REPAIR`。fixture 自造该字段，写入/不写入两路各有断言。
- **阈值显式、可配置、建议性**：`PHASH_SUGGEST_MAX_DISTANCE = 12`（Hamming 距离，64 位）。刻意 **宽于**
  ingest 去重阈值 6——被去重合并的页已同属一个 doc，建议列表只对「未被自动合并的相近页」有价值。API 支持
  `?max_distance=`（限 0..64，越界 422），函数级同样可传参。**低于/高于阈值的两侧均不自动建立任何关联**：
  候选只在用户显式 `POST .../relations` 后才落 `manual` 边。
- **manual 边复用既有图模型**：确认时在**双方** `record.json` 写 `{"kind":"manual","from","to","reason",
  "created_at",(distance/similarity)}`，`graph.build_graph` 的 `_manual_relation_specs` 原样投影为
  `source="manual"` 的边；不新增边类型。关系写入通过新增的 `store.set_manual_relations`（唯一 store 改动）。
- **拒绝记录独立于文档**：`<storage>/evolution.json` 持久化 `{rejected: {"doc-a|doc-b": {...}}}`（无序对
  规范化 key），候选列表同时排除「已确认对」与「已拒绝对」；确认会把同一对从拒绝表移除。
- **不自动合并、不做内容级跨文档关联**：pHash 仅建议；版本链只聚合同 doc_id。
- **S3 契约稳定**：`evolution` 用 S1 公开面 `graph2note.semantic.diff_ir` + `DiffReport`，不改 `diff.py` 内部。

## 4. AC 逐条证据

| AC | 证据 |
|---|---|
| 1 版本链 API 按时间排序，每版含来源 + DiffReport 摘要；空链/单版安全 | `test_versions_endpoint_returns_time_ordered_chain_with_sources`（来源、`diff_from`、`summary` 字段、`changes` 块定位 `index/block_type/anchor`）；`test_versions_endpoint_is_safe_for_single_version_and_empty_chain`（单版 `diff=null`、未知 404）；unit `test_version_chain_single_version_and_empty_are_safe`（空链 `count=0/empty=true`）。时间排序：`versions_for_document` 按 `(created_at, 原始顺序)` 稳定排序 |
| 2 fixture 中 parse/reparse/edit/repair 正确标注；R1 repair 写入字段 | `test_classify_version_source_rule_table`（11 行表）；`test_version_chain_labels_sources_and_diffs_each_step`（parse/repair/reparse + `provenance_detail`）；`test_uncommitted_edit_is_the_timeline_head`（edit）；`test_versions_endpoint_reads_r1_repair_provenance_from_record_json`（**写入** `provenance:"repair"` 的 record.json → 标 repair；同 fixture 未写字段的另一版仍 parse，即**不写入**路）；`test_saved_edits_show_as_the_edit_head`（API 侧编辑保存） |
| 3 候选只读展示；确认后建 manual 关联并持久化；重启仍在；拒绝不再提示 | `test_candidates_are_read_only_until_confirmed`（列候选前后 `/api/graph` 边不变）；`test_candidates_confirm_graph_edge_and_restart_persistence`（确认→边；新 store+新 app 重启后关联仍在、被拒/已确认对不再出现；`evolution.json` 记录仍在）；unit `test_rejection_persists_across_store_reload`；`test_phash_candidates_exclude_confirmed_rejected_and_far_documents` |
| 4 确认关联出现在 `/api/graph` manual 边 | 同上 API 测试断言 `("document:doc-a","document:doc-b")` 与反向边均 `source="manual"`，且所有边只属 `{topic,tag,manual}`；`test_api_contract_with_in_memory_stub_store` 亦断言 manual 边 |
| 5 阈值上下两侧边界 + 无候选/低相似安全空态 | unit `test_within_suggestion_threshold_boundaries`（0/1 与 11/12/13/64 两侧）、`test_versions_for_original_phash_threshold_upper_bound`（12 位在内、13 位排除、收紧到 11 排除 12）；`test_phash_candidates_empty_states`（无 hash 空、全远空）；API `test_candidate_threshold_is_configurable_and_bounded`（0→空、64→含最远页、999/-1→422） |
| 6 API 契约（stub store）+ 来源/阈值表驱动单测；无 LLM | `test_evolution_api.py` 10 项（temp `FileDocumentStore` + `SessionDocumentStore` 内存 stub）；`test_evolution.py` 全部纯逻辑/StubStore；无任何 gateway/`call_ir` 调用 |

## 5. API 契约（S3 消费面，稳定）

**`GET /api/documents/{document_id}/versions`** → 404（未知文档）或：

```jsonc
{
  "document_id": "doc-x", "title": "C28",
  "count": 3, "empty": false,
  "latest_version_id": "v3",           // 最新“已提交”版本（不含 edit 头）
  "has_uncommitted_edit": false,
  "versions": [                         // 旧 → 新
    {
      "version_id": "v1",
      "index": 0,
      "created_at": "2026-09-11T22:55:35",
      "model": "deepseek-v4-flash-vision-exp",
      "source": "parse",                // parse|reparse|edit|repair|unknown
      "source_label": "解析",           // 界面直接可用的中文名
      "provenance_detail": null,        // R1 重跑：{source,repair_id,old_version_id,repaired_at,model}
      "current": false,
      "is_edit": false,                 // true 仅未提交编辑头
      "block_count": 16,
      "diff_from": null,                // 前一条 version_id（首个为 null）
      "diff": null,                     // S1 DiffSummary dump；无前版/IR 缺失时 null
      "changes": []                     // S1 BlockChange dump 列表（块定位：block_ref_a/b.index/block_type/anchor/preview）
    }
    // ... ; 若存在未提交编辑，末尾追加 {version_id:"working-copy", is_edit:true, source:"edit", diff_from:<最新版本>, diff:{...}}
  ]
}
```

**`GET /api/documents/{id}/candidates?max_distance=12`** → 只读建议（不写任何关系）：

```jsonc
{ "document_id":"doc-x", "title":"C28", "max_distance":12, "bits":64,
  "target_hashes":["..."], "empty":true|false,
  "candidates":[{"document_id":"doc-y","title":"C27","distance":14,"similarity":0.7812}] }
```

**`POST /api/documents/{id}/relations`** body `{"target_id":"doc-y","distance":14?}` → `{ok, document_id,
target_id, relation:{kind:"manual",from,to,...}, confirmed_at}`；双方 `record.json` 写 manual 关系；
`/api/graph` 出现对应 `manual` 边。缺 `target_id`/自关联 422、未知 404。

**`POST /api/documents/{id}/candidates/reject`** body `{"target_id":"doc-y","distance":14?}` →
`{ok,pair,document_id,target_id,rejected_at}`；写入 `<storage>/evolution.json`，此后候选列表不再返回该对。

**Python 面（S3/其他后端复用）**：`graph2note.evolution` 公开 `versions_for_document`、
`build_version_chain`、`versions_for_original_phash`、`find_phash_candidates`、`confirm_relation`、
`reject_candidate`、`load_rejections`、`classify_version_source`、`similarity_from_distance`、
`within_suggestion_threshold`、`PHASH_SUGGEST_MAX_DISTANCE`、`SOURCE_LABELS`。

## 6. 离线测试

```bash
uv run pytest tests/test_evolution.py tests/test_evolution_api.py   # 40 passed
uv run pytest -m "workspace or store or webapp or cli or ir or meta" # 192 passed
uv run pytest                                                        # 556 passed（基线 516 + 40）
```

零 LLM/零网络：pHash 为纯 numpy/PIL；diff 走 S1 纯函数；所有 store 为 temp `FileDocumentStore`
或 `SessionDocumentStore`；R1 provenance 由 fixture 直接写 `record.json`。

## 7. 真实用户库验证（只读，零模型调用）

库：`~/Library/Application Support/Graph2Note/storage`（43 篇）。脚本前后对 `documents/` 做 SHA-256
目录指纹，结果 **byte-identical**（只读）。

- 版本链：40 篇多版本 → 92 个时间线条目，来源 `{parse:40, reparse:51, repair:1}`，0 失败。
- **R1 字段真实命中**：`doc-9ddad73fc1` 的 `v1789179179109-4` 从 `record.json` 读出
  `source=repair` 且 `provenance_detail = {source:"preprocessed_raw", repair_id:"repair-20260912101227-dfd18f",
  old_version_id:"v1789176190097-3"...}`，与前后版 diff `major/33` —— 证明 S2 与 R1 的字段约定在真实
  数据上天然对上（R1 尚未合并，字段已由其真实运行写入库）。
- 单版本文档：`diff=null`，无异常；不存在文档 → `build_version_chain` 返回 `None`（API 404）。
- 候选：默认阈值 12 下全库 **0 条建议**（最近跨文档 pHash 距离为 14——更近的页在 ingest 阶段已被去重
  合并为同一 doc，符合 §3 阈值设计）；把阈值显式放宽到 16 得到 5 组建议，例如
  `doc-71b1803c98 ↔ doc-a9483ffb2b distance=14 similarity=0.7812`。

## 8. 边界 / 未尽事项

1. **`store.versions_for_document` / `store.versions_for_original_phash` 实际并不存在**。issue 文本
   假设它们已交付，但 main 上 `store.py` 无此方法。为不修改共享 store 的既有方法（并与 R1 的 store 改动
   错开），同名能力实现为 `graph2note.evolution.versions_for_document` /
   `versions_for_original_phash`，并作为公开函数导出；`store.py` 仅新增 `set_manual_relations`。若维护者
   希望方法挂在 store 上，可在后续把 evolution 函数薄封装进 `DocumentStore`（签名已对齐），无行为变化。
2. **`reparse` 为位置推断**：第二个及以后的持久版本一律标 `reparse`（真实库 51 条均如此）；若某天 store
   能记录每版的入库原因（重解析 vs 重复上传合并），`classify_version_source` 的显式字段分支可直接吃下，
   规则不变。
3. **`unknown` 分支当前只由显式未知 provenance 触发**；真实库 0 条。已在 README 说明「无法判定的来源
   显式归 unknown」。
4. **候选计算为 O(全库)**（每篇读 `get_document`/版本 hash）。43 篇量级 < 0.1s；个人本地库可接受。若未来
   上万篇，可在 `evolution.json` 同级加缓存，不改 API。
5. **编辑头 diff 依赖 `vlm._markdown_to_ir`**（既有确定性转换，route_b 亦用）。导入失败时 edit 头仍出现，
   仅 `diff=null`（不阻塞版本链）。
6. **前端为最小区块**：`evolution.js` 自挂 `#evolution-panel`、只读 `#doc/` 路由，未改 `app.js`；U1/U3
   重构 `webstatic/` 时可整体迁移或删除，后端 API 不受影响。

## 9. 相关文件

- 实现：`graph2note/evolution.py`、`graph2note/store.py`、`graph2note/webapp.py`、
  `graph2note/webstatic/evolution.js`、`graph2note/webstatic/index.html`
- 测试：`tests/test_evolution.py`、`tests/test_evolution_api.py`、`tests/taxonomy.py`
- 消费：`graph2note.semantic`（S1 `diff_ir`/`DiffReport`）、`graph2note.graph.build_graph`（manual 边）、
  `graph2note.ingest.hash`（hamming）
- 上游：`.scratch/usable-product-iteration/ISSUE-DRAFT.md` §2.3、`issues/S2-evolution-anchoring.md`、
  `handoffs/S1-ir-block-diff.md` §6、R1 handoff「与 S2 的约定」
- 下游：`issues/S3-version-diff-ui.md`（消费 §5 版本链 API）
