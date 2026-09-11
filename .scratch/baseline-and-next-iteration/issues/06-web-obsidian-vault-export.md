# 从 Web 导出 Obsidian Vault

Status: ready-for-agent

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：现有 Obsidian 导出能力形成可操作入口。

## What to build

用户在 Web 中选择本机目标目录并发起全库 Vault 导出，使用当前实际文档库，看到进度、完成位置或错误。复用现有增量导出器及修改保护，不引入双向同步。首版沿用现有规则分类，不顺带扩展自动分类策略。

## Acceptance criteria

- [ ] Web 发起 → 后端执行 → 结果展示路径完整，导出的是当前文档库，目标目录规则明确且错误可解释。
- [ ] 导出包含 Markdown、原稿、附件、时间/标签/集合元数据及 MOC，来源链接和附件均可解析。
- [ ] 空库、目标不可写、处理中重复发起、导出失败有明确状态；失败不会被展示为成功。
- [ ] 保持现有增量与用户修改保护，界面使用“导出”语义，不暗示双向同步。
- [ ] 通过 API/浏览器集成与独立 fixture Vault 验证，并在 Obsidian 中打开样例验证来源图、附件和 MOC 导航；不修改用户真实 Vault。

## Blocked by

- [03 — clean-baseline-release](03-clean-baseline-release.md)
