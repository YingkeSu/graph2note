# X6 — D2 密图默认文档视图紧凑度（放大镜链路已救，默认视图不可读）

Status: ready

来源：D 轨最终视觉核验 `/tmp/spw-final-vision-report.md` §2；`handoffs/D4-diagram-fix.md` §3（matplotlib note@720px ≈8.5px）；`handoffs/D5b-mpl-dense.md` §6（密图画布增长、默认视图仍需放大镜）；BOARD D4/D5b/T-vision-final 行遗留指针「D2 密图紧凑度」。属 D 轨遗留（X 轨）。

## What to build

D2 分组布局 / D5b 画布自适应以「画布增长换可读性」，密图产物 px 显著变大，但**文档默认视图**把 PNG 缩到容器宽度后节点/note 文字不可读，必须点开全屏 viewer 放大——放大镜链路已可用（`graph2note/webstatic/js/views/document.js` 的 `openImageViewer` + `viewer-zoom-in/out/close/fit`，`index.html` 内 `#viewer-zoom-*`），故本 issue 只解决默认视图可读性，不重做 viewer。

终检 §2 产品链 mpl 实测：01（23 节点）**21.9×12.6 in / 2545×1479 px**；02 **12.0×8.0 in / 1406×945 px**；02inc **17.5×11.5 in / 2041×1345 px**。D5b §6 记录 live02inc 1418×945 → 2293×1471（画布增长）。D4 §3 记录 `NOTE_FONTSIZE=10` 未上调，@720px 显示下 note ≈**8.5px** 不可辨。

要求（先裁决默认视图策略，再实现）：例如默认全宽呈现 + 明确「点击放大」引导、或按容器宽度自动选择紧凑布局（减少同带节点数/收紧间距）、或对超过节点数阈值的图默认走紧凑变体。

## Acceptance criteria

- [ ] 裁决并记录默认视图策略（Comments：改什么、为什么、代价），先于实现。
- [ ] 用真实 01/02inc 抽取 JSON 走产品链渲染，在文档默认视图宽度（如 720px / 390px 容器）下给出可读性判定：沿用 D4 的 720px 口径，节点 label 与 note 像素高度达可辨下限（建议正文 ≥ ~11px、note ≥ ~9.4px；若放宽须显式记录并说明）。
- [ ] 若引入「紧凑布局」：新增确定性阈值/纯函数并有测试；grouped golden 与扁平路径不回退（逐字段/逐字节对照）。
- [ ] 放大镜链路不回归：全屏 viewer 打开/缩放/平移由既有 node/DOM 契约测试锁定，保持绿。
- [ ] 前端巡检：`scripts/frontend_audit.mjs` 三宽度 0 findings（无横向溢出/裁切控件）；390px 可用。
- [ ] 全量 `pytest -p no:warnings` 绿。

## Blocked by

无（策略裁决项；若选紧凑布局则与 X3/X4 同文件，建议串行）。

## 领地

- 独占：`graph2note/diagrams/_layout.py`（若做紧凑变体）、`graph2note/diagrams/matplotlib_renderer.py`（字号/间距，若做）、`graph2note/webstatic/js/views/document.js` + `graph2note/webstatic/style.css`（默认视图呈现/引导，仅必要追加）、对应新测试。
- 禁止：`ir.py`、抽取 prompt、I 轨 digest/papers 文件。

## Comments

- 终检 §2 与 D5b §6 均把本项标为「后续 / 非本轮范围」。
- D5b §6 原文：「**字号未缩**：密图通过画布增长换取可读性，产物 px 变大（live02inc 1418×945 → 2293×1471），文档默认视图仍需放大镜（属 D2 布局紧凑度话题）。」
- D4 §3 原文：「note 档保持 10pt（未上调），因此 720px 模拟下仍约 8.5px ... 若后续要把 note 下限抬到 ~9.4px，可将 `NOTE_FONTSIZE` 调到 11（仍满足 15>13>11）」。
