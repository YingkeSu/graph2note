# D6 — mpl 组标题互压修复（handoff）

Status: **ready-for-review**
分支：`dev/D6-grouptitle`（基线 `main 8142345`，未 push）
日期：2026-09-15
领地：`graph2note/diagrams/matplotlib_renderer.py`（仅组标题层）+ `tests/test_diagram_render_groups.py`。
**未动** `graph2note/diagrams/_layout.py`（无必要：缺陷完全在标题锚点层，节点布局/组框几何不需要改）。
未碰：`.scratch/baseline-and-next-iteration/issues/06-web-obsidian-vault-export.md`（脏文件）、`.env`/密钥、`vlm.py`；未 push；未 `find /Users/suyingke`。

输入证据（只读，未复制进仓库）：`/tmp/spw-final-vision-report.md` §3/§4/§5-4（组标题文字∩文字 01=2 对、02inc=1 对；VLM 在 02inc 顶带独立确认）。

---

## §0 总览

| # | 任务 | 结论 | 关键证据 |
|---|---|---|---|
| 1 | 组标题跨组去冲突（只动标题层） | **达成**：live 3 图标题文字∩文字 **0/0/0**（main 2/0/1） | §2、§3-1 |
| 2 | 节点级指标不回退 | **达成**：node∩node / 文字越框 / 无唯一归属框 / 标题压节点框 / 边标签压节点框 全 0，与 main 逐项相等 | §3-1 |
| 3 | goldens（4 layout golden + anchor01/02/02inc）与 main 一致 | **达成**：0 diff（逐字段 + PNG SHA） | §3-2 |
| 4 | 扁平路径逐字节一致 | **达成**：ungrouped mpl PNG SHA / gv.dot SHA == main；graphviz 3 图 PNG 逐字节同 | §3-2 |
| 5 | 新增回归测试锁「组标题互斥」 | **达成**：2 个新用例在 main 树上红、本分支绿；另给 `_assert_no_overlap` 加第 5 项 | §3-4 |
| 6 | 全量 pytest + node tests 绿 | **达成**：`pytest -p no:warnings` **1048 passed / 0 skipped**（node 套件由 pytest 包装，含在 1048 内） | §3-5 |
| 7 | 视觉抽检（可选，≤4 次） | **达成**（4 次 kimi）：01/02inc 顶带标题可辨、无压叠；01 全图无重叠/无裁切 | §3-6 |

**未做/明确不在本轮**：组框∩组框（01=9 / 02inc=2，与 main 同值）属布局语义残留，未处理；节点布局、组框几何、字号三档、边标签逻辑均未动。

---

## §1 根因

`_draw_groups`（`matplotlib_renderer.py`）在分组/密图路径把每个组标题锚在

```
tx = 组框 x0 + 0.008
ty = 该组最高成员所在行的 row_top − title_gap     # va="bottom"，向上生长
```

`row_top` 是**整行**节点框顶的最小值（D5b 的修正），但**没有跨组去冲突**。当同一行带
（同 `row_top`）里有两个组、且两者 `bbox.x0` 相同（典型：lane 带 + 其内部的 cluster，
或同一列的 cluster + cluster），两个标题锚点重合 → 文字逐字叠印。

live 实测锚点完全相同（`/tmp/spw-D6-diag.py`）：

| 图 | 组 A | 组 B | 共同锚点 |
|---|---|---|---|
| 01 | lane `用户侧` (x0=0) | cluster `调度方案选型` (x0=0) | `(0.008, 0.0215)` |
| 01 | cluster `通信源` (x0=0.1) | cluster `问题与项目结构` (x0=0.1) | `(0.108, 0.0215)` |
| 02inc | cluster `笔记/手册电子化入口` (x0=0) | cluster `输出与视图` (x0=0) | `(0.008, 0.0237)` |

## §2 处置（仅标题层）

新增三个纯函数 + `_draw_groups` 两遍化（先算锚点、后画），**组框/节点/边一律不动**：

1. `_title_box(tx, ty, w, h)` → `(x0, top, x1, bottom)`（y 轴反转，`va="bottom"` 向上生长）；
   `_boxes_hit(a, b, pad_x, pad_y)` 矩形相交（带 slack）。
2. `_place_group_titles(candidates, node_boxes, axes_size, title_gap)`：按 `sem.groups`
   顺序贪心放置。标题**默认保留历史锚点**；仅当它的文本框与「已放置标题」相交时才移动：
   - 先尝试**同一标题带内水平滑移**：贴到同带已放标题的右侧（`max(x1)+pad_x`）或左侧
     （`min(x0)−pad_x−w`）——同一 y 带一定在节点框之上（D5b 已预留），横向移动不会压节点；
   - 再尝试**向上叠**到该行预留带之上的条带（`ty − k·(h+title_gap)`，k=1..3）；密图行带通常只
     容一条标题带，故该分支大多被「越出画布 / 压到节点框」检查否决，属兜底；
   - 每个候选都要通过三重检查：不出画布（`0 ≤ x ≤ 1`、`y ≥ 0`，带 `_CANVAS_EPS` 容差）、
     不与已放标题相交（含 pad）、不压任何节点框；
   - 全部候选失败 → 回退历史锚点（best effort，永不更差）。
