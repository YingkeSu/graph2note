# BOARD：usable-product-iteration

发布日期：2026-09-12
维护者已确认方向（UX 优化 / 存量修复 / Semantic Diff / PDF 问答增强；同日追加：自动整理标签 / 每周小结 / 自定义 LLM API）并要求**一次全量发布**供自动调度队列消费。拆分与 PRD 级决策见 [拆分草案](ISSUE-DRAFT.md)（UX 实地考察证据亦在其中）。

## 发布与执行状态

- 已发布：15（R1、U1–U5、P1–P3、S1–S3、A1–A3）。已认领：14（S1、P1、R1、A1、U1、A3、S2、A2、U3、P2、U2、U5、S3、U4）。已完成：14（S1、P1、R1、A1、U1、A3、S2、A2、U3、P2、U2、U5、S3、U4）。已合并：14（S1，merge `582aa61`；P1，merge `e682e3f`；R1，merge `e1281d8`；A1，merge `6fe379e`；U1，merge `7643f9e`；A3，merge `21533ce`；S2，merge `57bd28a`；A2，merge `361e79e`；U3，merge `6272463`；P2，merge `9a6890f`；U2，merge `1b765af`；U5，merge `d1fe8bb`；S3，merge `2e6b7f3`；U4，merge `eacb48a`）。
- 本次合并后**已解锁**：P3（P1、U1 均已合并）；U4 已合并（merge `eacb48a`）。
- 全部 issue `ready-for-agent` = 需求已就绪，**不表示阻塞依赖已完成**；依赖以各 issue Blocked by 为准。
- 第一波（无阻塞，可立即并行派）：**R1、U1、P1、S1、A1、A2、A3**（R1/U1/P1/S1/A1/A2/A3 已合并）。
- 第二波：U2/U3/U4/U5（U1 已合并 → **已解锁**）、P2（U1+P1 均已合并 → **已解锁**）、P3（待 P1，建议待 U1 —— 两者均已合并）、S2（S1 已合并 → **已合并**，merge `57bd28a`）。
- 第三波：S3（S1+U3 均已合并 → **已合并**，merge `2e6b7f3`）。
- R1 与 S2 有字段约定（重跑版本标注 repair 来源），两 issue 派发时调度需知晓；P2 与 P3 均触碰问答前端，先后派发由调度协调（P2 先）。
- 领地隔离：U 系 issues 大量触碰 `webstatic/`，U1 与 U2–U5 严禁并行领取（骨架未定时视图实现会全返工）；U2/U4/U5 之间可并行但需调度切分文件领地；U3 与 S3 串行。
- U1 合并（`7643f9e`）已把 `app.js` 拆为 17 个 ES modules（入口 `webstatic/app.js` + `webstatic/js/**`）；后续 U2–U5/P2/P3 以**新模块结构**为挂载点（视图模块见 U1 handoff §4）。整合时已把 P1 多轮问答控件、R1 repair 入口（侧栏次级 + `#repair` 路由）、A1 自动打标角标移植进新结构，行为未回退；A2 合并（`361e79e`）时同样把「每周小结」区块从旧单体 `app.js` 移植进 `webstatic/js/views/dashboard.js`（+ `state.js` 元素注册、`document.js` 导出 `renderMarkdownInto`），生成/历史/查看/空态行为保持。U3 合并（`6272463`）时编辑器 `#work-zone` 重排为「工具条 + 三栏 + 信息侧板 + 大图查看器」，S2 的 `#evolution-panel` 迁到三栏下方（保持文档路由自动显示），A2 的 `renderMarkdownInto`/digest 区块原样保留；侧板内 A1 provenance 行为逐行保留。U2 合并（`1b765af`）时 Library 网格升级为缩略图/标题/日期/标签/来源卡片并加密度切换，仅 `index.html`/`state.js`/`style.css` 共享区最小行改动；整合冲突仅 `docs/testing.md`、`tests/taxonomy.py` 两处登记表，按并集保留（U3 的 `test_webapp_editor_workspace`、S2 的 `test_evolution_api` 与 U2 的 `test_library_cards` 同时登记），合并后全量 `uv run pytest` 711 passed。U5 合并（`d1fe8bb`）时时间轴升级为「主干 + 刻度 + 空档标记 + 主题色带 + 月度密度条 + 懒加载缩略图」，`/api/timeline` 仅追加字段；与 U2/U3/P2 的共享文件（`index.html`/`state.js`/`style.css`）无冲突自动合并，仅 `tests/taxonomy.py`、`docs/testing.md` 两处登记表补登 `test_timeline_visual`，合并后全量 `uv run pytest` 722 passed。U5 缩略图与 U2 卡片缩略图**形态一致、可共存**（同为 `data-src` + IntersectionObserver 懒加载）；端点统一为 U2 的 `/api/documents/{id}/thumbnail` 因会使只读时间轴间接触发服务端缓存写入，留作 follow-up（补丁见 U5 评审报告）。S3 合并（`2e6b7f3`）时编辑器信息侧板升级为版本切换器（时间/来源/diff 徽标，消费 S2 版本链）并新增只读对比覆盖层 `#diff-view`（挂 `#doc-main` 内，块级高亮取自 S1 `DiffReport`、两版原图复用 U3 大图查看器、摘要后端模板拼接零模型调用），`index.html`/`state.js`/`style.css`/`document.js` 共享区最小行改动；整合冲突仅 `docs/testing.md`、`tests/taxonomy.py` 两处登记表，按并集保留（U2 的 `test_library_cards` 与 S3 的 `test_versiondiff_api` 同时登记），合并后全量 `uv run pytest` 747 passed。U4 合并（`eacb48a`）时图谱视图升级为确定性力导向布局 + 硬包围盒分离（节点零重叠）、0.25×–4× 滚轮/按钮缩放、抓取语义拖拽平移、边来源/集合/标签过滤与状态 chip、主题聚类收敛（点击展开）、文档邻域聚焦；`/api/graph` 仅追加 `clusters`/`filters` 字段；`index.html`/`state.js`/`style.css` 共享区最小行改动。整合冲突为 `docs/testing.md`（workspace 登记并集保留 U5 的 `test_timeline_visual` 与 U4 的 `test_graph_layout`/`test_graph_interaction`）与 `router.js`（U4 的 path/query 拆分与 S3 的 `#doc/.../diff`/`versions` 深链、P3 的 `#ask`/`#pdf-search` 别名合并保留，无行为回退），合并后全量 `uv run pytest` 760 passed。U4 评审修复 commit `085b995` 修掉拖拽平移二次加速、topic/tag/collection 单击导航回退两处 blocker 及 4 处 minor（聚类键盘展开、切换按钮两态反馈、tooltip 文案、缩放锚点用 rendered layout），并新增离线 DOM 交互断言 `tests/test_graph_interaction.py`。
- A 系领地提示：A1 编辑器标签区与 U3、A2 看板区块与 U1、A3 设置视图入口与 U1 均为弱交集——A 系以现行 UI 交付、U 系重构时承诺行为保持；若同期在跑由调度切分 `webstatic/` 文件领地。A3 另触碰 `llm_settings.py`/`eval/gateway.py`（独占）。

