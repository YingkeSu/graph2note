# 已确认并发布的纵向拆分

2026-09-16：用户回复“同意”，确认全部拆分、依赖与测试边界。6 张 issue 已按依赖顺序发布到 issues/，均标记 Status: ready-for-agent。drafts/ 保留为审阅时的历史草稿。

| 编号 | 交付 | 阻塞项 | 用户故事 |
|---|---|---|---|
| 01 | [生成并阅读有证据的科研周报](issues/01-research-report.md) | None - can start immediately | 1–6、12–13、21–23 |
| 02 | [逐段补充、原文锁定与报告修订](issues/02-incremental-authoring.md) | 01-research-report | 2、7–11、14、21–23 |
| 03 | [关联正文的双栏批注与窄屏阅读](issues/03-anchored-marginalia.md) | 02-incremental-authoring | 8、15–16、19 |
| 04 | [图文证据、原稿附录与可携带 Markdown](issues/04-evidence-appendix.md) | 02-incremental-authoring | 5、11、17–18、20、22 |
| 05 | [导出分页可靠的科研周报 PDF](issues/05-pdf-export.md) | 03-anchored-marginalia,04-evidence-appendix | 16–20、21–22 |
| 06 | [诊断当前 PDF 无法正确渲染的入口与根因](issues/06-pdf-diagnosis.md) | None - can start immediately | 24 |

主要测试边界：应用 API → 持久化/重启 → 浏览器阅读 → 下载产物；模型用离线替身，PDF 增加真实 macOS 应用与逐页视觉验收。

确认记录：采用上述粒度、依赖与测试边界，无合并或进一步拆分。PRD 中的待确认措辞为确认前历史状态，以本记录为准；保持父 PRD 原文不变。

可立即领取：01 科研周报生成与阅读、06 当前 PDF 渲染诊断。其余 issue 按阻塞关系领取。
