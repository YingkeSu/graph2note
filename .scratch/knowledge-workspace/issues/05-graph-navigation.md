# Graph 关系图谱导航

Status: merged

## What to build

覆盖 Knowledge Workspace User Stories 17–19。将现有文档、ClassificationScheme 主题、标签以及用户手工维护的关系投影为可导航的关系图谱。图谱边必须携带 topic、tag 或 manual 来源，来源在界面上有可区分的视觉表现；本切片不新增 AI 关系推断和 inferred 边。

端到端路径包括确定性的图谱视图模型、图谱 API、Web 交互和导航：点击文档节点打开文档，点击主题进入文档列表，点击标签进入标签过滤。

## Acceptance criteria

- [ ] 固定文档集、分类方案和标签元数据能生成稳定的节点与边；图谱模型不触网、不调用模型。
- [ ] topic、tag、manual 三类来源在 API 和 UI 中可辨识，用户手工维护的关系不会被误标为自动推断。
- [ ] 图谱 API 返回节点、边、来源和可用于导航的文档/标签标识，并覆盖空图和孤立节点。
- [ ] 点击文档、主题、标签节点分别能打开三栏编辑器、文档列表或标签过滤结果。
- [ ] 图谱视图模型快照、API 契约和离线 UI 交互测试覆盖来源区分与导航行为。

## Blocked by

- 02-tag-vocabulary-governance.md
- 03-collections-workspace-navigation.md
