# 搜索 PDF 内容并跳转命中原页

Status: ready-for-agent

来源：[已确认拆分草案](../ISSUE-DRAFT.md)；[现状与需求检查](../ASSESSMENT.md)。

覆盖需求：已导入 PDF 的内容查询。

## What to build

为已解析 PDF 内容建立本地关键词索引，提供 Web 搜索框、按 PDF 范围筛选、命中片段和原页跳转。搜索数据随新增、编辑、重解析、删除更新；首版不引入向量检索。

## Acceptance criteria

- [ ] 查询 → 检索 → 命中片段展示 → 打开原 PDF 页与对应校对文档的路径完整；支持单份 PDF 与全部已导入 PDF 的搜索范围。
- [ ] 中文、英文和混排固定样例可检索；无命中、无已解析页和仍在导入的 PDF 状态明确。
- [ ] 命中项关联来源 PDF、原始页序和内容版本，不将文档日期、逻辑编号或其他页误作引用页码。
- [ ] 新增、编辑、重解析、删除后索引与当前内容一致；索引可重建，不能出现已删除内容命中。
- [ ] 离线 Web/API/索引集成覆盖固定查询、来源跳转与索引更新，无 LLM 调用。

## Blocked by

- [08 — pdf-upload-parse-library](08-pdf-upload-parse-library.md)
