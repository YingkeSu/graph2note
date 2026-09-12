# Handoff — usable-product-iteration U5：时间轴可视化升级

**Status: in-review** · Worker：graph2note-40 · Branch：`dev/u5-timeline-visual`（基于本地 main `056998e`，即包含 S1/P1/R1/A1/U1/A3/S2/A2 的基线）
**Verified:** 全离线（TestClient + 纯函数 + Node 合同测试 + 本地 headless Chrome CDP 量测/截图；零真实网络调用）· 全量 `uv run pytest`：**694 passed, 0 failed, 0 skipped**（106.82s）· `node tests/timeline_view.mjs` 通过

> 基线提示：开工后 main 又合入 U3（`6272463`）与 P2（`9a6890f`），当前 main 尖端为 `1acad49`。本分支按协议仍基于 `056998e`、未合并 main；U3/P2 未触碰 `timeline.js/timeline.py/webapp.py`，仅与我在 `index.html` / `state.js` / `style.css` 三个共享文件上邻近，合并时以「各自区块」为准（见 §4）。

## 一句话

把时间轴从「分组卡片列表」升级为有时间感的只读可视化视图：垂直主干 + 按天/周刻度、条目缩略图/标题/来源图标/标签计数、空档「间隔 N 天」标记、同主题相邻段的可展开彩色色带，以及顶部按月密度条（点击跳转）；`/api/timeline` 仅追加字段（旧语义不变），真实浏览器 43 篇实测缩略图懒加载只请求视口内 5 条，全程零非 GET 调用。

## 1. 核心交付

| 文件 | 变更 |
|---|---|
| `graph2note/timeline.py` | `/api/timeline` 投影追加字段：`thumbnail_url`（preprocessed → original）、`source_kind` / `source_label`、`tag_count` / `topic_count`；每个分组追加 `first_date` / `last_date` / `gap_days`（相邻组实际文档日期间隔天数，首组为 `None`、相接为 `0`）；顶层追加 `density`（按月文档量，含可跳转的 `group_key`）与 `density_max`。既有字段与排序逻辑逐字未改。 |
| `graph2note/webapp.py` | `/api/timeline` handler 在调用纯投影前，用新增私有 `_resolve_thumbnail_url()` 对文件系统做只读存在性解析（preprocessed 缺失回退原图，均缺失为 `None`），使 `timeline.py` 保持纯函数。共享文件改动 +28 行。 |
| `graph2note/webstatic/js/timeline_view.js`（新，纯模块） | 无 import、加载期不碰 DOM，Node 可直接测：`topicColor`（主题稳定配色）、`sourceIcon`、`gapLabel`、`timelineItemVm`、条目/分组/gap/密度条 HTML、`runBandsHtml`、`createThumbnailLoader`（IntersectionObserver 视口门控）、`toggleRunBand`（展开/收起高亮）、`wireTimeline`（条目导航 + 色带 + 密度跳转）、`loadTimeline(api, groupBy)`（唯一一次 GET）。 |
| `graph2note/webstatic/js/views/timeline.js` | 重写渲染：主干 + 刻度分组、条目卡片、gap 标记、色带、密度条；接入视口懒加载；`#timeline/day|week` 与分组切换语义不变；只读（仅 `loadTimeline`）。 |
| `graph2note/webstatic/index.html` | 时间轴区块 +3 行：新增 `#timeline-density` 容器、无日期区回退说明文案、`#timeline-undated-items` 由 `<div>` 改为 `<ol>`（条目现在渲染为 `<li>`）。 |
| `graph2note/webstatic/js/state.js` | 追加 `el.timelineDensity` 一行。 |
| `graph2note/webstatic/style.css` | 仅替换/扩展 Timeline 段：密度条、主干 `::before` + 刻度圆点、gap 药丸、色带/色轨、缩略图/来源角标/标签计数、响应式（≤900px 隐藏主干）与 `#timeline-undated` 卡片。其它视图样式未动。 |
| `tests/test_timeline_visual.py`（新，11 测试） | 字段追加与旧语义；gap 标记与分组排序不回归；月度密度；API 追加字段 + 缩略图端点 200；空库/无日期状态；静态主干/只读 DOM 断言；Node 合同测试入口（无 node 时 skip）。 |
| `tests/timeline_view.mjs`（新） | Node 合同测试：配色/来源图标/gap、条目与分组 HTML、色带展开收起、密度条、**只读 mock（仅 GET）**、**43 条仅视口内 12 条赋 `src`**、无 IntersectionObserver 降级。 |
| `tests/taxonomy.py` / `docs/testing.md` 注释 | 登记 `test_timeline_visual`（workspace，integration）。 |
| `.scratch/usable-product-iteration/evidence/` | 改造前后截图 + CDP 量测 + 交互探针（43 篇 seeded 库）。 |

