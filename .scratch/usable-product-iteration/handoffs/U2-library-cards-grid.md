# Handoff — usable-product-iteration U2：文档卡片富化与 Library 网格重排

**Status: in-review** · Worker：graph2note-32 · Branch：`dev/u2-library-cards`（基于本地 main `63ffd0b`，已含 U1 merge `7643f9e`）
**Verified:** 全离线（TestClient + 纯函数 + Node 合同测试 + 本地 headless Chrome CDP 量测/截图；零真实网络调用）· 全量 `uv run pytest`：**626 passed, 0 failed, 0 skipped**（117.92s）· `node tests/library_cards.mjs` 通过

## 一句话

把 Library 卡片从「文件名 + 5 行空预览」升级为可辨识知识卡片（缩略图 / Markdown 标题 / 有效时间 / 标签 chips / 来源图标 / 悬停快捷操作），默认紧凑网格在 1440×1000 同屏完整可见 12 张卡（43 篇文档下首批缩略图请求 16 条，仅覆盖视口相交卡片），并新增舒适/紧凑密度切换与加载骨架。

## 1. 核心交付

| 文件 | 变更 |
|---|---|
| `graph2note/metadata.py` | 新增纯函数 `extract_headline(markdown)`：取首个非空行（剥离 ATX `#`、跳过 fenced code），无内容返回 `""` 交由前端降级文件名；导出到 `__all__`。 |
| `graph2note/store.py` | 新增 `_library_summary_fields(record)`，两个 store 的 `list_documents()` 统一追加 `headline / tags / source_pdf / page_number / version_count`（纯追加，不删字段）；`FileDocumentStore._load_record_with_metadata` 把已读到的 `markdown.md` 挂到 `current_markdown` 供摘要使用（不写入 record.json）。 |
| `graph2note/webapp.py` | `/api/documents` 追加 U2 卡片字段（`headline / tags / thumbnail_url / source_kind / source_label / source_pdf / page_number / version_count`），旧字段语义不变；新增 `GET /api/documents/{id}/thumbnail`（Pillow 离线缩放至最长边 480px，缓存为版本目录内 `thumbnail.png`，失败回退原图）。 |
| `graph2note/webstatic/js/library_cards.js`（新，纯模块） | 卡片 view-model（`cardTitle/cardFilename/cardDate/cardTags/cardSource`）、`cardHtml(doc, escape)`（缩略图仅 `data-src`+`loading="lazy"`）、`createThumbnailLoader`（IntersectionObserver 视口门控）、`wireCardActions`（点击进编辑器 / Enter / 悬停重新解析、删除，删除必须先确认）、密度规范化。无 import、加载期不碰 DOM，Node 直接可测。 |
| `graph2note/webstatic/js/views/library.js` | 卡片按新模块渲染；加载骨架（8 张 shimmer）替换空白等待；安装视口懒加载；密度切换写入 `localStorage` 并作用于 `#library-grid[data-density]`；快捷操作复用现有 `window.confirm` 文案，删除后重渲网格；顺带把 U1 未接线的过滤 chip 接上（切 URL）。 |
| `graph2note/webstatic/index.html` | `library-head` 内新增 `#library-density`（紧凑/舒适，`aria-pressed`）；4 行最小改动。 |
| `graph2note/webstatic/js/state.js` | 新增 `state.libraryDensity` 与 `el.libraryDensity` 两个字段（共享文件，最小行数）。 |
| `graph2note/webstatic/style.css` | Library 网格 `minmax(250px,1fr)`（舒适 `minmax(300px,1fr)`）、卡片缩略图紧凑 130px / 舒适 200px、标题 2 行截断、文件名次级、标签 chips、来源角标、悬停操作条、骨架 shimmer。仅改 Library 段。 |
| `tests/test_library_cards.py`（新，14 测试） | 纯函数 headline 边界；`/api/documents` 追加字段 + 旧字段不回退；编辑 Markdown 后 headline 跟随、无标题为 `""`；日期来自 `select_effective_time` 的 `effective_time`；标签透传；PDF 页来源；缩略图缩放 + 缓存 + 404；密度切换标记与前端接线；删除确认不回退；Node 合同测试入口（无 node 时 skip）。 |
| `tests/library_cards.mjs`（新） | Node 合同测试：标题/日期/标签/来源 view-model、卡片 HTML（`data-src`、无 eager `src`、转义）、**懒加载视口门控（43 张卡初始仅 12 张 `src`）**、小 fake DOM 上的点击/Enter/删除确认/重新解析确认行为。 |
| `tests/taxonomy.py` / `docs/testing.md` | 登记 `test_library_cards`（webapp 模块）。 |
| `.scratch/usable-product-iteration/evidence/` | `library-cards-1440.png`（`graph2note visual-qa capture`，1440×1000，43 篇 seeded 文档）与 `library-cards-metrics.json`（CDP 量测）。 |

