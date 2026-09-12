# Handoff — usable-product-iteration U1：全局布局与导航重构（地基）

**Status: in-review** · Worker：graph2note-17 · Branch：`dev/u1-global-layout`（基于本地 main `fd10919`）
**Verified:** 全离线（TestClient + Node 纯函数 + 本地 headless Chrome 截图/CDP；零真实网络调用）· 全量 `uv run pytest`：**487 passed, 0 failed, 0 skipped**（80.24s）

## 一句话

把单页堆叠布局重构成「左侧栏 + 顶栏 + 内容区」三区骨架，`app.js`（1652 行）拆成 1 个入口 + 17 个 ES modules（zero-build、浏览器可直接 `type="module"` 加载），并把 Library 的集合树/标签词表/PDF 搜索问答迁出；hash 路由与 URL 完全一致，浏览器前进/后退与直接打开任一 hash 均正确。

## 1. 核心交付

| 文件 | 变更 |
|---|---|
| `graph2note/webstatic/index.html` | 重排为 `.app-shell = .sidebar + .main(.topbar + .content)`。侧栏：视图导航（文档库/时间轴/知识图谱/数据看板/Inbox/标签词表/PDF 检索）+ 集合树（含新建集合）+ 底部次级入口（LLM 设置/导出 Vault）；顶栏仅 4 项（折叠 ☰ / 品牌 / 全局搜索占位 / 新解析）；Library 净化为 `library-head`（含 4 个过滤 chip）+ `library-grid` + 空态；新增 `#tags-zone`、`#pdf-search-zone`（原 `#pdf-search`/`#pdf-search-results`/`#pdf-qa-form` 原样迁入）；`app.js` 改为 `<script type="module">`。 |
| `graph2note/webstatic/app.js` | 收窄为入口：import 各 view + `wireShell()` + `startRouter()` + 首次 `render()` + `beforeunload` 自动保存 flush。 |
| `graph2note/webstatic/js/*.js` | 新增 17 个模块：`utils`（常量/转义/时间）、`api`（fetch 包装）、`state`（共享 state + el 注册 + zone 显隐）、`router`（hash 解析/视图注册/go/render/onRender hook）、`ui`（toast/侧栏折叠/导航高亮/集合树/全局搜索占位）、`jobs`（解析任务轮询）；`js/views/` 下 11 个视图模块（library/document/timeline/graph/dashboard/inbox/settings/vault/upload/pdf/tags）。 |
| `graph2note/webstatic/style.css` | 新增 `.app-shell/.sidebar/.nav-item/.main/.content/.global-search` 与 tags/pdf-search 视图、过滤 chip、侧栏集合树样式；配色/字号体系不变，未做视觉重设计。 |
| `tests/test_webapp_layout.py`（新） | 7 个离线测试：自写 stdlib HTML DOM 树断言三区骨架 / 侧栏导航集 / 顶栏 ≤4 控件 / Library 不再含迁出块 / 单一 module 入口且 ≥5 模块全部可达；Node 路由契约；静态服务 zero-build 可用。 |
| `tests/router_routes.mjs`（新） | Node 纯函数测试：全部 hash → 视图映射、library filter 往返、`render()` 分发 + shell hook、未知 hash 回退 library。 |
| `tests/static_assets.py`（新） | 测试辅助：拼接 `app.js + js/**` 供既有测试做行为字符串断言（对应 AC「允许适配 import 结构」）。 |
| `tests/taxonomy.py` / `docs/testing.md` | 登记 `test_webapp_layout`（webapp 模块）。 |
| 6 个既有测试文件 | `test_webapp / test_graph / test_inbox / test_llm_settings / test_telemetry / test_timeline / test_webapp_vault_export` 中 `/static/app.js` 断言改为 `static_js()` 拼接（仅取源方式变化，断言内容未放宽）。 |
| `.scratch/usable-product-iteration/evidence/` | `library-before.png` / `library-after.png`（`graph2note visual-qa capture`，1440×1000，14 篇 seeded 文档）+ `library-layout-metrics.json`（CDP 量测前后对比）。 |

## 2. Key decisions

