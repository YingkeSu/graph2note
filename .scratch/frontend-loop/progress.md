# 前端逐页反馈循环 · 进度记录（方向 B「纸感阅读室」）

分支：`dev/frontend-loop-b`（基线 `c1313f0`，绝不 push / 不合并 main）
协议：`docs/design/frontend-loop/README.md`；方向：`.scratch/frontend-loop/direction-approved.md`
设计层：`graph2note/webstatic/reading.css`（新增，独立于 `style.css` 的既有布局）

## 自动化结果

- `pytest` 全量：881 passed（0 failed）。
- 浏览器几何巡检 `scripts/frontend_audit.mjs`：11 路由 × {390,768,1440} = 33 行，
  横向溢出 0、裁切 0、pageerror 0。
- 浏览器交互 `scripts/frontend_interactions.mjs`：8/8 PASS，pageerror 0。
- 正文/辅助对比度（WCAG）：ink/bg 13.14、muted/bg 5.83、muted/panel 6.02、
  accent/bg 5.75、accent-dark/accent-soft 6.44、danger/bg 6.00、错误面板 7.32 —— 全部 ≥4.5:1。
- 正文字号 14px、辅助 12px（`reading.css` 顶层规则）。

## 截图索引（相对 `.scratch/frontend-loop/`）

- 修改前（空库）：`evidence/{1440,390}-*.png`
- 修改前（有内容）：`before-populated/{1440,390}-*.png`
- 修改后（有内容，1440/768/390）：`final-populated/`
- 修改后（空态）：`round-2-empty/`
- 失败态与交互（错误面板、编辑器、PDF 状态、问答引用）：`interactions/`

## 逐页记录

### 1. 共享顶栏（BOARD 优先待修 #1）
- 任务/入口：全部 11 个路由的 `header.topbar`（折叠钮、品牌、全局搜索「新解析」）。
- 修改前：390px 下「新解析」被挤出视口（`evidence/390-*.png`）。
- 修改：顶栏 flex 收缩链（`.global-search{flex:1 1 320px;min-width:0}`、
  `.topbar .icon-btn,#nav-upload{flex-shrink:0}`），≤600px `flex-wrap:wrap` 且搜索独占一行；
  新增阅读层令牌、`focus-visible` 焦点环、跳转链接、`--muted` 对比度、统一 `view-error` 面板；
  ≤900px 侧栏默认折叠（首个 Tab 可达跳转链接）。未改路由与 API。
- 验证：33 行巡检 0 溢出/裁切；交互「skip link 保持当前路由」「移动端折叠/切换」。

### 2. 文档库（BOARD 优先待修 #2）
- 任务：浏览/筛选/密度；入口 `#library`。
- 修改前：窄窗口标题与筛选逐字竖排（`before-populated/390-library.png`）。
- 修改：`.library-head{flex-wrap:wrap}`、`.library-filters{order:2;width:100%;border-top}`、
  `.filter-chip{white-space:nowrap}`；卡片网格 `minmax(min(100%,240px),1fr)`；
  筛选加 `aria-pressed`；空态改为「你的第一份手稿…」+ 主操作「上传手稿」+ 筛选态「查看全部文档」；
  加载失败改为带「重新加载」的 `view-error`（不再只弹 toast）；来源徽标由 emoji 改为文字（PDF/图片）。
- 验证：`tests/library_cards.mjs`、`tests/test_library_cards.py`；交互错误恢复；截图 `final-populated/{390,768,1440}-library.png`、`round-2-empty/390-library.png`、`interactions/error-library.png`。

### 3. 时间轴
- 修改：分组标题排印、密度条与条目字号、gap/run band 换行；滚动改为容器内
  `timelineZone.scrollTo`（不再滚动整个 shell，尊重 reduced-motion）；失败态 `view-error`。
- 验证：`tests/timeline_view.mjs`、`tests/test_timeline_visual.py`；头图 `final-populated/*-timeline-day.png`、`interactions/error-timeline-day.png`。

### 4. 知识图谱
- 任务：节点可读性（验收明确项）。
- 修改：`labelCharWidth 11→18`、`labelHeight 14→22`、`TARGET_SPAN 980→640`（默认 fit 缩放下标签
  更大且不重叠）；文档节点用赤陶强调色；hover/focus 不发光只加描边；失败态 `view-error`。
- 验证：交互断言每个标签 `width ≤ 直径+40`、缩放/复位、来源过滤 `aria-pressed`；
  `tests/graph_interaction.mjs`、`tests/graph_layout.mjs`、`tests/test_graph_interaction.py`；
  截图 `final-populated/1440-graph.png`、`interactions/desktop-graph.png`、`error-graph.png`。

### 5. 数据看板
- 修改：指标大字（display 字体）、行/桶/模型名换行、说明字号；失败态 `view-error`。
- 验证：几何巡检；`interactions/error-dashboard.png`、`final-populated/1440-dashboard.png`。

