# D3 — 渲染与前端呈现（handoff）

Status: **ready-for-review**（返工轮 1，处置 F1–F6）
分支：`dev/D3-diagram-render`；基线：本地 `main`（`916846d`）。**本轮未 rebase**——等调度「D1/D2 已合并」通知后再 rebase 到新 main、删 `_ENGINE_GROUPS_SUPPORT`、用真 D2 engine 复跑（见 §3）。
提交：10 个（返工 2 个：`6595ef1` `a733266`）；未 push origin，未自审，未合并。

> 上一轮 verdict `reject` 的唯一阻断项是 **F1**（分组语义在 engine→renderer 边界被静默丢弃，产品链上分组是 no-op）。返工轮按 `review-spw-D3-verdict.md` §0 + F1–F6 逐项处置，见 §4。

## 1. 改动清单（vs `916846d`，15 文件）

| 提交 | 内容 |
|---|---|
| `677d55f` | `graph2note/diagrams/render_semantics.py`（新）：SPEC §1 dict/IR 归一化器 |
| `abdbf8d` | `graphviz_renderer.py`：`cluster_*` / `rank=same`(layer) / 组标题 / note 小字 / dashed |
| `532827e` | `matplotlib_renderer.py`：分组背景框+组标题 / note 小字 / dashed / `build_figure()` |
| `b9e8aef` | `tests/test_diagram_render_groups.py` + taxonomy |
| `2f724e5` | `degrade.py` + `attachments.py` + `render.py`：语义流经导出链 |
| `27b1ed9` | `assets.js` / `views/document.js` / `style.css`：结构图 figure + 缩放 |
| `3923903` | 词感知换行（ASCII 不截断） |
| `6595ef1` | **返工 F1/F2/F3/F4/F6**：语义层改为 D2 layout 纯适配层；边不再去重；共享 accessor；degrade docstring 更正 |
| `a733266` | **返工 F1**：两个 renderer 消费 `layout=`；新增产品链端到端测试 |
| `12ddc82` | 上一轮 handoff（docs） |

领地：新增 `graph2note/diagrams/render_semantics.py`（渲染层新文件）与 `tests/` 新文件；`ir.py`/`diagram.py`/`infer.py`/`_layout.py`/`_canonical.py`/`engine.py`/`index.html`/`router.js`/`api.js`/`state.js`/`digest.py`/`webapp.py`/`store.py` **未改动**。

## 2. 实现要点（对齐 SPEC §1「渲染」条）

1. **graphviz（首选）**：`groups` → `subgraph cluster_<id>`（`kind=layer` 追加 `rank=same`），组标题 + 每组固定调色板；`node.note` → HTML-like label 第二行小一号（14 < 节点 20）；`edge.style=dashed` → `style=dashed`（solid 不写 style）。
2. **matplotlib（回退）**：分组背景框（layer 通栏 / lane 通高 / cluster 包络）+ 组标题；note 10 < 节点 13；`GROUP_FONTSIZE=13 ≥ NOTE_FONTSIZE=10`；dashed 线+箭头。
3. **D2 layout 消费（F1/F3，本轮核心）**：
   - 两个 `render(...)` / `build_digraph(...)` / `build_figure(...)` 增加 `layout: dict | None = None`，符合 D2 handoff「D3 增加 `layout=` 形参后引擎侧零改动自动接线」的契约；
   - `render_semantics.normalize(nodes, edges, groups, layout)`：**有 layout 时是纯适配层**——组序/kind/members/bbox 与 `positions` 逐字取自 `layout['groups']`/`layout['positions']`（`groups_from_layout`/`positions_from_layout`），不再自行排序、不再降级 kind；无 layout 时保持旧的 node-reading-order 分组；
   - graphviz 用 layout 的 groups 元数据建 cluster（dot 自算几何）；matplotlib 用 `positions` 放置节点、用 `groups[].bbox` 画背景框（按 orientation 做轴映射），使回退引擎与几何拥有者一致。
4. **可读性**：层级块 CJK 感知换行（ASCII 词不截断，`wrap_display_label`）；前端结构图 `<figure class="g2n-diagram">` + 图注 + 点击/Enter/Space 打开大图查看器；`style.css` 只追加。
5. **导出链**：`DiagramSemantics.groups`；`FileAssetWriter.write_diagram` 归一化后把 `groups/notes/dashed_edges` 记入 `results[i]["semantics"]`；`render_markdown` 在块带语义时追加确定性、不可见 sidecar 注释 `<!-- diagram-semantics: {…} -->`（`<`/`>` 转义为 `\u003c`/`\u003e`）。无语义块输出逐字节不变。

## 3. 与 D1/D2 的接线状态

