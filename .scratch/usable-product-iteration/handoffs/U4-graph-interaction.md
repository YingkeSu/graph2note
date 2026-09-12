# Handoff — usable-product-iteration U4：知识图谱交互升级

**Status: in-review** · Worker：graph2note-39 · Branch：`dev/u4-graph-interaction`（基于本地 main `056998e`）
**Verified:** 全离线（TestClient + Node 纯函数 + 本地 headless Chrome CDP/`visual-qa capture`；零真实网络、零模型调用）· 全量 `uv run pytest`：**692 passed, 0 failed, 0 skipped**（102.94s）

## 一句话

把「43 文档全量挤成一根 3348px 高、节点 8px 的不可读列」升级为可导航视图：确定性力导向布局 + 包围盒分离保证**零节点重叠**、滚轮缩放（0.25×–4×）/拖拽平移/适应视图、按边来源与集合/标签过滤（URL 状态 + 可见反馈）、大库默认主题聚类收敛（点击展开）、点击节点 1-hop 邻域聚焦；导航三类节点行为与现状一致。

## 1. 核心交付

| 文件 | 变更 |
|---|---|
| `graph2note/webstatic/js/views/graph-layout.js`（新，730 行） | 纯函数布局引擎：`computeLayout`（确定性力导向 + 空间哈希包围盒分离）、`solveFromPositions`（聚类视图二次分离）、`nodeBox/labelWidth/overlapCount/findOverlaps`、`subgraph`（来源/集合/标签过滤）、`applyClusters`、`focusSet`、`viewBoxFor/zoomedViewBox/panBy/clampZoom`。无 DOM、无 `fetch`、无 CDN、无构建。 |
| `graph2note/webstatic/js/views/graph.js`（93 → 548 行） | 图谱视图：渲染 + 工具栏（缩放±/适应/重置/聚类）+ 过滤 chips + 状态行 + 邻域聚焦 + `window.__g2nGraph` 只读 QA seam。 |
| `graph2note/webstatic/index.html` | `#graph-zone` 内新增 `#graph-toolbar`（12 个控件）、`#graph-filters`（来源/集合/标签 chips + 清除）、状态行；**现有 `.graph-legend`（主题/标签/手工）原样保留**。 |
| `graph2note/webstatic/style.css` | 仅替换/扩展 Graph 段（`.graph-toolbar/.graph-chip/.graph-node-cluster/.graph-node.faded` 等），无其它视图改动。 |
| `graph2note/webstatic/js/state.js` | +12 行元素注册（graph 控件）。 |
| `graph2note/webstatic/js/router.js` | `#graph?src=&set=&tag=&topic=&focus=&clusters=` 解析 + `graphHash()`；`#graph` 旧路径返回值与 U1 完全一致。 |
| `graph2note/graph.py` | `/api/graph` 响应**新增** `clusters`（按首个主题聚合文档，投影字段，不进 `nodes`）与 `filters`（collections/tags 计数 + sources）；`nodes/edges/sources/empty/counts` 语义未动。 |
| `tests/graph_layout.mjs`（新） | Node 纯函数契约：**零重叠（展开/收敛两种视图）**、确定性（输入反转仍逐点相同）、0.25×–4× 边界、缩放锚点不漂移、平移、1-hop 聚焦、来源/集合/标签过滤、标签截断；输出 JSON 摘要供 Python 断言。 |
| `tests/test_graph_layout.py`（新，9 测试） | 三层：API 契约（新增字段 + 前 U4 字段逐项不变 + TestClient 端到端）、graph-zone DOM 契约（控件/图例/zero-build 红线）、布局引擎摘要断言（`overlapPairs == 0`）。 |
| `tests/router_routes.mjs` | 增补 graph URL 状态解析与 `graphHash()` 往返（含中文/空格编码、旧 `#graph` 形状）。 |
| `tests/test_graph.py` | 空图断言改为「前 U4 键逐项相等 + 新增键为空」（语义未放宽）。 |
| `tests/taxonomy.py` / `docs/testing.md` | 登记 `test_graph_layout`（workspace 模块）。 |
| `scripts/seed_u4_evidence.py` / `scripts/u4_graph_probe.mjs` / `scripts/u4_evidence_metrics.py` / `scripts/u4_capture_evidence.sh` | 43 文档种子库 + CDP 量测 + `visual-qa capture` 前后对比的可复现管线。 |
| `.scratch/usable-product-iteration/evidence/` | `graph-before.png` / `graph-after.png`（`graph2note visual-qa capture`，1440×1000）+ `graph-interaction-metrics.json`（CDP 量测前后对比）。 |

