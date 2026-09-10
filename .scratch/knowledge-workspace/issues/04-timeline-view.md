# Timeline 时间轴浏览

Status: merged

## What to build

覆盖 Knowledge Workspace User Stories 5、14–16。把文档及其时间元数据投影为确定性的 Timeline 视图数据，按有效文档时间浏览全部文档，支持日/周分组切换，并在同一主题的相邻条目之间提供聚合展示。Timeline 通过工作台 API 和界面呈现，点击条目可直接打开既有三栏编辑器继续校对。

时间轴只读消费 DocumentRecord、ClassificationScheme 和文档级元数据，不在时间轴中编辑 Markdown 或触发新的模型调用。

## Acceptance criteria

- [ ] Timeline 纯函数覆盖有效时间优先级“手工修正 > 手稿日期 > 拍摄时间 > 导入时间”，缺失字段按约定安全回退。
- [ ] API 支持日/周分组切换并返回稳定的分组、排序、主题聚合和文档定位信息。
- [ ] Web Timeline 能浏览全部文档，同一主题的相邻条目可聚合显示，空数据和无日期数据有明确状态。
- [ ] 点击时间轴条目能打开对应文档的三栏编辑器；Timeline 本身不修改内容。
- [ ] 固定 fixture 的排序、分组、聚合和 API 集成测试离线可重复，结果可快照。

## Blocked by

- 01-document-time-metadata.md
- 03-collections-workspace-navigation.md