### 6. 待整理
- 修改：中文命名（原 `Inbox`）、条目层级与 hover、reason 换行；失败态 `view-error`。
- 验证：`tests/inbox_merge_dom.mjs`；`final-populated/*-inbox.png`、`interactions/error-inbox.png`。

### 7. 标签词表
- 修改：词条行可换行、分组标题与操作间距、`document-tag` 用强调底色、输入不溢出；失败态 `view-error`。
- 验证：`tests/tag_organize_dom.mjs`、`tests/test_tagorg.py`；`final-populated/*-tags.png`、`interactions/error-tags.png`。

### 8. 问答
- 任务：引用与会话恢复（验收明确项）。
- 修改：会话滚动限制在 `#ask-conversation`（不再滚动 shell）；≤900px 输入区 sticky、会话列表不设高；
  引用块换行与强调底色；失败态 `view-error`。
- 验证：交互「等待→错误→重试→带 p1 引用的回答」；`tests/ask_view.mjs`、`tests/test_ask_view.py`；
  `interactions/mobile-ask.png`、`mobile-ask-answer.png`。

### 9. LLM 设置
- 修改：区块与标签排印、自定义供应商区与通道列表分隔、文案精简（保留「Key 只写不读」事实）；失败态 `view-error`。
- 验证：`final-populated/1440-settings.png`（基线中该页最高 120KB，信息密集）、`interactions/error-settings.png`。

### 10. 导出 Vault
- 修改：表单纸感（顶部 2px 墨线）、状态文本换行、≤600px 行列堆叠、按钮可达。
- 验证：`final-populated/1440-vault-export.png`；`tests/test_webapp_vault_export.py` 未改动逻辑。

### 11. 新解析
- 修改：去掉装饰 emoji，改为 kicker + 阅读式标题 + 明确格式限制（图片 ≤10MB / PDF ≤50MB）；
  「上传 PDF（逐页解析入库）」→「选择 PDF」；≤600px 按钮占满宽度。文件处理逻辑未改。
- 验证：交互 PDF 上传状态与失败详情；`final-populated/*-upload.png`、`interactions/mobile-pdf-status.png`。

### 12. 修复报告
- 修改：报告行布局、文档名换行、操作区换行；文案从「透视 bug/黑图」改为用户视角描述。
- 验证：`tests/test_repair.py` 未改动契约；`final-populated/1440-repair.png`。

### 13. 编辑器 + PDF 详情
- 任务：保存状态与三栏滚动（验收明确项）。
- 修改：三栏轴与各自滚动、`md-editor` 14px/1.8、预览 15px、侧栏最大宽度；
  ≤900px 单列且 `.panes` 可滚动（交互断言 `scrollHeight > clientHeight`）；
  原图加载失败先退到 `original`，再失败则显示 `#original-image-hint` 且不再重试（避免请求循环）；
  补 `aria-label`（Markdown 编辑器、重载原图、文档标签/集合）。
- 测试夹具：`tests/editor_workspace_dom.mjs` 的 DOM shim 缺少标准 `getElementById`，
  新代码使用后渲染中止；已在 shim 补 `getElementById`（测试专用，不改产品契约）。
- 验证：交互断言自动保存「已保存」、侧栏开关、移动端三栏可滚；
  `tests/test_webapp_editor_workspace.py`、`tests/test_graph_interaction.py` 全绿；`interactions/desktop-editor.png`、`mobile-editor.png`。

### 14. 跨页回归
- 修改：`scripts/frontend_audit.mjs` 增加 768 宽度、把 `header` 控件纳入裁切检测、原型截图改为
  opt-in（`--prototypes`）；新增 `scripts/frontend_interactions.mjs`。
- 修复脚本竞态：`waitForFunction(hash===...)` 在 hashchange 渲染前返回，
  改为等待视图出现后再断言导航 `aria-current`（产品侧已由探针确认正确）。
- 证据：`final-populated/`（本轮巡检输出）、`interactions/{results.json,*.png}`（本轮交互输出）。

## 剩余限制

- 自动化只证明几何、无 pageerror 与关键交互；视觉质量仍以截图肉眼复核为准，不宣称「优秀」。
- 失败态覆盖 7 个数据视图的加载错误；编辑器保存失败、PDF 上传失败沿用既有 toast/状态行，
  未新增专用面板（未纳入本轮验收项）。
- 浏览器巡检/交互依赖 Playwright + Chrome，CI 不运行它们（保持离线零网络）；
  本轮通过其它项目的 playwright 模块 + 系统 Chrome 本地执行。
- 图谱标签只验证 bbox 不越界与截图可读，未做逐字形抗锯齿评估。
- 证据保留 `round-2-empty`（空态）与 `final-populated`（有内容）；中间轮 `round-1-populated` 未纳入，因已被最终轮取代。
- 未改动 `BOARD.md` 阶段状态，未改动 API / 存储 / 自动保存契约。
