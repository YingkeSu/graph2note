# 解析遥测持久化与 Dashboard

Status: merged

## What to build

覆盖 Knowledge Workspace User Stories 20–23。把每次解析的模型、供应商、输入/输出/推理/总 token、延迟、重试和缓存命中等遥测随 DocumentRecord 版本持久化，并以纯函数聚合为工作台统计。Dashboard 通过 API 和 Web 界面展示今日、本周和累计解析页数及新增文档趋势、分类分布、标签使用 Top、按模型及按日/月的 token 用量与成本估计、平均耗时和重试率。

成本只使用本地可配置价目表，不引入外部计量服务；历史记录缺少新遥测字段时应能被安全读取并明确显示数据不可用。

## Acceptance criteria

- [x] 新解析、重试和缓存命中路径都会保存可关联到版本的规范化遥测；缺失的供应商或 token 字段使用明确的空值语义，不伪造成本。
- [x] 统计纯函数用固定 fixture 覆盖今日/本周/累计、分类分布、标签 Top、模型 token、日/月成本、平均延迟和重试率口径。
- [x] 本地价目配置能计算可解释的成本；未配置价格的模型在 API/UI 中显示“无价格配置”，不会调用外部服务。
- [x] /api/stats 与 Dashboard 展示上述指标，并处理空文档库、无遥测和旧记录三种状态。
- [x] TestClient、stub gateway 和固定 fixture 测试全程离线；统计结果可快照且不泄露凭证。

## Blocked by

- 01-document-time-metadata.md
- 02-tag-vocabulary-governance.md
- 03-collections-workspace-navigation.md
