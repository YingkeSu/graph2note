# Handoff P3 — 跨文档问答与统一搜索（⌘K）

Branch: `dev/p3-unified-search`（原自本地 `main` = `184500f` 新建，收尾时 rebase 到 U1 的 `main` = `7643f9e`；底座已含 P1、R1、S1、U1）
Issue: `issues/P3-cross-doc-unified-search.md` · Status → ready-for-review

## 1. 一句话结论

统一检索层落地：抽出的共享关键词引擎 `searchlib`，PDF 页索引（`pdfsearch`，兼容旧 API/落盘格式）
与新的文档 Markdown 块级索引（`unifiedsearch`）共用同一套 token/snippet/postings/持久化实现；
`/api/search` 一次返回**文档 + PDF 页**两组结果。跨文档问答把 scope 从单 PDF 扩到多 PDF / 全部，
跨 PDF 合并排序、按 PDF 去重、引用带 **PDF 名 + 页码**，无命中的 PDF 不进上下文。
顶栏搜索面板（⌘K 唤起、Esc 关闭、分组展示、文档进编辑器、PDF 跳原页、「就这些结果提问」跨视图预填）
以自包含 ES module 交付并在真实浏览器验证。全程离线 stub 测试可重复，CI 零真实模型调用。

## 2. 交付物

| 文件 | 内容 |
|---|---|
| `graph2note/searchlib.py`（新） | 共享检索引擎：中英混排 tokenizer（ASCII 词 + CJK bigram）、snippet、content hash、加权倒排构建（标题权重 2）、AND/OR 匹配、评分、fingerprint、JSON 索引读写。PDF 与文档两条索引都从这里取实现（非复制） |
| `graph2note/pdfsearch.py` | 改为调用 `searchlib` 原语；保留全部旧公开 API（`tokenize/make_snippet/store_fingerprint/index_path/build_index/load_index/get_index/search`、`INDEX_VERSION`、`_mem_cache`）与旧落盘结构不变；hit 新增 `pdf_name` |
| `graph2note/unifiedsearch.py`（新） | 统一索引：文档 Markdown 按**块/段级**入索引（空行 + 标题边界切块，按文档聚合命中 `matched_blocks`），PDF 页一页一条；fingerprint（id+updated_at+latest version+content hash）驱动增量一致；落盘 `<store>/search/unified-index.json`；`search()` 返回分组结果，支持 `kind` 过滤与 PDF scope |
| `graph2note/pdfqa.py` | 跨文档问答：`_search_scope` 对「全部/多 PDF」做**一次全局检索 + 跨 PDF 合并排序**（score → PDF 名 → 原页序，按 `(pdf_id,page_index)` 去重）；`_aggregate_by_pdf` 给出每 PDF 命中数/页（无命中为 0，不进上下文）；`Source`/引用/prompt 新增 `pdf_name`；`answer_question(pdf_names=...)`；`retrieval` 新增 `by_pdf`/`matched_pdfs`；顺带清掉重复的 `_call_with_timeout`/`_source_from_hit` 定义 |
| `graph2note/webapp.py` | 新增 `GET /api/search`（统一分组检索）与 `POST /api/search/reindex`；`_pdf_name_map()`（内存 job + 落盘 `job.json`）把上传 PDF 文件名接进统一检索与问答引用；`/api/pdf/ask` 传入 `pdf_names` |
| `graph2note/webstatic/search-panel.js`（新） | ⌘K/顶栏统一搜索面板（ES module）：输入即搜（180ms 防抖 + 请求代际防乱序）、文档/PDF 页分组、文档进编辑器、PDF 跳原页、「就这些结果提问」经 `sessionStorage` 跨视图预填问答输入；shell 自适应（U1 的 `#pdf-search-zone` 或现行 `#library`），Node 下无副作用可单测 |
| `graph2note/webstatic/index.html` | 顶栏加 `#global-search-form/#global-search-input`；新增 `#global-search-panel` 静态面板 DOM（含两组容器、Esc 关闭、提问按钮）；尾部加载 `search-panel.js` |
| `graph2note/webstatic/style.css` | 追加 `.global-search` / `.search-panel*` 样式（沿用既有配色/圆角体系） |
| `tests/searchlib` 无 | — |
| `tests/test_unified_search.py`（新，8 项） | 文档入索引（块级/标题/聚合/空查询）、文档+PDF 共用一个检索、增/改/删一致、**真实 R1 repair API 产生新版本**后索引跟随、reindex 落盘与缓存损坏自愈、API 分组结果与 kind 过滤、编辑后 API 一致 |
| `tests/test_p3_cross_doc_qa.py`（新，6 项） | 多 PDF 合并排序 + PDF 名/页码引用、无命中 PDF 不进上下文、scope=全部、无命中的 PDF 范围 → insufficient_evidence 且不调模型、引用纪律（越界 `[9]` → untrusted）、多 PDF scope 绑定会话 |
| `tests/test_search_panel.py`（新，3 项） | index.html DOM 断言（顶栏入口 + 面板两组结构 + 提问按钮）、`search-panel.js` 行为源断言（⌘K/Esc/防抖/分组/跳转/跨视图）、`node tests/search_panel.mjs` |
| `tests/search_panel.mjs`（新） | Node 纯函数 + 轻量 DOM stub：结果分组、页码回退、pending-ask 往返、QA 路由探测、**⌘K 打开 / Esc 关闭 / 输入框内忽略 / 分组渲染 / 跨视图提问预填** |
| `tests/taxonomy.py` | 登记 `test_unified_search` / `test_p3_cross_doc_qa` / `test_search_panel` → `webapp` |

