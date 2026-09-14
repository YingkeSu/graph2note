# D3 — 渲染与前端呈现（handoff）

Status: **ready-for-review**（终段收尾完成：已 rebase 到 D1+D2 合并后的 main）
分支：`dev/D3-diagram-render`，**代码 SHA `f75db65`**（其后的 `docs` 提交仅更新本 handoff）；基线：`main d745c52`（D1 `b4d09d1` + D2 `4002288` + BOARD/docs）；rebase 时 `tests/taxonomy.py` 冲突按并集解决。
提交：12 个（D3 全部）；未 push origin，未自审，未合并。

## 0. 终段收尾结果（本轮）

| 项 | 结果 |
|---|---|
| rebase 到 `main d745c52` | ✅（`GIT_EDITOR=true git rebase main`；`tests/taxonomy.py` 冲突按 D1 2 行 + D2 1 行 + D3 4 行并集解决） |
| 删 `_ENGINE_GROUPS_SUPPORT` 临时探测 | ✅ 改为无条件 `groups=list(semantics.groups) or None`；`inspect` 导入一并删除 |
| 全量 `python -m pytest` | ✅ **exit 0**，收集 **1027** 项（基线 980 + D3 新增 45 + 归并差异），0 failed/error |
| 两个 `.cjs` | ✅ `node tests/diagram_presentation.cjs`、`node tests/assets_rewrite.cjs` |
| 产品链锚点（真 D2 engine） | ✅ `/tmp/spw-D3/anchors-product/` 6 张（graphviz+matplotlib × 3 锚点），re-render 字节一致 |
| 02-increment 两簇不重叠 | ✅ `g_atomic.x1=0.5 <= g_incremental.x0=0.5`（产品链 layout bbox 断言） |
| reviewer F1 探针（本分支，真 engine） | ✅ `[graphviz] grouped_sha=7afad391… flat_sha=500a7ba9… SAME=False`；`[matplotlib] grouped_sha=6e310b72… flat_sha=0fb23547… SAME=False` |
| reviewer F2 重复边探针 | ✅ 与基线 916846d 完全一致（`81476346…`/`cfc48c58…`、`e55c288d…`/`f4e04d78…`） |

结构判据（T-vision §4 的渲染可证子集，产品链 spy 采集，`/tmp/spw-D3/anchors-product-report.json`）：
`A1_group_containers_with_titles=true`、`A2_font_grading=true`、`B3_increment_two_clusters=true`、`01_three_layer_bands=true`（3 cluster + 3 `rank=same`）、`02_side_notes_dashed=true`（2 条 dashed）。

## 1. 改动清单（vs `main d745c52`，16 文件 +2220/−58）

| 提交 | 内容 |
|---|---|
| `5784559` | `graph2note/diagrams/render_semantics.py`（新）：SPEC §1 dict/IR 归一化器 |
| `ebd5846` | `graphviz_renderer.py`：`cluster_*` / `rank=same`(layer) / 组标题 / note 小字 / dashed |
| `9b6806e` | `matplotlib_renderer.py`：分组背景框+组标题 / note 小字 / dashed / `build_figure()` |
| `d5bce14` | `tests/test_diagram_render_groups.py` + taxonomy（D1/D2 条目并集保留） |
| `9a2c2d0` | `degrade.py` + `attachments.py` + `render.py`：语义流经导出链 |
| `95ae7df` | `assets.js` / `views/document.js` / `style.css`：结构图 figure + 缩放 |
| `1808e72` | 词感知换行（ASCII 不截断） |
| `0edcc33` | 语义层改为 D2 layout 纯适配层（F1/F2/F3/F4/F6） |
| `6ebca0c` | 两个 renderer 消费 `layout=`；产品链端到端测试（F1） |
| `a3fa542` | 返工轮 handoff（docs） |
| `f75db65` | **终段**：删 `_ENGINE_GROUPS_SUPPORT`，无条件 `groups=`；测试改用真 D1+D2 engine |

