# D5b — mpl 密图原生重叠修复 + CJK 粗体 + N1 corner（handoff）

Status: **ready-for-review**
分支：`dev/D5b-mpl-dense`（基线 `main 883f8cb`，未合并、未 push）
日期：2026-09-15
领地：`graph2note/diagrams/matplotlib_renderer.py`（渲染/字体）、`graph2note/diagrams/_layout.py`（经授权，仅 N1 corner）+ 对应测试。
未碰：`graph2note/vlm.py`（另一 worker 在改抽取 prompt）、`.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`（脏文件）。

输入证据（只读，未复制进仓库）：`/tmp/spw-T-vision-recheck-live.md`（§2/§4/§7-5）、
`/tmp/review-spw-D3fix-verdict.md`（finding N1）、密图用例
`/tmp/spw-taudit-artifacts/recheck-live/raw/*-deepseek__extract.json`（21/10/32 节点）。

---

## §0 总览

| # | 任务 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | mpl 密图原生重叠（≥21 节点） | **达成**：画布/布局按内容自适应（不缩字号）；live 3 图的 artist 重叠全部归零 | §1 |
| 2 | CJK 粗体退化（findfont bold warning） | **达成**：组标题选真 CJK 粗体面（Hiragino Sans GB W6/600）；无任何 findfont 警告 | §2 |
| 3 | N1：自由连通节点被拖入孤立沉底带 | **达成**：锚深度只由*连通*层带认领；goldens/anchors 零变化 | §3 |
| 4 | 回归底线 | **达成**：4 golden + anchor01/02/02inc 逐字段 == main；扁平（含 note+dashed）两引擎 PNG/DOT 逐字节 == main；pytest 1043 passed；node 2 套通过 | §4 |

**未做**：未合并、未自审、未 push；未改 `vlm.py` / `.env` / 密钥；未做 live VLM 调用；未 `find /Users/suyingke`。

---

## §1 mpl 密图原生重叠

### 根因

`build_figure` 恒用 `figsize=(12,8)`，而 `positions` 是 `[0,1]²` 归一化网格：节点越多，网格
间距（`1/ncols`、`1/nrows`）越小，但节点框尺寸公式（`box_w` 最高 0.42、`box_h` 最高 0.28）
与字号（pt，固定）不随密度收敛 → 框框互压、文字越框、组标题压节点。

实测（修复前、live 用例走产品链 artist bbox 相交）：

| 图 | nrows×ncols | node-node 交叠对数 | text 越框 | 组标题压节点框 |
|---|---|---|---|---|
| live01（21 节点） | 5×10 | 24 | 14 | 1 |
| live02（10 节点） | 4×4 | 1 | 0 | 1 |
| live02inc（32 节点） | 8×9 | 45 | 12 | 15 |

### 处置（`matplotlib_renderer.py`）

**优先自适应画布/布局，字号三档 15/13/10 未动**（T-vision 明示：缩字伤可读性）。

1. 新增物理文字度量 `_text_size_in(text, fontsize)`：复用渲染器既有「1 unit = 半 em」约定
   （CJK 2 unit = 1 em）→ `width = (max line units)/2 * fontsize / 72`（英寸），与字体文件无关、确定性。
2. 新增 `_grid_dims(pos)`：由最小坐标间距（网格 pitch，`ceil` 保守）反推 `(nrows, ncols)`，
   不依赖 `layout["rows"]`，因此对直接调用 renderer（无 layout）同样成立。
3. 新增 `_grouped_geometry(sem, pos, wrapped, notes)`（仅 `sem.groups` 非空时启用）：
   - `cell_w_in = (max 文字宽 + 2·pad_x)/(1-0.16)`，故每个节点框 ≤ 网格宽度且留有横向间隙；
   - `cell_h_in = max 文字高 + 2·pad_y + 2·(标题高 + 标题间隙)`，即每行为组标题预留一条竖带；
   - `fig_w = max(12, ncols·cell_w_in/0.96)`、`fig_h = max(8, nrows·cell_h_in/0.96)`
     → 小图仍落在 12×8（扁平路径逐字节不变的保障），密图才长。
   - 逐节点框 `box_w/box_h`、以及 label/note 作为一整个文字块在框内居中的 `label_dy/note_dy`。