## Issue 清单

| Issue | 类别 | Blocked by | Status |
|---|---|---|---|
| [R1 黑图存量检测与重解析闭环](issues/R1-black-image-repair-loop.md) | 修复 | 无 | merged (e1281d8) |
| [U1 全局布局与导航重构（地基）](issues/U1-global-layout-navigation.md) | UX | 无 | merged (7643f9e) |
| [U2 文档卡片富化与 Library 网格重排](issues/U2-library-cards-grid.md) | UX | [U1](issues/U1-global-layout-navigation.md) | merged (1b765af) |
| [U3 编辑器工作区改造](issues/U3-editor-workspace.md) | UX | [U1](issues/U1-global-layout-navigation.md) | merged (6272463) |
| [U4 知识图谱交互升级](issues/U4-graph-interaction.md) | UX | [U1](issues/U1-global-layout-navigation.md) | merged (eacb48a) |
| [U5 时间轴可视化升级](issues/U5-timeline-visual.md) | UX | [U1](issues/U1-global-layout-navigation.md) | merged (d1fe8bb) |
| [P1 PDF 多轮问答](issues/P1-pdf-multiturn-qa.md) | PDF | 无 | merged (e682e3f) |
| [P2 问答对话式界面与一级入口](issues/P2-qa-conversation-ui.md) | PDF | [U1](issues/U1-global-layout-navigation.md)、[P1](issues/P1-pdf-multiturn-qa.md) | merged (9a6890f) |
| [P3 跨文档问答与统一搜索](issues/P3-cross-doc-unified-search.md) | PDF | [P1](issues/P1-pdf-multiturn-qa.md)（建议 U1 后） | open |
| [S1 IR 块级 diff 引擎](issues/S1-ir-block-diff.md) | Semantic | 无 | merged (582aa61) |
| [S2 演进锚定（版本链+pHash）](issues/S2-evolution-anchoring.md) | Semantic | [S1](issues/S1-ir-block-diff.md) | merged (57bd28a) |
| [S3 版本对比视图](issues/S3-version-diff-ui.md) | Semantic | [S1](issues/S1-ir-block-diff.md)、[U3](issues/U3-editor-workspace.md) | merged (2e6b7f3) |
| [A1 解析结果自动打标签](issues/A1-auto-tag-from-recognition.md) | 助理 | 无 | merged (`6fe379e`) |
| [A2 每周小结](issues/A2-weekly-digest.md) | 助理 | 无 | merged (361e79e) |
| [A3 自定义 LLM API](issues/A3-custom-llm-provider.md) | LLM | 无 | merged (21533ce) |

## 背景速览

- 上一轮（baseline-and-next-iteration）11+1 issue 全部 merged（2026-09-12 收官），本地 main `1334411` 领先 origin 57 commit **未 push**——推送时机仍归维护者，不阻塞本轮。
- 本轮 UX 痛点来自 2026-09-12 对真实库的实地截图考察（工具：`graph2note visual-qa capture`），证据摘要见草案 §1。
- 黑图存量实测：43 篇中 22 篇 `preprocessed.png` 纯黑待修复（R1 验收基线）。