## 2. Key decisions

- **标题 = 后端纯函数，前端只降级**：`extract_headline` 只有一份实现（Python），`/api/documents` 以追加字段 `headline` 暴露；前端 `cardTitle` 在 `headline` 为空时才用 `doc.title`（原文件名），避免「文件名优先」也不重复实现解析逻辑。
- **日期复用既有优先级链，不重写**：`/api/documents` 早已返回由 `graph2note.metadata.select_effective_time`（document_time > capture_time > import_time）选出的 `effective_time`；`cardDate` 只做 `slice(0,10)` 到天。测试用 `PUT metadata{document_time}` 验证手动日期胜出，未在 JS 里重实现时间戳链。
- **缩略图走服务端缩放端点而非原图 + CSS**：`/api/documents/{id}/thumbnail` 用 Pillow 缩到最长边 480px，缓存到版本目录内 `thumbnail.png`（新版本 = 新目录，天然失效）；缩放失败回退原图。相比直排 43 张原图，首屏 raster 体积显著下降。
- **懒加载是显式 IntersectionObserver 门控**：卡片 HTML 只产出 `data-src`（无 `src`），`createThumbnailLoader` 在进入视口时才赋 `src`；无 IO 环境降级为立即加载。这使「初始 img 请求数」可被 Node 合同测试直接断言，而不是依赖浏览器原生 `loading="lazy"` 的实现差异。
- **卡片操作复用现有破坏性操作确认**：删除用与文档视图一致的「不可恢复」确认文案；重新解析沿用会覆盖 Markdown 的确认。快捷操作在缩略图右上角悬停/聚焦时出现，点击它 `stopPropagation` 不会触发进入编辑器。
- **网格密度用 `data-density` + localStorage**：默认紧凑（`minmax(250px,1fr)`，4 列 @1440），舒适 `minmax(300px,1fr)`；`minmax` 保证 1280–1920 无横向滚动。
- **骨架只作用于 Library**：加载中渲染 8 张 shimmer 卡，不动全局 spinner 机制（按 issue 允许范围）。

## 3. 验证

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-32
uv run pytest tests/test_library_cards.py   # 14 passed
node tests/library_cards.mjs                 # library_cards: all assertions passed ✓
uv run pytest                                # 626 passed, 0 failed, 0 skipped (117.92s)
```

**视觉证据**（临时 seeding/server/CDP probe 仅在本机 `/tmp` 运行，仓库只留证据）：

- `graph2note visual-qa capture http://127.0.0.1:8766/#library -o .scratch/usable-product-iteration/evidence/library-cards-1440.png --viewport 1440x1000`
- `library-cards-metrics.json`（device-metrics 1440×1000，43 篇 seeded 文档，全部带标签、每 7 篇一个 PDF 页）：

| 指标 | 值 |
|---|---|
| 1440×1000 同屏完整可见卡片 | **12**（4 列 × 3 行） |
| 卡片总数 / 带缩略图 / 带标题 / 带日期 / 带来源图标 / 带 chips | 43 / 43 / 43 / 43 / 43 / 43 |
| 初始图片（缩略图）网络请求数 | **16**（视口内 12 张 + 第 4 行露出视口的 4 张；全库 43 张） |
| 横向溢出 @1440 / @1280 / @1920 | false / false / false（列数 4 / 3 / 6） |
| 密度切换 | `comfortable` → `data-density=comfortable`、3 列；切回 `compact` → 4 列 |
| 首卡 | 标题「强化学习纲要（第 43 页）」、文件名「IMG_2043.png」次级、日期「2026-02-17」、chips `#手稿 #待复习 #数学 +1`、来源 `image` |

**AC 逐条对照**