4. 组标题（`_draw_groups`）：`row_top` = **该行所有节点**框顶的最小值（不只是本组成员，否则会压到同排
   更高的邻框），标题 `va="bottom"` 锚在 `row_top - title_gap`，向上生长，落在预留带内。
5. 边标签（`_place_edge_label`）：分组路径下，若边中点标签框压到任一节点框，按固定候选序列
   `t∈{0.5,0.35,0.65,…,0.15,0.85}` 沿边滑动到首个不压框的位置；**扁平路径不调用**（PNG 字节锁定）。
6. 位置与组 bbox 仍是 D2 layout 的权威几何，**未平移节点、未改 bbox**（`test_matplotlib_uses_layout_positions_and_bbox` 绿）。

### 结果（修复后，同样 artist bbox 相交）

| 图 | figsize(in) | 产品链 px | node-node | text-text | text 越框 | 组标题压节点 |
|---|---|---|---|---|---|---|
| live01 | 21.89×8 | 2545×945 | 0 | 0 | 0 | 0 |
| live02 | 12×8 | 1406×945 | 0 | 0 | 0 | 0 |
| live02inc | 19.70×12.56 | 2293×1471 | 0 | 0 | 0 | 0 |

确定性：live01/live02inc 两次 `render` SHA256 相同。程序化判定已写进
`tests/test_diagram_render_groups.py::test_dense_grouped_diagram_has_no_artist_overlap`
（+ `_dense_fixture` 24 节点/3 层带/含 note/含跨图对角带标签边）。有牙实证：同 fixture 在
`883f8cb` 上 39 组框框相交 + 2 个边标签压框；本分支 0 / 0。

---

## §2 CJK 粗体退化

### 根因

`_register_cjk_font` 取候选列表第一个存在的字体 `/Library/Fonts/Arial Unicode.ttf`
（family `Arial Unicode MS`，只有 400 面），组标题 `fontweight="bold"`（=700）→
matplotlib `font_manager` 记 `findfont: Failed to find font weight bold`，实际退化为 400。

### 处置

`_select_cjk_fonts()`：注册**所有**存在的候选字体，返回
`(regular_family, bold_family, bold_weight)`：

- `regular` 仍是列表首个匹配（Arial Unicode MS），**保证扁平 PNG 逐字节不变**；
- `bold_family/bold_weight` = 首个含 ≥600 面的候选（本机 `Hiragino Sans GB` 600；
  Linux/Noto Sans CJK 同理取 Bold 面）；
- 组标题用 `fontfamily=[bold_family]` + `fontweight=<数字权重>`。**关键**：请求数字 600 而非
  `"bold"`，否则即便命中 600 面，matplotlib 仍会记「Failed to find font weight bold, now using 600」。
- 无任何 ≥600 CJK 面时回退：保留 regular family、权重 normal，用 `path_effects.withStroke`
  做合成加粗（可区分、且绝不产生 findfont 警告）。

### 证据

- 本机：`_CJK_FAMILY='Arial Unicode MS'`、`_CJK_BOLD_FAMILY='Hiragino Sans GB'`、`_CJK_BOLD_WEIGHT=600`；
  组标题 artist `get_fontweight()==600`、`get_fontfamily()==['Hiragino Sans GB']`。
- live01 渲染期捕获 `matplotlib.font_manager` logger：`findfont` 相关 warning = **[]**（修复前有 bold 警告）。
- 测试：`test_group_title_does_not_degrade_weight_silently`（caplog 断言无
  “Failed to find font weight”）、`test_group_title_style_never_requests_a_missing_weight`。

---

## §3 N1 corner（自由连通节点被并入孤立沉底带）

### 根因（review N1 复述）

`_layout.grouped_layout` 里 `anchor_values` 收集了**所有** layer 带的锚深度，`anchor_row` 也由
所有带 `setdefault`。当某 layer 带孤立（无邻接边、median depth=0）、且存在 depth=0 的自由源点
（不属于任何 layer 带）时，该自由点会经 `anchor_row[0.0]` 并进被沉到最底部的孤立带行，
其出边视觉向上。真实锚点/golden/live 不触发，fuzz ~5% 命中。

### 处置（`_layout.py`）

