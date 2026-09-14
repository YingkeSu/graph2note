# D2 — 分组感知布局引擎（handoff）

Status: **ready-for-review**
分支:`dev/D2-diagram-layout`(已 rebase 到 main `916846d`)
契约:[SPEC.md §1](../SPEC.md) 布局条（**已按 T-audit 阶段1 证据更正的锚点**）
提交:`5b65632` `3d9755a` `394168b` `6331db8` `e3b52a0` `3a362f2` `c2a18fe` `54a471e` `bae1baf` `37fe378` `148c846`（rebase 后重放为 `942e9a1` `fc8109e` `b23447f` `11487a2` `221d228` `7074765` `6107de7` `b9800ad` `9d896a9` `2279c4a` `6531daa`）+ `d32672a`（D1 接线测试）
最终实现 SHA:`d32672a`；handoff 提交为其后 docs commit。

## 改动清单（严格限于领地）

| 文件 | 改动 |
|---|---|
| `graph2note/diagrams/_canonical.py` | 追加 `canonical_groups()` + `group_as_dict()`；`canonical_nodes`/`canonical_edges` **零改动** |
| `graph2note/diagrams/_layout.py` | `LayerLayout` **零改动**；追加 `grouped_layout()` 及内部辅助（`_reduce_crossings` 等） |
| `graph2note/diagrams/engine.py` | 追加 `prepare_diagram_layout()`；`render_structured`/`render_to_png` 增加可选 `groups=`；`RenderOutcome` 追加 `layout` 字段（默认 `None`） |
| `tests/test_diagram_group_layout.py` | 新增 60 个离线测试 |
| `tests/golden/diagram-layout-{layer,lane,cluster,increment}.json` | 场景 golden（fixture + expected 全量几何），已对齐更正后锚点 |
| `tests/taxonomy.py` | **领地外唯一改动**：`FILE_TO_MODULE` 追加一行登记新测试文件（见「边界说明」） |

## 布局规则（分组感知分层）

坐标系（对外契约，JSON 可序列化 dict）：`x` 左→右，`y` 上→下，归一化到 `[0,1]×[0,1]`。

1. **基准层**:先用**原封不动的** `LayerLayout`（Kahn 最长路径 + 层内 barycenter）算出每个节点的 base depth 与 **base 层内序位 `base_order`**（= `LayerLayout.positions()[n][1]`，即 base 布局的 y / 层内序位，**不是水平 x**；评审 F1）。无 groups 时**直接返回 `LayerLayout.layers()` 的行序**（回归锁定）。
2. **layer（水平层带，跨图整行）**:每个非空 layer 组取成员 base depth 的**中位数**作为锚，按 `(锚, 组 id)` 排序决定自上而下的带序；**该组成员被强制到同一行**。非组节点按自身 depth 插入到带之间（depth 恰好等于某带锚时并入该带行）。→ 保证「同 layer 成员同一水平带」。
3. **lane（垂直泳道）**:lane 组按成员 `base_order` 均值排序得到列索引；**该组优先占一列**，跨行形成垂直泳道。**注意这是有条件的**（评审 F3）：只有「同一 base 行内该 lane 至多一个成员」时成员才严格同列；同一行第二个成员会**溢出到空闲列**（SPEC 原文是「**优先**同列」，故实现为 best-effort）。极端情况下两条并行 lane 的溢出成员会让列相互穿插。
4. **cluster（局部簇）**:簇成员在行内排序时以 `cluster_key` 为主键（稳定排序保留 barycenter 次序），被分配到**连续列**；输出其成员包络框。
5. **交叉减少**:对所有行做固定 2 轮下→上 barycenter 扫描（确定性有限步，不用随机/迭代到收敛），邻居均值作键、当前下标作稳定 tie-break。**确定性优先于最优性**。
6. **包络框**:每组输出 `bbox`（成员位置外扩半格、裁剪到画布内）、`row_span`、`col_span`；空组 `bbox=None`。

输出 dict 形状（完整字段见 `_layout.py` 模块 docstring）：
`positions{id:{x,y}}` / `rows[[id]]` / `columns[[id]]` / `groups[{id,label,kind,members,bbox,row_span,col_span}]` / `node_groups{id:[gid]}` / `dangling[member]` / `nrows` / `ncols`。