- 本分支仍基于 `main 916846d`（**未 rebase**，未收到合并通知）；按 SPEC §1 dict 形状开发，不 import D1/D2 代码。
- `attachments.py` 保留 `_ENGINE_GROUPS_SUPPORT` 签名探测：预 D2 不转发 groups 也不报错；D2 合并后自动转发（`engine` 自行算 layout 并转发给声明了 `layout=` 的 renderer）。**收到通知后**：rebase → 删探测（改无条件 `groups=`）→ 用真 D2 engine 复跑全量 + 产品链锚点。
- **已用一次性集成树验证真实 D1+D2+D3**（`/tmp/d3-int2`，本地 clone，未触碰仓库分支）：D1 `dddc2c7` + D2 `148c846` + 本分支 `a733266`，taxonomy 冲突按并集解决；集成树全量 pytest **exit 0**，`/tmp/d3-int-check.py` 结果见 §4-F1。

## 4. 返工处置（F1–F6）

### F1（阻断，已修）— 产品链丢分组
**根因**：D2 的 `engine._renderer_layout_kwargs` 只向声明了 `layout` 形参的 renderer 转发几何；D3 的 `render()` 只加了 `groups=`，没有 `layout=` → `kwargs={}` → 扁平渲染；且 `attachments` 即使在无 D2 时也不转发 groups（单分支 no-op）。测试盲区：导出链测试用了假 engine 且从未断言真实 `FileAssetWriter→engine→renderer` 产物。

**处置**：
1. 两个 renderer 增加 `layout=` 并按其消费（§2.3）；
2. 保留 `groups=` 供 dict 直调/测试；`_ENGINE_GROUPS_SUPPORT` 仍在（D2 未并入本分支）；
3. 新增 `tests/test_diagram_engine_integration.py`（11 项）：走**真实产品链** `render_markdown → FileAssetWriter → engine → renderer`，断言
   - grouped PNG ≠ flat PNG（两引擎）——正是 reviewer 的失败探针；
   - spy `build_digraph`/`build_figure`，断言引擎确实把 `layout` 传给了 renderer，且 `layout["groups"]`/`positions` 非空；
   - group/note/dashed 都到达绘制层（DOT 含 3 个 `cluster_` + `style=dashed` + `POINT-SIZE`；matplotlib `drawn==[g1,g2,g3]`）；
   - `results["semantics"]` 记录 group/note/dashed。
   D2 未合并时自动安装**严格实现 D2 契约**的 stub engine（同 layout dict 形状 + 同签名转发门），因此缺 `layout=` 会被测试当场抓住；D2 合并后改用真 engine。

**证据（真实 D1+D2+D3 集成树 `/tmp/d3-int2`，reviewer 的 `/tmp/d3-int-check.py`）**：

| | 上一轮（reject 证据） | 返工后 |
|---|---|---|
| `graphviz.render` 接受 `layout` | False | **True** |
| `[graphviz] grouped==flat` | True | **False**（`7afad391…` vs `500a7ba9…`） |
| `[matplotlib] grouped==flat` | True | **False**（`6e310b72…` vs `0fb23547…`） |
| `engine groups= → layout present` | True | True |
| `engine grouped vs flat identical` | True | **False** |

产品链锚点产物（集成树，`FileAssetWriter→engine→renderer`）：`/tmp/spw-D3/anchors-product/*.{graphviz,matplotlib}.png`（6 张，均 re-render 字节一致；increment 两簇 `bbox` 左右相接不重叠）。

### F2（medium，已修）— 重复边导致与基线不一致
`normalize_edges` 曾对 `(from,to,label,style)` 完全相同的边去重；`_canonical.canonical_edges` 不去重、旧渲染器会画两次。**处置**：删除去重，与 `_canonical` 对齐。旧 handoff 的「无 groups 逐字节一致」表述同时更正为：**在无 groups/note/dashed 的输入上逐字节一致（含完全重复边）**。

**证据（reviewer 的 `/tmp/d3-dup-probe.py`）**：

| | 基线 916846d | 返工后 |
|---|---|---|
| graphviz dup vs uniq | `81476346…` vs `cfc48c58…` | **相同值** |
| matplotlib dup vs uniq | `e55c288d…` vs `f4e04d78…` | **相同值** |

另跑 reviewer 的 no-dup / dup 两套回归探针对拍基线树：`diff` **IDENTICAL**（`/tmp/spw-D3/d3-new*.json`）。

### F3（low，设计，已修）— 与 D2 双源分歧
**处置**：有 `layout` 时 `render_semantics` 为纯适配层，组序/kind/members/bbox/positions 全以 `layout` 为准（未知 kind 原样保留，不再降级）；无 layout 时才走自身排序。决策：**layout 是唯一几何真源；render_semantics 只做 dict/IR 形状适配与绘制所需最少派生**（换行、调色板、membership first-wins，后者与 D2 `_first_owner` 同规则）。

