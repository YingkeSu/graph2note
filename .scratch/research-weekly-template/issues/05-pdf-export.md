# 05 — 导出分页可靠的科研周报 PDF

Status: ready-for-agent
User stories: 16–20、21–22

## Parent

[科研周报 PRD](../PRD.md)

## What to build

从当前选定报告修订导出与预览一致的 PDF，包含双栏侧注、图表、附录与来源；渲染失败可以重试且不丢报告。

## Acceptance criteria

- [ ] 实际 macOS 应用离线导出中文 PDF；字体和图片加载结束再输出，失败不伪报成功。
- [ ] 长报告逐页渲染检查：无裁切重叠、空白汉字、侧注撑空正文，长批注有续注。
- [ ] 页码、周区间、图题、表头与链接正确，打印产物不含编辑控件。
- [ ] 同一修订 Markdown 与 PDF 内容一致；导出和布局调整不触发模型。

## Blocked by

- [03-anchored-marginalia](03-anchored-marginalia.md)
- [04-evidence-appendix](04-evidence-appendix.md)

## Comments

- 2026-09-16：用户确认拆分粒度、依赖关系及测试边界，正式发布；尚未开始实现或诊断。