## 3. 关键决策

- **共享引擎而非复制**：`searchlib` 只做与领域无关的原语（tokenizer/snippet/hash/倒排/持久化），
  `pdfsearch` 与 `unifiedsearch` 各自负责「快照哪些记录、元数据长什么样、结果如何分组」。
  `pdfsearch` 的公开 API、`INDEX_VERSION`、落盘 JSON 结构与 `_mem_cache` 全部保留，既有 issue 10
  测试一行未改即通过（含「删掉 index 文件 + 清 `_mem_cache` → 自愈重建」）。
- **文档按块索引、按文档聚合**：一个 Markdown 文档切成多个块 entry（召回更细），结果按
  `document_id` 归并为一个文档项并给出 `matched_blocks`；标题 token 权重 2，因此「标题命中」也能
  搜到且排在正文命中之前。PDF 页天然一页一条，不做二次聚合。
- **一致性口径沿 issue 10**：fingerprint 混入 `document_id + updated_at + latest version_id + 当前
  markdown 哈希`（哈希解决 1 秒时间戳分辨率下同秒编辑不可见的问题）。新建/编辑/删除/R1 重跑新版本
  都会改变 fingerprint → 下次检索重建；检索时再比对 entry 的 content hash 与快照内容，双保险，
  绝不返回已删除/过期文档。
- **多 PDF 合并排序**：`scope` 为空（全部）或多元素时，用**一次**全局检索（`MAX_LIMIT`）取回再
  限定 scope、按 `(pdf_id,page_index)` 去重、按 `score → PDF 名 → 原页序` 排序后取 top-k；单 PDF
  仍走单库检索。`retrieval.by_pdf` 逐 PDF 报命中数/页，无命中的 PDF 恒为 0 且从不进入 prompt/引用。
- **引用带 PDF 名 + 页码**：`Source` 增加 `pdf_name`，prompt 写作
  `<source id="1" pdf="a.pdf" page="2">`，citation payload 增加 `pdf_name`；文件名优先取
  webapp 的上传 job（内存 + 落盘 `job.json`），退化为 store 内可从页标题推导的 stem。
- **问答联动只做查询词传递**：面板「就这些结果提问」仅把当前查询词写入
  `sessionStorage["graph2note.pendingAsk"]` 并跳到问答视图预填首问，**不实现对话 UI**（归 P2）。
  已在问答视图时原地预填；跨视图时由 `hashchange` 后消费 pending 值。
