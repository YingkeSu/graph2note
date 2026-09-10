# 集合多归属与工作台导航

Status: merged

## What to build

覆盖 Knowledge Workspace User Stories 10–13。把 collection 实现为文档级多对多归属，不移动物理文件：用户可以在 Web 中新建、重命名、删除集合，并把同一文档加入多个集合或移出集合。已有 ClassificationScheme 的主题可推导默认集合，用户手工调整后应保留。集合到 Obsidian 导出文件夹的映射需要稳定、可解释，并沿用现有导出的幂等和用户修改保护规则。

同时把现有文档列表升级为工作台入口：左侧显示集合和导航树，中间保留 Library/文档列表，右侧提供今日新增、本周新增和最近编辑入口；这些入口都能回到既有三栏编辑器。

## Acceptance criteria

- [ ] 一个文档可以同时属于多个集合；集合的创建、重命名、删除和文档归属变更不会移动物理文件或误删文档。
- [ ] 集合归属和用户手工调整在进程重启、重新加载文档库后仍然存在；默认集合可由 ClassificationScheme 稳定推导。
- [ ] 集合 CRUD、文档归属变更和 Library 过滤有 API 契约测试及 Web 可操作路径。
- [ ] 集合到 Obsidian 文件夹的映射确定且可重复，增量导出能看到集合变更，并保持既有用户编辑保护与无死链约束。
- [ ] 工作台导航显示集合树、Library、今日/本周/最近编辑入口；从任一入口打开文档仍进入三栏编辑器。

## Blocked by

- 01-document-time-metadata.md
