# X6 — D2 密图默认文档视图紧凑度（放大镜链路已救，默认视图不可读）

Status: ready-for-review

来源：D 轨最终视觉核验 `/tmp/spw-final-vision-report.md` §2；`handoffs/D4-diagram-fix.md` §3（matplotlib note@720px ≈8.5px）；`handoffs/D5b-mpl-dense.md` §6（密图画布增长、默认视图仍需放大镜）；BOARD D4/D5b/T-vision-final 行遗留指针「D2 密图紧凑度」。属 D 轨遗留（X 轨）。

## What to build

D2 分组布局 / D5b 画布自适应以「画布增长换可读性」，密图产物 px 显著变大，但**文档默认视图**把 PNG 缩到容器宽度后节点/note 文字不可读，必须点开全屏 viewer 放大——放大镜链路已可用（`graph2note/webstatic/js/views/document.js` 的 `openImageViewer` + `viewer-zoom-in/out/close/fit`，`index.html` 内 `#viewer-zoom-*`），故本 issue 只解决默认视图可读性，不重做 viewer。

终检 §2 产品链 mpl 实测：01（23 节点）**21.9×12.6 in / 2545×1479 px**；02 **12.0×8.0 in / 1406×945 px**；02inc **17.5×11.5 in / 2041×1345 px**。D5b §6 记录 live02inc 1418×945 → 2293×1471（画布增长）。D4 §3 记录 `NOTE_FONTSIZE=10` 未上调，@720px 显示下 note ≈**8.5px** 不可辨。

要求（先裁决默认视图策略，再实现）：例如默认全宽呈现 + 明确「点击放大」引导、或按容器宽度自动选择紧凑布局（减少同带节点数/收紧间距）、或对超过节点数阈值的图默认走紧凑变体。

## Acceptance criteria

- [x] 裁决并记录默认视图策略（Comments：改什么、为什么、代价），先于实现。
- [x] 用真实 01/02inc 抽取 JSON 走产品链渲染，在文档默认视图宽度（如 720px / 390px 容器）下给出可读性判定：沿用 D4 的 720px 口径，节点 label 与 note 像素高度达可辨下限（建议正文 ≥ ~11px、note ≥ ~9.4px；若放宽须显式记录并说明）。
- [x] 若引入「紧凑布局」：新增确定性阈值/纯函数并有测试；grouped golden 与扁平路径不回退（逐字段/逐字节对照）。
- [x] 放大镜链路不回归：全屏 viewer 打开/缩放/平移由既有 node/DOM 契约测试锁定，保持绿。
- [x] 前端巡检：`scripts/frontend_audit.mjs` 三宽度 0 findings（无横向溢出/裁切控件）；390px 可用。
- [x] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（策略裁决项；若选紧凑布局则与 X3/X4 同文件，建议串行）。

## 领地

- 独占：`graph2note/diagrams/_layout.py`（若做紧凑变体）、`graph2note/diagrams/matplotlib_renderer.py`（字号/间距，若做）、`graph2note/webstatic/js/views/document.js` + `graph2note/webstatic/style.css`（默认视图呈现/引导，仅必要追加）、对应新测试。
- 禁止：`ir.py`、抽取 prompt、I 轨 digest/papers 文件。

## Comments

- 终检 §2 与 D5b §6 均把本项标为「后续 / 非本轮范围」。
- D5b §6 原文：「**字号未缩**：密图通过画布增长换取可读性，产物 px 变大（live02inc 1418×945 → 2293×1471），文档默认视图仍需放大镜（属 D2 布局紧凑度话题）。」
- D4 §3 原文：「note 档保持 10pt（未上调），因此 720px 模拟下仍约 8.5px ... 若后续要把 note 下限抬到 ~9.4px，可将 `NOTE_FONTSIZE` 调到 11（仍满足 15>13>11）」。

### 维护者裁决（2026-09-15）——默认视图策略

- **原文**：「不可读说明设计有问题，优化设计」。
- **决策人**：维护者（orchestrator 转述，2026-09-15）。
- **解读**：不接受「默认全宽呈现 + 点击放大引导」的绕行——把可读性推给全屏 viewer 只是转移问题。默认文档视图本身必须可读；
  要动的是渲染设计，而不是补一层引导。因此 X6 不新增/不改放大引导，只改「产物在默认阅读宽度下的几何」。
- **设计决策**（已实现，见下）：把分组渲染的画布宽度做成**阅读宽度的函数**，而不是内容的无界函数：
  1. 预算：默认阅读宽 720px、最小可辨 note 10pt→≥9.4px，反解出最大图宽 `legibility_max_figure_width()`
     ≈10.87in（eff = 0.96·fig_w + 0.2 的 tight-bbox 模型）；超过预算的宽排自动收紧**逐行换行预算**（词感知），
     换行只增加行数/高度，字号三档 15/13/10 不动。
  2. 下限：分组画布 floor 12in→6in（=720px@120dpi，阅读窗不会上采样），避免紧凑图被重新撑宽。
  3. 收紧间距：文字横向 pad 0.07→0.05in、格间 seam 0.16→0.10，仍保留可见间隙。
