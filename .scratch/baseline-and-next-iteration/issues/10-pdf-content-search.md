# 搜索 PDF 内容并跳转命中原页

Status: merged

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：已导入 PDF 的内容查询。

## What to build

为已解析 PDF 内容建立本地关键词索引，提供 Web 搜索框、按 PDF 范围筛选、命中片段和原页跳转。搜索数据随新增、编辑、重解析、删除更新；首版不引入向量检索。

## Acceptance criteria

- [x] 查询 → 检索 → 命中片段展示 → 打开原 PDF 页与对应校对文档的路径完整；支持单份 PDF 与全部已导入 PDF 的搜索范围。— `test_search_chinese_english_mixed_with_complete_links`（`review_url`/`source_page_url`/`pdf_page_url` 均可用）/ `test_search_scope_single_pdf_vs_all`（全部=2 份，`pdf_id` 过滤=1 份）
- [x] 中文、英文和混排固定样例可检索；无命中、无已解析页和仍在导入的 PDF 状态明确。— `test_search_chinese_english_mixed_with_complete_links`（中/英/「状态空间 filter」）/ `test_search_states_no_hit_no_parsed_and_importing`（空库/空白页 PDF 范围/未知词/空 query 四种明确提示）
- [x] 命中项关联来源 PDF、原始页序和内容版本，不将文档日期、逻辑编号或其他页误作引用页码。— hit 携带 `pdf_id`/`page_index`/`version_id`，测试回读文档记录断言 `pdf_id`、`page_index` 与 hit 一致；页码仅取自 provenance
- [x] 新增、编辑、重解析、删除后索引与当前内容一致；索引可重建，不能出现已删除内容命中。— `test_index_updates_on_edit_reparse_delete` / `test_reindex_rebuilds_and_persists`（索引持久化 + 删除后可自动重建）
- [x] 离线 Web/API/索引集成覆盖固定查询、来源跳转与索引更新，无 LLM 调用。— `tests/test_pdf_search.py` 6 项均离线（注入 golden router），来源跳转验证真实 PNG 响应

## Blocked by

- [08 — pdf-upload-parse-library](08-pdf-upload-parse-library.md)

## Comments

- 2026-09-12 认领：graph2note-16（08 合并入 main 后接力），分支 `ao/graph2note-16/pdf-content-search`。
- 2026-09-12 graph2note-16 交付：`pdfsearch` 本地关键词索引（CJK 二元组 + 英文词，含内容哈希新鲜度指纹，持久化于 `search/`）+ `GET /api/search/pdf`、`POST /api/search/pdf/reindex`、`GET /api/pdf` + 文档库搜索框/范围/命中卡片与原页跳转。新增 6 项离线测试（`tests/test_pdf_search.py`）。`-m "webapp or ingest or meta"` 97 passed；全量 470 passed。AO Browser panel 实机验证搜索渲染（命中 2 条/原页序正确）。详见 `handoffs/10-pdf-content-search.md`。
- 2026-09-12 复核通过并合并入 main（d716590）。验收：6 项离线测试、CJK 二元组检索正确、页级映射准确、索引一致性含 content_hash 校验，无整改项。