3. 落点由**估算文字框**驱动（复用 D5b 的 `_text_size_in`，CJK 精确、确定性），滑移留白
   `_TITLE_SLIDE_PAD_IN = 0.12in`、行带判定留白 `_TITLE_ROW_PAD_IN = 0.02in`。
4. **golden-safe**：无冲突的图（含全部 anchor、golden fixture、02 live）每个标题都保留原锚点，
   artist 顺序不变 → PNG 逐字节不变；只有真正相交的标题才位移。

新增常量：`_TITLE_SLIDE_PAD_IN`、`_TITLE_ROW_PAD_IN`、`_CANVAS_EPS`（1e-6，避免 `ty−h`
浮点落到 `−3.5e-18` 时把合法锚点当"越出画布"否决——这是实现期实测到的一个边界）。

## §3 验收（全部本轮自跑）

### §3-1 live 3 图（产品链，`/tmp/spw-final/raw/*__extract.json`，23/9/17 节点）

链路同 T-vision：抽取 JSON → `validate_diagram_json` → `ir.load_dict_as_ir`
→ `render.render_markdown` → `FileAssetWriter(prefer=matplotlib/graphviz)`
→ `diagrams.engine.render_to_png`；spy `build_figure` 抓**产出该 PNG 的同一 figure**，
`canvas.draw()` 后按 artist `window_extent` 求交（面积 >1px²）。

| 指标（mpl） | 01 (23) main → D6 | 02 (9) main → D6 | 02inc (17) main → D6 |
|---|---|---|---|
| **组标题文字∩文字** | **2 → 0** | 0 → 0 | **1 → 0** |
| 节点框∩节点框 | 0 → 0 | 0 → 0 | 0 → 0 |
| 文字越出自己节点框 | 0 → 0 | 0 → 0 | 0 → 0 |
| 文字无唯一归属框 | 0 → 0 | 0 → 0 | 0 → 0 |
| 组标题压节点框 | 0 → 0 | 0 → 0 | 0 → 0 |
| 边标签压节点框 | 0 → 0 | 0 → 0 | 0 → 0 |
| 组框∩组框（**不在本轮**，与 main 同值） | 9 → 9 | 0 → 0 | 2 → 2 |
| figsize(in) | 21.887×12.637 不变 | 12.0×8.0 不变 | 17.51×11.468 不变 |
| 节点/文字/边标签计数、notes、dashed | 23/28/8/6、5、5 不变 | 9/13/0/4、4、0 不变 | 17/21/1/5、4、3 不变 |

移动后的锚点（数据坐标，`/tmp/spw-D6-anchors.py`）：

- 01：`用户侧` 0.008 / `通信源` 0.108 保持；`调度方案选型` 0.008→**0.1435**、`问题与项目结构`
  0.108→**0.2087**（仍在各自组的组框内）
- 02inc：`笔记/手册电子化入口` 0.008 保持；`输出与视图` 0.008→**0.1329**
- 相邻标题实测像素间隙 14–15px（120dpi）

**组框∩组框 9/0/2 与 main 完全同值**：本轮只动标题层，未触碰布局/组框几何（按任务要求明确不在本轮）。

### §3-2 goldens / anchors / 扁平路径与 main 逐字段（逐字节）

`/tmp/spw-D6-verify.py` 对两棵树各产一份 `acceptance.json`（4 golden fixture 的
`grouped_layout` dict SHA + DOT 源 SHA；3 anchor 的两引擎 PNG SHA、groups/notes/dashed 语义、
全部 text 坐标、节点框坐标、全部 text `window_extent`；扁平 ungrouped mpl PNG SHA + flat DOT SHA），
递归逐字段 diff：

```
DIFFS: 0        # /tmp/spw-D6-acc-main  vs  /tmp/spw-D6-acc-branch
```

即 4 golden（layer/lane/cluster/increment）与 anchor01/02/02inc 逐字段一致，扁平路径逐字节一致。
另：3 张 graphviz PNG 与 02 mpl PNG 的 sha256 与 main **逐字节相同**；01/02inc 的 mpl PNG 仅因标题
位移而变化（图幅、尺寸不变）。仓库内 `MPL_GOLDEN_SHA`（ungrouped）用例亦通过。

### §3-3 组标题互斥（程序化）

`/tmp/spw-final/group_frame_check.py`（真实 window extent，>1px² 记相交）：

```
main    : 01=2 pairs, 02=0, 02inc=1
branch  : 01=0 pairs, 02=0, 02inc=0
```

### §3-4 新增回归测试（基线红 / 分支绿）

`tests/test_diagram_render_groups.py`：

- `_same_left_edge_two_group_layout()`：手写 D2 layout（lane `用户侧` x0=0 + cluster
  `调度方案选型` x0=0，两者都有成员落在同一行 `y=0.25`，成员不重叠）——正是 live 01 的形状。