- **为什么不是「减少同带节点数/紧凑布局」**：拆带要改 D2 `_layout.py` 的 rows，会破坏「layer = 同一带/同一 dot rank」契约、
  X3 框划分的几何源、以及 dot rank pinning，回归面大；换行保持图结构（rows/positions/bbox/边）逐字段不变，只改文字横向排版，
  验收目标（720px 下 label≥11px、note≥9.4px）同样达成。
- **为什么不是点击放大引导**：维护者已明确否决（见原文）。
- **代价与回退**：宽排（live01 顶排 10 列）下个别 ≥9 字符的拉丁词会被词尾硬拆（`LangGraph`→`LangGrap|h`）；
  其余按词换行。回退路径：`git revert` 本分支提交即可，flat/无分组路径逐字节不变、layout goldens 逐字段不变，
  回退不会牵连 D 轨其它成果。

### 交付记录（2026-09-15，worker）— Status: ready-for-review

- **分支/提交**：`dev/X6-dense-view` @ `d0d987a`（基线 rebase 到 `main 6dc7b2a`；**未 push、未合并**）。
- **改动**：
  - `graph2note/diagrams/matplotlib_renderer.py`：新增 `legibility_max_figure_width()` / `default_view_text_px()` /
    `_compact_text()`（纯函数，词感知换行预算 18→2）；分组画布上限=阅读宽预算、floor 12→6in、
    pad 0.07→0.05、seam 0.16→0.10；`_grouped_geometry` 返回实际绘制的 `wrapped/notes`。
  - `tests/fixtures/diagrams/*.json`：真实 01/02/02inc DeepSeek-vision 抽取（保留 caption/nodes/edges/groups，去 meta），
    供 CI 离线复现验收（provenance 见同目录 README.md）。
  - `tests/test_diagram_render_groups.py`：X6 断言——预算纯函数互逆性、真实三图 720px 可读性、
    重排后仍无 artist 重叠、已适配时不改动 wrap、flat 路径仍 12×8。
- **验收数字**（产品链：抽取→`prepare_diagram_layout`→`build_figure`→PNG，容器宽度缩放）：

  | 图 | PNG px | fig (in) | @720 node / note | @390 node / note |
  |---|---|---|---|---|
  | 01 (21n,5×10) | 1213×945 | 10.32×8.00 | **12.86 / 9.89** | 6.97 / 5.36 |
  | 02 (10n,4×4) | 981×945 | 8.31×8.00 | **15.90 / 12.23** | 8.61 / 6.63 |
  | 02inc (32n,8×9) | 1127×2187 | 9.58×18.78 | **13.84 / 10.65** | 7.50 / 5.77 |

  对比修复前：01 node 5.81 / note 4.47，02 11.10 / 8.53，02inc 6.60 / 5.08。目标（node≥11、note≥9.4 @720）全部达成，未放宽下限；
  390px 走「可用」口径（无横向溢出、控件不裁切；密图仍需 viewer 放大），与 issue 验收一致。
- **回归**：
  - 全量 `pytest -p no:warnings`：**1255 passed**（基线 `main 6dc7b2a` 实测 **1245 passed**，新增/改动测试净 +10）。
  - grouped golden（layer/lane/cluster/increment）与 D1 anchor01/02/02inc 的 `grouped_layout` **逐字段相同**；
    扁平路径 matplotlib PNG / graphviz dot 源 **逐字节相同**（SHA 对照，脚本 `/tmp/x6/compare.py`）。
  - node 契约：`tests/diagram_presentation.cjs`、`tests/assets_rewrite.cjs`、`tests/editor_workspace_dom.mjs`（含 viewer 链路）全绿。
  - 前端巡检：`PLAYWRIGHT_MODULE=…/playwright/index.mjs node scripts/frontend_audit.mjs http://127.0.0.1:8794 /tmp/x6/audit-out` → `{"checks":33,"findings":[]}`（1440/768/390）。
- **残留/边界**：① 极端宽排（>28 列）下 u=2 仍可能超预算，此时宁可超预算也不缩字（`_compact_text` 已注明）；
  ② 390px 密图 note ~5.4px，默认视图仍偏小，依赖既有 viewer（issue 只要求「可用」）；
  ③ 个别 ≥9 字符拉丁词硬拆（见「代价」）。
- **未做**：未改前端（默认视图已在渲染层修好，避免维护者否决的引导式绕行）、未改 `_layout.py`/`ir.py`/prompt/I 轨文件、未 push、未自评合并。