**`rows` 内序注意（评审 F2）**：`rows[r]` 是 **barycenter 扫描序**，**不保证左→右**，可能与 `columns`/`positions` 的 x 顺序相反（golden 现状即如此，如 increment 的 `rows[0]==["R1","L1"]` 而 L1 在左）。D3 取 x 请用 `columns`/`positions`，不要按 `rows` 内序画。

## 确定性决策（任务项 2）

- **不实现 `order_hint`，也不读取任何 `order` 字段**：带序完全由「base depth + 组标签」派生。数据层保留该字段（extra key 原样透传），布局忽略它。测试 `test_band_order_ignores_vlm_order_hint` 用相矛盾的 `order` 值断言布局逐字节不变。
- 规范化：`canonical_groups` 按 `(id, kind, label, members)` 全序排序，成员去重+排序，悬空成员剔除（与 `canonical_edges` 行为对齐）。节点 id 统一排序。
- `grouped_layout` 对输入顺序不敏感（反转 nodes/edges/groups/成员后输出完全一致，已测，FR-020 延续）。

## 与 D3 的接口（重点）

D3 **不需要 import D2 的 pydantic 类型**，走纯 dict：

```python
from graph2note.diagrams import engine

layout = engine.prepare_diagram_layout(nodes, edges, groups)   # nodes/edges: ir.Node/ir.Edge
# layout 形状见上；D3 消费：
#   graphviz: 用 groups[].members + groups[].kind 建 cluster_* 子图（dot 自算几何）
#   matplotlib: 用 groups[].bbox(+label) 画背景框，用 positions 放置（或让 renderer 自己算）
```

- **几何计算在 D2，绘制在 D3**：`positions`/`bbox`/`row_span`/`col_span` 已备好。
- `engine.render_structured` / `render_to_png` 新增可选关键字 `groups=`，并把算好的 `layout` **只在 renderer 签名声明了 `layout` 关键字时**转发（`inspect.signature` 探测，见 `_renderer_layout_kwargs`）。因此：
  - D3 在 `graphviz_renderer.render(...)` / `matplotlib_renderer.render(...)` 增加 `layout: dict | None = None` 形参后**引擎侧零改动自动接线**；
  - 未加之前，传 `groups=` 也能算几何并挂在 `RenderOutcome.layout`，只是 renderer 暂不消费。
- `RenderOutcome` 新增 `layout: dict | None = None`（追加字段，旧调用方不受影响）。
- 当前 `render.py` / `attachments.py` 仍按旧签名调用（`groups` 缺省 `None`）→ **无 groups 路径与改动前逐字节一致**（`tests/test_diagrams.py` 既有 PNG golden/byte-determinism 全绿）。
- `__init__.py` 未改（非本 worker 领地）：D3 用 `from graph2note.diagrams import engine` 即可。若 D3/评审希望包顶层导出 `prepare_diagram_layout`，请由拥有者追加一行。
- **02-increment 特别提示**：D3 画 `groups` 时应把每个 flow 簇做成独立子图/背景框，避免两侧压成一张散点图；D2 的几何保证左右两簇 `bbox` 不重叠、列集合不相交（见 golden `diagram-layout-increment.json`）。
- **lane 背景框宽度不能假设为单列（评审 F3）**：lane 组在「同行多成员溢出/并行 lane」时 `col_span` 可能 >1（极端下相互穿插）；请按 `groups[].col_span`/`bbox` 实际范围绘制，勿写死单列宽。

## rebase 状态（D1 合并后，已完成）

- **已 rebase 到 main `cb989c7`（D1 已并入：merge `b4d09d1` + board `cb989c7`）**。11 个 D2 提交全部重放，`git merge-base main HEAD == cb989c7`。
- rebase 唯一冲突：`tests/taxonomy.py`（D1 追加了 `test_diagram_groups_ir`/`test_diagram_groups_pipeline` 两行，D2 追加 `test_diagram_group_layout`）→ **按并集解决**，三行均保留，未删 D1 登记。
- **D1 接线（复核零逻辑改动）**：D1 的 `DiagramGroup` 是 pydantic 模型，`model_dump()` 正是 SPEC §1 dict 形状；`_canonical.group_as_dict` 已同时接受 dict 与 pydantic 对象，因此 `canonical_groups`/`prepare_diagram_layout` **无需改任何逻辑**即可直接吃 `DiagramBlock.groups`。新增测试证明：
  - `test_d1_diagram_block_groups_flow_into_the_layout`：真实 `DiagramBlock(groups=[DiagramGroup(...)])` 经 `prepare_diagram_layout(block.nodes, block.edges, block.groups)` 得到预期带布局；
  - `test_d1_serialized_groups_dict_matches_pydantic_groups`：`block.groups` 与 `[g.model_dump() for g in block.groups]` 两路径逐字段一致（dict 形状 == pydantic 形状）。
