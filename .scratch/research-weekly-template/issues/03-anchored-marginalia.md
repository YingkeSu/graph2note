# 03 — 关联正文的双栏批注与窄屏阅读

Status: ready-for-agent
User stories: 8、15–16、19

## Parent

[科研周报 PRD](../PRD.md)

## What to build

作者创建并保存关联段落的 tips/碎碎念，重开后在双栏对应位置阅读，长批注连续安排，窄屏按正文与批注顺序展示。

## Acceptance criteria

- [ ] 批注使用稳定锚点，编辑/重排正文后仍关联正确，删除锚点后提示重新关联。
- [ ] 长批注与连续批注不遮挡正文、不通过撑高正文行制造空白；溢出有清晰续注。
- [ ] 390/768/1440 宽度可读、键盘可操作；正文保持分段与约 1.5 倍行距。
- [ ] 创建、保存、重开、响应式阅读全路径有行为与截图证据。

## Blocked by

- [02-incremental-authoring](02-incremental-authoring.md)

## Comments

- 2026-09-16：用户确认拆分粒度、依赖关系及测试边界，正式发布；尚未开始实现或诊断。
