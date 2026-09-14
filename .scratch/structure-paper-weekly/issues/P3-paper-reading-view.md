# P3 — 论文阅读视图与库集成

Status: ready

来源：维护者 2026-09-14 指令「针对论文识别读取做全线优化」；共享契约 [SPEC.md §2](../SPEC.md)。

## What to build

论文专用阅读视图：`doc_kind == "paper"` 的文档在 Web 端打开时呈现论文阅读界面——左侧章节导航（`PaperSection` 树）、正文按节渲染、顶部元数据卡片（`PaperMeta`：标题/作者/年份/venue/DOI/摘要）、底部参考文献列表（`PaperReference`，已关联库内文档的条目可跳转）；论文在文档库列表中有可识别标识；与既有搜索/问答/vault 导出的集成不断裂（论文文档是普通库文档的超集）。

## Acceptance criteria

- [ ] 新视图 `webstatic/js/views/paper.js`（命名可调）经 `router.js`/`index.html` 追加注册；`doc_kind=="paper"` 文档从库列表/搜索结果打开时进入论文视图，非 paper 文档路径完全不变（回归断言）。
- [ ] 章节导航：fixture 驱动的 section 树渲染、点击定位、当前节高亮；无 sections 的旧 paper 文档回退为现行文档视图（契约降级）。
- [ ] 元数据卡片与参考文献列表：按 SPEC §2 数据形状渲染；`resolved_document_id` 非空条目可点击跳转到库内对应论文；字段缺失时留空不显示占位垃圾。
- [ ] 视觉与可达性沿用纸感阅读室基线：正文 ≥14px / 辅助 ≥12px / 对比度 ≥4.5:1；390px 窄窗口无横向溢出；用 `scripts/frontend_audit.mjs`（Playwright 模块路径见 BOARD 教训节）做 3 宽度几何巡检，0 溢出/0 裁切/0 pageerror。
- [ ] 数据来源只读：视图消费 API 只读端点（P1/P2 追加的 `/api/papers/*`）；本 issue 自身用 fixture/stub 数据开发，**不依赖 P1/P2 未合并代码**；webapp 如需补充展示聚合端点只追加 `/api/papers/*` 段。
- [ ] 前端测试（node mjs 契约或既有等价机制）+ 后端聚合端点测试全部离线；全量 pytest 绿。

## Blocked by

无（fixture 驱动并行开发；真实数据集成验证由 reviewer 在 P1/P2 合并后执行——前轮 P3 qaRoute 集成 bug 教训：reviewer 必须跑真实路由集成验证）。

## 领地

- 独占：`webstatic/js/views/paper.js`（新）、`webstatic/index.html`（导航/容器追加）、`webstatic/js/router.js`（追加注册，最小改动）、`tests/test_papers_view*.py` / 前端契约测试新文件。
- 只追加：`graph2note/webapp.py`（`/api/papers/*` 展示聚合端点）、`webstatic/js/api.js`/`state.js`（确需时最小追加）。
- 禁止：`ir.py`、`diagram*`、`digest.py`、`dashboard.js`、`upload.js`、`papers/*.py` 既有文件（P1/P2 领地）、`style.css` 大改（论文视图样式追加独立区块，不改既有选择器）。

## Comments

（待 worker 填写交付记录）