- **路由即唯一事实来源**：`render()` 只从 `location.hash` 推导视图；集合/标签/主题/过滤 chip/时间轴分组全部写 URL（`#library/collection/<id>`、`#library/filter/<f>` 等），不再有「改了 state 不换 URL」的路径。`go()` 同 hash 强制重渲、异 hash push 历史记录 → 前进/后退语义正确。视图通过 `registerView()` 注册，`router.js` 不 import 任何 view（无循环依赖）。
- **导航高亮用 `onRender` hook 而非 router→ui 依赖**：`ui.js` 在 `wireShell()` 里订阅，`render()` 回调 `syncNav()`；`doc/<id>` 归属 Library 高亮。
- **顶栏 ≤4 项的落地**：折叠按钮 + 品牌链接 + 搜索输入 + 新解析按钮；视图导航全部在侧栏，次级入口（LLM 设置/导出 Vault）在侧栏底部。全局搜索只做占位：提交给出「P3 落地」提示，⌘K 聚焦、Esc 失焦（P3 替换为统一搜索面板）。
- **PDF 搜索/问答的临时家**：按 issue 允许的「独立区域」方案落到侧栏 `#pdf-search` 视图（而非顶栏旁），把顶栏控制在 4 项；区块内部逻辑原样搬移，仅去掉「与 Library 网格互相 hide/show」的旧耦合（原实现靠 `resetPdfSearchUI` 在进入 Library 时恢复网格，拆分后不再需要）。
- **标签词表 `#tags` 视图**：issue 只要求「迁出 Library」，未指定去向；放在侧栏次级导航的独立路由，行为（新增/重命名/合并）不变，避免侧栏信息过载。
- **`assets.js` 保持经典全局脚本**：marked 渲染器需要 `window.__g2nAssets` 先于预览模块存在；只有应用入口改为 module（经典脚本先于 defer/module 执行）。
- **既有测试适配方式**：新增 `tests/static_assets.py::static_js()` 拼接全部前端源码，既有断言字符串与语义完全不变（不是删除或放宽断言）。

## 3. 验证

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-17
uv run pytest                       # 487 passed, 0 failed, 0 skipped (80.24s)
uv run pytest tests/test_webapp_layout.py -q   # 7 passed（DOM + 路由 + 静态服务）
node tests/router_routes.mjs         # router_routes: all assertions passed ✓
```

**AC 逐条对照**

| AC | 证据 |
|---|---|
| 1440×1000 Library 首屏 ≥2 行卡片；`visual-qa capture` 前后对比 | 前后截图 `.scratch/usable-product-iteration/evidence/library-{before,after}.png`；CDP 量测（`library-layout-metrics.json`）：网格起点 `gridTop 470 → 128`，首屏完整可见行数 `2 → 3`（共 3 行 / 14 卡片），Library 内 `pdfSearch/collectionTree/tagVocabulary` 均为 `false`。 |
| 顶栏按钮数 ≤4；视图导航全在侧栏；当前视图高亮；切换无整页刷新 | `test_topbar_has_at_most_four_controls` 断言顶栏交互元素恰为 4（sidebar-toggle/global-search-input/nav-upload/brand）且无 `nav-*` 视图导航；`test_sidebar_owns_view_nav_and_collection_tree`；CDP 量测顶栏控件 `10 → 4`；`u1_nav_check` 逐路由断言 `.nav-item.active` 正确，且 window 标记在 hash 切换后仍在（无整页刷新）。 |
| 后退/前进在 Library ↔ 时间轴 ↔ 图谱 ↔ 看板 ↔ Inbox ↔ `#doc/<id>` 正确；直接打开任一 hash 直达 | `tests/router_routes.mjs` 覆盖全部 hash 解析 + 分发 + 未知回退；CDP `u1_nav_check`：逐路由 goto 正确、`history.back/forward` 两次往返恢复 `#tags → #doc/<id> → #tags → #pdf-search`、`#graph/#dashboard/#inbox/#library` 直接打开均直达。 |
| 集合树（含新建集合）在侧栏可用，行为一致；collections 测试不回归 | CDP `u1_collections_check`：侧栏表单新建 → 出现在 `#collection-tree` → 点击打开 → URL 变为 `#library/collection/<id>`、侧栏项 `selected`、Library 可见；`tests/test_collections.py` 等既有测试全绿。 |
| `app.js` 拆 ≥5 个 ES modules，`index.html` `type="module"`，无构建步骤，静态服务直接可用 | 17 个模块（11 个视图 + 6 个基础）；`test_entry_is_one_es_module_and_split_is_reachable` 断言唯一 module 入口 `/static/app.js`、无经典 app.js、模块数 ≥5 且全部可达；`test_static_modules_are_served` 逐模块 `GET /static/...` 200（zero-build）。 |
| 既有 webapp 离线测试全绿；新增路由与布局有 DOM 断言测试 | 全量 487 passed；`tests/test_webapp_layout.py` 自建 DOM 树断言布局/导航结构，Node 测试断言路由契约。 |