- D3 接线（render.py / attachments.py 把 `block.groups` 传给 `render_to_png(groups=...)`）仍属 D3 领地，D3 rebase 后自行接。

## 测试证据（离线，无网络/无 LLM）

- `python -m pytest` → **980 passed**（本分支，2026-09-14；D1 合并后 main 基线 920 + D2 新增 60，无新增失败）。
- `python -m pytest tests/test_diagram_group_layout.py --collect-only` → **60 tests**。
- 覆盖：
  - 场景 golden（`tests/golden/diagram-layout-*.json`，fixture+expected 全量几何锁定）：`layer`=01 三层带、`cluster`=02 主线+「调研：」/「设计：」旁注簇、`increment`=02-increment 左右两独立流程、`lane`=泳道 kind 覆盖；
  - 锚点专项断言：`test_01_fixture_covers_the_three_bands_anchor`、`test_02_fixture_uses_the_research_and_design_annotations`、`test_increment_fixture_keeps_two_flows_distinguishable`；
  - 确定性：同输入两次 `json.dumps` 逐字节一致；反转输入顺序输出不变；`order` 字段被忽略；
  - 不变式：组 `bbox` 包含全部成员、layer 同 y、lane 同 x、cluster 行内相邻；
  - 无 groups 回归：**5 张图**（单点/链/菱形/环/多连通）行序 == `LayerLayout.layers()`；`None`/`[]`/`()` 三种空值一致；
  - 边界：0 节点、1 节点、空组、单节点组、悬空成员(report+drop)、未知 kind(降级为 cluster 且保留原 kind)、同节点跨 layer+lane；
  - 规范化：排序/去重/默认 kind/透传 extra key/接受 `model_dump()` 对象与属性对象/既有 `canonical_nodes|edges` 行为不变；
  - 引擎：`prepare_diagram_layout` 位置完整、无 groups 为分层、`RenderOutcome.layout` 默认 None、matplotlib 下带 groups 挂载 layout。

## 验收锚点覆盖（T-audit 几何 + T-vision 视觉分执）

| 更正后锚点 | D2 覆盖 |
|---|---|
| 01 三层带（层间通信/通信层/执行层），文字区不混入节点 | layer golden：三个 `kind=layer` 组，成员各同 y、带序按图结构；真实节点名 macmini/macbook/win-laptop |
| 02 主线 + 「调研：」「设计：」旁注（note/虚线弱关联，不同级混排） | cluster golden：主线 `input→parse→format→output` + 两簇 `调研：`/`设计：`；断言簇成员行内相邻、`bbox` 仅包络旁注成员 |
| 02-increment 左右两张独立流程保持可分辨（至少 groups 区分） | increment golden：`flow-left`/`flow-right` 两簇，断言 `bbox` 不重叠、列集合不相交 |
| groups>0（≥2 layer 组）、孤立节点归组、组件数下降 | layer/increment fixture 体现；最终以 T-audit 用 D3 合并后产物度量 |

注：像素级「层次看得出」由 T-vision 判定；D2 交付几何与带序，**不产出渲染图**（领地外）。

## 边界说明（需评审确认）

- `tests/taxonomy.py` 不在 brief 领地列表内，但 `tests/test_taxonomy.py::test_every_test_file_has_module_mapping` 强制要求新增 `tests/test_*.py` 必须在 `FILE_TO_MODULE` 登记，否则全量 pytest 变红。brief 明确授权新增测试文件，故做了**唯一一处、append-only、不改既有行**的登记。若评审要求零越界：替代方案是并入既有 `tests/test_diagrams.py`（同样越界且改动更大）。本 worker 选择最小 diff，请评审裁决。

