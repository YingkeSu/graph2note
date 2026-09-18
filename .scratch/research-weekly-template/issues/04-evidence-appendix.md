# 04 — 图文证据、原稿附录与可携带 Markdown

Status: ready-for-agent
User stories: 5、11、17–18、20、22

## Parent

[科研周报 PRD](../PRD.md)

## What to build

作者从已存在材料引用原图/整理图及来源页，在正文保留图题和交叉引用，在附录核对原稿，下载可携带资产的 Markdown 包。

## Acceptance criteria

- [ ] 图/表/公式/代码及单位口径按原材料保留，不生成虚构结果。
- [ ] 正文引用跳到正确附录与文档页/版本，重复材料引用不丢失。
- [ ] 资产包离线解压后图片可解析；纯文本继续支持单 Markdown。
- [ ] 来源删除或图片缺失显示明确状态；文件引用不允许越过已授权资产范围。

## Blocked by

- [02-incremental-authoring](02-incremental-authoring.md)

## Comments

- 2026-09-16：用户确认拆分粒度、依赖关系及测试边界，正式发布；尚未开始实现或诊断。
