# Inbox 与 Obsidian 导出一致性

Status: merged

## What to build

覆盖 Knowledge Workspace User Stories 24–26。增加 Inbox 视图，集中展示无主题、无标签或被明确标记为待整理的文档，并让用户从 Inbox 回到已有的时间、标签和集合管理路径完成整理。工作台中对时间、标签和集合的修改必须作为文档级元数据持久化，并在下一次 Obsidian 增量导出中生效；工作台各视图只读消费解析产物，Markdown 内容编辑仍然只能通过三栏编辑器完成。

本切片收口工作台元数据与既有 notes-organizer 导出的端到端一致性，包含存量文档、重载、增量导出和用户修改保护场景。

## Acceptance criteria

- [x] Inbox 判定规则确定且有纯函数测试：无主题、无标签或显式待整理的文档会出现，已整理文档会移出；低置信信号只在已有数据中存在时参与判定。
- [x] Inbox 条目能打开文档并通过元数据控件完成整理；修改在进程重启后仍保留。
- [x] 时间、标签、集合变更进入下一次增量 Obsidian 导出，导出内容、frontmatter、集合文件夹和标签引用保持一致且无死链。
- [x] 用户在 Obsidian 中手工编辑或改名的文件仍受既有冲突保护，不会被工作台整理覆盖或误删。
- [x] 工作台 Timeline、Graph、Dashboard、Inbox 不提供 Markdown 写入口；内容编辑仍回到三栏编辑器，API/集成测试覆盖此边界。

## Blocked by

- 01-document-time-metadata.md
- 02-tag-vocabulary-governance.md
- 03-collections-workspace-navigation.md
