# U1：全局布局与导航重构（地基）

Status: ready-for-agent
Labels: track-ux, priority-high

## What to build

覆盖 usable-product-iteration 草案 §1 P0-1/2/3 与 §2.1 决策。把单页堆叠布局重构为「左侧栏 + 顶栏 + 内容区」三区骨架，并把 `app.js`（1652 行单文件）拆成 ES modules。**这是 UX track 的地基，只做骨架迁移，不动各视图内部质量**（卡片/编辑器/图谱/时间轴分别归 U2–U5）。

目标骨架（对齐概念稿，非逐像素契约）：

- **左侧栏**：视图导航（文档库 / 时间轴 / 知识图谱 / 数据看板 / Inbox）+ 集合树（从 Library 区块迁入）+ 底部次级入口（LLM 设置、导出 Vault）。当前导航项高亮可见；侧栏可折叠。
- **顶栏**：品牌 + 全局搜索框（本 issue 只做占位与焦点行为，统一搜索实现在 P3）+「新解析」主按钮。
- **内容区**：按视图切换；Library 页从「6 区块纵向堆叠」净化为「文档网格为主」（集合树/标签词表迁走后首屏应能直接看到 ≥2 行文档卡片）；PDF 搜索与问答区迁出 Library（问答一级入口在 P2 落地前，搜索表单可在顶栏搜索框旁保留临时入口）。
- **路由**：hash 路由保留，修复浏览器前进/后退语义（每个视图与 `#doc/<id>` 可直达、可回退），导航状态与 URL 始终一致。

工程约束：vanilla JS + ES modules（`type="module"`），zero-build（CDN marked/KaTeX 不变），不引入框架与构建步骤；`style.css` 相应重排但不做视觉风格重设计（配色/字号体系保持）。

## Acceptance criteria

- [ ] 1440×1000 下 Library 视图首屏可见文档网格 ≥2 行卡片（不再被搜索/集合/词表区块挤占），用 `graph2note visual-qa capture` 截图前后对比留证。
- [ ] 顶栏按钮数 ≤4（品牌/搜索/新解析/折叠侧栏），视图导航全部在侧栏；当前视图高亮，点击切换无整页刷新。
- [ ] 浏览器后退/前进在 Library ↔ 时间轴 ↔ 图谱 ↔ 看板 ↔ Inbox ↔ `#doc/<id>` 之间行为正确；直接打开任一 hash URL 直达对应视图。
- [ ] 集合树（含新建集合）在侧栏可用，行为与迁移前一致（既有 collections 测试不回归）。
- [ ] `app.js` 拆分为 ≥5 个 ES modules（建议按 router/views/api/components/utils），`index.html` 以 `type="module"` 引入；无构建步骤，静态服务直接可用。
- [ ] 既有 webapp 离线测试全绿（允许适配 import 结构，不允许行为回退）；新增路由与布局有 DOM 断言测试。

## Blocked by

None - can start immediately
