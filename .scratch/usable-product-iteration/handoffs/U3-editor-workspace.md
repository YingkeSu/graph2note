# Handoff U3 — 编辑器工作区改造（信息侧板 + 原图查看器 + 快捷键）

Branch: `dev/u3-editor-workspace` · Issue: `issues/U3-editor-workspace.md` · Status → in-review
Base: 本地 main `63ffd0b`（含 `merge: U1 — 全局布局与导航重构`）
Verified: 全离线（FastAPI TestClient + Node DOM 行为 harness + headless Chrome CDP；零真实网络调用）
全量 `uv run pytest`：**619 passed, 0 failed, 0 skipped**（111.53s）

## 1. 一句话结论

编辑器从「三栏 + 下方纵向堆 5 个区块」改为「常驻工具条 + 三栏主轴 + 右侧可折叠信息侧板 + 大图查看器」：
标签/集合/时间元数据/待整理/版本信息全部脱离纵向主轴进入侧板（默认收起），三栏可视高度 **396px → 784px**
（1440×1000，+388px）；原图栏点击或「⤢ 大图」进入大图模式（滚轮/按钮缩放、拖拽平移、适应窗口、Esc 退出），
图片上传与 PDF 来源页两种来源均可用；⌘S 显式保存、⌘/ 侧板、Esc 退出，输入框聚焦时不误触发；自动保存指示与
warnings 固定在工具条，不被编辑器滚动带走。表单 API 与状态更新行为与迁移前完全一致（含 A1 auto/manual provenance）。

## 2. 交付物

| 文件 | 变更 |
|---|---|
| `graph2note/webstatic/index.html` | 重写 `#work-zone`：新增 `.doc-toolbar`（`#doc-panel-toggle` / `#status-text` / `#warnings` / `#save-indicator` / 操作按钮）、`.doc-main`（`.panes` 三栏 + `#doc-side-panel`）、`#image-viewer` 覆盖层。标签/集合/时间元数据/待整理/版本区块原样迁入侧板；`#version-info` 迁入新增 `#version-panel`（含 S3 挂载点 `#version-list`）；原「待整理」占位 marker 迁进工具条。 |
| `graph2note/webstatic/js/views/document.js` | 编辑器视图：新增侧板开合（`toggleSidePanel`/`isSidePanelOpen`）、版本索引渲染（`renderVersions`）、大图查看器（`openImageViewer`/`closeImageViewer`/`fitImageViewer`/`zoomImageViewer`/`viewerSource`，滚轮+按钮缩放、指针拖拽平移）、快捷键（`handleEditorShortcut`/`isTextInputFocused`/`explicitSave`）。标签/集合/元数据表单逻辑与 A1 provenance 渲染**逐行保留**；`autosave` 与 ⌘S 共用 `saveMarkdown`。 |
| `graph2note/webstatic/js/state.js` | `el` 注册表 +15 行：工具条、侧板、查看器相关元素（无行为改动）。 |
| `graph2note/webstatic/style.css` | 新增 `.doc-toolbar` / `.doc-main` / `.doc-side-panel` / `.doc-side-section` / `.version-*` / `.image-viewer*` 样式；`.metadata-grid` 由 4 列改 2 列（侧板宽度）；`#original-img` 加 `cursor: zoom-in`。视觉体系/配色/字号未变。 |
| `tests/test_webapp_editor_workspace.py`（新） | 7 项离线测试：结构 DOM（主轴 = 工具条 + 三栏、侧板归属、工具条常驻、查看器 markup/入口）+ Node DOM 行为 harness 运行器 + 静态服务断言。 |
| `tests/editor_workspace_dom.mjs`（新） | Node DOM 行为 harness（零依赖小 DOM shim + 录制 fetch）：真实加载 `js/views/document.js`，断言侧板内表单 → API → `state`/DOM 更新全链（标签增删/转手工、集合增删、日期修正、待整理），以及 ⌘S/⌘//Esc、图片与 PDF 两种查看器来源、缩放 ≥2×。 |
| `tests/html_dom.py`（新） | 供结构断言复用的小型 stdlib DOM 树（与 U1 `test_webapp_layout.py` 内联解析器同源；未改动 U1 测试文件以避开并行领地）。 |
| `tests/taxonomy.py` / `docs/testing.md` | 登记 `test_webapp_editor_workspace → webapp`，并补进模块→测试映射表。 |
| `.scratch/usable-product-iteration/evidence/` | `editor-before.png` / `editor-after.png` / `editor-after-panel.png` / `editor-after-viewer.png` / `editor-after-viewer-pdf.png` + `editor-layout-metrics.json`（1440×1000；前后 CDP 量测 + 浏览器交互检查）。 |

