# 01 — 生成并阅读有证据的科研周报

Status: in-review
User stories: 1–6、12–13、21–23

## Parent

[科研周报 PRD](../PRD.md)

## What to build

从日期选择到生成、持久化、历史重开与阅读，交付科研版章节及模板版本，并保留旧版四节小结兼容。将模板/章节耦合的必要整理纳入这条完整链路，不单开纯重构票。

## Acceptance criteria

- [x] 科研版显示概览、进展、问题与求助；专题按配置启闭排序；无依据实验不出现，空求助仅标题。
- [x] 来源、统计、预算和模型失败状态可见；旧报告原样可读可导出。
- [x] 相同生成输入复用且零模型调用；模板/模块变化不误用旧结果；空材料无调用。
- [x] API 生成后重启读取及浏览器展示通过离线 planner 场景。

## Blocked by

None - can start immediately

## Comments

- 2026-09-16：用户确认拆分粒度、依赖关系及测试边界，正式发布；尚未开始实现或诊断。
- 2026-09-17（dev/rwt-01-report，AO graph2note-136）：实现完成，置 in-review。交付内容与证据见
  [handoff 01](../handoffs/01-research-report.md)。共享文件仅做最小接线：`webapp.py`（import + 4 个
  `/api/reports*` 端点）、`index.html`（侧栏入口 + `#report-zone`）、`router.js`（一行路由）、
  `state.js`（zone 注册）、`app.js`（一行 import）。未 push、未建 PR、未合并 main、未改 BOARD。
- 2026-09-17（Rework R1，回应 reviewer `graph2note-138` 的 CHANGES_REQUESTED）：
  - F1 修复：命中指纹但展示字段（汇报人/日期）变化时，从持久化的结构化分节正文**零模型调用**重渲染，写入新修订，旧快照不变。
  - F2 修复：可选专题需“正文非空 + 至少一个属于当前材料的有效 `source_document_ids`”才渲染；有正文但空/失效来源的专题不再作为有依据成果输出。
  - F3 修复：科研周报改用既有 `/api/digests` 创建/列表/详情边界与共享 `digests/` 历史（`template` 字段区分模板），移除 `/api/reports*` 平行端点/存储；旧四节文件不改写。
  - F4 修复：章节顺序改为 TEMPLATE 的概览→进展→可选专题→问题与求助→附录，并按实际章节连续编号。
  - F5 修复：模型异常分支 `llm_calls` 报实际发起数 1（与空回复分支一致）。
  - F6 修复：不同 range kind/label 但同日期不再返回旧标签；零调用重渲染新标签。
  - F7 修复：新增可复跑浏览器证据脚本 `scripts/rw01_browser_evidence.sh`（注入 stub planner，附 `ao browser` 命令）。
  - 全量离线 `pytest` **1395 passed, 1 skipped**；新增回归见 `tests/test_research_report.py`（F1/F2/F4/F5/F6）与统一边界断言。未 push/PR/合并。