## 2. Key decisions

- **字段只追加，不改旧语义**：`build_timeline` 原有键（`document_id/title/date/effective_time/topics/tags/collections/updated_at/route/document_url`、`topic_aggregates/adjacent_topic_runs`、`group_by/groups/undated/undated_count/total/has_undated`）全部保留；新增键均为 append-only，分组排序/主题运行段逻辑未动（既有 `test_timeline.py` 逐字通过）。
- **缩略图：U2 未合并，按协议用现有原图端点 + CSS 缩放 + 懒加载，并注明假设**。U2 的 `/api/documents/{id}/thumbnail`（服务端 480px 缩放）与 `data-src` 门控模式在 U2 合并后应统一：本 issue 的 `thumbnail_url` 目前指向既有 `GET /api/documents/{id}/preprocessed`（失败回退 `/original`），前端已用同一 `data-src` + IntersectionObserver 形态，替换端点即可，无需改交互。
- **纯投影 vs 文件系统**：`_thumbnail_url` 在直接调用时信任记录声明的路径（保持纯函数、便于单测）；API handler 通过 `record["thumbnail_url"]` 显式传入文件系统校验结果（含显式 `None` 哨兵，避免缺失文件仍生成 404 链接）。
- **gap 以「相邻分组实际文档日期」计算**：`(本组首文档日 − 上组末文档日) − 1`，日/周分组通用；相接为 0，首组为 `None`。这样周分组下也能表达真实空档（例：W01 末文档 1/1、W02 首文档 1/14 → 间隔 12 天），而不是被周边界掩盖成 0。
- **色带聚合沿用现有 `adjacent_topic_runs`**：不新增后端语义。每个 run 在组内渲染为带色块的「主题 · 连续 N 份 · 展开/收起」按钮；展开时该 run 覆盖的**连续条目**加 `.run-active`（左侧连续色轨 + 高亮底），收起消失——即视觉上的连续色带，且可辨、可收起。重叠 run（一个条目属多主题）按数据真实情况给同一行多条色轨。
- **密度条只读跳转**：`density[].group_key` 由后端指向该月第一个分组 key，前端点击 `scrollIntoView` 到 `[data-group-key]`，不改变 URL/数据，符合只读定位。
- **「展开/收起交互保留」的落地**：现状是纯文本 run chip，本 issue 将其升级为可展开色带按钮（保留 chip 的语义与计数，新增高亮交互）。
- **只读红线三重证据**：(1) Node mock 断言 `loadTimeline` 只发 GET；(2) Python 源码/ DOM 断言时间轴区无 `<form>`/`method=`/写动词；(3) 真实 Chrome CDP 抓包：43 篇加载全程 `methods == ["GET"]`、`nonGet == []`。

## 3. 验证

```bash
cd /Users/suyingke/.ao/data/worktrees/graph2note/graph2note-40
uv run pytest tests/test_timeline_visual.py -q   # 11 passed
node tests/timeline_view.mjs                      # timeline_view: all assertions passed ✓
uv run pytest -m "workspace or webapp" -q          # 209 passed
uv run pytest                                      # 694 passed, 0 failed, 0 skipped (106.82s)
```