## 2. Key decisions

- **布局引擎与视图分离且可测**：所有几何/过滤/缩放数学都在 `graph-layout.js`（纯函数），所以「节点包围盒相交数为 0」是 Node 里可复现的程序化断言（`overlapCount` + `findOverlaps`），不是目测；`graph.js` 只做渲染与事件。
- **零外部图库**：力导向（斥力 + 弹簧 + 重力）与包围盒分离共约 200 行自写，浏览器 `type="module"` 直接加载，无构建步骤。这是 issue 允许的「轻量自写算法」路径，未引入任何 CDN。
- **零重叠是硬保证，不是调参侥幸**：分离阶段把每个节点的包围盒按 `nodeGap/2` 外扩后再判定，因此收敛后两盒间距 ≥ `nodeGap`（不只是不相交）；`overlapCount` 在最终坐标下严格为 0。注意顺序：先按目标跨度 `TARGET_SPAN` 归一，**再**在最终单位做分离，避免缩放把间隙重新压没（这是首版失败的根因）。
- **节点包围盒 = 圆 ∪ 预留标签矩形**：标签渲染在圆内、11px CJK 字形可能高于圆直径，所以 `nodeBox` 取两者并集；渲染截断（`LAYOUT.maxLabelChars`）与布局引擎共用同一常量，DOM 量测 `textW ≤ nodeW` 为 0 例溢出。
- **聚类是投影，不改图语义**：`clusters` 按 `topics[0]` 聚合（无主题进单一「未归类」桶），每个文档恰好属于一个聚类；聚类节点只在视图侧合成（`kind="cluster"`），不写回 `nodes`。大库（>24 可见节点）默认收敛，点击聚合节点就地展开该聚类；「聚类收敛/展开」按钮切换全局。
- **聚焦是视图态、不重排**：点击文档节点 → 1-hop 高亮 + 其余透明度 0.16；再点同节点或点空白 → 恢复（不触发 `computeView`，只重绘，保持位置稳定）。双击（或对已聚焦节点再点一次 / Enter）走既有导航。
- **过滤状态进 URL**：`#graph?src=topic,tag&set=<collection>&tag=<tag>&focus=<id>&clusters=collapse`，与 U1「URL 即唯一事实来源」一致；空状态折叠回 `#graph`，旧链接/前进后退不受影响。
- **导航语义零改动**：文档 → `#doc/<id>` 三栏编辑器；主题 → `#library/topic/<t>`；标签 → `#library/tag/<t>`（CDP 逐项验证 `editorVisible/libraryVisible`）。
- **测试纪律**：既有断言不放宽；`test_graph.py` 的空图断言从整体 `==` 改为「前 U4 键逐项 `==` + 新增键为空」，是新增字段的必要适配（issue 明确允许扩展响应字段）。