**证据文件**：`.scratch/usable-product-iteration/evidence/library-before.png`、`library-after.png`、`library-layout-metrics.json`。

## 4. 后续 issue 的挂载点（重要）

- **U2 文档卡片**：`graph2note/webstatic/js/views/library.js`（`renderLibrary` 的卡片模板）+ `style.css` `.library-grid/.doc-card`；首屏空间已腾出（`gridTop≈128`）。
- **U3 编辑器**：`js/views/document.js` + `#work-zone`（`index.html` 内三栏 + 状态栏/标签/集合/时间元数据/操作按钮仍在原位，U3 需自行重排为侧板）。
- **U4 图谱**：`js/views/graph.js`；**U5 时间轴**：`js/views/timeline.js`。
- **A2 每周小结**：数据看板视图 `js/views/dashboard.js` + `#dashboard-zone` 内 `.dashboard-panel` 区块（U1 未改其内部结构）。
- **A3 自定义 LLM 供应商**：设置视图 `js/views/settings.js` + `#settings-zone`（内部结构未改）。
- **P1 PDF 多轮问答**：问答 markup 现位于 `index.html` 的 `#pdf-search-zone > #pdf-search > .pdf-qa`（`#pdf-qa-form/#pdf-qa-input/#pdf-qa-status/#pdf-qa-result`），逻辑在 `js/views/pdf.js`；轮询/scope 选择同处该视图。
- **P2 问答一级视图**：侧栏 `#sidebar-nav` 加 `nav-ask` + 新 `registerView("ask", ...)`；`parseHash` 加 `ask` 分支即可。
- **P3 统一搜索/⌘K**：顶栏占位 `#global-search-input`，焦点行为在 `js/ui.js::wireGlobalSearch()`（⌘K 聚焦 / Esc 失焦），替换为搜索面板即可；侧栏 `#pdf-search` 可随之收敛。
- **测试辅助**：新增前端行为字符串断言请用 `tests/static_assets.py::static_js()`；新增测试文件记得在 `tests/taxonomy.py` 登记。

## 5. 未尽事项 / 已知边界

- 全局搜索与 PDF 检索尚未统一（按计划归 P3）；顶栏搜索框提交只给占位提示，不发起请求。
- 侧栏折叠状态持久化在 `localStorage`（key `graph2note.sidebar-collapsed`）；窄屏（≤900px）为 best-effort 堆叠布局，未做窄屏专项验收（草案 §2.1：桌面 ≥1280 为主场景）。
- PDF 检索结果不再跨视图保留（旧实现依赖 Library 与结果同区，U1 拆分后改为进入视图时重置）；问答/搜索行为本身未变。
- 未 push（按协议推送时机归维护者），未合并 `main`，未自审。
- 截图证据依赖本机 Chrome；`tests/test_webapp_layout.py` 的 Node 路由测试在无 `node` 环境会 skip（DOM 断言仍全跑）。

## Suggested skills

- `impeccable`：U2–U5 在骨架上做视图级信息密度/交互打磨时使用（U1 只做骨架，未做视觉重设计）。
- `diagnose`：若后续出现「URL 与视图不一致」或「模块循环依赖」类问题，用于按 `parseHash → render → view` 链定位。
- `prototype`：U3/U4 的交互形态探索（侧板、图谱缩放）可在动正式实现前先出一版可玩原型。
