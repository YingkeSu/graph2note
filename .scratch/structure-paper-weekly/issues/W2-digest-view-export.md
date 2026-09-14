# W2 — 周报展示交互与导出优化

Status: ready（开发在 W1 合并后启动，fixture 驱动可提前备料）

来源：维护者 2026-09-14 指令「优化周报模块」；共享契约 [SPEC.md §3](../SPEC.md)。现状：dashboard.js 的周报区块为单篇 Markdown 渲染 + 历史列表，无分节导航、无来源跳转、无导出。

## What to build

周报在 dashboard 的展示升级：分节导航（消费 W1 meta 的 `sections` 结构；旧 meta 回退现行整篇渲染）、每节来源文档可点击跳转库内对应文档、历史列表可读性优化（范围标签/生成时间/模型与 token 摘要）、导出能力（下载 Markdown；如 vault 导出机制可低成本复用则接入，不做则不阻塞）；空态/生成中/失败态的可操作反馈。只动展示与交互，**不改 `digest.py` 生成逻辑**。

## Acceptance criteria

- [ ] 分节渲染：带 `sections` 的 meta 渲染为分节视图（节标题锚点导航）；无 `sections` 的旧 meta 回退现行渲染，两条路径都有测试/巡检证据。
- [ ] 来源跳转：节内来源文档 id 列表渲染为可点击链接，路由到库内文档；失效 id 有可解释行为（灰显/提示，不炸页）。
- [ ] 导出：当前周报可下载为 `.md` 文件（文件名含范围与日期）；实现为前端生成 Blob 或只读 API 端点（webapp 只追加 `/api/digests/*` 段）。
- [ ] 历史列表：范围/时间/模型/token-cost 摘要可读；空态、生成中、失败三态有明确文案与可操作按钮（重试/改范围）。
- [ ] 视觉与可达性沿用纸感阅读室基线：正文 ≥14px / 辅助 ≥12px / 对比度 ≥4.5:1；390px 窄窗口无横向溢出；`scripts/frontend_audit.mjs` 3 宽度巡检 0 溢出/0 裁切/0 pageerror（dashboard 路由 + 交互路径）。
- [ ] 前端契约测试（node mjs 或既有等价机制）覆盖分节/回退/跳转/导出；全量 pytest 绿；CI 不触网。

## Blocked by

- [W1 — 周报内容结构与材料策略](W1-digest-content-structure.md)（契约字段 `sections` 由 W1 定义落盘；本 issue 以 SPEC §3 + 自建 fixture meta 先行，真实数据集成由 reviewer 验证）。

## 领地

- 独占：`webstatic/js/views/dashboard.js`（周报区块）、前端契约测试新文件。
- 只追加：`graph2note/webapp.py`（`/api/digests/*` 段内下载端点，确需时）、`webstatic/js/api.js`/`state.js`（最小追加）、`webstatic/style.css`（周报区块独立选择器追加，不改既有规则）。
- 禁止：`digest.py`、`index.html`（原则上不动；确需追加须在最末尾独立容器并 handoff 说明）、`ir.py`、`diagram*`、`papers/*`、`router.js`。

## Comments

（待 worker 填写交付记录）
