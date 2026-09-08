# Ingest↔Store 集成：同页多次扫描合并为 DocumentRecord 候选版本

Status: in-review

## Parent

[PRD](../PRD.md) User Story 31 + 「扫描 PDF 接入与页级去重（P1 增补）」决策（同页多次扫描/拍摄合并为同一 DocumentRecord 的候选版本，默认取最新、其余版本留存可查）。证据：issue 07 交付时明确遗留（"full FR-022 pHash ingest merge deferred to issue 09 机制"），09 的 pHash 聚类与 07 的 FileDocumentStore 均已合并但尚未打通。

## What to build

把 09 的页级近重复检测接入 07 的文档库写入路径。端到端行为：`同一页的第二次扫描/拍摄上传 → pHash 判定同源 → 并入既有 DocumentRecord 成为候选版本（默认取最新，历史版本留存可查）；不同页不误并；误并可拆分`。

- 上传/ingest 路径：对新页图计算 pHash（复用 `graph2note/ingest/` 的 hash/cluster），与库内既有页图比对；命中近重复 → 并入目标 DocumentRecord 作为新候选版本（含来源图与解析结果），不新建文档。
- 版本呈现：文档详情可见候选版本列表（来源、时间、当前生效版）；默认取最新，可查看历史版本（最小 UI 呈现即可，web 已有版本徽章可扩展）。
- 阈值可调 + 误合并可拆分：复用 09 的 recluster 可逆机制；Web 提示「检测到重复页，已并入文档 X」。
- 与 PDF 批量 ingest（09 CLI）打通：批量导入时同页去重后逐页建档。

## Acceptance criteria

- [x] 同页不同光照/角度的两次上传端到端并入同一 DocumentRecord（合成样本测试）
- [x] 不同页不误并（负例测试）；误并后可拆分（recluster 路径测试）
- [x] 候选版本留存可查，默认最新生效
- [x] PDF 批量 ingest 去重后逐页建档的集成测试
- [x] Web 端重复并入提示与版本查看最小呈现
- [x] 全部离线测试绿，无网络依赖

## Status note (delivery)

实现完成（分支 `dev/13-ingest-store-dedup`，commit `见 git log`），**198 tests 全绿**（含新增 7 条 store-bridge + 1 条 web AC5 = 8 条针对本 issue）。

交付要点：

- **Store 扩展（07 之上加装）**：`save_document` 新增 `pg_hash` 参数；每条候选版本写入 `pg_hash`/`original_ext`；版本目录新增来源页 `versions/<v>/page.<ext>`；record 写入 `current_hash`；新增 `document_hashes()`/`version_hashes()`/`remove_versions()`（Session + File 双实现）；`FileDocumentStore.get_document` 版本列表逐条附 `page_path`/`pg_hash`/`current` 标记。
- **新桥接层 `graph2note/ingest/store_bridge.py`**：`hash_page_image`（PIL 单图→pHash+low-info）、`near_duplicate`/`resolve_merge`、`ingest_single_page`（单页提交/并入）、`ingest_report_to_store`（PDF 批量去重后逐唯一页建档，跨 PDF/既有库近重复并入）、`split_document_versions`（以版本源页 hash 做 recluster，可逆拆分误并）。
- **Web 接线**：`_run_parse` 每次 fresh 上传先算页 pHash，near-dup 命中→并入既有文档（`merged_into` + job.public() 暴露「已并入文档 X」信号）；re-parse 在自身 hash 仍匹配时**不挪页**（保持 07 语义）；文档详情已有候选版本列表（来源页 `page_path`、当前生效 `latest_version_id`）。
- **提交时序修正**：`_run_parse` 先把文档 durable 落盘、再置 `status="done"`，消除“done 早于存储”的竞态，保证 poller 看到 done 即记录已提交且 `document_id`/`merged_into` 为最终值。
- **离线实现**：pHash 纯 PIL/numpy；PDF 批量经 `ingest` 纯聚类；闸门零网络。ac5 web 测试用 golden router 离线跑完全流程。

实测提示：同页光照/角度合成样本在默认阈值 6 下合并（lighting=0、angle=4），不同页相距 ≥24 不误并；阈值经 `create_app(dedup_threshold=…)` 可调。

## Blocked by

None（09、07 均已合并；机制齐备，纯集成）
