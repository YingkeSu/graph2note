# S2：演进锚定——版本链与 pHash 跨文档候选

Status: merged
Labels: track-semantic

## What to build

覆盖 usable-product-iteration 草案 §2.3。把「同一项目的演进」从单一 diff 扩展为可查询、可确认的锚定体系，回答"这份手稿有哪些版本/演进关系"。

两条锚定线（严格区分，不混淆语义）：

1. **同 doc_id 版本链（确定性，主锚）**：`store.versions_for_document` 已返回版本列表；本 issue 把版本链整理为可消费的「演进时间线」——每版本带时间、来源（解析/重解析/编辑保存/修复 R1）、与前版的 DiffReport 摘要（消费 S1）。API：`GET /api/documents/{id}/versions`（含每版 diff 摘要与块定位）。
2. **pHash 跨文档候选（建议性，辅锚）**：`store.versions_for_original_phash` 已支持按原图 pHash 找候选。新增「可能是同一手稿演进」的**建议列表**（如 Library/编辑器侧板展示"检测到相似手稿：doc-X、doc-Y，相似度 z"），**只建议、用户确认后才建立关联**；关联关系持久化为 manual 边（进入图谱 `manual` 来源，复用现有图模型，不新造关系类型）。阈值显式、可配置；低于阈值的绝不自动关联。

**不做**：自动把候选合并进版本链；内容级（Markdown 相似度）的跨文档关联。

## Acceptance criteria

- [ ] 版本链 API 返回按时间排序的版本列表，每版含来源标注与 DiffReport 摘要；空链/单版本文档安全返回。
- [ ] 版本来源（解析/重解析/编辑保存/R1 修复）在 fixture 文档库中正确标注（R1 的重跑产物标 repair 来源——与 R1 约定好写入字段）。
- [ ] pHash 候选建议只读展示，用户确认后建立 manual 关联并持久化；重启后关联仍在；拒绝后不再重复提示同一对。
- [ ] 确认的关联出现在 `/api/graph` 的 manual 边中（现有图模型消费，无新边类型）。
- [ ] 阈值行为边界测试（上下两侧）；无候选、低相似库的安全空态。
- [ ] API 契约测试（stub store）+ 阈值/来源规则的表驱动单测；无 LLM 调用。

## Blocked by

- [S1](S1-ir-block-diff.md)