领地：新增 `graph2note/diagrams/render_semantics.py` 与 `tests/` 新文件；`ir.py`/`diagram.py`/`infer.py`/`_layout.py`/`_canonical.py`/`engine.py`/`index.html`/`router.js`/`api.js`/`state.js`/`digest.py`/`webapp.py`/`store.py` **未改动**（`git diff --name-only main..HEAD` 已核对；`tests/taxonomy.py` 仅并集追加）。

## 2. 实现要点（对齐 SPEC §1「渲染」条）

1. **graphviz（首选）**：`groups` → `subgraph cluster_<id>`（`kind=layer` 追加 `rank=same`），组标题 + 每组固定调色板；`node.note` → HTML-like label 第二行小一号（14 < 节点 20）；`edge.style=dashed` → `style=dashed`（solid 不写 style）。
2. **matplotlib（回退）**：分组背景框（layer 通栏 / lane 通高 / cluster 包络）+ 组标题；note 10 < 节点 13；`GROUP_FONTSIZE=13 ≥ NOTE_FONTSIZE=10`；dashed 线+箭头。
3. **D2 layout 消费（F1/F3）**：两个 `render()`/`build_digraph()`/`build_figure()` 声明 `layout: dict | None`，符合 D2 契约；`render_semantics.normalize(..., layout)` 为纯适配层——组序/kind/members/bbox 与 positions 逐字取自 `layout['groups']`/`layout['positions']`（未知 kind 原样保留）。graphviz 用 layout 组元数据建 cluster（dot 自算几何）；matplotlib 用 positions 放节点、`groups[].bbox` 画框（按 orientation 轴映射）。
4. **可读性**：层级块 CJK 感知换行（ASCII 词不截断）；前端结构图 `<figure class="g2n-diagram">` + 图注 + 点击/Enter/Space 打开大图查看器；`style.css` 只追加。
5. **导出链**：`DiagramSemantics.groups`；`FileAssetWriter.write_diagram` 归一化后把 `groups/notes/dashed_edges` 记入 `results[i]["semantics"]`；`render_markdown` 在块带语义时追加确定性、不可见 sidecar `<!-- diagram-semantics: {…} -->`（`<`/`>` 转义）。无语义块输出逐字节不变。

## 3. 接线状态（合并后）

- D1 的 `ir.Node.note` / `ir.Edge.style` / `DiagramBlock.groups` 已被 `render.py`（`getattr`）与 `render_semantics`（dict-or-object）无缝消费；
- D2 的 `engine.prepare_diagram_layout` 计算几何，`engine._renderer_layout_kwargs` 检测到 D3 renderer 的 `layout=` 后自动转发；
- `attachments.FileAssetWriter` 现已**无条件**传 `groups=`（空 groups → `None`），无临时探测、无 TODO 残留。

## 4. 返工处置（F1–F6，均已在合并后复验）

### F1（阻断，已修）
根因：D2 只向声明 `layout=` 的 renderer 转发几何，D3 当时只加 `groups=` → 产品链扁平化。处置：renderer 增加并消费 `layout=`；新增 `tests/test_diagram_engine_integration.py`（12 项）走真实产品链 `render_markdown → FileAssetWriter → engine → renderer`，断言 grouped≠flat（两引擎）、spy 证明 `layout` 到达 renderer、group/note/dashed 到达绘制层、`results["semantics"]` 完整。
**合并后实测**（本分支，真 D1+D2 engine）：`graphviz.render accepts layout: True`；两引擎 `SAME=False`（见 §0 表）。
**非空洞性**：临时删 graphviz 的 `layout=` → e2e 立刻 2 项失败；恢复后全绿。

### F2（medium，已修）
删除 `normalize_edges` 去重，与 `_canonical` 对齐；重复边探针与基线 916846d 逐字节一致。原「无 groups 逐字节一致」表述更正为：**在无 groups/note/dashed 的输入上逐字节一致（含完全重复边）**。

### F3（low，已修）
有 layout 时 `render_semantics` 为纯适配层，组序/kind/members/bbox/positions 全以 layout 为准；决策：**layout 是唯一几何真源**。

### F4（low，已修）
`degrade_required` docstring 改为兼容性断言锚点（engine 内联判断，非本 worker 领地）；行为不变。