**视觉/行为证据**（43 篇 dated + 2 篇无日期 seeded 真实库；临时 seeding/server/CDP 仅在本机 `/tmp` 运行，仓库只留证据）：

- `graph2note visual-qa capture http://127.0.0.1:8766/#timeline/day -o .scratch/usable-product-iteration/evidence/timeline-before-1440.png --viewport 1440x1000`（baseline，main）
- `graph2note visual-qa capture http://127.0.0.1:8765/#timeline/day -o .scratch/usable-product-iteration/evidence/timeline-after-1440.png --viewport 1440x1000`（本分支）

| 指标（1440×1000，day 分组） | 改造前 | 改造后 |
|---|---|---|
| 分组 / 条目 | 38 / 45 | 38 / 45 |
| 主干刻度 `.timeline-tick` | 0（无主干） | **38** |
| 缩略图条目 | 0 | **43** |
| 来源图标 / 标签计数 | 0 / 0 | **45 / 43** |
| 主题色带 run band | 0（纯文本 chip） | **3** |
| 空档标记「间隔 N 天」 | 0 | **10**（含 6/8/12/12/15 天…） |
| 月度密度条 | 0 | **6** |
| 初始缩略图请求 / 视口内张数 | 0 / 0 | **5 / 5**（其余 38 张 `data-src` 未请求） |
| 网络方法 | GET | **GET（`nonGet == []`）** |
| 横向溢出 | false | false |

- 交互探针 `timeline-interaction.json`：3 条色带 → 点击首条 `aria-expanded=true`、按钮文案「收起」、高亮 2 行；再点回落 `run-active=0`；密度条点击后目标分组 `top 232 → 61`（跳转生效）。
- 周分组 `timeline-after-week-metrics.json`：14 组 / 14 刻度 / 45 条目 / 10 gap / 6 密度条 / GET-only，语义与日分组一致。

**AC 逐条对照**

| AC | 证据 |
|---|---|
| 主干+刻度形态（截图与改造前对比）；条目含缩略图/标题/来源图标/标签计数 | 前后截图 `timeline-before-1440.png` / `timeline-after-1440.png`；CDP：ticks 0→38、thumbs 0→43、sourceIcons 0→45、tagCounts 0→43、trunk `::before` width 2px + 渐变 |
| 日/周切换语义与现状一致（排序稳定性测试不回归）；空档期间隔指示 | `test_day_and_week_grouping_semantics_not_regressed` 逐项复核 day/week key 顺序、item 顺序、`topic_aggregates`/`adjacent_topic_runs` 与既有 `test_timeline.py` 全绿；`test_gap_markers_and_group_dates` 覆盖日/周 gap（None/12/0/4）；CDP day=38 组、week=14 组，gap 标记 10 个 |
| 同主题相邻聚合视觉可辨、可展开/收起；沿用现有 API 字段 | 数据源为既有 `adjacent_topic_runs`（未新增语义）；`tests/timeline_view.mjs` §6/§8 断言色带 HTML 与展开→高亮→收起状态机；CDP 交互探针实测 3 色带、展开高亮 2 行、收起归零；截图 `timeline-after-1440.png` |
| 点击条目进入编辑器；时间轴无写操作（DOM 断言 + API mock 零非 GET） | `tests/timeline_view.mjs`：`loadTimeline` mock 断言全部 GET、`wireTimeline` 点击 → `go("#doc/doc-1")`；`test_static_timeline_markup_is_trunk_based_and_read_only` 断言时间轴区无 `<form>`/`method=`、源码无 POST/PUT/PATCH/DELETE；CDP 真实抓包 `methods=["GET"]`、`nonGet=[]` |
| 无日期与空库两种状态明确展示 | `test_timeline_api_empty_and_undated_states`（空库 `total=0/groups=[]/density=[]`；legacy 无时间记录 → `has_undated=true`、`undated[0].date=None`）；`index.html` 保留空态文案并新增无日期回退原因文案；CDP `undatedVisible=true`、`undatedCount="2 份"` |
| 43 篇真实库截图可读性；缩略图懒加载断言（视口外不发请求） | 43 篇 seeded 库截图（1440×1000，无横向溢出）；`tests/timeline_view.mjs` 断言 43 张中仅 12 张（视口）赋 `src`、视口外 0 张；CDP 实测初始缩略图请求 5 = 视口内 5，其余 38 张保持 `data-src` |