### F4（low，已修）
`degrade_required` 的 docstring 不再自称 engine 的「single source of truth」：明确 engine 目前内联 `if nodes or edges`，该 helper 是**兼容性断言锚点**、待 engine 拥有者接线。行为不变。

### F5（low，评审已接受，无改动）
`attachments.py` 除 `DiagramSemantics` 外改了 `FileAssetWriter.write_diagram`（转发 + `results["semantics"]` 审计）：brief 任务 4 必需，改动最小，已在上一版 handoff §6.6 披露。

### F6（nit，已修）
三份 dict-or-object 取值助手合并为一份：`attachments.semantics_field`，`render.py` 与 `diagrams/render_semantics.py` 共用。放在 `attachments` 是因为 `render.py` 必须保持无 numpy 依赖（`diagrams/__init__` 会拉 `degrade→numpy`），不能从 `render_semantics` 反向导入。

## 5. 测试证据

环境：本 worktree `.venv` 仅基础依赖，故用主仓 venv + `PYTHONPATH`：
`PYTHONPATH=$PWD /Users/suyingke/Programs/OHO/graph2note/.venv/bin/python -m pytest …`

- **本分支全量** `pytest -q -p no:randomly -W ignore`：**exit 0**（无 failed/error；本环境末行统计被某测试 stdout 捕获吞掉，以退出码为准）。
- **集成树 `/tmp/d3-int2`（真实 D1+D2+D3）全量**：**exit 0**。
- 新增/相关测试：`test_diagram_engine_integration.py` **11**、`test_diagram_render_groups.py` **18**、`test_diagram_semantics_export.py` **12**、`test_diagram_presentation.py` **4**；集成树 D3+D1+D2 相关子集 **145 passed**。
- Node：`node tests/diagram_presentation.cjs` ✓、`node tests/assets_rewrite.cjs` ✓。
- 回归锁定：
  - graphviz 无 groups → DOT 源码 == 内嵌旧实现；
  - matplotlib 无 groups/notes → PNG sha == 基线 `e5f561dd…`（matplotlib 3.11.1；版本不符 skip）；
  - 无语义 diagram 的 Markdown 逐字节不变；
  - 重复边输入与基线树 `diff` IDENTICAL（F2）。

## 6. 诚实限制

1. **本轮未 rebase**：按调度指示等「D1/D2 已合并」通知；集成验证在 `/tmp/d3-int2` 一次性 clone 完成，**不代表本分支已合并 D1/D2**，也尚未删除 `_ENGINE_GROUPS_SUPPORT`。
2. F1 的 stub-engine 端到端测试在本分支上执行；真 engine 端到端结论来自 `/tmp/d3-int2`（同源 commit，taxonomy 冲突手工并集）。rebase 后须在真实分支复跑。
3. `/tmp/d3-int2` 集成树的 taxonomy 冲突解法为并集（D1 2 行 + D2 1 行 + D3 4 行），与 reviewer 的处理一致；合并入 main 时需同样处理。
4. AO 桌面浏览器面板无网络：index.html 的 marked/KaTeX 来自 CDN，面板内预览显示「marked 未能加载」；上一轮已用 Playwright + CDN shim 走真实 `document.js` 路径验证（本轮前端未改动）。
5. `PLAYWRIGHT_MODULE` 需指向 `…/node_modules/playwright/index.js`（Node 25 拒绝目录 ESM import）；`/tmp/spw-D3/pw-shim.mjs` 供 `scripts/frontend_audit.mjs` 使用。
6. matplotlib CJK 组标题 bold 会打印 `findfont: Failed to find font weight bold`（回退 400），仅日志噪音。
7. matplotlib golden sha 与 matplotlib 版本绑定（PNG 内嵌版本串）。
8. `attachments.py` 范围偏差见 F5。
9. 锚点仍是**手写 SPEC §1 fixture**（非真实 VLM 产物）；真实三图的视觉复验归 T-audit/T-vision，且必须用**产品链产物**（`/tmp/spw-D3/anchors-product/` 即该形态）。

## 7. 复验建议（fresh reviewer）

1. `PYTHONPATH=$PWD <full-venv>/bin/python -m pytest tests/test_diagram_engine_integration.py tests/test_diagram_render_groups.py tests/test_diagram_semantics_export.py tests/test_diagram_presentation.py -q`
2. `node tests/diagram_presentation.cjs`
3. 复跑 reviewer 探针：本分支上 `tests/test_diagram_engine_integration.py::test_product_chain_grouped_render_differs_from_flat[graphviz|matplotlib]` 必过；集成树上跑 `/tmp/d3-int-check.py` 应看到两条 `SAME=False`。
4. 关注点：F1 的 `layout=` 接线是否会在 rebase 后回退（删 `_ENGINE_GROUPS_SUPPORT` 时）；F2 去重删除是否与 `_canonical` 长期一致；F3 的 layout 单源决策是否被接受。