- `test_same_left_edge_group_titles_are_kept_apart`：两个标题渲染框不相交，且位移后的标题仍
  不压任何节点框、不出画布；两个标题都完整存在。
- `test_same_left_edge_group_titles_are_deterministic`：两次构建锚点完全相同，且第二个标题确实
  发生了水平位移（`x` 不同）。
- `_assert_no_overlap` 追加第 5 项：密图 fixture 的组标题两两不相交（现已由修复保证）。

基线验证：把同一测试文件拷进 `git archive 8142345` 树 `/tmp/spw-final/main-tree` 跑：

```
FAILED test_same_left_edge_group_titles_are_kept_apart
FAILED test_same_left_edge_group_titles_are_deterministic
（main 树上第二个标题 x == 0.008，assert 0.008 != 0.008 红）
```

分支：`tests/test_diagram_render_groups.py` 30 passed。

### §3-5 全量测试

```
pytest -p no:warnings --tb=short     # cwd = 本分支 worktree
1048 passed in 122.16s               # 0 skipped；node 套件（graph_layout/ask_view/... ）含在内
```

### §3-6 视觉抽检（可选，kimi 网关，4 次调用）

经 `eval.gateway.transcribe_image`（`GRAPH2NOTE_GATEWAY=kimi`，key 只在主检出 `.env`，未打印）：

| 输入 | 渲染版本 | 判读 |
|---|---|---|
| 01-mpl 顶带裁片 | pad 0.08in 版 | 「4 个组标题：用户侧 / 通信源 / 调度方案选型 / 问题与项目结构」，**无压叠、无字叠字、未压节点框** |
| 02inc-mpl 顶带裁片 | pad 0.08in 版 | 「笔记/手册电子化入口 输出与视图 / 数据来源与存储 / 变量处理」，**overlap=无、title_on_node=无** |
| 01-mpl 全图 | pad 0.08in 版 | 无文字互相重叠、无越框、无裁切 |
| 02inc-mpl 顶带裁片 | **终版 pad 0.12in** | 「4 个：笔记/手册电子化入口 / 输出与视图 / 数据来源与存储 / 变量处理」，**overlap=无、title_on_node=无** |

即 4 次调用（≤4 预算）。前 3 次跑在 pad 0.08in 的产物上（当时标题间隙 9–10px），其后把留白调到
0.12in（间隙 14–15px），**终版已对最紧的 02inc 顶带重跑确认**；其余读数只受「间隙变宽」影响，结论
方向不变。

对照 T-vision 的旧判读（01 顶带被读成乱码 2 条串、02inc 顶带 `输出…` 与 `笔记/手册电子化入口`
叠在一起）：同口径输入下已不再出现。程序化几何为主证，VLM 为辅证。

## §4 复现命令

```bash
cd /Users/suyingke/Programs/OHO/graph2note          # 仅为 .venv / .env
W=/Users/suyingke/.ao/data/worktrees/graph2note/graph2note-90
.venv/bin/python /tmp/spw-final/render.py           $W /tmp/spw-D6-render        # 产物 + artist 重叠报告
.venv/bin/python /tmp/spw-final/group_frame_check.py $W /tmp/spw-D6-fix-groupframe.json
.venv/bin/python /tmp/spw-D6-verify.py /tmp/spw-final/main-tree /tmp/spw-D6-acc-main
.venv/bin/python /tmp/spw-D6-verify.py $W /tmp/spw-D6-acc-branch   # 两目录逐字段 diff = 0
.venv/bin/python /tmp/spw-D6-anchors.py $W          # 移动后的标题锚点
.venv/bin/python /tmp/spw-D6-vlm.py /tmp/spw-D6-render /tmp/spw-D6-vlm-out   # 视觉抽检
cd $W && .venv.../python -m pytest -p no:warnings
```

## §5 诚实边界

- **单样本**：live 结论基于 T-vision 的同一份抽取 JSON（每手稿 1 个样本），未做多采样稳定性验证；
  组数/kind 在样本间有波动（D5a 已证）。
- **行带容量**：`_grouped_geometry` 每行只预留**一条**标题带（`title_h + title_gap`），因此对顶部
  行或满格行，竖直叠放通常不可用，实际生效的是水平滑移；竖直叠放仅在该行节点框明显矮于上限时可用
  （已由「不压节点框」检查守门）。若将来出现「一行 3+ 个同左界组」，可能滑移空间不足 → 回退历史
  锚点（best effort，仍会更差吗：不会比未修复更差，但可能仍压叠）。本样本 01/02inc 均为 2 个一组。
- **滑移使用估算文字宽**（`_text_size_in`）而非真实字体度量；本轮留白 0.12in（约 14px@120dpi），
  实测真实 extents 相交 = 0。真实粗体 CJK 若比估算显著更宽，理论上仍可能擦边。
- 未处理的相邻层：组框∩组框 9/0/2（布局语义，按任务不在本轮）。
- 未改 `_layout.py`；未改字号/画布公式；未合并、未自审、未 push。