| AC | 证据 |
|---|---|
| 1440×1000 同屏 ≥12 张卡片，每张含缩略图/可读标题/日期/chips/来源图标；截图留证 | CDP：`fullyVisibleCards=12`、`first12FullyVisible=12`、`withThumbnail/withTitle/withDate/withSource/withChips` 全 43；截图 `library-cards-1440.png` |
| 43 篇下首屏图片懒加载，初始请求只覆盖视口内卡片（测试断言初始 img 请求数） | `tests/library_cards.mjs` 断言 43 卡初始仅 12 张赋 `src`、视口外 0；CDP 实测初始缩略图请求 16（均为与视口相交的卡片），远小于 43 |
| 标题取自 Markdown 首个非空标题/首行，无标题降级文件名 | `test_extract_headline_*`（5 例边界）+ `test_headline_follows_edited_markdown_and_falls_back_to_filename`；Node `cardTitle` 回退断言 |
| 日期取有效时间优先级链（复用既有纯函数） | `/api/documents` 返回既有 `effective_time`；`test_card_date_uses_effective_time_priority_chain` 断言手动 `document_time` 胜出、`source=manual`；JS 仅格式化 |
| 默认/密度网格在 1280–1920 无溢出、无横向滚动 | CDP `widthSweep` 1280/1920 与 1440 均 `horizontalOverflow=false`；密度切换后仍 false |
| 卡片点击/快捷操作有 DOM 断言测试；删除确认不回退 | `tests/library_cards.mjs` §8（fake DOM：click→open、Enter→open、取消删除不删、确认删除、取消/确认重新解析）；`test_delete_confirmation_is_not_bypassed` 断言 `window.confirm` 未被绕过 |
| 既有 documents/collections 元数据测试全绿；新增 API 字段向后兼容（老字段不变） | 全量 626 passed；`test_documents_list_appends_card_fields_without_touching_legacy` 断言 legacy 字段集合仍在、`title`/`metadata` 不变 |

## 4. 并行领地与共享文件（合并时协调）

- **共享文件改动（最小行数）**：`graph2note/webstatic/index.html`（`library-head` 内 +4 行密度控件）、`graph2note/webstatic/style.css`（**仅 Library 段**替换/新增）、`graph2note/webstatic/js/state.js`（+`libraryDensity` 两个字段）。U3/P2 若同改这三处，合并时以「各自区块」为准。
- **本 issue 独占**：`graph2note/webstatic/js/library_cards.js`、`graph2note/webstatic/js/views/library.js`、`graph2note/metadata.py`（新增函数）、`graph2note/store.py`（新增摘要字段与 helper）、`graph2note/webapp.py`（`/api/documents` 追加字段 + thumbnail 端点）、新增测试与证据。
- **未触碰**：编辑器模块（`views/document.js`）、问答视图（`views/pdf.js`）、数据看板（`views/dashboard.js`）、`repair.js`、`assets.js`；未改集合/标签/时间轴行为。

## 5. 未尽事项 / 已知边界

- `rootMargin` 设为 `0px` 以严格对齐「初始请求只覆盖视口内卡片」；滚动时缩略图随进入视口即时请求（本地工具延迟可忽略），未做预取。
- 卡片快捷「重新解析」只在卡片处发起并 toast，不跳转文档视图（解析进度仍由文档视图轮询展示）。
- 缩略图缓存写在文档版本目录 `thumbnail.png`（派生文件，删除文档时随之清理；`rglob` 类测试已按名称定位）。
- 顺带修复：U1 拆分后 `wireLibraryFilters()` 未被调用导致过滤 chip 失效——U2 在 `library.js` 模块初始化时接线（同一领地内）。
- 视觉证据依赖本机 Chrome；`tests/test_library_cards.py` 的 Node 合同测试在无 `node` 环境会 skip（其余断言仍全跑）。
- 未 push（按协议推送时机归维护者），未合并 `main`，未自审。

## Suggested skills

- `impeccable`：后续 U3/U4/U5 在骨架上继续做信息密度/交互打磨时可参考本卡的视觉层次（标题优先、次级信息降权、悬停操作）。
- `diagnose`：若出现「卡片标题/日期与文档视图不一致」，沿 `extract_headline` / `select_effective_time` → `/api/documents` → `library_cards.js` 链定位。
