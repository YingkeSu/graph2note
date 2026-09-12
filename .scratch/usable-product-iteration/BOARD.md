# BOARD：usable-product-iteration

发布日期：2026-09-12
维护者已确认方向（UX 优化 / 存量修复 / Semantic Diff / PDF 问答增强；同日追加：自动整理标签 / 每周小结 / 自定义 LLM API）并要求**一次全量发布**供自动调度队列消费。拆分与 PRD 级决策见 [拆分草案](ISSUE-DRAFT.md)（UX 实地考察证据亦在其中）。

## 发布与执行状态

- 已发布：15（R1、U1–U5、P1–P3、S1–S3、A1–A3）。已认领：0。已完成：0。已合并：0。
- 全部 issue `ready-for-agent` = 需求已就绪，**不表示阻塞依赖已完成**；依赖以各 issue Blocked by 为准。
- 第一波（无阻塞，可立即并行派）：**R1、U1、P1、S1、A1、A2、A3**。
- 第二波：U2/U3/U4/U5（待 U1）、P2（待 U1+P1）、P3（待 P1，建议待 U1）、S2（待 S1）。
- 第三波：S3（待 S1+U3）。
- R1 与 S2 有字段约定（重跑版本标注 repair 来源），两 issue 派发时调度需知晓；P2 与 P3 均触碰问答前端，先后派发由调度协调（P2 先）。
- 领地隔离：U 系 issues 大量触碰 `webstatic/`，U1 与 U2–U5 严禁并行领取（骨架未定时视图实现会全返工）；U2/U4/U5 之间可并行但需调度切分文件领地；U3 与 S3 串行。
- A 系领地提示：A1 编辑器标签区与 U3、A2 看板区块与 U1、A3 设置视图入口与 U1 均为弱交集——A 系以现行 UI 交付、U 系重构时承诺行为保持；若同期在跑由调度切分 `webstatic/` 文件领地。A3 另触碰 `llm_settings.py`/`eval/gateway.py`（独占）。

## Issue 清单

| Issue | 类别 | Blocked by | Status |
|---|---|---|---|
| [R1 黑图存量检测与重解析闭环](issues/R1-black-image-repair-loop.md) | 修复 | 无 | open |
| [U1 全局布局与导航重构（地基）](issues/U1-global-layout-navigation.md) | UX | 无 | open |
| [U2 文档卡片富化与 Library 网格重排](issues/U2-library-cards-grid.md) | UX | [U1](issues/U1-global-layout-navigation.md) | open |
| [U3 编辑器工作区改造](issues/U3-editor-workspace.md) | UX | [U1](issues/U1-global-layout-navigation.md) | open |
| [U4 知识图谱交互升级](issues/U4-graph-interaction.md) | UX | [U1](issues/U1-global-layout-navigation.md) | open |
| [U5 时间轴可视化升级](issues/U5-timeline-visual.md) | UX | [U1](issues/U1-global-layout-navigation.md) | open |
| [P1 PDF 多轮问答](issues/P1-pdf-multiturn-qa.md) | PDF | 无 | open |
| [P2 问答对话式界面与一级入口](issues/P2-qa-conversation-ui.md) | PDF | [U1](issues/U1-global-layout-navigation.md)、[P1](issues/P1-pdf-multiturn-qa.md) | open |
| [P3 跨文档问答与统一搜索](issues/P3-cross-doc-unified-search.md) | PDF | [P1](issues/P1-pdf-multiturn-qa.md)（建议 U1 后） | open |
| [S1 IR 块级 diff 引擎](issues/S1-ir-block-diff.md) | Semantic | 无 | open |
| [S2 演进锚定（版本链+pHash）](issues/S2-evolution-anchoring.md) | Semantic | [S1](issues/S1-ir-block-diff.md) | open |
| [S3 版本对比视图](issues/S3-version-diff-ui.md) | Semantic | [S1](issues/S1-ir-block-diff.md)、[U3](issues/U3-editor-workspace.md) | open |
| [A1 解析结果自动打标签](issues/A1-auto-tag-from-recognition.md) | 助理 | 无 | open |
| [A2 每周小结](issues/A2-weekly-digest.md) | 助理 | 无 | open |
| [A3 自定义 LLM API](issues/A3-custom-llm-provider.md) | LLM | 无 | open |

## 背景速览

- 上一轮（baseline-and-next-iteration）11+1 issue 全部 merged（2026-09-12 收官），本地 main `1334411` 领先 origin 57 commit **未 push**——推送时机仍归维护者，不阻塞本轮。
- 本轮 UX 痛点来自 2026-09-12 对真实库的实地截图考察（工具：`graph2note visual-qa capture`），证据摘要见草案 §1。
- 黑图存量实测：43 篇中 22 篇 `preprocessed.png` 纯黑待修复（R1 验收基线）。
