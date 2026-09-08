# Obsidian Vault 导出器（含溯源）

Status: claimed

## Parent

[PRD](../PRD.md)（notes-organizer feature）；依赖 manuscript-compiler-mvp 的 07（DocumentRecord 持久化）与 09（页级去重）。

## What to build

把文档库一键导出为 Obsidian 可用的 vault 结构。端到端行为：`DocumentRecord 集合 → vault 目录树（笔记 + frontmatter 溯源 + 嵌入原图 + 附件）`，导出器为纯函数、快照测试。

- 每份文档一篇笔记（标准 Markdown + frontmatter）：frontmatter 必含 `document_id / source_image / parsed_at / exported_at / topics`。
- 正文首部以相对路径嵌入原始手稿图片（溯源对照一步到位）；文档附件（流程图重建图等）随导出复制并保持引用有效。
- 同源重复解析只导出最新版（消费 09 的去重结论）。
- 全 vault 链接有效性（笔记 ↔ 附件 ↔ 图片引用）在导出时校验，死链即失败。

## Acceptance criteria

- [ ] fixture 文档集导出产出期望 vault 树（快照测试：目录结构、frontmatter 字段、附件落位）
- [ ] frontmatter 溯源字段齐全，`source_image` 可定位回系统内 DocumentRecord
- [ ] 笔记内嵌原图与全部附件引用可达（无死链断言）
- [ ] 同源重复文档只导出最新版
- [ ] 从真实（小规模）文档库导出到临时目录的集成测试通过
- [ ] 导出幂等：同一输入两次导出结果逐字节一致（不含时间戳字段漂移——exported_at 等不稳定字段有确定化策略）

## Blocked by

- manuscript-compiler-mvp/issues/07-local-document-library
- manuscript-compiler-mvp/issues/09-pdf-split-dedup-missing-alert
