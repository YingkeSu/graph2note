# 02 — 逐段补充、原文锁定与报告修订

Publication: draft — 待拆分确认，尚未发布
Proposed status: ready-for-agent
User stories: 2、7–11、14、21–23

## Parent

[科研周报 PRD](../PRD.md)

## What to build

作者可补充文字、指定目标章节并追加整理，保留已确认内容与全部证据；编辑汇报信息和下周计划，保存新修订后立即预览，历史可重新打开。

## Acceptance criteria

- [ ] 连续追加两段后首段仍存在；锁定段落重生成后逐字不变。
- [ ] 重复笔记合并表达并保留全部来源；用户补充明确标识，未完成待办不变成成果。
- [ ] 过期修订保存提示冲突而非覆盖；失败后可恢复当前输入。
- [ ] 修改生成相关输入使缓存正确失效，打开旧修订不再调用模型。

## Blocked by

- [01-research-report](01-research-report.md)