### F5（low，评审已接受）
`attachments.py` 除 `DiagramSemantics` 外改了 `FileAssetWriter.write_diagram`（任务 4 必需，改动最小，已披露）。

### F6（nit，已修）
三份 dict-or-object 助手合并为 `attachments.semantics_field`，`render.py` 与 `render_semantics.py` 共用（放 attachments 以免 `render.py` 引入 numpy）。

## 5. 测试证据

环境：worktree `.venv` 仅基础依赖，用主仓 venv + `PYTHONPATH`：
`PYTHONPATH=$PWD /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest …`

- **全量**：**exit 0**，收集 **1027**，0 failed/error（本环境末行 "N passed" 被某测试 stdout 捕获吞掉，以退出码 + collect-only 计数为准）。
- 新增/相关：`test_diagram_engine_integration.py` **12**、`test_diagram_render_groups.py` **18**、`test_diagram_semantics_export.py` **13**、`test_diagram_presentation.py` **4**；D1+D2+D3 相关子集 145 passed（rebase 前集成树）→ rebase 后同源子集全绿。
- Node：`node tests/diagram_presentation.cjs` ✓、`node tests/assets_rewrite.cjs` ✓。
- 回归锁定：graphviz 无 groups → DOT 源码 == 内嵌旧实现；matplotlib 无 groups/notes → PNG sha == 基线 `e5f561dd…`（matplotlib 3.11.1，版本不符 skip）；无语义 diagram 的 Markdown 逐字节不变；重复边输入与基线树 `diff` IDENTICAL。
- 产品链锚点：`/tmp/spw-D3/anchors-product/{01-requirements-arch,02-digitize-pipeline,02-digitize-pipeline-increment}.{graphviz,matplotlib}/assets/doc-diagram-0.png`（6 张，均 re-render 字节一致；结构判据见 §0）。
- reviewer 探针：`/tmp/spw-D3/probe-final.py`（`/tmp/d3-int-check.py` 去掉已删除的 shim 行）、`/tmp/d3-dup-probe.py`；结果见 §0。

## 6. 诚实限制

1. 锚点是**手写 SPEC §1 fixture**（非真实 VLM 产物）；真实三图的视觉复验归 T-audit/T-vision，须用**产品链产物**（`/tmp/spw-D3/anchors-product/` 即该形态）。
2. 真实图片的 C1（720px 可辨）仍属视觉判据：D3 的换行只压缩文字宽度，不减少同 rank 节点数；`rank=same` 层带宽度由 D2 布局与 D1 抽取决定。
3. AO 桌面浏览器面板无网络（marked/KaTeX 来自 CDN），面板内预览显示「marked 未能加载」；前端验证用 Playwright + CDN shim 走真实 `document.js`（返工轮起前端未再改动）。
4. `PLAYWRIGHT_MODULE` 需指向 `…/node_modules/playwright/index.js`（Node 25 拒绝目录 ESM import）；`/tmp/spw-D3/pw-shim.mjs` 供 `scripts/frontend_audit.mjs`。
5. matplotlib CJK 组标题 bold 打印 `findfont: Failed to find font weight bold`（回退 400），仅日志噪音。
6. matplotlib golden sha 与 matplotlib 版本绑定（PNG 内嵌版本串）。
7. `attachments.py` 范围偏差见 F5。

## 7. 复验建议（fresh reviewer）

1. `git log --oneline main..dev/D3-diagram-render`（应见 12 提交，tip `f75db65`）；`git diff --name-only main..HEAD` 核对领地。
2. `PYTHONPATH=$PWD <full-venv>/bin/python -m pytest tests/test_diagram_engine_integration.py tests/test_diagram_render_groups.py tests/test_diagram_semantics_export.py tests/test_diagram_presentation.py -q`（应全绿）。
3. `node tests/diagram_presentation.cjs`；`node tests/assets_rewrite.cjs`。
4. 目验产品链产物：`/tmp/spw-D3/anchors-product/`（A1/A2/B3）；结构判据 `/tmp/spw-D3/anchors-product-report.json`。
5. 关注点：F1 的 `layout=` 接线（删 shim 后仍成立，已实测）、F2 去重与 `_canonical` 一致、F3 layout 单源决策。