## 3. 验证

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-39
uv run pytest                                  # 692 passed, 0 failed, 0 skipped (102.94s)
uv run pytest tests/test_graph_layout.py -q    # 9 passed（API + DOM + 引擎摘要）
node tests/graph_layout.mjs                    # 11 项断言全过（含 overlapPairs=0）
node tests/router_routes.mjs                   # router_routes: all assertions passed ✓
bash scripts/u4_capture_evidence.sh            # 43 文档库 → before/after 截图 + 量测 JSON
```

**AC 逐条对照**

| AC | 证据 |
|---|---|
| fixture 图（≥30 文档 + 多主题/标签）渲染后无节点重叠（包围盒相交数 = 0，程序化断言），默认无需缩放可辨主体 | `tests/graph_layout.mjs`：37 文档 / 76 边 fixture，展开视图 `overlapPairs=0`、收敛视图 `overlapPairs=0`；`tests/test_graph_layout.py::test_layout_engine_reports_zero_overlap` 断言 `documents>=30` 且两种视图均为 0。真实库 CDP：默认收敛 26 节点、展开 60 节点、单标签过滤 24 节点，DOM 包围盒相交数均为 **0**（`graph-interaction-metrics.json`）。默认视图 `pixelsPerUnit=0.7753`，节点渲染 ~60px（before 为 0.1885 / 8px）。 |
| 缩放/平移/适应视图可用，覆盖 0.25×–4×，操作不丢节点 | CDP：`zoom.min={label:"25%", nodes:26}`、`zoom.max={label:"400%", nodes:26}`、`fit={label:"100%", nodes:26}`；滚轮 110%→100%；拖拽 `panBefore 0 0 828 801 → panAfter 103.19 64.49 828 801`。Node 断言 `clampZoom(0.01)=0.25`、`clampZoom(99)=4`、缩放锚点分数位置不漂移、各缩放级节点数不变。 |
| 按边来源与集合/标签过滤后仅显示匹配子图；过滤状态有 UI 可见反馈 | CDP：关掉 `manual` → `sources=["topic","tag"]`，60→58 节点、141→126 边，hash `#graph?src=topic%2Ctag&clusters=expand`；单标签「参考」→ 24 节点 / 38 边；`清除过滤` 回 60 节点。DOM 断言 `#graph-status` 文案含「边来源：…」「标签：#…」「聚类收敛：9 个主题聚合」，chips `aria-pressed` 与 `.active` 同步（`tests/test_graph_layout.py::test_graph_zone_owns_toolbar_filters_and_legend`）。聚类收敛可点击展开：点 `cluster:topic:化学` → 该主题 5 篇文档就地展开（26→30 节点、聚类 9→8），全局按钮展开 → 60 节点，三种视图 `overlaps=0`。 |
| 点击文档节点进入邻域聚焦态，导航三类节点行为与现状一致（DOM 断言） | CDP 聚焦：点击 `document:doc-22` → 56 节点 + 138 边淡化、状态行「聚焦邻域（点击空白恢复）」；点空白 → 淡化归 0、`focusId=null`。导航：文档 dblclick → `#doc/doc-22` 且 `work-zone` 可见；主题 → `#library/topic/%E5%8C%96%E5%AD%A6`；标签 → `#library/tag/%E5%8F%82%E8%80%83`，`library-zone` 均可见。 |
| 真实库（43 篇）截图前后对比留证（`visual-qa capture`），对比显示重叠/可读性显著改善 | `.scratch/usable-product-iteration/evidence/graph-before.png`、`graph-after.png`（均 `graph2note visual-qa capture` 1440×1000）+ `graph-interaction-metrics.json`：before `viewBox 0 0 1000 3348`、`pixelsPerUnit 0.1885`、节点 8px；after 默认收敛 `viewBox 0 0 828 801`、`pixelsPerUnit 0.7753`、节点 47px；展开视图 60 节点 `pixelsPerUnit 0.5853`、节点 35px。复现：`bash scripts/u4_capture_evidence.sh`。 |
| 图谱视图模型与 API 测试全绿；不新增真实模型调用 | 全量 692 passed；`/api/graph` 新增字段有 TestClient 契约测试；`tests/test_graph_layout.py::test_layout_engine_is_offline`（引擎无 `fetch`/`http`）与 `::test_u4_sources_do_not_call_models`（视图无 `/api/parse`、`openai`、`gateway`）。 |

**证据文件**：`graph-before.png`、`graph-after.png`、`graph-interaction-metrics.json`。

## 4. 后续 issue 的挂载点

