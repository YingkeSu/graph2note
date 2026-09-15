# X3 — mpl 组框相交（01 图 9 对，lane×cluster 布局语义层）

Status: ready-for-review

来源：D 轨最终视觉核验 `/tmp/spw-final-vision-report.md` §3；BOARD D6 与 T-vision-final 行残留「组框∩组框 01=9 / 02inc=2 不变」；`/tmp/review-spw-D3fix-verdict.md` 布局层残留 N1。属 D 轨遗留（X 轨）。产地：`graph2note/diagrams/_layout.py` + `matplotlib_renderer.py`。

## What to build

matplotlib 渲染路径的**组框（group frame）之间相交**。终检 §3 用自写 harness（spy `matplotlib_renderer.build_figure` 抓产出 PNG 的 figure，`fig.canvas.draw()` 后取 artist `window_extent` 做矩形相交）测得：01 图 **组框∩组框 9 对**、02inc **2 对**、02 = 0；基线（D4 合并点 `4c3782a`）同为 9/0/2，即 D5b/D6 未触及此项。

根因在**布局语义层**：lane 组（泳道列）与 cluster 组（行内相邻域）可被放进同一行带且左边界相同，`_group_extent` 据成员外扩出的矩形因此重叠；`_draw_groups` 无跨组框去冲突。D6 只修了**组标题文字**的跨组去冲突（标题锚点层，01 2 对 → 0/0/0），组框本身未动。

要求：消除或明确降级组框相交——在 lane/cluster 同带时分离列域，或在渲染层对相交框做并集/收缩并标注，使 01/02inc 的组框∩组框降为 0（若保留语义重叠，须在 SPEC/注释中给出可解释定义）。

## Acceptance criteria

- [ ] 复现：用终检同一 harness（真实 01/02inc 抽取 JSON → `ir.load_dict_as_ir` → `FileAssetWriter(prefer="matplotlib")`）测得组框∩组框 01=9、02inc=2，作为修复前基线写进 Comments。
- [ ] 修复后同 harness 组框∩组框 **0/0/0**（01/02/02inc），且节点级五项（节点框∩节点框、文字越框、文字无唯一归属框、组标题压节点框、边标签压节点框）零回退。
- [ ] 组框语义不丢：lane 泳道列语义、cluster 行内相邻语义在 golden/fixture 上仍可断言（不靠删框/隐藏组「清零」）。
- [ ] 确定性：同输入两次渲染 SHA256 相同；`PYTHONHASHSEED` 多变体一致。
- [ ] golden 与扁平路径不回退：4 个 layout golden（layer/lane/cluster/increment）+ anchor01/02/02inc 逐字段对照，扁平（无 groups）逐字节 SHA256 同。
- [ ] mutation 有牙：把修复逻辑改回旧行为时新相交断言变红。
- [ ] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（与 X4 同文件，建议串行或同一 worker 协调）。

## 领地

- 独占：`graph2note/diagrams/_layout.py`（lane/cluster 列域分离）、`graph2note/diagrams/matplotlib_renderer.py`（`_group_extent`/`_draw_groups` 框层）、`tests/test_diagram_render_groups.py`、`tests/test_diagram_group_layout.py`。
- 不回归：D6 已合并的标题层（`_place_group_titles`）。
- 禁止：`ir.py`、`diagram.py` 抽取段、I 轨文件。

## Comments

- 相关残留指针（`/tmp/review-spw-D3fix-verdict.md`）：N1「无邻接边层带下沉把自由连通节点拖入沉底行」是 D2 布局层 corner（fuzz 243 例命中 12 例；真实锚点/golden/live 不触发）；N5「幻影空行会让 `len(set(ranks))==nrows` 断言报错而非静默」。两者同属布局层；若在本 issue 一并处理请补 Acceptance 条目，否则保持独立后续项。
- 影响面：仅 mpl 分组路径；graphviz 与扁平路径不在内。
- 终检 §3 数据：01 组框∩组框 9 对、02inc 2 对、02 0 对（基线与现状相同）。
- 交付记录（branch `dev/X3X4-mpl-layout` @ `b74f0cc`）：Status → ready-for-review。
  - 复现（修复前基线，终检同一 harness `/tmp/spw-final/group_frame_check.py`：真实 01/02/02inc 抽取 JSON → `ir.load_dict_as_ir` → `FileAssetWriter(prefer="matplotlib")`，spy `build_figure` 取 artist `window_extent`）：组框∩组框 **01=9 / 02=0 / 02inc=2**（9 对 / 2 对明细见 `/tmp/spw-final/group-frame-report-X3X4-base.json`），与终检 §3 一致。
  - 修复（`matplotlib_renderer.py`，框层）：`_group_frames` 在**组框两两不相交时原样沿用 layout bbox**（保 D3「renderer 不臆造几何」合同与 golden/扁平不变）；一旦相交，改用 `_group_frame_cells` 把每个组的 domain（`_group_extent`）落到布局网格并做**划分**——持有他组成员的 cell 不被认领、可共用的空 cell 由先序组认领，`_merge_cells` 合并成最大矩形。每 cell 至多属一组，框可贴边不可相交，成员仍在自己组框内。
  - 修复后同 harness：01/02/02inc 组框∩组框 **0/0/0**；`title∩title` 0；节点级五项（节点框∩节点框 / 文字越框 / 文字无唯一归属框 / 组标题压节点框 / 边标签压节点框）+ 文字∩文字 **全 0**（`/tmp/spw-final/group-frame-report-X3X4-r2.json`、`/tmp/spw-final/render-X3X4-r2/render-overlap-report.json`）。
  - 语义不丢：lane 泳道列语义与 cluster 行内相邻语义仍可断言——新增 `test_lane_frames_stay_columns_on_golden_fixture`（golden lane 每个 lane 仍是**单一整列**框、两列互不相交、与 layout bbox 逐字段一致）、`test_group_frame_rects_partition_the_grid_and_cover_members`（划分互斥 + 成员必在自组框内）；未删框/隐藏组。
  - 确定性：同输入两次渲染 SHA256 同（`test_matplotlib_groups_path_is_deterministic`）；新增 `test_grouped_frame_geometry_is_hash_seed_independent`（`PYTHONHASHSEED` 0/1/2 子进程框几何一致）。
  - golden/扁平不回退：4 layout golden（layer/lane/cluster/increment）+ anchor01/02/02inc 逐字段对照通过；扁平（无 groups）PNG 逐字节 SHA256 命中锁 `test_matplotlib_ungrouped_png_matches_baseline_golden`。
  - mutation 有牙：把新 X3 断言跑在 main `e6009fc` 树（`/tmp/spw-X3X4-base-tree`）→ `test_group_frames_do_not_intersect_on_overlapping_layout` 红。
  - 全量 `pytest -p no:warnings`：分支 **1224 passed**（base `e6009fc` 1218）。改动仅 `graph2note/diagrams/matplotlib_renderer.py` + `tests/test_diagram_render_groups.py`（外加 X4 同文件改动）。