- **前端自包含且可移植**：面板只依赖 `/api/search` 与固定元素 id，并自动探测 shell
  （存在 `#pdf-search-zone` → 跳 `#pdf-search`，否则 `#library`）。未触碰现行 `app.js` 内部，
  也不新增构建步骤。
- **搜索延迟**：`search` 每次先做一次轻量快照（读库记录算 fingerprint），这是「绝不返回过期内容」
  的代价；42 篇真实库实测快照 ~190ms、倒排构建 ~30ms，命中后不再重复读记录（快照顺带返回内容）。
  面板 180ms 防抖 + 请求代际，打字不卡。

## 4. AC 逐条证据

| AC | 证据 |
|---|---|
| 问答 scope=多 PDF：命中合并排序、引用含 PDF 名+页码、无证据/引用纪律沿 P1 | `tests/test_p3_cross_doc_qa.py`：`test_multi_pdf_scope_merges_and_cites_name_and_page`（A 页2 + B 页1 合并，`citations[*].pdf_name==[a.pdf,b.pdf]`，页码/`pdf_page_url` 对应，prompt 含 `<source id="1" pdf="a.pdf" page="2">`）；`test_scoped_pdf_without_hits_stays_out_of_context`（无命中 PDF → `by_pdf.hits==0`、prompt 只 1 个 source、无 b.pdf）；`test_scope_with_no_hits_is_insufficient_evidence`（不调模型）；`test_citation_discipline_is_unchanged_for_multi_pdf`（`[9]` → untrusted） |
| 文档 Markdown 入索引；新建/编辑/删除/R1 新版本后一致 | `tests/test_unified_search.py`：`test_document_markdown_enters_unified_index`（块级 + 标题 + 聚合）、`test_index_tracks_document_add_edit_delete`、**`test_repair_run_updates_unified_index`**（走真实 `/api/repair/run`，断言 `versions[-1].provenance=="repair"`，旧占位词消失、修复后新词可搜）、`test_reindex_builds_and_persists_for_both_sources`（落盘 + 删缓存自愈） |
| ⌘K 唤起面板、Esc 关闭；结果分组；文档进编辑器 / PDF 跳原页（DOM 断言） | `tests/test_search_panel.py`：`test_index_has_topbar_entry_and_search_panel_dom`（DOM 树断言顶栏 `#global-search-input`、`#global-search-panel[role=dialog]`、`data-search-group=documents/pdf_pages` 顺序、`#global-search-ask`）；`test_search_panel_js_wires_shortcuts_groups_and_jump_targets`（`metaKey/ctrlKey`+`"k"`、`escape`、`/api/search?q=`、`"#doc/"`、`source_page_url`、`target="_blank"`）；`tests/search_panel.mjs`（DOM stub 实跑 ⌘K 开、Esc 关、输入框内忽略、两组渲染、跨视图预填） |
| 「就这些结果提问」把查询词带入问答视图预填（跨视图传递测试） | `tests/search_panel.mjs`：pending-ask 写入/读取/清除往返；`askAboutResults()` 在异视图写入 pending → 路由切换 → `applyPendingAsk()` 落到 `#pdf-qa-input`；在当前问答视图则原地预填。真实浏览器另验（见 §6） |
| 索引构建/更新耗时记录（43 篇 + 多 PDF，无硬指标但要可感知不卡顿） | 见 §5：真实 43 篇快照 ~190ms / 建索引 ~30ms；43 篇 + 120 PDF 页冷检索 ~307ms、缓存命中 ~223ms、单文档编辑后 ~292ms |
| 离线契约测试全绿；CI 无真实模型调用 | `uv run pytest`：rebase 到 U1 底座后 **595 passed, 0 failed**（交付时为 567 passed；U1 底座自带约 28 项布局/路由测试）；全部通过 stub answerer / 合成 PDF / 注入 router，无网络与真实 LLM |

## 5. 索引耗时实测（AC5）

**环境**：本机 macOS，43 篇真实库 `~/Library/Application Support/Graph2Note/storage`（2402 个文档块 entry、4169 个 postings token）。真实库当前**无 PDF 页**（`pdf_id` 命中 0，无 `pdfs/` 目录），因此另在临时库中「复制 43 篇 + 注入 12 个 PDF × 10 页 = 120 页」（2522 entry、4191 token）模拟「43 篇 + 多 PDF」。测量只读：`build_index(persist=False)` 计时 + 临时库全链路，不写真实库。

