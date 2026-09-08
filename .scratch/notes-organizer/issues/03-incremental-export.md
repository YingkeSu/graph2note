# 增量导出闭环：幂等、不覆盖用户修改

Status: in-review

## Parent

[PRD](../PRD.md)（notes-organizer feature）。

## What to build

让 vault 可以长期演进而不是一次性产物。端到端行为：`已有 vault + 文档库变化（新增/更新/删除）→ 增量导出 → 只更新系统生成物，用户在 vault 中的手工修改完好保留`。

- 以 document_id 为锚做 diff：新增文档生成新笔记；更新文档再生成系统生成物；删除文档移除其系统生成物与附件。
- 保护用户修改：文件内容或路径与上次导出不一致（用户编辑/改名）时不覆盖——冲突文件重命名保留双方，导出报告中列出。
- MOC 与分类随增量更新重建（MOC 是系统生成物，始终可再生成）。
- 导出报告：新增/更新/删除/冲突四类清单。

## Acceptance criteria

- [x] 新增/更新/删除文档后增量导出，vault 中对应变化正确落地 — `test_add_new_document`/`test_update_document`/`test_delete_document`
- [x] 用户编辑过的笔记文件不被覆盖，冲突文件重命名保留双方且报告列出 — `test_user_edit_not_overwritten`（`note.md` → `note.md.user-<hash>`，报告 `conflicts`/`conflict_backups`）
- [x] 用户改名的文件不被当作已删除而清理（路径追踪测试）— `test_user_renamed_file_not_deleted`（`My Essay.md` 保留，受管理路径回填，不在 `deleted`）
- [x] MOC 在增量后与实际笔记集一致（无死链、无遗漏）— `test_moc_matches_docs_after_remove_and_add`（+ 全量死链校验全程）
- [x] 连续两次无变化导出为零写入（幂等性测试）— `test_no_change_export_is_zero_write`（mtime 稳定）
- [x] 以上场景在临时目录集成测试中全部覆盖 — 全部离线集成

## Blocked by

- 01-vault-exporter
- 02-topic-classification-moc

## Handoff