**证据文件**：`timeline-before-1440.png`、`timeline-after-1440.png`、`timeline-before-metrics.json`、`timeline-after-metrics.json`、`timeline-after-week-metrics.json`、`timeline-interaction.json`。

## 4. 并行领地与共享文件（合并时协调）

- **共享文件改动（最小行数）**：`graph2note/webstatic/index.html`（时间轴区 +3/−1 行）、`graph2note/webstatic/js/state.js`（+1 行 `timelineDensity`）、`graph2note/webstatic/style.css`（**仅 Timeline 段**替换/扩展 + ≤900px 的 timeline 响应式 4 行）。U3/P2 同改这三处但位于其它区块，合并时按区块取用。
- **本 issue 独占**：`graph2note/webstatic/js/timeline_view.js`、`graph2note/webstatic/js/views/timeline.js`、`graph2note/timeline.py`（追加字段与 helper）、`graph2note/webapp.py`（`_resolve_thumbnail_url` + timeline handler 3 行）、新增测试与证据。
- **未触碰**：图谱视图（U4）、Library 卡片（`library_cards.js` / `views/library.js`）、编辑器（`views/document.js`）、问答视图（`views/pdf.js` / `ask`）、`repair.js`、`assets.js`；未动 BOARD.md 与 issues/*.md。
- **缩略图与 U2 的协调**：U2（`dev/u2-library-cards`）尚未合并。U2 合并后建议统一为 `/api/documents/{id}/thumbnail`（服务端缩放 + 缓存）：本 issue 只需把 `timeline.py::_thumbnail_url` 的首选端点从 `/preprocessed` 换为 `/thumbnail`（前端懒加载形态一致）。若 U2 先合，reviewer 可直接改这一行。

## 5. 未尽事项 / 已知边界

- 缩略图走既有 `preprocessed` 端点（原图尺寸），依赖 CSS `object-fit: cover` 缩放；43 篇下体积可控但非服务端缩略图——见 §4 的 U2 统一方案。
- 主干刻度圆点的 `top` 为固定 24px 对齐卡片标题，长标题多行时圆点仍居标题首行位置（不随卡片高度居中），实测 1440 宽下可读性良好。
- 色带展开为「高亮连续条目」而非重排/折叠行（重叠 run 无法嵌套 DOM）；语义与可辨性满足 AC，若后续要真正的分组折叠可另开 issue。
- 密度条按月，未做 hover tooltip 之外的筛选；点击为平滑滚动跳转，不改变 URL。
- 视觉证据依赖本机 Chrome/CDP；`tests/test_timeline_visual.py` 的 Node 合同测试在无 `node` 环境会 skip（其余断言仍全跑）。
- 未 push（按协议推送时机归维护者），未合并 `main`，未自审。

## Suggested skills

- `impeccable`：若后续要进一步提升时间轴信息密度/节奏感（刻度对齐、缩略图尺寸分档、暗色主题下色带对比度）。
- `diagnose`：若出现「时间轴空白 / 条目点不进编辑器」，沿 `loadTimeline → timelineGroupsHtml → wireTimeline → go(route)` 链定位；若缩略图整列 404，检查 `_resolve_thumbnail_url` 的 preprocessed/original 回退。