**未改**（按 issue 边界）：解析流程、版本机制、Markdown 双向同步逻辑、导出/删除操作**语义**（仅按钮位置迁到工具条）。
未触碰 U2/P2 领地（`js/views/library.js`、`js/views/pdf.js`）；未改 `router.js` / `app.js`。

## 3. Key decisions

- **侧板是覆盖式抽屉，不是第四栏**：`#doc-side-panel` 绝对定位在 `.doc-main` 右缘之上（`z-index:20`），
  默认 `hidden`。因此打开/关闭都不改变三栏高度，编辑 Markdown 时零干扰；「脱离纵向主轴」由结构断言兜底
  （`#work-zone` 可视主轴恰为 `[doc-toolbar, doc-main]`，`#image-viewer` 为 fixed 覆盖层）。
- **工具条是唯一常驻状态位**：`#save-indicator` 与 `#warnings` 从三栏下方状态栏提到 `.doc-toolbar`，
  工具条 `flex: 0 0 auto`，滚动发生在 `.pane-body`/`.preview` 内部 → AC5 的结构保证。
- **查看器来源解析**（`viewerSource`）：有 `pdf_id + page_index` → `/api/documents/{id}/source-page`
  （服务端即 `/api/pdf/{id}/page/{n}` 语义）；否则 `/api/documents/{id}/preprocessed`，`onerror` 回退 `/original`。
  图片以 CSS `transform: translate() scale()` 渲染（`transform-origin: 0 0`），缩放到指针位置；缩放范围 0.1×–8×。
- **快捷键语义**：`⌘S`（或 Ctrl+S）永远生效（textarea 聚焦也保存，防抖计时器立即 flush，反馈「已保存 …（⌘S）」）；
  `⌘/` 与 `Esc` 在 `input/textarea/select/contenteditable` 聚焦时不劫持。Esc 优先退出最上层的大图查看器，
  其次在没有输入焦点时收起侧板。查看器是模态层（`z-index:40`，低于 toast 的 50，保证操作反馈可见）。
- **A1 行为保持红线**：`renderDocumentTags` 及提交/移除/转手工三个 handler、`applyTagResult` 原样保留
  （「自动」角标、✓ 保留为手工、× 移除、PATCH `{provenance:"manual"}`）；仅容器从 `.document-tags` 迁到
  `.doc-side-section`，CSS 以 `.document-tag`/`.tag-auto-badge`/`.tag-promote` 继续生效。
- **侧板默认收起**：每次打开文档 `toggleSidePanel(false)`，保证「默认收起 / 零干扰」；用户当次会话内可随时展开。
- **S3 挂载点**：`#doc-side-panel > #version-panel` 内的 `#version-list`（每项带 `data-version-id`），
  由 `renderVersions(doc)` 用 `GET /api/documents/{id}` 的 `versions[]`（`{version_id, created_at, model, markdown, ir_json, …}`
  + `latest_version`）渲染当前/历史；S3 直接在此挂载「选择两版 → diff」控件即可，无需改本视图的布局。
  版本对比引擎为 `graph2note/semantic/diff.py::diff_ir`（S1），原图对照可复用 `/source-page`。
- **impeccable 技能**：仅应用其 product register 设计准则（身份保持、状态可见、无装饰动效），
  **未** 运行 `impeccable init` 生成 `PRODUCT.md`/`DESIGN.md`——该动作会新增跨 issue 共享文件，超出 U3 领地，交由维护者决定。

