# 01 — 生成并阅读有证据的科研周报

Status: in-review
User stories: 1–6、12–13、21–23

## Parent

[科研周报 PRD](../PRD.md)

## What to build

从日期选择到生成、持久化、历史重开与阅读，交付科研版章节及模板版本，并保留旧版四节小结兼容。将模板/章节耦合的必要整理纳入这条完整链路，不单开纯重构票。

## Acceptance criteria

- [ ] 科研版显示概览、进展、问题与求助；专题按配置启闭排序；无依据实验不出现，空求助仅标题。
- [ ] 来源、统计、预算和模型失败状态可见；旧报告原样可读可导出。
- [ ] 相同生成输入复用且零模型调用；模板/模块变化不误用旧结果；空材料无调用。
- [ ] API 生成后重启读取及浏览器展示通过离线 planner 场景。

## Blocked by

None - can start immediately

## Comments

- 2026-09-16：用户确认拆分粒度、依赖关系及测试边界，正式发布；尚未开始实现或诊断。
- 2026-09-17（dev/rwt-01-report，AO graph2note-136）：实现完成，置 in-review。交付内容与证据见
  [handoff 01](../handoffs/01-research-report.md)。共享文件仅做最小接线：`webapp.py`（import + 4 个
  `/api/reports*` 端点）、`index.html`（侧栏入口 + `#report-zone`）、`router.js`（一行路由）、
  `state.js`（zone 注册）、`app.js`（一行 import）。未 push、未建 PR、未合并 main、未改 BOARD。
