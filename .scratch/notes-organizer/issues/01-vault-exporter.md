# Obsidian Vault 导出器（含溯源）

Status: merged

## Parent

[PRD](../PRD.md)（notes-organizer feature）；依赖 manuscript-compiler-mvp 的 07（DocumentRecord 持久化）与 09（页级去重）。

## What to build

把文档库一键导出为 Obsidian 可用的 vault 结构。端到端行为：`DocumentRecord 集合 → vault 目录树（笔记 + frontmatter 溯源 + 嵌入原图 + 附件）`，导出器为纯函数、快照测试。

- 每份文档一篇笔记（标准 Markdown + frontmatter）：frontmatter 必含 `document_id / source_image / parsed_at / exported_at / topics`。
- 正文首部以相对路径嵌入原始手稿图片（溯源对照一步到位）；文档附件（流程图重建图等）随导出复制并保持引用有效。
- 同源重复解析只导出最新版（消费 09 的去重结论）。
- 全 vault 链接有效性（笔记 ↔ 附件 ↔ 图片引用）在导出时校验，死链即失败。

## Acceptance criteria

- [x] fixture 文档集导出产出期望 vault 树（快照测试：目录结构、frontmatter 字段、附件落位）— `test_snapshot_tree_and_frontmatter`/`test_frontmatter_traceability_fields`
- [x] frontmatter 溯源字段齐全，`source_image` 可定位回系统内 DocumentRecord — 必含 `document_id/source_image/parsed_at/exported_at/topics` + `source_original_path` 回链
- [x] 笔记内嵌原图与全部附件引用可达（无死链断言）— `test_all_references_resolve`/`test_dead_link_raises`
- [x] 同源重复文档只导出最新版 — `test_dedupe_latest_only`/`test_export_dedupes_duplicates`/`test_integration_reparse_same_record_no_duplicate`
- [x] 从真实（小规模）文档库导出到临时目录的集成测试通过 — `test_integration_from_real_library`/`test_integration_reparse_same_record_no_duplicate`
- [x] 导出幂等：同一输入两次导出结果逐字节一致（exported_at 确定化）— `test_idempotent_exports_byte_identical`/`test_export_timestamp_is_deterministic`

## Blocked by

- manuscript-compiler-mvp/issues/07-local-document-library
- manuscript-compiler-mvp/issues/09-pdf-split-dedup-missing-alert

## Handoff

`.scratch/notes-organizer/handoffs/01-vault-exporter.md`（2026-09-08）。

## Comments

- 2026-09-08 graph2note-2：实现完成，Status → in-review。新增 `graph2note/notes/`（exporter.py 纯函数导出器 + loader.py DocumentStore→Entry 薄接缝）：每文档一篇笔记，frontmatter 必含 document_id/source_image/parsed_at/exported_at/topics + source_original_path 回链系统记录；正文首部相对路径嵌入原图；附件随导出复制、相对引用保持有效；全 vault 链接校验死链即失败；确定性 exported_at（输入记录时间显式化，非墙钟）→ 同输入两次导出逐字节一致。同源去重双口径：记录内由 07 版本链（只导出最新版，reparse 同记录不重复）、记录间由 09 pHash 聚类（hamming≤6，保最新 updated_at，hash 可注入）。测试 `tests/test_vault_exporter.py` 全离线：fixture 快照、frontmatter 字段、附件落位、无死链+死链抛错、同源去重、真实小规模 FileDocumentStore 集成、reparse 不重复、幂等逐字节。全套 168 passed / 2 skipped。topics 暂为 []（分类 seam 待后续写入记录，loader 已读取）；增量/MOC/文件夹分类非本 AC 范围。