| 场景 | 快照（fingerprint） | 倒排构建 | 冷检索（建+落盘） | 缓存命中检索 | 单文档编辑后重建 | 新内容可见 |
|---|---|---|---|---|---|---|
| 真实 43 篇（无 PDF） | 192 ms | 30 ms | — | — | — | — |
| 43 篇 + 120 PDF 页 | 251 ms | 40 ms | **307 ms** | **223 ms** | **292 ms** | 228 ms |
| PDF-only 快照（共用引擎） | 99 ms（43 篇）/ 265 ms（+120 页） | — | — | — | — | — |

统一索引落盘 ≈ **1.7 MB**（43 篇 + 120 页）。结论：一次构建/更新 < 0.35s，命中匹配（postings）< 0.02ms；
主要成本是快照读库记录（保证不返回过期内容的既定代价），前端以 180ms 防抖 + 请求代际消化，
打字无明显卡顿。无硬性指标，故不改动快照策略以保证 issue 10 的一致性口径。

## 6. 真实浏览器验证（现行 UI）

用临时库（2 篇文档 + 1 个双页 PDF 页文档）启动 `uvicorn graph2note.webapp:create_app --factory`，
在 AO Browser 面板实测：

- 顶栏出现「统一搜索」输入框；输入「卡尔曼」自动弹面板，`/api/search` 返回分组：**文档 1** +
  **PDF 页 1**（PDF 项显示 `scan-review · 第1页`、正文高亮、含「打开校对文档 / 查看原 PDF 页」）。
- `Esc` 实测关闭面板。
- `#global-search-ask`「就这些结果提问」实测关闭面板并把问答输入框预填为「卡尔曼」。
- 说明：AO 自动化的 `press "Meta+k"`/`click` 在本机 Electron 环境未把修饰键事件送达页面（⌘K 被宿主
  快捷键层截获），故 ⌘K 行为以 `tests/search_panel.mjs` 的 DOM stub 行为测试为准（同一条
  `keydown` 监听路径已由实测的 Esc 开关键盘行为证明可用）。

## 7. 与 U1 的适配（已落地：P3 三个提交 rebase 到 U1 底座）

开工时（~10:43）`main` 仅含 R1，故先以**现行 UI** 上的自包含面板交付；收尾时 U1 已并入 `main`
（`7643f9e merge: U1 — 全局布局与导航重构`），因此把 P3 的 3 个提交 rebase 到 `7643f9e`，
并落地原计划的适配步骤：

1. `graph2note/webstatic/app.js` 顶部 `import "./search-panel.js";`——U1 的
   `tests/test_webapp_layout.py` 断言唯一 module 入口 `/static/app.js`，故不再新增
   `<script type="module">`。
2. `#global-search-panel` 静态块移入 U1 的 `index.html`（U1 顶栏已有 `#global-search-input`，
   占位文案改为「搜索文档 / PDF（⌘K）」）。
3. `js/ui.js::wireGlobalSearch()` 的 U1 占位提示退化为 no-op：⌘K / Esc / 顶栏入口统一由
   `search-panel.js` 处理，避免重复 submit 与重复 keydown 行为。
4. `tests/test_search_panel.py` 改为断言 `app.js` 导入该模块（不再断言 `index.html` 中的
   `/static/search-panel.js`），DOM 断言保持不变。
5. 面板自动探测 `#pdf-search-zone` → 「就这些结果提问」跳 `#pdf-search`，无需改动。

rebase 中 `graph2note/webstatic/index.html` 出现冲突，按上述口径手工解决；其余文件无冲突。

