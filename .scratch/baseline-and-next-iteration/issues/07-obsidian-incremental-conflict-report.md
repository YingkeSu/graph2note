# 展示 Obsidian 增量变化与冲突结果

Status: merged

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：导出可重复使用，用户知道哪些内容更新、哪些手工修改被保留。

## What to build

在 Web 导出流程中展示新增、更新、删除、无变化和冲突明细。冲突项给出保留文件位置与受管输出位置，让用户能够核对两份内容；不实现自动语义合并。

## Acceptance criteria

- [x] 首次导出、无变化重跑、修改内容/元数据、删除文档均返回与落盘一致的分类明细。— `test_report_first_export_task_id_and_added` / `test_report_no_change_reprun_zero_write` / `test_report_content_change_marks_updated` / `test_report_metadata_change_marks_updated` / `test_report_delete_document_marks_deleted`
- [x] 无变化重跑不改写文件；用户手工编辑或改名的文件仍被保留，结果中能定位这些文件。— `test_report_no_change_reprun_zero_write`（mtime 稳定）/ `test_report_user_edit_conflict_locatable`（managed+backup 双路径）/ `test_report_user_rename_preserved_and_locatable`（`user_files` 列出改名文件）
- [x] 界面明确说明“保留用户备份并生成系统版本”，不将冲突保护描述为已自动合并。— `app.js` `vaultConflictsHtml` 文案「已保留为备份并同时生成系统版本（未自动合并）」
- [x] 导出失败或部分完成能区别显示；不把不同任务的报告混用，也不让重试掩盖已发生的冲突。— `test_report_failure_partial_vs_clean`（partial true/false）；`task_id` 贯穿 POST/GET/report，前端按 task_id 过滤；重跑后旧冲突备份仍在 `user_files`
- [x] 离线端到端场景覆盖用户编辑、改名、重跑、来源/附件引用与元数据更新。— 8 个离线测试（真实 FileDocumentStore + 临时 vault；来源/附件引用由 exporter 死链校验兜底；元数据更新由 `test_report_metadata_change_marks_updated` 覆盖）

## Blocked by

- [06 — web-obsidian-vault-export](06-web-obsidian-vault-export.md)

## Comments

- 2026-09-12 graph2note-11 交付（Status → in-review）：把 06 的导出报告升级为逐文件明细 + 冲突双路径 + `user_files` 定位，后端增加 `partial` 判定与 `task_id` 隔离，并修了空库不重置状态导致 GET 返回上次 stale 报告的 bug。新增 8 个离线测试（`tests/test_webapp_vault_export.py`，共 15 个）。
- 2026-09-12 复核通过（整改：.scratch 文档不再进入提交，仅 4 个代码文件）并合并入 main（9db65c1）。全量 pytest 399 passed（main 大版本合并验证见合并记录）。
- 非阻塞项：Obsidian 桌面打开核对冲突/改名场景为人工步骤（handoff §3）；冲突不自动语义合并（首版明确不含）；目录选择仍是文本框。详见 `handoffs/07-obsidian-incremental-conflict-report.md`。