- 新增 `connected_anchors`（只含**非孤立** layer 带的锚深度）：自由节点的 `depth` 只有落在
  `connected_anchors` 时才并入对应带；`anchor_row` 也只登记非孤立带。
- 于是 depth 仅与孤立带锚值相同的自由点获得自己的 `depth:d` 行（rank=1、isolated_flag=0），
  排在所有沉底孤立带之上 → 出边方向恢复正常。孤立带仍按 F-C 下沉。
- 连通带认领锚深度的既有规则**保留**（`test_connected_band_still_claims_its_anchor_for_free_nodes`）。

### 证据

```
BASE(883f8cb)  grouped_layout(["a","b","iso"], [("a","b")], G孤立[iso])
  rows=[["b"],["iso","a"]]   # a 被拖进孤立行，a->b 向上
NEW
  rows=[["a"],["b"],["iso"]] # a 在第 0 行，a->b 向下，孤立带仍沉底
```

测试：`test_isolated_band_does_not_absorb_a_free_source_node`（含输入乱序不变）。
**goldens 零变化**：4 个 golden + anchor01/02/02inc 的 `grouped_layout` JSON 与 `883f8cb`
逐字段相同（脚本见 §5）。

---

## §4 回归底线（全部自跑）

| 项 | 命令 | 结果 |
|---|---|---|
| 全量 | `.venv/bin/python -m pytest -p no:warnings` | **1043 passed**（126s） |
| node 1 | `node tests/diagram_presentation.cjs` | all assertions passed ✓ |
| node 2 | `node tests/assets_rewrite.cjs` | all assertions passed ✓ |
| 4 golden 布局 | base(`883f8cb`) vs new `grouped_layout` JSON | 逐字段相同（4/4） |
| anchor01/02/02inc 布局 | 同上 | 逐字段相同（3/3） |
| 扁平路径（无 groups，含 note + dashed） | gv.png / mpl.png / gv.dot SHA256 | **两者逐字节相同** |
| 扁平 PNG golden | `test_matplotlib_ungrouped_png_matches_baseline_golden` | 绿 |

扁平回归脚本：`/tmp/d5b/flat_run.py`（对 `/tmp/d5b-base`=`git archive 883f8cb` 与分支各跑一次，
比较 SHA256）。golden/anchor 脚本：`/tmp/d5b/anchors.py`。

---

## §5 复现 / 证据

```bash
# 全量
PY=.venv/bin/python
$PY -m pytest -p no:warnings
node tests/diagram_presentation.cjs && node tests/assets_rewrite.cjs

# 产品链渲染 live 3 图（IR→render→FileAssetWriter→engine.render_to_png）
$PY /tmp/d5b/product_chain.py "$PWD" /tmp/d5b/product

# artist bbox 相交判定（程序化）
$PY /tmp/d5b/overlap.py "$PWD"

# 扁平逐字节 + golden/anchor 对照（base 树）
git archive 883f8cb | tar -x -C /tmp/d5b-base
$PY /tmp/d5b/flat_run.py /tmp/d5b-base /tmp/d5b/base
$PY /tmp/d5b/flat_run.py "$PWD" /tmp/d5b/new
$PY /tmp/d5b/anchors.py /tmp/d5b-base /tmp/d5b/anchors-base.json
$PY /tmp/d5b/anchors.py "$PWD" /tmp/d5b/anchors-new.json && diff anchors-*.json
```

---

## §6 未尽事项 / 已知边界

- **边标签压节点仅分组路径处理**：扁平路径为逐字节锁死，不做滑移；若未来扁平密图也要避让，
  需先解除扁平 PNG golden 锁。
- **title strip 的坐标轴假设**：竖带预留基于「行水平排布（TB）」。产品链固定 `orientation="TB"`；
  LR/RL/BT 仍会自适应画布，但组标题避让按 y 轴预留，未做轴向特化。
- **字号未缩**：密图通过画布增长换取可读性，产物 px 变大（live02inc 1418×945 → 2293×1471），
  文档默认视图仍需放大镜（属 D2 布局紧凑度话题，非本轮范围）。
- **真 CJK 粗体依赖候选列表**：本机命中 Hiragino Sans GB W6；无重面环境走合成加粗回退（无警告）。
- 未做 live VLM 调用、未 push、未合并。