**评审期集成补充（reviewer，合并进 main 后）**：P2 已在 main 上把问答视图升为一级 `#ask` 并把
`#pdf-search-zone` 改名为 `#ask-zone`（`#pdf-search` 仅留作别名路由），因此 P3 原来的 shell 探测
（无 `#pdf-search-zone` → `#library`）会在集成后把「就这些结果提问」落到不承载问答表单的 Library。
已在集成提交 `e11f827` 把 `qaRoute()` 改为优先探测 `#ask-zone` → `#ask`（U1 与旧壳回退不变），
并补齐 `tests/search_panel.mjs` / `tests/test_search_panel.py` 断言；`sessionStorage["graph2note.pendingAsk"]`
+ `#pdf-qa-input` 的 P2 兼容入口不变。合并后全量 `uv run pytest` 777 passed / 0 failed。

## 8. 如何运行

```bash
uv run pytest tests/test_unified_search.py tests/test_p3_cross_doc_qa.py tests/test_search_panel.py
node tests/search_panel.mjs
uv run pytest -m webapp          # 全量 webapp 模块
uv run pytest                    # rebase 到 U1 后全量 595 项（108s–5m16s，视整机负载）
```

> **收尾验证（P3 收尾会话，rebase 到 U1 之后离线复跑）**：`node tests/search_panel.mjs` →
> `all assertions passed`；`uv run pytest` 一次全量运行 **595 passed, 0 failed（108s）**。
> 另一次全量运行出现 1 红：`tests/test_pdf_job_recovery.py::test_page_timeout_marks_failed_and_job_completes`
> ——issue 09 的墙钟超时用例（`pdf_page_timeout=1` + 1.5s 慢页），整机高负载（10 核 load ~5–9）下
> 非慢页也会超过 1s；该测试文件与 `graph2note/pdflib.py` 相对 `main` 未改动，隔离运行 4/4 通过，
> 属既有负载敏感 flake，与 P3 无交集。

## 9. 未尽事项 / 已知边界

1. **首版无向量检索**（草案既定）：统一检索与跨文档问答都用关键词倒排；embedding 通道是开放问题，
   不在本 issue。
2. **快照成本**：每次检索先读库算 fingerprint（~190ms/43 篇）。若未来库规模显著变大，可引入
   「按记录 mtime 短路的内容哈希缓存」，但需保持 issue 10 的一致性口径，未在本 issue 做。
3. **PDF 名来源**：上传 PDF 的文件名来自 webapp job（内存 + `job.json`）；脱离 webapp 直接调用
   `pdfsearch/unifiedsearch` 时退化为 store 内页标题 stem。`pdfqa.answer_question` 新增可选
   `pdf_names` 参数供调用方注入。
4. **「跳原页」是打开原 PDF 页 PNG**（新标签），因为应用没有独立的 PDF 阅读器路由；文档项点击/链接
   进入三栏编辑器。若后续 U 系引入 PDF 阅读器视图，可改为应用内跳转。
5. **面板交互依赖设备键盘事件**：⌘K 在宿主 Electron 中可能被截获；面板同时支持点击顶栏输入框打开，
   `Ctrl/⌘K` 在普通浏览器中生效。
6. **U1 适配已随 rebase 落地**（见 §7）：P3 的 3 个提交现以 U1 的 `main`（`7643f9e`）为底座。
7. **未 push / 未合并 / 未自审**：所有提交留在 `dev/p3-unified-search`，推送与合并归维护者；
   未改 `BOARD.md` 与 `issues/*.md`。

## 10. 相关文件

- 实现：`graph2note/searchlib.py`（新）、`graph2note/unifiedsearch.py`（新）、`graph2note/pdfsearch.py`、
  `graph2note/pdfqa.py`、`graph2note/webapp.py`
- 前端：`graph2note/webstatic/search-panel.js`（新）、`graph2note/webstatic/index.html`、
  `graph2note/webstatic/style.css`
- 测试：`tests/test_unified_search.py`（新）、`tests/test_p3_cross_doc_qa.py`（新）、
  `tests/test_search_panel.py`（新）、`tests/search_panel.mjs`（新）、`tests/taxonomy.py`
- 上游：`handoffs/P1-pdf-multiturn-qa.md`、`graph2note/pdfsearch.py`（issue 10）、`handoffs/R1-*.md`
- 下游：P2（消费「就这些结果提问」的查询词预填、对话 UI）
