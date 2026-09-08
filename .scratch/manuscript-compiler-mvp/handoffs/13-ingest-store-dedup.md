# Handoff 13 — Ingest↔Store 集成：同页多次扫描合并为候选版本

Branch: `dev/13-ingest-store-dedup`  ·  Issue: `issues/13-ingest-store-dedup-integration.md`  ·  Status → in-review

## What shipped

把 issue 09 的页级近重复检测接入 issue 07 的文档库写入路径，端到端实现 PRD US-31。
纯集成：**不修改任何 03 解析管线文件**；改动集中于 store 扩展、新桥接层与 webapp 提交点。

| module | role |
|---|---|
| `graph2note/store.py` (扩展) | `save_document` 新增 `pg_hash`；每条候选版本写 `pg_hash`/`original_ext`；版本目录新增来源页 `versions/<v>/page.<ext>`；record 写 `current_hash`；新增 `document_hashes()` / `version_hashes()` / `remove_versions()`（Session + File 双实现）；`FileDocumentStore.get_document` 版本列表逐条附 `page_path`/`pg_hash`/`current` 标记与 `latest_version_id`。版本号改为 `time-ms-序号` 消除同毫秒合并冲突。 |
| `graph2note/ingest/store_bridge.py` (新) | `hash_page_image`（PIL 单图→pHash+low-info）、`near_duplicate`/`resolve_merge`（Hamming 阈值内最近者）、`ingest_single_page`（单页提交/并入）、`ingest_report_to_store`（PDF 批量去重后逐唯一页建档，跨 PDF/既有库近重复并入）、`split_document_versions`（版本源页 hash recluster，可逆拆分误并）。 |
| `graph2note/webapp.py` (接线) | `_run_parse` 每次 fresh 上传先算页 pHash；near-dup 命中→并入既有文档，暴露 `job.merged_into`（「已并入文档 X」信号）；re-parse 在自身 hash 仍匹配时**不挪页**；提交时序改为先落盘再置 `done`（消除 done 早于存储的竞态）。`create_app(dedup_threshold=6)` 阈值可调。 |

## Key decisions

- **单一入口统一策略**：webapp 每条上传都已有 `job.document_id`（07 为“同 upload 稳定 id，reparse 复用”）。为兼容 07 语义并支持 13，`_run_parse` 统一逻辑：算 pg_hash → 若本 upload 自己文档的 hash 与当前页在阈值内（= re-parse 同页）→ 留在自身（不挪页/不误并入）；否则 `near_duplicate` 命中其他文档 → 并入该文档成为候选版本；未命中 → 用自身 id 新建。这样 fresh 同页二扫并入、re-parse 保持原文档、新页建档三种情况都正确。
- **并入即候选版本**：near-dup 命中时复用 `save_document(document_id=既有)` —— 它天然 append 新不可变版本；版本携带各自来源页 hash + `page.<ext>` 与解析结果，默认取最新、历史可查。**不新建文档**。
- **可逆拆分**：`split_document_versions` 取文档全部候选版本的源页 hash，用 ingest `cluster_pages` 聚类；含**首个版本**的簇留在原文档（误并叠加进来的被剥走），其余簇各自建档成新文档 —— 与 09 `recluster` 同源的可逆路径。
- **PDF 批量**：`ingest_report_to_store` 按 cluster 唯一代表逐页建档；跨 PDF 同页 / 与既有库近重复页并入既有文档而非新建（“去重后逐页建档”+“并入既有库”）。
- **竞态修复**：原 `_run_parse` 在 durable save **之前**置 `status="done"`，poller 可能在记录落盘前读到 done、或读到尚未并入的旧 `document_id`。已改为先 `save_document` 再置 done，保证 done ⇒ 已提交且 `document_id`/`merged_into` 为最终值。
- **`version_id` 唯一性**：原 `v{time_ms}` 在同毫秒内多次合并会撞 id → 追加 `-序号`。

## Verification

- 全量 `pytest tests/ spike3/tests/` → **198 passed**（含本 issue 新增 8 条：7 条 `test_store_bridge.py` + 1 条 web AC5 `test_duplicate_upload_merges_and_versions_viewable`）。全离线（golden router / 合成样本），零网络。
- AC 逐条：同页光照/角度合成样本在默认阈值 6 下并入同一文档（lighting 距离 0、angle 4），不同页相距 ≥24 不误并；误并经 recluster 可拆（Session + File 双实现均测）；候选版本留存可查、默认最新生效；PDF 批量去重+既有库并入；web 重复上传并入显示 notice + 文档详情版本列表。
- 既有问题修复：`tests/test_documents.py` 的 fixture 原是“不同文件名但字节相同页面”，新 dedup 将其正确并入，故改为按文件名派生不同布局（`(ord*53)%600` 置换），保持 07 “两页两文档”断言语义；`test_parse_auto_…` 因竞态暴露而受益于提交时序修复。

## Risks / follow-ups

- pHash 阈值 6 为经验默认；`dedup_threshold` 可调（webapp / `ingest_single_page` / `ingest_report_to_store` / `split_document_versions` 均暴露）。真实扫描若出现角度/透视失真较大，可能需要更低阈值或先做 deskew 预处理（超出本期范围）。
- `split_document_versions` 拆出文档沿用源版本首内容；若拆出簇含多版本，只取其最新一版建档（历史版本不再细分）——够用但非完美。
- Web UI 最小呈现当前为 job 响应 `merged_into` + 文档详情 `versions`；前端 badge/提示文案由 UI 层接这些字段（本期未改 webstatic JS）。