## 诚实限制

- **live VLM / 真实手稿未跑**：无 API key、无网络；golden 是自建 SPEC 形状 fixture，非真实 VLM 输出。真实抽取质量属 D1 / T-audit。
- **未做渲染验证**：D2 不画图、D3 未合并，故「分组在 PNG 里长什么样」未经端到端视觉确认；只证明了几何正确与确定性。
- **02 旁注的「不同级混排」根因在抽取/渲染**：SPEC 用 `Node.note` + `Edge.style=dashed` 表达旁注；D2 的 cluster 分组保证旁注节点成簇、有独立 `bbox`，但把它们与主流程节点放在同一行仍是可能的（取决于 base depth）。真正的「以小字 note / 虚线呈现、不与主流程同级」由 D1（抽取为 note/style）与 D3（字号/虚线渲染）负责。D2 fixture 用的是「旁注为独立分组节点」这一种合法建模。
- **启发式非最优**：交叉减少是固定 2 轮 barycenter，不保证交叉最少；层带锚用中位数，成员 base depth 跨度大时会被强压到同一行（可能变宽）——这是「层带=整行」的有意取舍。
- **多组交叉的优先级**：同一节点同时属多个同 kind 组时，约束按组 id 最小者生效（其他组仍计入 `members`/`bbox`）；layer+lane 可同时生效。
- **cluster 相邻性**：仅保证「同一行内连续列」；若簇成员同时是 lane 成员（跨 kind），lane 固定列优先，簇连续性可能被打破（当前 fixture 不涉及）。
- **lane 同列是有条件的（评审 F3）**：同一 base 行内每 lane 至多一个成员时才严格同列；同行的额外成员溢出到空闲列，两条并行 lane 可能列相互穿插。已由 `test_lane_members_on_the_same_row_overflow_to_free_columns` 与 `test_parallel_lanes_on_the_same_row_may_interleave_columns` 锁定。
- **layer 重叠组会产生幻影空行（评审 F4）**：同一节点属多个 layer 组时，落败组（id 较大）仍占一条带行；若其成员全被更小 id 的组认领，该行会空置并计入 `nrows`，使所有 y 被摊薄。确定且对渲染无害，但调用方勿假设 `nrows` == 非空带数。
- **increment 两侧 bbox 仅「不重叠」**：`diagram-layout-increment.json` 中左 `x1`=0.5 与右 `x0`=0.5 相接，未留间隙；D3 绘制时可加 gap，D2 不再引入。

## Review 修正记录（round 1，verdict=approve + 合并前清单）

评审 verdict：**approve（无阻断）**，附合并前清单；本轮执行第 1–3 项（第 4 项等 D1 合并后由调度通知）：

| Finding | 处理 | 提交 |
|---|---|---|
| F1 hpref 命名/描述误导 | 重命名 `hpref`→`base_order`，docstring/规则 1、3 改为「base 层内序位」 | `54a471e` |
| F2 `rows` 内序易误解 | docstring/handoff 明确 rows 为 barycenter 序、x 用 `columns`/`positions` | `54a471e` |
| F3 lane 同列过强 + 测试盲区 | docstring/handoff 改为「优先同列/同行多成员溢出」；新增 2 个回归测试 | `54a471e` `37fe378` |
| F4 幻影空行未披露 | docstring/handoff 在「已知限制」披露（不改逻辑） | `54a471e` |
| F5 engine.py 多余空行 | 删至 2 行 | `bae1baf` |
| F6 handoff「6 张图」笔误 | 更正为 5 张（single/chain/diamond/cycle/disconnected） | 本次 docs 提交 |
| F7 handoff SHA/状态偏差 | 已于 `c2a18fe` 同步（评审已确认） | — |
| F8 D1 分支已推进 | rebase 段更新为「D1 已有提交但未合并」 | 本次 docs 提交 |
| F9 taxonomy.py 领地 | 评审已接受该 1 行 append-only | — |
| F10 n=0 差异 | 已被 `test_zero_nodes_yields_empty_layout` 锁定，无渲染影响 | — |

**纯文档修正未改任何布局逻辑**；全部改动后 `tests/test_diagram_group_layout.py` 58 passed（后续 D1 接线测试增至 60）；全量 pytest 见「测试证据」。