- **U5 时间轴**：未触碰 `js/views/timeline.js` 与 `#timeline-zone`；图谱新增的 `.graph-chip/.graph-toolbar` 样式是 graph 专属 class，可直接复用视觉。
- **P2 问答 / P3 搜索**：未触碰侧栏、顶栏、`#pdf-search-zone`、`ui.js`。
- **P3 若要给图谱接搜索**：`window.__g2nGraph` 的 `focusId/clusters/sources` getter 可作为只读查询面；过滤状态走 `graphHash()`（`router.js`）。
- **API 扩展**：新增字段集中在 `graph.py` 的 `_build_clusters/_collection_filters/_tag_filters`，`counts` 未变；后续若要「集合层聚合」可复用 `clusters` 结构（`documents` + `label` + `route`）。
- **测试辅助**：前端行为断言用 `tests/static_assets.py::static_js()`；Node 纯函数测试沿用 `tests/*.mjs` + Python 驱动的模式（`tests/test_graph_layout.py` 是模板）。

## 5. 未尽事项 / 已知边界

- **窄屏（≤900px）为 best-effort**：工具栏/chips 会换行，未做窄屏专项验收（草案 §2.1 以桌面 ≥1280 为主场景）。
- **超大规模库**：布局求解是 O(n²) 力导向 + 空间哈希分离；43 文档 60 节点实测 <100ms，几百节点仍在预期内，但未在 >500 节点库上验收。
- **聚类只在视图侧展开**：点击聚合节点就地展开的是当前渲染（`view.expanded`），不写入 URL，也不跨重新渲染保留；全局「聚类收敛/展开」按钮走 URL。若后续需要「记住展开的聚类」，可把 `expanded` 编入 `graphHash`。
- **未 push（按协议推送时机归维护者），未合并 `main`，未自审，未改 `BOARD.md` / `issues/*.md`。**
- 截图与 CDP 量测依赖本机 Chrome；`tests/graph_layout.mjs` 在无 `node` 环境会 skip（Python 端 DOM/API 断言仍全跑）。

## Suggested skills

- `impeccable`：图谱视觉密度/配色/微交互进一步打磨（本轮以交互与可读性为先，配色沿用既有体系）。
- `diagnose`：若出现「布局失真/缩放后节点丢失」类问题，按 `computeLayout → fitToViewBox → separate → applyViewBox` 链定位（首版失败根因即在此链的顺序）。
- `prototype`：聚类展开/过滤形态的进一步探索可在动正式实现前先出可玩原型。

## 评审修复记录（review-U4：2 blocker + 4 minor）

**基线**：`005fc3b`（评审对象）→ 本段记录修复后分支状态。修复提交仍在
`dev/u4-graph-interaction`；未 push、未合并 `main`、未自审、未改 `BOARD.md` / `issues/*.md`。

### Blocker

| Finding | 修复方式 | 测试证据 |
|---|---|---|
| **U4-1 平移二次加速**：`pointermove` 在已含上一次 pan 的 CTM 下换算指针，`dragging.x` 又是 pointerdown 参考点，pan 累计位移被反复计入（50 事件位移 -2550px），且单次移动方向与 grab 光标相反。 | `pointerdown` 只记录屏幕坐标 `lastX/lastY`；`pointermove` 用 `pointerToLayout()` 对“上次/本次”两个 client 点各算一次布局坐标，取**增量** `view.pan -= (to - from)`（每步独立，不再喂回累计 pan），方向改为 grab 语义（内容跟随指针）。布局取 `currentLayout()`。 | `tests/graph_interaction.mjs` → `drag_pan_is_linear_across_many_pointermoves`：6 事件（≥5）每步增量恒为 `(-20, -10)`，总位移 `(-120, -60)`；`tests/test_graph_interaction.py` 逐项断言 `increments == [-20]×5`、`total == -20/step`、方向为负。**回归有效性**：把 `graph.js` 暂存回 `005fc3b` 后该断言在 step 1 即失败（旧实现 step1 `pan.x=+20`，方向反且随后进入 20/40/80… 累加）。 |
| **U4-2 topic/tag 单击导航回退**：`wireGraphNodes()` 的 click 对所有 kind 先进聚焦态，topic/tag 单击不再 `go(route)`。 | 抽出单一 `activateNode()`：cluster → 就地展开；document → 首击聚焦、再击导航；topic/tag/collection → 直接 `go(route)`（不进入聚焦）。click 与 keydown 共用该路径，鼠标/键盘不再分叉。 | `tests/graph_interaction.mjs` → `document_click_focuses_then_navigates`（首击 `focusId`、hash 不动；再击到 `#doc/d00`）与 `topic_and_tag_click_navigate_directly`（topic/tag/collection 单击后 `focusId===null` 且 hash 为目标 `#library/...` route）。Python 端 `test_single_click_navigation_for_document_topic_tag` 断言三类 nodeId/route/focusId。 |