## 4. 验证

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-33
uv run pytest                                   # 619 passed, 0 failed, 0 skipped (111.53s)
uv run pytest tests/test_webapp_editor_workspace.py -q -p no:warnings   # 7 passed
node tests/editor_workspace_dom.mjs             # editor_workspace_dom: all assertions passed ✓
uv run pytest -m "workspace or webapp"          # 文档/元数据/标签/集合相关既有套件全绿
```

**AC 逐条对照**

| AC | 证据 |
|---|---|
| 主轴只有三栏 + 工具条；标签/集合/时间元数据/待整理全在侧板；1440×1000 三栏可视高度增加（截图前后对比） | `test_editor_axis_is_toolbar_plus_three_panes` / `test_info_panel_owns_tags_collections_metadata_versions`；CDP 量测：pane 高度 `396 → 784`、panes `418 → 812`（`editor-layout-metrics.json`）；`editor-before.png` vs `editor-after.png`/`editor-after-panel.png`。 |
| 大图缩放 ≥2× 清晰、平移、适应窗口、Esc 退出；图片与 PDF 页两种来源可用 | 浏览器 CDP：开图 → 8 次放大到 **596%**、适应窗口 **73%**、Esc 退出关闭；图片源 `/preprocessed`；PDF 文档源 `/source-page`（`editor-after-viewer.png` / `editor-after-viewer-pdf.png`）。Node harness 断言 `viewerSource()` 两分支与 `zoomImageViewer` ≥200%。 |
| ⌘S / ⌘/ / Esc 在 macOS Chrome 行为正确，输入框聚焦不误触发（⌘S 例外） | CDP：`⌘/` 开/闭侧板、textarea 聚焦时 `⌘/` 不生效；查看器内 Esc 退出；textarea 聚焦时 `⌘S` 仍发起 `/markdown` 并显示「已保存 …（⌘S）」。Node harness 覆盖同一组契约。 |
| 元数据/标签/集合全部操作有 DOM 断言测试（表单 → API → 状态更新），行为等价 | `tests/editor_workspace_dom.mjs`：加载文档 → 断言 DOM/`state`；标签表单 POST `/tags/manual`、× DELETE、✓ PATCH provenance、集合 PUT、元数据 PUT（含 needs_organization）逐项断言请求体 + `state.doc` + 重渲染后的 DOM；覆盖 A1 auto 角标与转手工。 |
| 自动保存指示与 warnings 在工具条常驻，滚动不丢失 | `test_toolbar_keeps_autosave_and_warnings_visible`：`#save-indicator`/`#warnings` 在 `.doc-toolbar`，且不在任何 `.pane-body` 内；`.doc-toolbar` 不随 pane 滚动（CSS `flex: 0 0 auto` + 内部滚动）。 |
| 既有 document/metadata/tags/collections 离线测试全绿 | 全量 `619 passed`（含 `test_documents` / `test_document_metadata` / `test_tags` / `test_collections` / `test_autotag` / `test_webapp` / `test_inbox` / `test_pdf_qa_multiturn`）。 |

## 5. 共享文件改动（并行领地）与已知边界

- **共享文件最小改动**：`index.html` 仅重写 `#work-zone` 区块（其余视图/壳未动）；`style.css` 仅编辑器相关段
  （`.work-zone` 起至 `.actions`，及新增查看器/侧板规则），媒体查询与公共段未动；`state.js` 仅 +15 行元素注册。
  `router.js` / `app.js` / `library.js` / `pdf.js` **零改动**。
- 侧板为覆盖层：展开时遮住预览栏右缘约 340px（可通过 `⌘/` 或关闭按钮立即收起）；窄屏（≤900px）为 best-effort，
  未做窄屏专项验收（草案主场景为桌面 ≥1280）。
- 大图查看器平移用 pointer 事件（鼠标/触控板拖拽）；触屏捏合缩放未实现（滚轮/按钮已满足 AC）。
- `.markers` 容器已移除，issue 09/10 占位 marker 现作为隐藏 span 位于工具条内（未被任何测试引用的占位）。
- 未 push（按协议推送时机归维护者）、未合并 `main`、未自审。
- 证据截图依赖本机 Chrome；`tests/editor_workspace_dom.mjs` 的 Node harness 在无 `node` 环境会 skip
  （Python 结构 DOM 断言仍全跑）。

## Suggested skills

- `impeccable`（product register）：S3 在 `#version-panel` 内做版本对比信息密度/交互打磨时使用。
- `diagnose`：若出现「统一保存指示不更新」或「查看器缩放偏移」，沿 `saveMarkdown`/`applyViewerTransform` 链定位。
- `prototype`：S3 的并排 diff 形态可在动正式实现前先出一版可玩原型。