### Minor

| Finding | 修复方式 | 测试证据 |
|---|---|---|
| **U4-3 聚类节点 keydown 无效**（role=button/tabindex=0 无 data-route，Enter/Space 无响应） | keydown 改走 `activateNode()`，cluster 分支展开该聚合（不再依赖 `data-route`）；Enter 与 Space 行为一致。 | `tests/graph_interaction.mjs` → `cluster_keyboard_expand_and_toggle_feedback`：对 cluster 节点派发 Enter 后可见节点数 `before 9 → after 16`；Python 断言 `after > before`。 |
| **U4-4 聚类切换按钮无状态反馈**（两态文本/class 不变，`.graph-button.active` 死 CSS） | 新增 `renderClusterToggle()`（随每次 `renderSvg`）：按**渲染结果**（`view.rendered.aggregates`）更新文案「聚类收敛/聚类展开」、`.active` 与 `aria-pressed`。 | 同一 harness 断言：收敛态文案「聚类收敛」+ `.active` + `aria-pressed="true"`；展开态「聚类展开」、无 `.active`、`aria-pressed="false"`。 |
| **U4-5 tooltip 文案与实现不符**（聚类写「双击展开」，实为单击；首击后节点重建 dblclick 不生效） | 聚类 tooltip 改为「单击展开」；顺带把 document/其它节点的 route hint 改为与当前语义一致（文档「单击聚焦邻域、双击进入编辑器」，主题/标签/集合「单击在文档库中过滤」）。 | harness 断言收敛视图 `canvas.innerHTML` 含「单击展开」。 |
| **U4-6 缩放锚点用未收敛布局**（缩放/按钮传 `view.layout`，`viewBoxFor()` 用 `view.rendered.layout`） | 新增 `currentLayout()` 统一取 `view.rendered.layout`，`viewBoxFor`、滚轮缩放、缩放±按钮全部改用它；fit/reset 只改 zoom/pan 不受影响。 | harness → `zoom_button_anchor_uses_rendered_layout`：先确认收敛 rendered layout 与展开 layout 不同（`680×826` vs `477×574`），再点「放大」断言 `pan.x = 0.5·W·(1-1/zoom)`、`pan.y = 0.5·H·(1-1/zoom)`，W/H 为**收敛后** rendered 尺寸；若仍传 `view.layout` 该值不等。 |

**观察项（可读性口径，不改 AC 文案）**：tooltip / 状态提示只是把「节点上已有的交互语义」说清楚——单击=聚焦（仅文档）/导航（主题、标签、集合）/展开（聚类），双击仅作为文档的直达编辑器快捷键保留；切换按钮文案描述当前渲染态而非固定值。这些均为文案与标签口径，不改变任何 AC 的判定条件或阈值。

### 修复后验证（全离线，CI 零网络 / 零模型调用）

```bash
uv run pytest            # 696 passed（基线 692 + 新增 4 条 DOM 交互断言）
node tests/graph_layout.mjs       # 通过（零重叠等原有断言不变）
node tests/router_routes.mjs      # router_routes: all assertions passed
```

新增测试文件 `tests/graph_interaction.mjs`（Node 最小 DOM shim，驱动真实 `views/graph.js`）与
`tests/test_graph_interaction.py`（`build_graph` 真实 payload + 运行 harness 并断言摘要），
已在 `tests/taxonomy.py` 登记为 `workspace`；`docs/testing.md` 模块表同步。
后一位 reviewer 可只跑 `uv run pytest tests/test_graph_interaction.py -q` 复核本段全部 6 条。

